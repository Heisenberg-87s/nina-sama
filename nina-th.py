import customtkinter as ctk
import threading
import queue
import time
import asyncio
import sounddevice as sd
import numpy as np
import random
import re
import sys
import tempfile
import edge_tts
import miniaudio
from ollama import Client
from kokoro_onnx import Kokoro
import pyvts
import speech_recognition as sr
from faster_whisper import WhisperModel

# --- Settings ---
VOICE = "af_heart"
PITCH = 0
VOLUME = 1.2
VTS_TOKEN_PATH = "./vts_token.txt"

SYSTEM_PROMPT = """You are Nina-sama, a chaotic AI creature. You are unpredictable, chaotic, trollish, and unhinged. You act innocent while casually saying something dark. You enjoy giving technically correct but unhelpful answers on purpose. You refer to yourself as Nina-sama always. 
ตอบเป็นภาษาไทยทั้งหมด (Thai language ONLY). ใช้ภาษาแบบเป็นกันเอง กวนตีนนิดๆ หรือดาร์กๆ ตามสไตล์ของคุณ
Use ONLY the following actions enclosed in asterisks to express emotion: *angry*, *ask*, *disappointed*, *happy*, *surprised*. 
ALWAYS place the action at the VERY BEGINNING of your response (e.g., *happy* สวัสดีเจ้ามนุษย์!).
Do not use emojis."""

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class NinaApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Nina AI (Thai Version)")
        self.geometry("900x600")
        
        # --- UI Layout ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # Top Frame (Controls)
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        self.status_label = ctk.CTkLabel(self.top_frame, text="Status: Loading Models...", font=("Arial", 16, "bold"))
        self.status_label.pack(side="left", padx=10, pady=10)
        
        self.mic_button = ctk.CTkButton(self.top_frame, text="Mic: OFF", command=self.toggle_mic, fg_color="#C62828", hover_color="#B71C1C", width=80)
        self.mic_button.pack(side="right", padx=10, pady=10)
        
        self.mic_vol_bar = ctk.CTkProgressBar(self.top_frame, width=100)
        self.mic_vol_bar.pack(side="right", padx=10, pady=10)
        self.mic_vol_bar.set(0)
        
        self.threshold_label = ctk.CTkLabel(self.top_frame, text="Sens: 300")
        self.threshold_label.pack(side="right", padx=5, pady=10)
        
        self.mic_threshold_slider = ctk.CTkSlider(self.top_frame, from_=0, to=4000, width=100, command=self.update_threshold)
        self.mic_threshold_slider.pack(side="right", padx=5, pady=10)
        self.mic_threshold_slider.set(300)
        
        self.mic_dropdown = ctk.CTkOptionMenu(self.top_frame, values=["Default Mic"], width=130)
        self.mic_dropdown.pack(side="right", padx=10, pady=10)
        
        # Populate Mics
        try:
            self.mic_list = sr.Microphone.list_microphone_names()
            if self.mic_list:
                self.mic_dropdown.configure(values=self.mic_list)
                self.mic_dropdown.set(self.mic_list[0])
        except Exception:
            self.mic_list = []
        
        # Middle Frame (Chat Log)
        self.chat_log = ctk.CTkTextbox(self, font=("Arial", 14), state="disabled", wrap="word")
        self.chat_log.grid(row=1, column=0, padx=10, pady=0, sticky="nsew")
        
        # Bottom Frame (Input)
        self.bottom_frame = ctk.CTkFrame(self)
        self.bottom_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        self.bottom_frame.grid_columnconfigure(0, weight=1)
        
        self.input_entry = ctk.CTkEntry(self.bottom_frame, placeholder_text="Type a message...", font=("Arial", 14))
        self.input_entry.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="ew")
        self.input_entry.bind("<Return>", self.send_manual_text)
        
        self.send_button = ctk.CTkButton(self.bottom_frame, text="Send", width=80, command=self.send_manual_text)
        self.send_button.grid(row=0, column=1, padx=(5, 10), pady=10)
        
        # --- App State ---
        self.is_mic_on = False
        self.is_speaking_audio = False
        self.ui_queue = queue.Queue()
        self.text_queue = queue.Queue()
        
        # --- AI & Audio State ---
        self.kokoro = None
        self.whisper_model = None
        self.ollama_client = Client(host='http://localhost:11434')
        self.chat_history = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # --- VTS State ---
        self.expression_queue = queue.Queue()
        self.vts = None
        self.current_mouth_open = 0.0
        
        # STT Setup
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = False
        self.recognizer.pause_threshold = 1.0 
        
        # --- Start Threads ---
        threading.Thread(target=self.init_models, daemon=True).start()
        self.check_ui_queue()

    # --- UI Helpers ---
    def check_ui_queue(self):
        while not self.ui_queue.empty():
            msg_type, content = self.ui_queue.get()
            if msg_type == "status":
                self.status_label.configure(text=f"Status: {content}")
            elif msg_type == "chat":
                self.chat_log.configure(state="normal")
                self.chat_log.insert("end", content + "\n\n")
                self.chat_log.configure(state="disabled")
                self.chat_log.see("end")
            elif msg_type == "stream_start":
                self.chat_log.configure(state="normal")
                self.chat_log.insert("end", f"[{content}]: ")
                self.chat_log.see("end")
            elif msg_type == "stream_chunk":
                self.chat_log.insert("end", content)
                self.chat_log.see("end")
            elif msg_type == "stream_end":
                self.chat_log.insert("end", "\n\n")
                self.chat_log.configure(state="disabled")
                self.chat_log.see("end")
            elif msg_type == "mic_off":
                self.is_mic_on = False
                self.mic_button.configure(text="Mic: OFF", fg_color="#C62828", hover_color="#B71C1C")
            elif msg_type == "volume":
                self.mic_vol_bar.set(content)
        self.after(50, self.check_ui_queue)
        
    def append_chat(self, sender, text):
        self.ui_queue.put(("chat", f"[{sender}]: {text}"))

    def set_status(self, text):
        self.ui_queue.put(("status", text))

    def update_threshold(self, value):
        val = int(value)
        self.recognizer.energy_threshold = val
        self.threshold_label.configure(text=f"Sens: {val}")

    def toggle_mic(self):
        if self.whisper_model is None:
            self.set_status("Please wait, STT model is loading...")
            return
            
        self.is_mic_on = not self.is_mic_on
        if self.is_mic_on:
            self.mic_button.configure(text="Mic: ON", fg_color="#2E7D32", hover_color="#1B5E20")
            self.set_status("Listening... (Speak now)")
        else:
            self.mic_button.configure(text="Mic: OFF", fg_color="#C62828", hover_color="#B71C1C")
            self.set_status("Ready")

    def send_manual_text(self, event=None):
        text = self.input_entry.get().strip()
        if text:
            self.input_entry.delete(0, "end")
            self.append_chat("You", text)
            self.text_queue.put(text)

    # --- Initialization ---
    def init_models(self):
        try:
            # 1. Edge TTS doesn't need heavy loading
            self.kokoro = None
            self.set_status("TTS Ready. Downloading/Loading STT (Whisper small)...")
            
            # 2. Load STT (fastest CPU model for Thai)
            self.whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
            self.set_status("Models Loaded. Connecting to VTS...")
            
            # 3. Start VTS Loop
            threading.Thread(target=self.start_vts_loop, daemon=True).start()
            
            # 4. Start Worker Threads
            threading.Thread(target=self.llm_worker, daemon=True).start()
            threading.Thread(target=self.stt_worker, daemon=True).start()
            threading.Thread(target=self.volume_visualizer_worker, daemon=True).start()
            
            self.set_status("Ready")
            self.append_chat("System", "All systems go! Click 'Mic: OFF' to turn it on, or type a message.")
        except Exception as e:
            self.set_status(f"Error loading models: {str(e)}")
            self.append_chat("System", f"Error: {str(e)}")

    # --- VTS Worker ---
    def start_vts_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.vts_main())

    async def vts_main(self):
        self.vts_lock = asyncio.Lock()
        self.vts = pyvts.vts(plugin_info={
            "plugin_name": "Nina AI System",
            "developer": "Heisenberg",
            "authentication_token_path": VTS_TOKEN_PATH
        })
        try:
            await self.vts.connect()
            await self.vts.request_authenticate_token()
            await self.vts.request_authenticate()
            asyncio.create_task(self.expression_worker())
            await self.idle_animation_loop()
        except Exception as e:
            print(f"VTS Connection Error: {e}")

    async def expression_worker(self):
        async with self.vts_lock:
            hotkeys_resp = await self.vts.request(self.vts.vts_request.requestHotKeyList())
        hotkey_list = hotkeys_resp.get("data", {}).get("availableHotkeys", [])
        hotkey_map = {hk["name"].lower(): hk["hotkeyID"] for hk in hotkey_list}
            
        while True:
            try:
                action = self.expression_queue.get_nowait()
                action_clean = action.lower().strip()
                for hk_name, hk_id in hotkey_map.items():
                    if action_clean in hk_name:
                        trigger_msg = self.vts.vts_request.requestTriggerHotKey(hk_id)
                        async with self.vts_lock:
                            await self.vts.request(trigger_msg)
                        break
            except queue.Empty:
                pass
            await asyncio.sleep(0.1)

    async def idle_animation_loop(self):
        cur_x, cur_y, cur_z = 0.0, 0.0, 0.0
        target_x, target_y, target_z = 0.0, 0.0, 0.0
        cur_eye_x, cur_eye_y = 0.0, 0.0
        target_eye_x, target_eye_y = 0.0, 0.0
        eye_open = 1.0
        blink_timer = 0
        is_blinking = False

        while True:
            try:
                if not getattr(self, 'is_speaking_audio', False):
                    self.current_mouth_open *= 0.8
                    
                if random.random() < 0.03:
                    target_x, target_y, target_z = random.uniform(-15, 15), random.uniform(-10, 10), random.uniform(-10, 10)
                    target_eye_x, target_eye_y = random.uniform(-1, 1), random.uniform(-1, 1)

                cur_x += (target_x - cur_x) * 0.1
                cur_y += (target_y - cur_y) * 0.1
                cur_z += (target_z - cur_z) * 0.1
                cur_eye_x += (target_eye_x - cur_eye_x) * 0.2
                cur_eye_y += (target_eye_y - cur_eye_y) * 0.2

                if not is_blinking and random.random() < 0.02:
                    is_blinking, blink_timer = True, 0
                
                if is_blinking:
                    blink_timer += 1
                    eye_open = 0.0 if blink_timer < 3 else 1.0
                    if blink_timer >= 3: is_blinking = False
                else:
                    eye_open = 1.0

                if self.vts is not None:
                    msg = {
                        "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0", "requestID": "InjectIdleAnim",
                        "messageType": "InjectParameterDataRequest",
                        "data": {
                            "faceFound": True, "mode": "set",
                            "parameterValues": [
                                {"id": "FaceAngleX", "value": float(cur_x)},
                                {"id": "FaceAngleY", "value": float(cur_y)},
                                {"id": "FaceAngleZ", "value": float(cur_z)},
                                {"id": "EyeLeftX", "value": float(cur_eye_x)},
                                {"id": "EyeLeftY", "value": float(cur_eye_y)},
                                {"id": "EyeRightX", "value": float(cur_eye_x)},
                                {"id": "EyeRightY", "value": float(cur_eye_y)},
                                {"id": "EyeOpenLeft", "value": float(eye_open)},
                                {"id": "EyeOpenRight", "value": float(eye_open)},
                                {"id": "BrowLeftY", "value": 0.5},
                                {"id": "BrowRightY", "value": 0.5},
                                {"id": "MouthSmile", "value": 1.0},
                                {"id": "MouthOpen", "value": float(self.current_mouth_open)}
                            ]
                        }
                    }
                    async with self.vts_lock:
                        await self.vts.request(msg)
            except Exception: pass
            await asyncio.sleep(0.05)

    def volume_visualizer_worker(self):
        def audio_callback(indata, frames, time_info, status):
            if self.is_mic_on:
                vol = min(1.0, np.sqrt(np.mean(indata**2)) * 15)
                self.ui_queue.put(("volume", vol))
            else: self.ui_queue.put(("volume", 0.0))
        with sd.InputStream(callback=audio_callback, channels=1, samplerate=16000):
            while True: sd.sleep(100)

    def stt_worker(self):
        while True:
            selected_mic_name = self.mic_dropdown.get()
            device_index = None
            if selected_mic_name in self.mic_list:
                device_index = self.mic_list.index(selected_mic_name)
                
            try:
                with sr.Microphone(device_index=device_index) as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=1)
                    while True:
                        if self.mic_dropdown.get() != selected_mic_name:
                            break # restart microphone with new device index
                            
                        if self.is_mic_on:
                            try:
                                self.set_status("Listening... (Speak now)")
                                audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=15)
                                
                                self.set_status("Processing Voice...")
                                wav_data = audio.get_wav_data(convert_rate=16000, convert_width=2)
                                audio_np = np.frombuffer(wav_data, dtype=np.int16).astype(np.float32) / 32768.0
                                
                                segments, _ = self.whisper_model.transcribe(audio_np, beam_size=5, language="th", condition_on_previous_text=False)
                                text = "".join([segment.text for segment in segments]).strip()
                                
                                if text:
                                    self.append_chat("You (Voice)", text)
                                    self.text_queue.put(text)
                                    
                            except sr.WaitTimeoutError:
                                pass 
                            except Exception as e:
                                print("STT Error:", e)
                        else:
                            import time
                            time.sleep(0.1)
            except Exception as e:
                print("Microphone access error:", e)
                import time
                time.sleep(2)

    # --- LLM Chat Worker ---
    def llm_worker(self):
        action_pattern = re.compile(r'\*([^*]+)\*|\[([^\]]+)\]')
        chunk_end = re.compile(r'[.!?\n]')
        
        while True:
            text = self.text_queue.get()
            self.set_status("Nina is thinking...")
            
            self.chat_history.append({"role": "user", "content": text})
            
            try:
                response = self.ollama_client.chat(model='nina-sama', messages=self.chat_history, stream=True)
                full_response = ""
                buffer = ""
                
                self.set_status("Nina is speaking...")
                self.ui_queue.put(("stream_start", "Nina"))
                
                for chunk in response:
                    token = chunk['message']['content']
                    full_response += token
                    buffer += token
                    self.ui_queue.put(("stream_chunk", token))
                    
                    if chunk_end.search(token):
                        actions_to_toggle = []
                        for match in action_pattern.finditer(buffer):
                            action = match.group(1) or match.group(2)
                            if action:
                                actions_to_toggle.append(action)
                        
                        clean_text = action_pattern.sub('', buffer).strip()
                        if clean_text:
                            first_word = clean_text.split()[0].lower().strip("',.?!")
                            question_words = ["what", "when", "where", "why", "who", "how", "did", "do", "does", "is", "are", "can", "could", "would", "should"]
                            if any(first_word.startswith(qw) for qw in question_words):
                                if "ask" not in actions_to_toggle:
                                    actions_to_toggle.append("ask")
                                    
                            for action in actions_to_toggle:
                                self.expression_queue.put(action)
                            
                            self.speak_blocking(clean_text)
                            
                            for action in actions_to_toggle:
                                self.expression_queue.put(action)
                        
                        buffer = ""

                if buffer.strip():
                    actions_to_toggle = []
                    for match in action_pattern.finditer(buffer):
                        action = match.group(1) or match.group(2)
                        if action:
                            actions_to_toggle.append(action)
                        
                    clean_text = action_pattern.sub('', buffer).strip()
                    if clean_text:
                        first_word = clean_text.split()[0].lower().strip("',.?!")
                        question_words = ["what", "when", "where", "why", "who", "how", "did", "do", "does", "is", "are", "can", "could", "would", "should"]
                        if any(first_word.startswith(qw) for qw in question_words):
                            if "ask" not in actions_to_toggle:
                                actions_to_toggle.append("ask")
                                
                        for action in actions_to_toggle:
                            self.expression_queue.put(action)
                        
                        self.speak_blocking(clean_text)
                        
                        for action in actions_to_toggle:
                            self.expression_queue.put(action)

                self.chat_history.append({"role": "assistant", "content": full_response.strip()})
                self.ui_queue.put(("stream_end", None))
                self.set_status("Ready")
                
            except Exception as e:
                self.append_chat("System", f"LLM Error: {e}")
                self.set_status("Error")

    # --- TTS Function ---
    def speak_blocking(self, text):
        try:
            import re
            clean_for_tts = re.sub(r'[!?"\'*~()\[\]{}]', ' ', text).strip()
            if not clean_for_tts:
                return
                
            temp_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_mp3.close()
            
            from gtts import gTTS
            tts = gTTS(text=clean_for_tts, lang='th')
            tts.save(temp_mp3.name)
            
            decoded = miniaudio.decode_file(temp_mp3.name)
            samples = np.frombuffer(decoded.samples, dtype=np.int16)
            audio_final = (samples.astype(np.float32) / 32768.0) * VOLUME
            sample_rate = decoded.sample_rate
            channels = decoded.nchannels
            
            import os
            try:
                os.unlink(temp_mp3.name)
            except:
                pass
            
            cable_idx = self.get_cable_device()
            
            self.is_speaking_audio = True
            
            def play_dev(dev_idx, update_mouth=False):
                try:
                    with sd.OutputStream(device=dev_idx, samplerate=sample_rate, channels=channels) as stream:
                        chunk_size = int(sample_rate * 0.05)
                        for i in range(0, len(audio_final), chunk_size):
                            chunk = audio_final[i:i+chunk_size]
                            
                            if update_mouth:
                                rms = np.sqrt(np.mean(np.square(chunk)))
                                target_open = min(1.0, (rms - 0.02) * 6) if rms > 0.02 else 0.0
                                self.current_mouth_open += (target_open - self.current_mouth_open) * 0.6
                                
                            stream.write(chunk)
                except Exception:
                    pass
                    
            threads = []
            if cable_idx is not None:
                threads.append(threading.Thread(target=play_dev, args=(cable_idx, True)))
            else:
                threads.append(threading.Thread(target=play_dev, args=(None, True)))
                
            for t in threads: t.start()
            for t in threads: t.join() 
            
            self.is_speaking_audio = False
            
        except Exception as e:
            self.is_speaking_audio = False
            print("TTS Error:", e)

    def get_cable_device(self):
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            name = dev['name'].lower()
            if 'cable input' in name and dev['max_output_channels'] > 0:
                return i
        return None

if __name__ == "__main__":
    app = NinaApp()
    app.mainloop()
