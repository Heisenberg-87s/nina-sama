from kokoro_onnx import Kokoro
try:
    k = Kokoro('kokoro-v1.0.onnx', 'voices-neuro.bin')
    text = "What's going on?"
    s, r = k.create(text, voice='neuro_sama', speed=1.0, lang='en-us')
    print('Len:', len(s))
except Exception as e:
    print(f"Error: {e}")
