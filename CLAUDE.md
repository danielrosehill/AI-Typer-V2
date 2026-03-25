# CLAUDE.md - AI Typer V2

## Project Overview

AI Typer V2 is a simplified PyQt6 desktop application for voice dictation with AI-powered transcription cleanup. It sends audio directly to multimodal AI models (Gemini via OpenRouter) along with a cleanup prompt — the model handles both transcription and text cleanup in a single pass.

This is a fresh start based on the learnings from AI-Transcription-Notepad (Voice Notepad V3), keeping the proven audio pipeline and transcription engine while dramatically simplifying the UI and configuration.

**Original app (V3)**: `~/repos/github/AI-Transcription-Notepad/` — the predecessor with full-featured UI including system tray with state icons, context menu, translation mode, segment indicators, mic selector, and tabbed settings. When porting features from V3, reference that repo's `app/src/` directory for implementation patterns.

## Core Concept

**Single multimodal pass**: Audio goes to Gemini, which transcribes AND cleans up simultaneously. No separate ASR + LLM stages. The cleanup prompt handles filler word removal, punctuation, paragraph spacing, grammar fixes, and smart format detection.

**Auto-detect by default**: The model infers what you're dictating (email, list, notes, etc.) and formats accordingly. Format/tone overrides are available but not required.

## Architecture

```
app/src/
├── main.py              # PyQt6 UI — single window, no tabs
├── config.py            # Config, prompt building, format presets
├── audio_recorder.py    # PyAudio microphone recording
├── audio_processor.py   # AGC + VAD + compression pipeline
├── vad_processor.py     # TEN VAD silence removal
├── transcription.py     # OpenRouter API client (multimodal)
├── hotkeys.py           # Global hotkeys (evdev + pynput)
└── clipboard.py         # wl-copy / xclip clipboard ops
```

## Running

```bash
./run.sh
```

## Development Guidelines

- Keep the UI simple — single window, no tabs, minimal controls
- Format/style features should be frictionless — auto-detect is the default
- The cleanup prompt is the core value — changes should be carefully tested
- Backend audio pipeline (recorder, processor, VAD) is proven code from V3 — modify carefully
- All models accessed via OpenRouter (no direct Gemini/Google API)
- **After debugging/changes: always rebuild the .deb and install** (`./build.sh --dev`). This is a persistent preference — every fix or feature change should end with a fresh build + install cycle.

## Environment Variables

```
GEMINI_API_KEY=your_key
```

## Building

```bash
./build.sh --deb    # Build .deb package
./build.sh --dev    # Fast dev build + install
```
