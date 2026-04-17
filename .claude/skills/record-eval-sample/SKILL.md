---
name: record-eval-sample
description: Generate a ~30-second dictation script, show it to Daniel, then trigger the mic recorder to capture him reading it aloud for bitrate/model A/B evaluation. Triggers on "record an eval sample", "new eval sample", "record a sample for evals", "capture dictation sample", "generate eval script and record".
---

# Record Eval Sample

Used to produce paired `(audio.wav, reference.txt)` samples in `evals/samples/` for the bitrate sweep harness (`evals/bitrate_sweep.py`). Each sample is Daniel reading a script aloud — the script is the ground truth that WER is computed against.

## Workflow

### 1. Generate a dictation script

Generate a **~30-second spoken-word script** (roughly 70-90 words — natural speaking pace is ~150 wpm, so aim for the low end to leave headroom). The script should:

- Sound like something Daniel would actually dictate — an email, a note, a bug report, a quick thought. Not a Wikipedia article.
- Include at least one mildly tricky element for ASR: a proper noun, a technical term, a number, a date, or an acronym. This is what exposes bitrate degradation.
- Be clean, well-formed English — no filler words, no self-corrections. Daniel will read it verbatim, so the reference text needs to be what a perfect transcription would look like.
- Vary in style across samples. If previous samples in `evals/samples/` are professional emails, generate something else (technical notes, casual message, list).

Ask Daniel if he wants to tweak the script before recording. Small edits are fine — just re-save the final version to the reference file.

### 2. Pick a sample name

Short kebab-case, topical: `quick-email`, `bug-report-terse`, `dense-numbers`, `israeli-names`. Check `evals/samples/` for existing names to avoid collisions.

### 3. Trigger the recorder

Run the recorder CLI — it handles the countdown, mic capture, and file saving:

```bash
python3 -m evals.record_sample \
  --name <sample-name> \
  --duration 30 \
  --text "<the generated script>"
```

Notes:
- `--duration` should match the expected read time. For ~80 words at natural pace, 30s is right. For longer scripts, bump to 45 or 60.
- `--countdown 5` is the default; Daniel can lower it to 3 if he's in a hurry.
- If the sample name already exists, pass `--force` to overwrite (ask first).
- The CLI prints the script on stdout before the countdown so Daniel can read from the terminal.

### 4. Offer next steps

After recording completes, offer:

- **Run the sweep now**: `python3 -m evals.bitrate_sweep --sample evals/samples/<name>.wav` — transcribes at 24/32/64 kbps and writes a report with WER.
- **Record another sample**: loop back to step 1 with a different style/topic.
- **Batch-run sweep across all samples**: iterate `evals/samples/*.wav` and sweep each.

## Constraints

- **Do not check in samples**: `evals/samples/` is gitignored. Samples may contain personal content and are local-only.
- **Do not modify the reference text after recording**: the whole point is that the text file matches what was read aloud. If Daniel flubbed the read, re-record with `--force`.
- **Mic permissions**: the recorder uses PyAudio against the default input device. If it fails, check that no other app (the main Voice Typer window, browser tabs) is holding the mic.
