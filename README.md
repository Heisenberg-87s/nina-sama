# Nina-sama AI VTuber Project

This repository contains the backend and UI for Nina-sama, a chaotic AI VTuber integrated with VTube Studio, Ollama, and Kokoro ONNX for text-to-speech.

## Prerequisites

Because of GitHub's file size limits, the large AI models are **not** included in this repository. You must download them manually before running the project.

1. **Ollama**: Install [Ollama](https://ollama.com/) and create the `nina-sama` custom model using your Modelfile.
2. **Kokoro ONNX Models**: Download the Kokoro ONNX model and voice bins:
   - `kokoro-v1.0.onnx`
   - `voices-neuro.bin`
   Place these files in the root directory of this project.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Heisenberg-87s/nina-sama.git
   cd nina-sama
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Install UI dependencies:
   ```bash
   cd nina-ui
   npm install
   ```

## Running the Application

You can use the provided batch script to launch both the backend and the UI simultaneously:

```bash
Launch_Nina.bat
```

Alternatively, you can run them separately:

**Backend:**
```bash
python nina_backend.py
```

**UI:**
```bash
cd nina-ui
npm run dev
```

## Setup VTube Studio
1. Open VTube Studio and enable the API on port `8001`.
2. Ensure you have the VB-Audio Virtual Cable installed if you want to route audio to Discord/Voicemod.
3. Configure your hotkeys (e.g., naming a hotkey "wink" for the `*wink*` action).
