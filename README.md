# AI Typer V2

Voice dictation with multimodal AI cleanup. Speak naturally, get polished text.

## What It Does

Records your voice, sends the audio to a multimodal AI model (Gemini via OpenRouter), and gets back clean, well-formatted text in a single pass. No separate speech-to-text step — the AI handles both transcription and cleanup simultaneously.

The model automatically detects what you're dictating (email, shopping list, meeting notes, etc.) and formats it appropriately. You can also force a specific format if you want.

## Key Features

- **Single-pass multimodal transcription** — audio goes directly to Gemini, which transcribes AND cleans up in one API call
- **Smart format detection** — the model figures out if you're dictating an email, a list, notes, etc.
- **Voice Activity Detection (VAD)** — strips silence before sending to the API (saves cost and time)
- **Automatic Gain Control (AGC)** — normalizes audio levels for consistent results
- **Second-pass review** — optional coherence check catches misheard words
- **Global hotkeys** — works system-wide, even when the app is minimized (F13-F24 keys)
- **Append mode** — record multiple segments, then transcribe them together
- **Output flexibility** — show in app, copy to clipboard, or type directly at cursor

## Quick Start

```bash
# Clone and run
git clone https://github.com/danielrosehill/AI-Typer-V2.git
cd AI-Typer-V2
chmod +x run.sh
./run.sh
```

On first run, you'll be prompted to enter your [OpenRouter API key](https://openrouter.ai).

### System Dependencies (Ubuntu/Debian)

```bash
sudo apt install python3 python3-venv ffmpeg portaudio19-dev
# For VAD:
sudo apt install libc++1
# For clipboard:
sudo apt install wl-clipboard   # Wayland
# For text injection:
sudo apt install ydotool
```

## Usage

### Simple Workflow
1. Press **Record** (or your hotkey, default F15)
2. Speak naturally
3. Press **Stop** — transcription appears automatically

### Append Workflow
1. Press **F16** to start recording
2. Press **F16** again to stop and cache the audio
3. Press **F19** to record another segment
4. Press **F17** to transcribe all segments together
5. Press **F18** to clear the cache

### Format & Tone
- **Format dropdown**: Auto-detect (default), General, Email, To-Do, Meeting Notes, Bullets, Technical
- **Tone dropdown**: Casual, Neutral, Professional
- These are applied at transcription time — you can change them between recording and transcribing

## Configuration

Settings are stored in `~/.config/ai-typer-v2/config.json`.

Access via **File → Settings** or **Ctrl+,**.

### Hotkeys

| Function | Default | Description |
|----------|---------|-------------|
| Toggle | F15 | Start recording, or stop and transcribe |
| Tap Toggle | F16 | Start recording, or stop and cache |
| Transcribe | F17 | Transcribe cached audio |
| Clear | F18 | Clear recording and cache |
| Append | F19 | Start a new recording segment |
| Pause | F20 | Pause/resume recording |

Hotkeys work globally on Wayland via evdev (reads from input-remapper devices). Falls back to pynput/X11 on other systems.

## Compatible Models

AI Typer V2 works with any OpenRouter model that accepts audio input and produces text output. The following models are currently available with this modality:

| Model | ID |
|-------|----|
| Xiaomi MiMo V2 Omni | `xiaomi/mimo-v2-omni` |
| Gemini 3.1 Flash-Lite Preview | `google/gemini-3.1-flash-lite-preview` |
| GPT Audio | `openai/gpt-audio` |
| GPT Audio Mini | `openai/gpt-audio-mini` |
| Gemini 3 Flash Preview | `google/gemini-3-flash-preview` |
| Voxtral Small 24B | `mistralai/voxtral-small-24b-2507` |
| GPT-4o Audio Preview | `openai/gpt-4o-audio-preview` |
| Gemini 2.5 Flash-Lite | `google/gemini-2.5-flash-lite` |
| Gemini 2.5 Flash | `google/gemini-2.5-flash` |
| Healer Alpha | `openrouter/healer-alpha` |

Browse the full list at [openrouter.ai/models](https://openrouter.ai/models?input_modalities=audio&output_modalities=text).

## Architecture

```
app/src/
├── main.py              # PyQt6 UI (single window, no tabs)
├── config.py            # Configuration and prompt building
├── audio_recorder.py    # PyAudio recording
├── audio_processor.py   # AGC + VAD + compression pipeline
├── vad_processor.py     # TEN VAD silence removal
├── transcription.py     # OpenRouter API client
├── hotkeys.py           # Global hotkeys (evdev + pynput)
└── clipboard.py         # Clipboard operations
```

## How It Works

1. **Record** audio from microphone (PyAudio)
2. **VAD** strips silence segments (TEN VAD)
3. **AGC** normalizes volume levels
4. **Compress** to 16kHz mono WAV
5. **Send** audio + cleanup prompt to Gemini via OpenRouter
6. **Review** (optional) — second pass catches misheard words
7. **Output** — display in app, copy to clipboard, or type at cursor

## License

MIT
