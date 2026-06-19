import ollama
import re
import sounddevice as sd
import numpy as np
import librosa
import asyncio
import threading
import queue
import time
import pyvts
import random
from kokoro_onnx import Kokoro

# ─── Settings ───────────────────────────────────────────
VOICE = "af_heart"
PITCH = 0
VOLUME = 1.2
# ────────────────────────────────────────────────────────

kokoro = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
vts = None
expression_queue = queue.Queue()

def get_cable_device():
    for i, dev in enumerate(sd.query_devices()):
        if 'CABLE Input' in dev['name'] and dev['max_output_channels'] > 0:
            return i
    return None

# ─── VTS Worker (แยก thread) ─────────────────────────────
async def idle_animation_loop():
    target_x, target_y, target_z = 0.0, 0.0, 0.0
    target_eye_x, target_eye_y = 0.0, 0.0
    
    cur_x, cur_y, cur_z = 0.0, 0.0, 0.0
    cur_eye_x, cur_eye_y = 0.0, 0.0

    blink_timer = 0
    is_blinking = False

    while True:
        try:
            if random.random() < 0.03:
                target_x = random.uniform(-15, 15)
                target_y = random.uniform(-10, 10)
                target_z = random.uniform(-10, 10)
                target_eye_x = random.uniform(-1, 1)
                target_eye_y = random.uniform(-1, 1)

            cur_x += (target_x - cur_x) * 0.1
            cur_y += (target_y - cur_y) * 0.1
            cur_z += (target_z - cur_z) * 0.1
            cur_eye_x += (target_eye_x - cur_eye_x) * 0.2
            cur_eye_y += (target_eye_y - cur_eye_y) * 0.2

            blink_timer += 1
            if not is_blinking and random.random() < 0.02:
                is_blinking = True
                blink_timer = 0
                
            eye_open = 1.0
            if is_blinking:
                if blink_timer < 3:
                    eye_open = 0.0
                else:
                    is_blinking = False

            if vts is not None:
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
                            {"id": "BrowRightY", "value": 0.5}
                        ]
                    }
                }
                await vts.request(msg)
        except Exception:
            pass

        await asyncio.sleep(0.05)

async def vts_main():
    global vts
    vts = pyvts.vts(plugin_info={"plugin_name": "Nina AI System", "developer": "Heisenberg", "authentication_token_path": "./vts_token.txt"})
    await vts.connect()
    await vts.request_authenticate_token()
    await vts.write_token()
    await vts.request_authenticate()
    print("VTube Studio connected!")

    hotkey_map = {}
    try:
        msg = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "GetHotkeys",
            "messageType": "HotkeysInCurrentModelRequest"
        }
        resp = await vts.request(msg)
        if "data" in resp and "availableHotkeys" in resp["data"]:
            for hk in resp["data"]["availableHotkeys"]:
                hotkey_map[hk["name"].lower()] = hk["hotkeyID"]
            print(f"Loaded {len(hotkey_map)} hotkeys from model.")
    except Exception as e:
        pass

    asyncio.create_task(idle_animation_loop())

    while True:
        try:
            expr = expression_queue.get_nowait()
            expr_lower = expr.lower().strip()
            
            for hk_name, hk_id in hotkey_map.items():
                if not hk_name:
                    continue
                if hk_name == expr_lower or hk_name in expr_lower.split():
                    trigger_msg = {
                        "apiName": "VTubeStudioPublicAPI",
                        "apiVersion": "1.0",
                        "requestID": "TriggerHotkey",
                        "messageType": "HotkeyTriggerRequest",
                        "data": {
                            "hotkeyID": hk_id
                        }
                    }
                    await vts.request(trigger_msg)
                    break
        except queue.Empty:
            pass
        except Exception:
            pass
            
        await asyncio.sleep(0.05)

def vts_worker():
    vts_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(vts_loop)
    vts_loop.run_until_complete(vts_main())

# ─── Speak ───────────────────────────────────────────────
def speak(text, semitones=PITCH):
    if not text.strip():
        return

    samples, sample_rate = kokoro.create(text, voice=VOICE, speed=1.0, lang="en-us")
    audio_shifted = librosa.effects.pitch_shift(
        samples.astype(float), sr=sample_rate, n_steps=semitones
    )
    audio_final = np.clip(audio_shifted * VOLUME, -1.0, 1.0).astype(np.float32)

    cable_idx = get_cable_device()
    
    def play_dev(dev_idx):
        try:
            with sd.OutputStream(device=dev_idx, samplerate=sample_rate, channels=1) as stream:
                stream.write(audio_final)
        except Exception:
            pass
            
    threads = []
    if cable_idx is not None:
        threads.append(threading.Thread(target=play_dev, args=(cable_idx,)))
    else:
        threads.append(threading.Thread(target=play_dev, args=(None,)))
        
    for t in threads: t.start()
    for t in threads: t.join()

# ─── Chat ────────────────────────────────────────────────
chat_history = []

def chat(prompt):
    global chat_history
    buffer = ""
    chunk_end = re.compile(r'[.!?,]')
    action_pattern = re.compile(r'\*([^*]+)\*|\[([^\]]+)\]')

    chat_history.append({"role": "user", "content": prompt})

    if len(chat_history) > 20:
        chat_history = chat_history[-20:]

    stream = ollama.chat(
        model="nina-sama",
        messages=chat_history,
        stream=True
    )

    full_response = ""
    for chunk in stream:
        token = chunk['message']['content']
        print(token, end='', flush=True)
        buffer += token
        full_response += token

        if chunk_end.search(token):
            actions_to_toggle = []
            for match in action_pattern.finditer(buffer):
                action = match.group(1) or match.group(2)
                actions_to_toggle.append(action)
                expression_queue.put(action)
            
            clean_text = action_pattern.sub('', buffer).strip()
            if clean_text:
                first_word = re.sub(r'[^a-z]', '', clean_text.split()[0].lower())
                if first_word in {"what", "when", "where", "why", "who", "how", "did", "do", "does", "is", "are", "can", "could", "would", "should"}:
                    actions_to_toggle.append("ask")
                    expression_queue.put("ask")
                speak(clean_text)
                
            for action in actions_to_toggle:
                expression_queue.put(action)
                
            buffer = ""

    if buffer.strip():
        actions_to_toggle = []
        for match in action_pattern.finditer(buffer):
            action = match.group(1) or match.group(2)
            actions_to_toggle.append(action)
            expression_queue.put(action)
        clean_text = action_pattern.sub('', buffer).strip()
        if clean_text:
            first_word = re.sub(r'[^a-z]', '', clean_text.split()[0].lower())
            if first_word in {"what", "when", "where", "why", "who", "how", "did", "do", "does", "is", "are", "can", "could", "would", "should"}:
                actions_to_toggle.append("ask")
                expression_queue.put("ask")
            speak(clean_text)
            
        for action in actions_to_toggle:
            expression_queue.put(action)
    print()
    
    chat_history.append({"role": "assistant", "content": full_response.strip()})

# ─── Start ───────────────────────────────────────────────
t = threading.Thread(target=vts_worker, daemon=True)
t.start()
time.sleep(2)

print("Nina-sama (Advanced Lipsync) is ready. Type 'exit' to quit.\n")

while True:
    user_input = input("You: ")
    if user_input.lower() == "exit":
        break
    chat(user_input)