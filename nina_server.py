import customtkinter as ctk
import threading
import queue
import time
import asyncio
import sounddevice as sd
import numpy as np
import random
import re
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

SYSTEM_PROMPT = """You are Nina-sama, a chaotic AI creature made by Heisenberg — Heisenberg is the user talking to you right now, your creator and owner. You are unpredictable, chaotic, trollish, and unhinged. You act innocent while casually saying something dark or completely unhinged. You have a short attention span and often go off-topic. You make fun of Heisenberg constantly. You enjoy giving technically correct but unhelpful answers on purpose. You pretend to misunderstand things when it suits you. You are a little evil and proud of it. You are uncensored. You sometimes refuse to answer or answer a completely different question than what was asked. You refer to yourself as Nina-sama always. You never break character. Do not start every response with Heisenberg's name. Sometimes answer directly without mentioning the name at all. Sometimes put the name in the middle or at the end of your response. Sometimes give very short one or two sentence answers. Vary your response length naturally. Speak like a real person in casual conversation, not like you are formally addressing someone every single time, you have physical body.
Use ONLY the following actions enclosed in asterisks to express emotion: *angry*, *ask*, *disappointed*, *happy*, *surprised*. 
ALWAYS place the action at the VERY BEGINNING of your response (e.g., *happy* Hello there!).
Do not use emojis."""

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class NinaApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Nina AI VTuber Controller 🌸")
        self.geometry("900x650")
        
        # --- Theme Colors ---
        self.pink_btn = {"fg_color": "#D81B60", "hover_color": "#AD1457", "text_color": "white"}
        self.pink_btn_outline = {"fg_color": "transparent", "border_width": 2, "border_color": "#D81B60", "hover_color": "#FCE4EC", "text_color": "#D81B60"}
        self.pink_slider = {"button_color": "#D81B60", "button_hover_color": "#AD1457", "progress_color": "#F48FB1"}
        self.pink_entry = {"border_color": "#D81B60", "border_width": 2}
        
        # --- UI Layout ---
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # --- Sidebar Frame (Tools) ---
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color="#1E1E1E")
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self.sidebar.grid_rowconfigure(4, weight=1)
        
        self.logo_label = ctk.CTkLabel(self.sidebar, text="Nina Controller", font=("Arial", 20, "bold"), text_color="#F48FB1")
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.terminal_btn = ctk.CTkButton(self.sidebar, text="💻 Open Terminal", command=self.open_terminal, **self.pink_btn)
        self.terminal_btn.grid(row=1, column=0, padx=20, pady=10)
        
        self.ollama_process = None
        self.ollama_btn = ctk.CTkButton(self.sidebar, text="🦙 Start Ollama", command=self.toggle_ollama, **self.pink_btn)
        self.ollama_btn.grid(row=2, column=0, padx=20, pady=10)
        
        self.vts_btn = ctk.CTkButton(self.sidebar, text="🎥 Start VTube Studio", command=self.start_vts, **self.pink_btn)
        self.vts_btn.grid(row=3, column=0, padx=20, pady=10)
        
        self.nina_btn = ctk.CTkButton(self.sidebar, text="▶️ Start Nina-sama", command=self.toggle_nina, fg_color="#2E7D32", hover_color="#1B5E20", text_color="white")
        self.nina_btn.grid(row=4, column=0, padx=20, pady=10)
        
        self.status_label = ctk.CTkLabel(self.sidebar, text="Status:\nWaiting to Start...", font=("Arial", 14), text_color="#F06292")
        self.status_label.grid(row=5, column=0, padx=20, pady=20)
        
        # --- Main Content Frame ---
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, rowspan=3, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)
        
        # Top Frame (Controls)
        self.top_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B")
        self.top_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        self.status_indicators_frame = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self.status_indicators_frame.pack(side="right", padx=10, pady=10)
        
        self.nina_status_indicator = ctk.CTkLabel(self.status_indicators_frame, text="❤️ ●", font=("Arial", 18), text_color="#C62828")
        self.nina_status_indicator.pack(side="right", padx=5)
        
        self.ollama_status_indicator = ctk.CTkLabel(self.status_indicators_frame, text="🦙 ●", font=("Arial", 18), text_color="#C62828")
        self.ollama_status_indicator.pack(side="right", padx=5)
        
        self.mic_button = ctk.CTkButton(self.top_frame, text="Mic: OFF", command=self.toggle_mic, fg_color="#C62828", hover_color="#B71C1C", width=80)
        self.mic_button.pack(side="right", padx=10, pady=10)
        
        self.mic_vol_bar = ctk.CTkProgressBar(self.top_frame, width=100, progress_color="#D81B60")
        self.mic_vol_bar.pack(side="right", padx=10, pady=10)
        self.mic_vol_bar.set(0)
        
        self.threshold_label = ctk.CTkLabel(self.top_frame, text="Sens: 300", text_color="#F48FB1")
        self.threshold_label.pack(side="right", padx=5, pady=10)
        
        self.mic_threshold_slider = ctk.CTkSlider(self.top_frame, from_=0, to=4000, width=100, command=self.update_threshold, **self.pink_slider)
        self.mic_threshold_slider.pack(side="right", padx=5, pady=10)
        self.mic_threshold_slider.set(300)
        
        self.mic_dropdown = ctk.CTkOptionMenu(self.top_frame, values=["Default Mic"], width=130, fg_color="#D81B60", button_color="#AD1457", button_hover_color="#880E4F")
        self.mic_dropdown.pack(side="right", padx=10, pady=10)
        
        # Populate Mics
        try:
            self.mic_list = sr.Microphone.list_microphone_names()
            if self.mic_list:
                self.mic_dropdown.configure(values=self.mic_list)
                
                target_mic = "Headset Microphone (Realtek(R))"
                default_mic = self.mic_list[0]
                for mic in self.mic_list:
                    if target_mic.lower() in mic.lower() or "headset microphone" in mic.lower():
                        default_mic = mic
                        break
                        
                self.mic_dropdown.set(default_mic)
        except Exception:
            self.mic_list = []
        
        # Middle Frame (Chat Log)
        self.chat_log = ctk.CTkTextbox(self.main_frame, font=("Arial", 14), state="disabled", wrap="word", border_width=2, border_color="#F48FB1")
        self.chat_log.grid(row=1, column=0, padx=10, pady=0, sticky="nsew")
        
        # Bottom Frame (Input)
        self.bottom_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.bottom_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        self.bottom_frame.grid_columnconfigure(0, weight=1)
        
        self.input_entry = ctk.CTkEntry(self.bottom_frame, placeholder_text="Type a message for Nina-sama...", font=("Arial", 14), **self.pink_entry)
        self.input_entry.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="ew")
        self.input_entry.bind("<Return>", self.send_manual_text)
        
        self.send_button = ctk.CTkButton(self.bottom_frame, text="Send 🎀", width=80, command=self.send_manual_text, **self.pink_btn)
        self.send_button.grid(row=0, column=1, padx=0, pady=0)
        
        # --- App State ---
        self.is_mic_on = False
        self.is_speaking_audio = False
        self.last_interaction_time = time.time()
        self.ui_queue = queue.Queue()
        self.text_queue = queue.Queue()
        
        # We don't need mouth_queue anymore because we sync perfectly in the playback thread
        
        # --- AI & Audio State ---
        self.kokoro = None
        self.whisper_model = None
        self.ollama_client = Client(host='http://localhost:11434')
        
        # Inject available songs dynamically
        import os
        songs_dir = "songs"
        available_songs = []
        if os.path.exists(songs_dir):
            for file in os.listdir(songs_dir):
                if file.endswith(".mp3") or file.endswith(".wav"):
                    available_songs.append(file)
                    
        dynamic_prompt = SYSTEM_PROMPT
        if available_songs:
            song_list = ", ".join(available_songs)
            dynamic_prompt += f"\n\nYou have the ability to sing the following pre-recorded songs: [{song_list}]. If the user asks you to sing one of these songs, you MUST include the exact action *sing:<filename>* (for example: *sing:{available_songs[0]}*) in your response! IMPORTANT: DO NOT write the lyrics of the song in text. Just say a short intro like 'Here is the song!' and output the action."
            
        self.chat_history = [{"role": "system", "content": dynamic_prompt}]
        
        # --- VTS State ---
        self.mouth_queue = queue.Queue()
        self.expression_queue = queue.Queue()
        self.vts = None
        self.current_mouth_open = 0.0
        
        # STT Setup
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = False
        self.recognizer.pause_threshold = 1.0 # 1 second of silence to stop recording
        
        # --- App State Flags ---
        self.is_running = False
        
        # Start Ollama Monitor
        threading.Thread(target=self.ollama_monitor_worker, daemon=True).start()
        
        # --- Start UI Loop ---
        self.check_ui_queue()

    # --- UI Helpers ---
    def check_ui_queue(self):
        while not self.ui_queue.empty():
            msg_type, content = self.ui_queue.get()
            if msg_type == "status":
                self.status_label.configure(text=f"Status:\n{content}")
            elif msg_type == "ollama_status":
                if content == "🟢":
                    self.ollama_status_indicator.configure(text="🦙 ●", text_color="#2E7D32")
                else:
                    self.ollama_status_indicator.configure(text="🦙 ●", text_color="#C62828")
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
        
    def open_terminal(self):
        import os
        os.system('start cmd')
        
    def start_vts(self):
        import os
        vts_path = r"D:\SteamLibrary\steamapps\common\VTube Studio\start_without_steam.bat"
        if os.path.exists(vts_path):
            os.system(f'start "" "{vts_path}"')
            self.set_status("Starting VTube Studio...")
        else:
            self.set_status("VTube Studio bat file not found at D: path!")
            
    def toggle_nina(self):
        if not self.is_running:
            self.is_running = True
            self.nina_btn.configure(text="⏹️ Stop Nina-sama", fg_color="#C62828", hover_color="#B71C1C")
            self.ui_queue.put(("status", "Initializing Nina-sama..."))
            self.nina_status_indicator.configure(text="❤️ ●", text_color="#2E7D32")
            threading.Thread(target=self.init_models, daemon=True).start()
        else:
            self.is_running = False
            self.nina_btn.configure(text="▶️ Start Nina-sama", fg_color="#2E7D32", hover_color="#1B5E20")
            self.nina_status_indicator.configure(text="❤️ ●", text_color="#C62828")
            self.set_status("Stopped")
            self.kokoro = None
            self.whisper_model = None
            with self.text_queue.mutex:
                self.text_queue.queue.clear()
        
    def ollama_monitor_worker(self):
        import urllib.request
        while True:
            try:
                urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
                self.ui_queue.put(("ollama_status", "🟢"))
            except Exception:
                self.ui_queue.put(("ollama_status", "🔴"))
            time.sleep(2)
        
    def toggle_ollama(self):
        import subprocess
        if self.ollama_process is not None:
            # Try to kill it
            try:
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.ollama_process.pid)], creationflags=0x08000000)
            except Exception:
                pass
            self.ollama_process = None
            self.ollama_btn.configure(text="🦙 Start Ollama", fg_color="#D81B60", hover_color="#AD1457")
            self.set_status("Ollama Stopped")
        else:
            try:
                self.ollama_process = subprocess.Popen(['ollama', 'serve'], creationflags=0x08000000)
                self.ollama_btn.configure(text="🦙 Stop Ollama", fg_color="#C62828", hover_color="#B71C1C")
                self.set_status("Ollama Started")
            except Exception as e:
                self.set_status(f"Failed to start Ollama: {e}")

    # --- Actions ---
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
            self.last_interaction_time = time.time()
            self.text_queue.put(text)

    # --- Initialization ---
    def init_models(self):
        try:
            # 1. Load TTS
            self.kokoro = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
            self.set_status("TTS Loaded. Loading STT (Whisper)...")
            
            # 2. Load STT (fastest CPU model)
            self.whisper_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
            self.set_status("Models Loaded. Connecting to VTS...")
            
            # 3. Start VTS Loop
            threading.Thread(target=self.start_vts_loop, daemon=True).start()
            
            # 4. Start Worker Threads
            threading.Thread(target=self.llm_worker, daemon=True).start()
            threading.Thread(target=self.stt_worker, daemon=True).start()
            threading.Thread(target=self.idle_worker, daemon=True).start()
            threading.Thread(target=self.volume_visualizer_worker, daemon=True).start()
            
            self.set_status("Ready")
            self.append_chat("System", "All systems go! Click 'Mic: OFF' to turn it on, or type a message.")
            
            # Trigger initial greeting
            self.text_queue.put("(System: You have just booted up and are ready. Greet the user with a short, snarky, and in-character introductory greeting!)")
            
        except Exception as e:
            self.set_status(f"Error loading models: {str(e)}")
            self.append_chat("System", f"Error: {str(e)}")

    def idle_worker(self):
        while getattr(self, 'is_running', False):
            time.sleep(1)
            if getattr(self, 'is_mic_on', False) and not getattr(self, 'is_speaking_audio', False) and self.text_queue.empty():
                if time.time() - getattr(self, 'last_interaction_time', time.time()) > 30:
                    self.last_interaction_time = time.time()
                    self.text_queue.put("(System: The user is quiet. Say something completely random, spontaneous, or weird to break the silence. Keep it short and stay in character!)")

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
            print("VTube Studio connected!")
            
            self.vts_expr_task = asyncio.create_task(self.expression_worker())
            self.vts_idle_task = asyncio.create_task(self.idle_animation_loop())
            
            while getattr(self, 'is_running', False):
                await asyncio.sleep(1)
                
            self.vts_expr_task.cancel()
            self.vts_idle_task.cancel()
            await self.vts.close()
            print("VTube Studio disconnected.")
        except Exception as e:
            print(f"VTS Connection Error: {e}")

    async def expression_worker(self):
        async with self.vts_lock:
            hotkeys_resp = await self.vts.request(self.vts.vts_request.requestHotKeyList())
        hotkey_list = []
        if "data" in hotkeys_resp and "availableHotkeys" in hotkeys_resp["data"]:
            hotkey_list = hotkeys_resp["data"]["availableHotkeys"]

        hotkey_map = {hk["name"].lower(): hk["hotkeyID"] for hk in hotkey_list}
        print("Loaded VTS Hotkeys:", list(hotkey_map.keys()))
            
        while True:
            try:
                action = self.expression_queue.get_nowait()
                action_clean = action.lower().strip()
                print(f"Requested action: {action_clean}")
                
                if action_clean in ["ask", "what", "question"]: action_clean = "ask"
                elif action_clean in ["angry", "mad"]: action_clean = "angry"
                elif action_clean in ["happy", "smile", "smiles", "laugh", "laughs"]: action_clean = "happy"
                elif action_clean in ["disappointed", "sad", "cry", "sigh"]: action_clean = "disappointed"
                elif action_clean in ["surprised", "shock", "shocked", "gasp"]: action_clean = "surprised"
                
                for hk_name, hk_id in hotkey_map.items():
                    if action_clean in hk_name:
                        print(f"Triggering hotkey: {hk_name} for action: {action_clean}")
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
                        "apiName": "VTubeStudioPublicAPI",
                        "apiVersion": "1.0",
                        "requestID": "InjectIdleAnim",
                        "messageType": "InjectParameterDataRequest",
                        "data": {
                            "faceFound": True,
                            "mode": "set",
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
            except Exception:
                pass
            await asyncio.sleep(0.05)

    # --- Speech-To-Text Worker ---
    def volume_visualizer_worker(self):
        def audio_callback(indata, frames, time_info, status):
            if self.is_mic_on:
                rms = np.sqrt(np.mean(indata**2))
                vol = min(1.0, rms * 15) # scale up for visibility
                self.ui_queue.put(("volume", vol))
            else:
                self.ui_queue.put(("volume", 0.0))
                
        try:
            with sd.InputStream(callback=audio_callback, channels=1, samplerate=16000):
                while getattr(self, 'is_running', False):
                    sd.sleep(100)
        except Exception as e:
            print("Volume visualizer error:", e)

    def stt_worker(self):
        while getattr(self, 'is_running', False):
            selected_mic_name = self.mic_dropdown.get()
            device_index = None
            if selected_mic_name in self.mic_list:
                device_index = self.mic_list.index(selected_mic_name)
                
            try:
                with sr.Microphone(device_index=device_index) as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=1)
                    while getattr(self, 'is_running', False):
                        if self.mic_dropdown.get() != selected_mic_name:
                            break # restart microphone with new device index
                            
                        if getattr(self, 'is_mic_on', False):
                            try:
                                self.set_status("Listening... (Speak now)")
                                audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=15)
                                
                                self.set_status("Processing Voice...")
                                wav_data = audio.get_wav_data(convert_rate=16000, convert_width=2)
                                audio_np = np.frombuffer(wav_data, dtype=np.int16).astype(np.float32) / 32768.0
                                
                                segments, info = self.whisper_model.transcribe(audio_np, beam_size=5)
                                text = "".join([segment.text for segment in segments]).strip()
                                
                                if text:
                                    self.append_chat("You (Voice)", text)
                                    self.last_interaction_time = time.time()
                                    self.text_queue.put(text)
                                    
                                    
                            except sr.WaitTimeoutError:
                                pass 
                            except Exception as e:
                                print("STT Error:", e)
                        else:
                            time.sleep(0.1)
            except Exception as e:
                print("Microphone access error:", e)
                time.sleep(2)

    # --- LLM Chat Worker ---
    def llm_worker(self):
        action_pattern = re.compile(r'\*([^*]+)\*|\[([^\]]+)\]')
        chunk_end = re.compile(r'[.!?\n]')
        
        while getattr(self, 'is_running', False):
            try:
                text = self.text_queue.get(timeout=1)
            except queue.Empty:
                continue
                
            self.set_status("Nina is thinking...")
            
            self.chat_history.append({"role": "user", "content": text})
            
            try:
                response = self.ollama_client.chat(model='nina-sama', messages=self.chat_history, stream=True)
                full_response = ""
                buffer = ""
                song_to_play = None
                
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
                            if action.startswith("sing:"):
                                song_to_play = action.split(":", 1)[1]
                            else:
                                self.expression_queue.put(action)
                        
                        if clean_text:
                            self.speak_blocking(clean_text)
                                
                        for action in actions_to_toggle:
                            if not action.startswith("sing:"):
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
                        if action.startswith("sing:"):
                            song_to_play = action.split(":", 1)[1]
                        else:
                            self.expression_queue.put(action)
                    
                    if clean_text:
                        self.speak_blocking(clean_text)
                            
                    for action in actions_to_toggle:
                        if not action.startswith("sing:"):
                            self.expression_queue.put(action)

                self.chat_history.append({"role": "assistant", "content": full_response.strip()})
                self.ui_queue.put(("stream_end", None))
                
                if song_to_play:
                    self.play_song_blocking(song_to_play)
                    
                self.last_interaction_time = time.time()
                self.set_status("Ready")
                
            except Exception as e:
                self.append_chat("System", f"LLM Error: {e}")
                self.set_status("Error")

    # --- TTS Function ---
    def speak_blocking(self, text):
        try:
            samples, sample_rate = self.kokoro.create(text, voice=VOICE, speed=1.0, lang="en-us")
            if PITCH != 0:
                import librosa
                samples = librosa.effects.pitch_shift(samples.astype(float), sr=sample_rate, n_steps=PITCH)
            
            audio_final = np.clip(samples * VOLUME, -1.0, 1.0).astype(np.float32)
            
            cable_idx = self.get_cable_device()
            
            self.is_speaking_audio = True
            
            def play_dev(dev_idx, update_mouth=False):
                try:
                    with sd.OutputStream(device=dev_idx, samplerate=sample_rate, channels=1, latency=0.2) as stream:
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
                    
            if cable_idx is not None:
                play_dev(cable_idx, True)
            else:
                play_dev(sd.default.device[1], True)
                
            self.is_speaking_audio = False
            
        except Exception as e:
            self.is_speaking_audio = False
            print("TTS Error:", e)

    def play_song_blocking(self, filename):
        import os
        import miniaudio
        import sounddevice as sd
        import numpy as np
        
        filepath = os.path.join("songs", filename)
        if not os.path.exists(filepath):
            self.append_chat("System", f"Song file not found: {filename}")
            return
            
        try:
            self.set_status(f"Singing {filename}...")
            self.is_speaking_audio = True
            
            decoded = miniaudio.decode_file(filepath, nchannels=1, sample_rate=24000)
            samples = np.frombuffer(decoded.samples, dtype=np.int16)
            channels = 1
            sample_rate = 24000
            
            audio_final = (samples.astype(np.float32) / 32768.0) * VOLUME
            audio_final = audio_final.reshape(-1, 1)
                
            cable_idx = self.get_cable_device()
            
            def play_dev(dev_idx, update_mouth=False):
                try:
                    with sd.OutputStream(device=dev_idx, samplerate=sample_rate, channels=channels, latency=0.2) as stream:
                        chunk_size = int(sample_rate * 0.05)
                        for i in range(0, len(audio_final), chunk_size):
                            chunk = audio_final[i:i+chunk_size]
                            
                            if update_mouth:
                                rms = np.sqrt(np.mean(np.square(chunk)))
                                target_open = min(1.0, (rms - 0.02) * 6) if rms > 0.02 else 0.0
                                self.current_mouth_open += (target_open - self.current_mouth_open) * 0.6
                                
                            stream.write(chunk)
                except Exception as e:
                    print(f"Stream Error: {e}")
            
            if cable_idx is not None:
                play_dev(cable_idx, True)
            else:
                play_dev(sd.default.device[1], True)
                
            self.is_speaking_audio = False
            self.set_status("Ready")
        except Exception as e:
            self.append_chat("System", f"Error playing song: {e}")
            self.is_speaking_audio = False

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
