# Evals — Audio Bitrate A/B Test

Harness for measuring how MP3 bitrate affects transcription accuracy on OpenRouter audio-LLMs.

## Purpose

The app currently encodes audio at **MP3 32kbps mono 16kHz** before upload. This folder lets you verify that choice is safe (vs. 64kbps) and explore whether we can go lower (24kbps) without accuracy loss.

The harness uses a dedicated **verbatim transcription prompt** — not the app's cleanup prompt — so differences between runs reflect audio-encoding quality rather than prompt-driven reformatting variance. WER is computed against your ground-truth reference text if provided.

## Workflow

1. **Record one or more reference clips** with `app/src/audio_recorder.py` (or any tool — must be WAV). Drop them into `evals/samples/`. Each sample should have a paired `<name>.reference.txt` containing the ground-truth text you dictated, so we can compute WER.
2. **Run the sweep**:
   ```bash
   python -m evals.bitrate_sweep --sample evals/samples/quick-email.wav \
     --model google/gemini-3.1-flash-lite-preview \
     --bitrates 24 32 64
   ```
3. **Inspect the report** written to `evals/results/<timestamp>/` — contains the transcription per bitrate, payload sizes, latencies, and (if a reference file exists) a word-error-rate vs. bitrate table.

## Layout

```
evals/
├── README.md              # this file
├── bitrate_sweep.py       # main harness — encodes + transcribes + reports
├── samples/               # your reference WAV recordings (gitignored)
│   └── <name>.wav
│   └── <name>.reference.txt    # optional ground-truth text for WER
└── results/               # timestamped run outputs (gitignored)
    └── 2026-04-17T14-30-00/
        ├── report.md
        ├── 24kbps.txt
        ├── 32kbps.txt
        └── 64kbps.txt
```

## Why run this locally instead of CI

- Needs real API key + real spend (small but nonzero — ~$0.001 per run at Flash Lite rates).
- Results are qualitative as much as quantitative — the report is meant to be eyeballed by Daniel, not gated in CI.
- Sample recordings may contain personal content and should not be checked in (`samples/` is gitignored).

## Adding more axes

The harness is structured so you can easily sweep a second variable — e.g. model at fixed bitrate — by passing multiple `--model` flags. See `bitrate_sweep.py` docstring.
