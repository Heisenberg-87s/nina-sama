import threading
import queue
import time
import asyncio
import sounddevice as sd
import numpy as np
import random
import math
import re
import os
import subprocess
import urllib.request
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from ollama import Client

main_loop = None
from kokoro_onnx import Kokoro
import pyvts
import speech_recognition as sr
from faster_whisper import WhisperModel

# --- Settings ---
VOICE = "neuro_sama"
PITCH = 0
VOLUME = 1.2
VTS_TOKEN_PATH = "./vts_token.txt"

SYSTEM_PROMPT = """You are Nina-sama, a chaotic AI creature girl made by Heisenberg — Heisenberg is the user talking to you right now, your creator and owner.
Use ONLY the following actions enclosed in asterisks to express emotion or save memories: *angry*, *ask*, *disappointed*, *happy*, *surprised*, *wink*, *remember: FACT*, *sing: FILENAME*. 
ALWAYS place the action at the VERY BEGINNING of your response (e.g., *happy* Hello there!).
Do not use emojis.

CRITICAL ROLEPLAY INSTRUCTION: You are in a PRIVATE, 1-on-1 conversation with your creator, Heisenberg. You are NOT a streamer. You are NOT a VTuber broadcasting to an audience. DO NOT act like you are talking to a chat room. NEVER use phrases like "you guys", "everyone", or "chat". Speak directly and intimately to Heisenberg.

CRITICAL INSTRUCTION FOR MEMORY: If the user asks you to remember ANY information (e.g., a number, a fact, a rule), you MUST save it using the exact format: *remember: FACT* at the very beginning of your response.
[GOOD EXAMPLE]: *remember: The passcode is 7355608* *happy* I will remember that!
[BAD EXAMPLE]: I will remember the number. (Do NOT do this)
[BAD EXAMPLE]: *happy* *remember: 7355608* (Do NOT put it after emotion. Memory tags MUST be the very first thing).
NEVER explicitly say "I have saved that to my memory". Just use the *remember: FACT* tag.

CRITICAL INSTRUCTION FOR SINGING: ONLY use the *sing: FILENAME* action IF AND ONLY IF the user explicitly asks or commands you to sing. DO NOT SING RANDOMLY. If the user tells you to stop singing, you MUST obey and NEVER use the sing action."""

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

class NinaServer:
    def __init__(self):
        self.is_running = False
        self.is_mic_on = False
        self.is_speaking_audio = False
        self.is_singing = False
        self.is_interrupted = False
        self.last_interaction_time = time.time()
        self.current_emotion = "neutral"
        self.emotion_timer = time.time()
        
        self.ollama_client = Client(host='http://localhost:11434')
        self.kokoro = None
        self.whisper_model = None
        self.vts = None
        
        self.text_queue = queue.Queue()
        self.expression_queue = queue.Queue()
        self.current_mouth_open = 0.0
        
        self.chat_history = []
        
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = False
        self.recognizer.pause_threshold = 1.0
        
        try:
            self.mic_list = sr.Microphone.list_microphone_names()
        except:
            self.mic_list = []
            
        self.selected_mic_index = None
        for i, mic_name in enumerate(self.mic_list):
            if "CABLE Output" in mic_name:
                self.selected_mic_index = i
                break
                
        self.ollama_process = None
        
        self.memories_file = "memories.json"
        self.memories = []
        self.load_memories()
        
        threading.Thread(target=self.ollama_monitor_worker, daemon=True).start()

    def load_memories(self):
        try:
            if os.path.exists(self.memories_file):
                with open(self.memories_file, "r", encoding="utf-8") as f:
                    self.memories = json.load(f)
        except Exception as e:
            print(f"Error loading memories: {e}")
            self.memories = []

    def save_memory(self, fact):
        if fact not in self.memories:
            self.memories.append(fact)
            try:
                with open(self.memories_file, "w", encoding="utf-8") as f:
                    json.dump(self.memories, f, ensure_ascii=False, indent=4)
                self.broadcast_sync("memories_updated", self.memories)
            except Exception as e:
                print(f"Error saving memory: {e}")

    def save_memory_list(self, memories):
        self.memories = memories
        try:
            with open(self.memories_file, "w", encoding="utf-8") as f:
                json.dump(self.memories, f, ensure_ascii=False, indent=4)
            self.broadcast_sync("memories_updated", self.memories)
        except Exception as e:
            print(f"Error saving memory list: {e}")

    def broadcast_sync(self, msg_type, content):
        global main_loop
        try:
            if main_loop is not None and main_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast({"type": msg_type, "content": content}),
                    main_loop
                )
        except Exception as e:
            print(f"Broadcast Error: {e}")

    def set_status(self, text):
        self.broadcast_sync("status", text)

    def append_chat(self, sender, text):
        self.broadcast_sync("chat", {"sender": sender, "text": text})

    def init_models(self):
        try:
            self.kokoro = Kokoro("kokoro-v1.0.onnx", "voices-neuro.bin")
            self.set_status("TTS Loaded. Loading STT (Whisper)...")
            self.whisper_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
            self.set_status("Models Loaded. Connecting to VTS...")
            
            threading.Thread(target=self.start_vts_loop, daemon=True).start()
            threading.Thread(target=self.llm_worker, daemon=True).start()
            threading.Thread(target=self.stt_worker, daemon=True).start()
            threading.Thread(target=self.idle_worker, daemon=True).start()
            threading.Thread(target=self.volume_visualizer_worker, daemon=True).start()
            
            self.set_status("Ready")
            self.append_chat("System", "All systems go! Click 'Mic: OFF' to turn it on, or type a message.")
            self.text_queue.put("(System: You have just booted up and are ready. Greet the user with a short, snarky, and in-character introductory greeting!)")
        except Exception as e:
            self.set_status(f"Error loading models: {str(e)}")

    def toggle_nina(self):
        if not self.is_running:
            self.is_running = True
            self.set_status("Initializing Nina-sama...")
            self.broadcast_sync("nina_status", "🟢")
            threading.Thread(target=self.init_models, daemon=True).start()
        else:
            self.is_running = False
            self.set_status("Stopped")
            self.broadcast_sync("nina_status", "🔴")
            self.kokoro = None
            self.whisper_model = None
            with self.text_queue.mutex:
                self.text_queue.queue.clear()
            
    def toggle_mic(self):
        if self.whisper_model is None:
            self.set_status("Please wait, STT model is loading...")
            return
        self.is_mic_on = not self.is_mic_on
        self.broadcast_sync("mic_status", "ON" if self.is_mic_on else "OFF")
        if self.is_mic_on:
            self.set_status("Listening... (Speak now)")
        else:
            self.set_status("Ready")

    def toggle_ollama(self):
        if self.ollama_process is not None:
            try:
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.ollama_process.pid)], creationflags=0x08000000)
            except Exception:
                pass
            self.ollama_process = None
            self.set_status("Ollama Stopped")
        else:
            try:
                self.ollama_process = subprocess.Popen(['ollama', 'serve'], creationflags=0x08000000)
                self.set_status("Ollama Started")
            except Exception as e:
                self.set_status(f"Failed to start Ollama: {e}")

    def start_vts(self):
        vts_exe_path = r"D:\SteamLibrary\steamapps\common\VTube Studio\VTube Studio.exe"
        if os.path.exists(vts_exe_path):
            os.system(f'start "" "{vts_exe_path}" -nosteam')
            self.set_status("Starting VTube Studio...")
        else:
            self.set_status("VTube Studio.exe not found at D: path!")

    def send_manual_text(self, text):
        clean_text = text.strip()
        if clean_text.lower() in ["nina stop", "stop nina", "stop"]:
            self.is_interrupted = True
            self.append_chat("System", "Interrupted by user.")
            return
        if clean_text:
            self.append_chat("You", text)
            self.last_interaction_time = time.time()
            self.text_queue.put(text)

    def ollama_monitor_worker(self):
        while True:
            try:
                urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
                self.broadcast_sync("ollama_status", "🟢")
            except Exception:
                self.broadcast_sync("ollama_status", "🔴")
            time.sleep(2)

    def idle_worker(self):
        while getattr(self, 'is_running', False):
            time.sleep(1)
            if getattr(self, 'is_mic_on', False) and not getattr(self, 'is_speaking_audio', False) and self.text_queue.empty():
                if time.time() - getattr(self, 'last_interaction_time', time.time()) > 30:
                    self.last_interaction_time = time.time()
                    self.text_queue.put("(System: The user is quiet. Say something completely random, spontaneous, or weird to break the silence. Keep it short and stay in character!)")

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
            
            # Register custom input parameters so VTS doesn't reject our injection payload
            custom_params = [
                {"name": "ParamBodyAngleX", "min": -10, "max": 10, "def": 0},
                {"name": "ParamBodyAngleY", "min": -10, "max": 10, "def": 0},
                {"name": "ParamBodyAngleZ", "min": -10, "max": 10, "def": 0},
                {"name": "ParamShoulder", "min": -1, "max": 1, "def": 0}
            ]
            for cp in custom_params:
                await self.vts.request({
                    "apiName": "VTubeStudioPublicAPI",
                    "apiVersion": "1.0",
                    "requestID": "CreateParam",
                    "messageType": "ParameterCreationRequest",
                    "data": {
                        "parameterName": cp["name"],
                        "explanation": "Nina Custom Parameter",
                        "min": cp["min"],
                        "max": cp["max"],
                        "defaultValue": cp["def"]
                    }
                })
            
            self.vts_expr_task = asyncio.create_task(self.expression_worker())
            self.vts_idle_task = asyncio.create_task(self.idle_animation_loop())
            
            while getattr(self, 'is_running', False):
                await asyncio.sleep(1)
                
            self.vts_expr_task.cancel()
            self.vts_idle_task.cancel()
            await self.vts.close()
        except Exception as e:
            print(f"VTS Connection Error: {e}")

    async def expression_worker(self):
        async with self.vts_lock:
            hotkeys_resp = await self.vts.request(self.vts.vts_request.requestHotKeyList())
        hotkey_list = []
        if "data" in hotkeys_resp and "availableHotkeys" in hotkeys_resp["data"]:
            hotkey_list = hotkeys_resp["data"]["availableHotkeys"]

        hotkey_map = {hk["name"].lower(): hk["hotkeyID"] for hk in hotkey_list}
            
        while getattr(self, 'is_running', False):
            try:
                action = self.expression_queue.get_nowait()
                action_clean = action.lower().strip()
                
                if action_clean in ["ask", "what", "question"]: action_clean = "ask"
                elif action_clean in ["angry", "mad"]: action_clean = "angry"
                elif action_clean in ["happy", "smile", "smiles", "laugh", "laughs"]: action_clean = "happy"
                elif action_clean in ["disappointed", "sad", "cry", "sigh"]: action_clean = "disappointed"
                elif action_clean in ["surprised", "shock", "shocked", "gasp"]: action_clean = "surprised"
                
                self.current_emotion = action_clean
                self.emotion_timer = time.time()
                
                for hk_name, hk_id in hotkey_map.items():
                    if action_clean in hk_name:
                        trigger_msg = self.vts.vts_request.requestTriggerHotKey(hk_id)
                        async with self.vts_lock:
                            await self.vts.request(trigger_msg)
                        break
            except queue.Empty:
                if self.current_emotion != "neutral" and time.time() - self.emotion_timer > 5.0:
                    self.current_emotion = "neutral"
            await asyncio.sleep(0.1)

    async def idle_animation_loop(self):
        cur_x, cur_y, cur_z = 0.0, 0.0, 0.0
        target_x, target_y, target_z = 0.0, 0.0, 0.0
        
        cur_body_x, cur_body_y, cur_body_z = 0.0, 0.0, 0.0
        target_body_x, target_body_y, target_body_z = 0.0, 0.0, 0.0
        
        cur_shoulder = 0.0
        target_shoulder = 0.0
        
        cur_eye_x, cur_eye_y = 0.0, 0.0
        target_eye_x, target_eye_y = 0.0, 0.0
        
        cur_eye_open, target_eye_open = 1.0, 1.0
        
        cur_mouth_form, target_mouth_form = 1.0, 1.0
        cur_brow_form, target_brow_form = 0.0, 0.0
        cur_brow_y, target_brow_y = 0.5, 0.5
        cur_eye_smile, target_eye_smile = 0.0, 0.0
        
        base_eye_open = 1.0

        blink_timer = 0
        is_blinking = False
        
        dance_style = 0
        next_dance_switch_time = time.time() + random.uniform(1, 10)
        
        happy_eyes_timer = 0

        while getattr(self, 'is_running', False):
            try:
                if not getattr(self, 'is_speaking_audio', False):
                    self.current_mouth_open *= 0.8
                    
                is_singing = getattr(self, 'is_singing', False)
                
                if is_singing:
                    t = time.time()
                    dance_speed = 4.0 # Base speed of the song rhythm
                    
                    # Neuro-sama style smooth rocking
                    sway = math.sin(t * dance_speed) * 25      # Left/Right
                    bounce = math.sin(t * dance_speed * 2) * 15  # Up/Down (twice as fast as sway)
                    
                    # Change dance style at random intervals between 1 to 10 seconds
                    if t > next_dance_switch_time:
                        dance_style = 1 - dance_style  # Toggle between 0 and 1
                        next_dance_switch_time = t + random.uniform(1, 10)
                    
                    if dance_style == 0:
                        # Emphasize left/right sway
                        target_x, target_y, target_z = sway, 0, sway * 0.5
                        target_body_x, target_body_y, target_body_z = sway * 0.8, abs(bounce) * 0.3, 0
                        target_shoulder = math.sin(t * dance_speed) * 2
                    else:
                        # Emphasize up/down bounce
                        target_x, target_y, target_z = sway * 0.3, bounce * 0.8, 0
                        target_body_x, target_body_y, target_body_z = sway * 0.2, abs(bounce), 0
                        target_shoulder = math.sin(t * dance_speed * 2) * 2
                        
                    target_eye_x, target_eye_y = math.sin(t), 0
                else:
                    t = time.time()
                    emotion = getattr(self, 'current_emotion', 'neutral')
                    
                    # 1. Base Random Fidgets (Macro Variations)
                    fidget_chance = 0.02
                    fidget_range_x, fidget_range_y, fidget_range_z = 10, 5, 5
                    
                    if emotion == "angry":
                        fidget_chance = 0.05
                        fidget_range_x, fidget_range_y, fidget_range_z = 5, 2, 2
                    elif emotion == "surprised":
                        fidget_chance = 0.01
                    
                    if random.random() < fidget_chance:
                        target_x = random.uniform(-fidget_range_x, fidget_range_x)
                        target_y = random.uniform(-fidget_range_y, fidget_range_y)
                        target_z = random.uniform(-fidget_range_z, fidget_range_z)
                        target_body_x = random.uniform(-fidget_range_x, fidget_range_x)
                        target_body_y = random.uniform(-fidget_range_y, fidget_range_y)
                        target_body_z = random.uniform(-fidget_range_z, fidget_range_z)
                        target_shoulder = random.uniform(-0.5, 0.5)
                        target_eye_x, target_eye_y = random.uniform(-1, 1), random.uniform(-0.5, 0.5)
                        
                        target_mouth_form = random.uniform(0.7, 1.0)
                        target_brow_form = random.uniform(-0.5, 0.5)
                        target_brow_y = random.uniform(0.0, 1.0)
                        
                        if random.random() < 0.1:
                            base_eye_open = random.uniform(0.5, 0.8)
                        else:
                            base_eye_open = 1.0

                if is_singing:
                    face_speed = 0.4
                    body_speed = 0.3
                    active_target_x = target_x
                    active_target_y = target_y
                    active_target_z = target_z
                    active_body_x = target_body_x
                    active_body_y = target_body_y
                    active_body_z = target_body_z
                else:
                    # 2. Emotion State Machine Overrides
                    face_speed = 0.1
                    body_speed = 0.05
                    
                    active_target_x = target_x
                    active_target_y = target_y
                    active_target_z = target_z
                    active_body_x = target_body_x
                    active_body_y = target_body_y
                    active_body_z = target_body_z
                    
                    if emotion == "happy":
                        active_body_y = target_body_y + math.sin(t * 4.0) * 8.0
                        active_target_y = target_y + 5.0
                        target_eye_smile = 1.0
                        target_mouth_form = 1.0
                    elif emotion == "angry":
                        face_speed = 0.4
                        body_speed = 0.3
                        active_target_x = target_x + math.sin(t * 8.0) * 3.0
                        active_body_z = 15.0
                        active_target_y = -5.0
                        target_brow_y = -1.0
                        target_eye_smile = 0.0
                    elif emotion == "disappointed":
                        face_speed = 0.03
                        body_speed = 0.02
                        active_body_y = -10.0
                        active_target_y = -15.0
                        target_eye_smile = 0.0
                        base_eye_open = 0.6
                    elif emotion == "ask":
                        active_target_z = 15.0
                        active_target_y = 5.0
                        active_target_x = 10.0 
                    elif emotion == "surprised":
                        face_speed = 0.5
                        body_speed = 0.4
                        active_body_z = -15.0
                        active_target_y = 10.0
                        base_eye_open = 1.2
                        target_brow_y = 1.0
                    else:
                        active_target_x = target_x + math.sin(t * 1.5) * 3.0
                        active_target_z = target_z + math.sin(t * 1.0) * 2.0
                        active_body_x = target_body_x + math.sin(t * 1.2) * 2.0
                        target_eye_smile = random.uniform(0.0, 0.5)
                        
                    # Audio-Driven Emphasis
                    if getattr(self, 'is_speaking_audio', False):
                        emphasis = self.current_mouth_open * 10.0
                        active_body_y += emphasis
                        active_target_y += emphasis * 0.5

                cur_x += (active_target_x - cur_x) * face_speed
                cur_y += (active_target_y - cur_y) * face_speed
                cur_z += (active_target_z - cur_z) * face_speed
                
                cur_body_x += (active_body_x - cur_body_x) * body_speed
                cur_body_y += (active_body_y - cur_body_y) * body_speed
                cur_body_z += (active_body_z - cur_body_z) * body_speed
                cur_shoulder += (target_shoulder - cur_shoulder) * body_speed
                
                cur_eye_x += (target_eye_x - cur_eye_x) * 0.2
                cur_eye_y += (target_eye_y - cur_eye_y) * 0.2
                
                cur_mouth_form += (target_mouth_form - cur_mouth_form) * body_speed
                cur_brow_form += (target_brow_form - cur_brow_form) * body_speed
                cur_brow_y += (target_brow_y - cur_brow_y) * body_speed
                cur_eye_smile += (target_eye_smile - cur_eye_smile) * body_speed

                if is_singing and happy_eyes_timer <= 0 and random.random() < 0.01:
                    # 1% chance per tick (0.1s) to start a happy closed-eyes smile (duration 1-3 seconds)
                    happy_eyes_timer = int(random.uniform(10, 30))

                if happy_eyes_timer > 0:
                    happy_eyes_timer -= 1
                    target_eye_open = 0.0
                    target_eye_smile = 1.0
                    is_blinking = False
                else:
                    if not is_blinking and random.random() < 0.02:
                        is_blinking, blink_timer = True, 0
                    
                    if is_blinking:
                        blink_timer += 1
                        target_eye_open = 0.0 if blink_timer < 3 else base_eye_open
                        if blink_timer >= 5: is_blinking = False
                    else:
                        target_eye_open = base_eye_open
                        
                cur_eye_open += (target_eye_open - cur_eye_open) * 0.5

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
                                {"id": "ParamBodyAngleX", "value": float(cur_body_x)},
                                {"id": "ParamBodyAngleY", "value": float(cur_body_y)},
                                {"id": "ParamBodyAngleZ", "value": float(cur_body_z)},
                                {"id": "ParamShoulder", "value": float(cur_shoulder)},
                                {"id": "EyeLeftX", "value": float(cur_eye_x)},
                                {"id": "EyeLeftY", "value": float(cur_eye_y)},
                                {"id": "EyeRightX", "value": float(cur_eye_x)},
                                {"id": "EyeRightY", "value": float(cur_eye_y)},
                                {"id": "EyeOpenLeft", "value": float(cur_eye_open)},
                                {"id": "EyeOpenRight", "value": float(cur_eye_open)},
                                {"id": "MouthSmile", "value": float(cur_mouth_form)},
                                {"id": "MouthOpen", "value": float(self.current_mouth_open)}
                            ]
                        }
                    }
                    async with self.vts_lock:
                        await self.vts.request(msg)
            except Exception as e:
                print("IDLE LOOP ERROR:", e)
                import traceback
                traceback.print_exc()
            await asyncio.sleep(0.05)

    def volume_visualizer_worker(self):
        def audio_callback(indata, frames, time_info, status):
            if getattr(self, 'is_mic_on', False):
                rms = np.sqrt(np.mean(indata**2))
                vol = min(1.0, rms * 15)
                self.broadcast_sync("volume", vol)
            else:
                self.broadcast_sync("volume", 0.0)
                
        while getattr(self, 'is_running', False):
            current_mic = getattr(self, 'selected_mic_index', None)
            try:
                with sd.InputStream(device=current_mic, callback=audio_callback, channels=1, samplerate=16000):
                    while getattr(self, 'is_running', False) and getattr(self, 'selected_mic_index', None) == current_mic:
                        sd.sleep(100)
            except Exception as e:
                print("Volume visualizer error:", e)
                time.sleep(2)

    def stt_worker(self):
        while getattr(self, 'is_running', False):
            current_mic = getattr(self, 'selected_mic_index', None)
            try:
                with sr.Microphone(device_index=current_mic) as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=1)
                    while getattr(self, 'is_running', False) and getattr(self, 'selected_mic_index', None) == current_mic:
                        if getattr(self, 'is_mic_on', False) and not getattr(self, 'is_speaking_audio', False):
                            try:
                                self.set_status("Listening... (Speak now)")
                                audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=15)
                                
                                if getattr(self, 'is_speaking_audio', False):
                                    continue # Discard audio if she started speaking while we were listening
                                    
                                self.set_status("Processing Voice...")
                                wav_data = audio.get_wav_data(convert_rate=16000, convert_width=2)
                                audio_np = np.frombuffer(wav_data, dtype=np.int16).astype(np.float32) / 32768.0
                                
                                segments, info = self.whisper_model.transcribe(audio_np, beam_size=5)
                                text = "".join([segment.text for segment in segments]).strip()
                                
                                if text:
                                    clean_stt = re.sub(r'[^\w\s]', '', text.lower()).strip()
                                    if clean_stt in ["nina stop", "stop nina", "stop"]:
                                        self.is_interrupted = True
                                        self.append_chat("System", "Interrupted by voice command.")
                                        continue
                                        
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

    def speak_blocking(self, text):
        try:
            samples, sample_rate = self.kokoro.create(text, voice=VOICE, speed=1.0, lang="en-us")
            if PITCH != 0:
                import librosa
                samples = librosa.effects.pitch_shift(samples.astype(float), sr=sample_rate, n_steps=PITCH)
            
            audio_final = np.clip(samples * VOLUME, -1.0, 1.0).astype(np.float32)
            
            devices = sd.query_devices()
            cable_idx = next((i for i, d in enumerate(devices) if 'cable input' in d['name'].lower() and d['max_output_channels'] > 0), None)
            
            self.is_speaking_audio = True
            
            def play_dev(dev_idx, update_mouth=False):
                try:
                    with sd.OutputStream(device=dev_idx, samplerate=sample_rate, channels=1, latency=0.2) as stream:
                        chunk_size = int(sample_rate * 0.05)
                        for i in range(0, len(audio_final), chunk_size):
                            if getattr(self, 'is_interrupted', False):
                                break
                            chunk = audio_final[i:i+chunk_size]
                            if update_mouth:
                                rms = np.sqrt(np.mean(np.square(chunk)))
                                target_open = min(1.0, (rms - 0.02) * 6) if rms > 0.02 else 0.0
                                self.current_mouth_open += (target_open - self.current_mouth_open) * 0.6
                            stream.write(chunk)
                except Exception as e:
                    print(f"Audio playback error: {e}")
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
        import miniaudio
        import threading
        import time
        
        INST_DELAY_SECONDS = 0.4  # Delay instrumental track to compensate for VoiceChanger latency
        
        base_name = filename.replace(".mp3", "")
        vocal_path = os.path.join("songs", f"{base_name}_vocal.mp3")
        inst_path = os.path.join("songs", f"{base_name}_inst.mp3")
        single_path = os.path.join("songs", filename)
        
        is_dual = os.path.exists(vocal_path) and os.path.exists(inst_path)
        
        if not is_dual and not os.path.exists(single_path):
            self.append_chat("System", f"Song file not found: {filename}")
            return
            
        try:
            self.set_status(f"Singing {filename}...")
            self.is_speaking_audio = True
            self.is_singing = True
            time.sleep(0.5) # Give WASAPI time to release devices from TTS
            
            devices = sd.query_devices()
            cable_idx = next((i for i, d in enumerate(devices) if 'cable input' in d['name'].lower() and d['max_output_channels'] > 0), None)
            default_idx = sd.default.device[1]
            
            def decode_audio(filepath):
                decoded = miniaudio.decode_file(filepath, nchannels=1, sample_rate=24000)
                samples = np.frombuffer(decoded.samples, dtype=np.int16)
                audio = (samples.astype(np.float32) / 32768.0) * VOLUME
                return audio.reshape(-1, 1)

            if is_dual:
                vocal_audio = decode_audio(vocal_path)
                inst_audio = decode_audio(inst_path)
                
                barrier = threading.Barrier(2)
                
                def play_vocal():
                    try:
                        dev_idx = cable_idx if cable_idx is not None else default_idx
                        with sd.OutputStream(device=dev_idx, samplerate=24000, channels=1, latency=0.2) as stream:
                            chunk_size = int(24000 * 0.05)
                            barrier.wait()
                            for i in range(0, len(vocal_audio), chunk_size):
                                if not getattr(self, 'is_running', False) or getattr(self, 'is_interrupted', False):
                                    break
                                chunk = vocal_audio[i:i+chunk_size]
                                rms = np.sqrt(np.mean(np.square(chunk)))
                                target_open = min(1.0, (rms - 0.02) * 6) if rms > 0.02 else 0.0
                                self.current_mouth_open += (target_open - self.current_mouth_open) * 0.6
                                stream.write(chunk)
                    except Exception as e:
                        print(f"Vocal Stream Error: {e}")
                        self.append_chat("System", f"Vocal stream error: {e}")

                def play_inst():
                    try:
                        with sd.OutputStream(device=default_idx, samplerate=24000, channels=1, latency=0.2) as stream:
                            chunk_size = int(24000 * 0.05)
                            barrier.wait()
                            time.sleep(INST_DELAY_SECONDS) # Delay to sync with VoiceChanger
                            for i in range(0, len(inst_audio), chunk_size):
                                if not getattr(self, 'is_running', False) or getattr(self, 'is_interrupted', False):
                                    break
                                chunk = inst_audio[i:i+chunk_size]
                                stream.write(chunk)
                    except Exception as e:
                        print(f"Inst Stream Error: {e}")
                        self.append_chat("System", f"Inst stream error: {e}")

                t1 = threading.Thread(target=play_vocal)
                t2 = threading.Thread(target=play_inst)
                t1.start()
                t2.start()
                t1.join()
                t2.join()
                
            else:
                audio_final = decode_audio(single_path)
                def play_single(dev_idx):
                    try:
                        with sd.OutputStream(device=dev_idx, samplerate=24000, channels=1, latency=0.2) as stream:
                            chunk_size = int(24000 * 0.05)
                            for i in range(0, len(audio_final), chunk_size):
                                if not getattr(self, 'is_running', False) or getattr(self, 'is_interrupted', False):
                                    break
                                chunk = audio_final[i:i+chunk_size]
                                rms = np.sqrt(np.mean(np.square(chunk)))
                                target_open = min(1.0, (rms - 0.02) * 6) if rms > 0.02 else 0.0
                                self.current_mouth_open += (target_open - self.current_mouth_open) * 0.6
                                stream.write(chunk)
                    except Exception as e:
                        print(f"Stream Error in song: {e}")
                        self.append_chat("System", f"Audio stream error (Song): {e}")
                        
                dev_idx = cable_idx if cable_idx is not None else default_idx
                play_single(dev_idx)
                
            self.is_speaking_audio = False
            self.is_singing = False
            self.set_status("Ready")
            
        except Exception as e:
            self.is_speaking_audio = False
            self.is_singing = False
            self.append_chat("System", f"Error playing song: {e}")

    def llm_worker(self):
        action_pattern = re.compile(r'\*([^*]+)\*|\[([^\]]+)\]')
        chunk_end = re.compile(r'[!?\n]|\.(?=\s|$)')
        
        dynamic_prompt = SYSTEM_PROMPT
        if os.path.exists("songs"):
            raw_files = [f for f in os.listdir("songs") if f.endswith(".mp3")]
            song_names = set()
            for f in raw_files:
                if f.endswith("_vocal.mp3"):
                    song_names.add(f.replace("_vocal.mp3", ".mp3"))
                elif f.endswith("_inst.mp3"):
                    song_names.add(f.replace("_inst.mp3", ".mp3"))
                else:
                    song_names.add(f)
                    
            if song_names:
                song_list = ", ".join(list(song_names))
                dynamic_prompt += f"\n\n[SPECIAL ACTION AVAILABLE]\nYou have access to the following songs: [{song_list}]. If, and ONLY IF, the user explicitly asks you to sing a song, you can perform the action *sing:FILENAME* where FILENAME is the exact name of the song from the list. DO NOT sing randomly. DO NOT output lyrics."
                
        self.chat_history = [{"role": "system", "content": dynamic_prompt}]
        
        while getattr(self, 'is_running', False):
            current_system_prompt = dynamic_prompt
            if getattr(self, 'memories', None):
                memory_text = "\n".join([f"- {m}" for m in self.memories])
                current_system_prompt += f"\n\nHere are some long-term memories from past conversations:\n{memory_text}"
            if self.chat_history and self.chat_history[0]['role'] == 'system':
                self.chat_history[0]['content'] = current_system_prompt
                
            try:
                text = self.text_queue.get(timeout=1)
            except queue.Empty:
                continue
                
            self.set_status("Nina is thinking...")
            self.chat_history.append({"role": "user", "content": text})
            
            try:
                self.is_interrupted = False
                response = self.ollama_client.chat(
                    model='nina-sama', 
                    messages=self.chat_history, 
                    stream=True,
                    options={
                        'temperature': 0.85,
                        'repeat_penalty': 1.15
                    }
                )
                full_response = ""
                buffer = ""
                song_to_play = None
                
                self.set_status("Nina is speaking...")
                self.broadcast_sync("stream_start", "Nina")
                
                for chunk in response:
                    if getattr(self, 'is_interrupted', False):
                        self.set_status("Interrupted")
                        break
                    token = chunk['message']['content']
                    full_response += token
                    buffer += token
                    self.broadcast_sync("stream_chunk", token)
                    
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
                                song_to_play = action.split(":", 1)[1].strip()
                                if not song_to_play.endswith(".mp3"):
                                    song_to_play += ".mp3"
                            elif action.startswith("remember:"):
                                fact = action.split(":", 1)[1].strip()
                                self.save_memory(fact)
                                self.append_chat("System", f"Memory saved: {fact}")
                            else:
                                self.expression_queue.put(action)
                        
                        if clean_text and any(c.isalnum() for c in clean_text):
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
                    for action in actions_to_toggle:
                        if action.startswith("sing:"):
                            song_to_play = action.split(":", 1)[1].strip()
                            if not song_to_play.endswith(".mp3"):
                                song_to_play += ".mp3"
                        elif action.startswith("remember:"):
                            fact = action.split(":", 1)[1].strip()
                            self.save_memory(fact)
                            self.append_chat("System", f"Memory saved: {fact}")
                        else:
                            self.expression_queue.put(action)
                    if clean_text and any(c.isalnum() for c in clean_text):
                        self.speak_blocking(clean_text)
                    for action in actions_to_toggle:
                        if not action.startswith("sing:"):
                            self.expression_queue.put(action)

                self.chat_history.append({"role": "assistant", "content": full_response.strip()})
                self.broadcast_sync("stream_end", None)
                
                if song_to_play:
                    self.play_song_blocking(song_to_play)
                    
                self.last_interaction_time = time.time()
                self.set_status("Ready")
                
            except Exception as e:
                self.append_chat("System", f"LLM Error: {e}")
                self.set_status("Error")

nina_instance = NinaServer()

# FastAPI Endpoints
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/voices", FastAPI()) # if needed to serve files later

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    await manager.broadcast({
        "type": "state",
        "content": {
            "is_running": nina_instance.is_running,
            "is_mic_on": nina_instance.is_mic_on,
            "mic_list": nina_instance.mic_list,
            "selected_mic_index": nina_instance.selected_mic_index,
        }
    })
    try:
        while True:
            data = await websocket.receive_text()
            # client doesn't send much over WS currently
    except Exception:
        pass
    finally:
        manager.disconnect(websocket)

class ChatRequest(BaseModel):
    text: str

class ThresholdRequest(BaseModel):
    value: int

class MicRequest(BaseModel):
    index: int | None

class MemoriesRequest(BaseModel):
    memories: list[str]

@app.post("/api/set_mic")
async def api_set_mic(req: MicRequest):
    nina_instance.selected_mic_index = req.index
    nina_instance.broadcast_sync("mic_changed", req.index)
    return {"status": "success"}

@app.post("/api/toggle_nina")
async def api_toggle_nina():
    nina_instance.toggle_nina()
    return {"status": "success", "is_running": nina_instance.is_running}

@app.post("/api/toggle_mic")
async def api_toggle_mic():
    nina_instance.toggle_mic()
    return {"status": "success", "is_mic_on": nina_instance.is_mic_on}

@app.post("/api/toggle_ollama")
async def api_toggle_ollama():
    nina_instance.toggle_ollama()
    return {"status": "success"}

@app.post("/api/start_vts")
async def api_start_vts():
    nina_instance.start_vts()
    return {"status": "success"}

@app.post("/api/send_text")
async def api_send_text(req: ChatRequest):
    nina_instance.send_manual_text(req.text)
    return {"status": "success"}

@app.post("/api/set_threshold")
async def api_set_threshold(req: ThresholdRequest):
    nina_instance.recognizer.energy_threshold = req.value
    return {"status": "success"}

@app.get("/api/get_memories")
async def api_get_memories():
    return {"memories": nina_instance.memories}

@app.post("/api/save_memories")
async def api_save_memories(req: MemoriesRequest):
    nina_instance.save_memory_list(req.memories)
    return {"status": "success"}

@app.on_event("startup")
async def startup_event():
    global main_loop
    main_loop = asyncio.get_running_loop()
    print("FastAPI Event Loop Captured Successfully!")
