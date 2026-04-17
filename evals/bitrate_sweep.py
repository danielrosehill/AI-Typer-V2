"""Bitrate sweep — transcribe one reference WAV at multiple MP3 bitrates.

Usage:
    python -m evals.bitrate_sweep --sample evals/samples/quick-email.wav
    python -m evals.bitrate_sweep --sample evals/samples/long-note.wav \\
        --model google/gemini-3.1-flash-lite-preview \\
        --bitrates 16 24 32 64

If a paired `<sample>.reference.txt` exists, WER is computed against it.
Otherwise the report just shows side-by-side transcriptions for eyeball review.
"""
import argparse
import io
import os
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pydub import AudioSegment  # noqa: E402

from app.src.transcription import get_client  # noqa: E402

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1

# Verbatim prompt — no cleanup, no reformatting. Isolates the bitrate variable
# by asking the model to report exactly what it heard. Any variation between
# bitrates should reflect audio quality, not prompt-driven editorial differences.
VERBATIM_PROMPT = """Transcribe the audio VERBATIM.

- Write exactly what was said, word for word, in the order spoken.
- Keep filler words ("um", "uh", "like", "you know") and false starts.
- Do NOT remove repetitions, self-corrections, or incomplete sentences.
- Do NOT rephrase, summarize, or reformat.
- Do NOT add headings, bullets, paragraphs, or markdown.
- Add only basic sentence punctuation (periods, commas, question marks) and capitalization at sentence starts.
- Output plain text only. No preamble, no commentary."""


def encode_mp3(wav_path: Path, bitrate_kbps: int) -> bytes:
    """Load WAV, resample to 16kHz mono, encode as MP3 at given bitrate."""
    audio = AudioSegment.from_wav(wav_path)
    if audio.channels > 1:
        audio = audio.set_channels(TARGET_CHANNELS)
    if audio.frame_rate != TARGET_SAMPLE_RATE:
        audio = audio.set_frame_rate(TARGET_SAMPLE_RATE)
    buf = io.BytesIO()
    audio.export(buf, format="mp3", bitrate=f"{bitrate_kbps}k")
    return buf.getvalue()


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Levenshtein-over-words WER. Returns fraction [0.0, 1.0+]."""
    ref = reference.lower().split()
    hyp = hypothesis.lower().split()
    if not ref:
        return 0.0 if not hyp else 1.0

    # Classic DP edit distance on word tokens
    dp = [[0] * (len(hyp) + 1) for _ in range(len(ref) + 1)]
    for i in range(len(ref) + 1):
        dp[i][0] = i
    for j in range(len(hyp) + 1):
        dp[0][j] = j
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[len(ref)][len(hyp)] / len(ref)


def run_sweep(sample: Path, model: str, bitrates: list[int], api_key: str) -> dict:
    """Encode + transcribe the sample at each bitrate. Returns result dict."""
    prompt = VERBATIM_PROMPT
    reference_path = sample.with_suffix(".reference.txt")
    reference_text = reference_path.read_text().strip() if reference_path.exists() else None

    client = get_client(api_key, model)
    results = []

    for br in bitrates:
        mp3_bytes = encode_mp3(sample, br)
        payload_kb = len(mp3_bytes) / 1024
        start = time.time()
        try:
            result = client.transcribe(mp3_bytes, prompt, audio_format="mp3")
            elapsed = time.time() - start
            text = result.text
            err = None
        except Exception as e:  # noqa: BLE001
            elapsed = time.time() - start
            text = ""
            err = str(e)

        wer = word_error_rate(reference_text, text) if reference_text and text else None
        results.append({
            "bitrate_kbps": br,
            "payload_kb": round(payload_kb, 1),
            "elapsed_s": round(elapsed, 2),
            "text": text,
            "error": err,
            "wer": wer,
        })
        status = f"{br}kbps: {payload_kb:.1f}KB in {elapsed:.2f}s"
        if wer is not None:
            status += f" | WER={wer:.3f}"
        if err:
            status += f" | ERROR: {err}"
        print(status)

    return {
        "sample": str(sample),
        "model": model,
        "reference_text": reference_text,
        "results": results,
    }


def write_report(run: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    for r in run["results"]:
        (out_dir / f"{r['bitrate_kbps']}kbps.txt").write_text(r["text"] or "")

    lines = [
        f"# Bitrate Sweep — {Path(run['sample']).name}",
        "",
        f"- **Model**: `{run['model']}`",
        f"- **Sample**: `{run['sample']}`",
        f"- **Reference text available**: {'yes' if run['reference_text'] else 'no'}",
        "",
        "## Results",
        "",
        "| Bitrate | Payload | Latency | WER | Notes |",
        "|---|---:|---:|---:|---|",
    ]
    for r in run["results"]:
        wer = f"{r['wer']:.3f}" if r["wer"] is not None else "—"
        note = r["error"] or ""
        lines.append(
            f"| {r['bitrate_kbps']} kbps | {r['payload_kb']} KB | "
            f"{r['elapsed_s']} s | {wer} | {note} |"
        )
    lines.append("")

    if run["reference_text"]:
        lines += ["## Reference", "", "```", run["reference_text"], "```", ""]

    lines += ["## Transcriptions", ""]
    for r in run["results"]:
        lines += [f"### {r['bitrate_kbps']} kbps", "", "```", r["text"] or "(empty)", "```", ""]

    (out_dir / "report.md").write_text("\n".join(lines))
    print(f"\nReport: {out_dir / 'report.md'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=Path, required=True, help="Reference WAV file.")
    ap.add_argument("--model", default="google/gemini-3.1-flash-lite-preview",
                    help="OpenRouter model id.")
    ap.add_argument("--bitrates", type=int, nargs="+", default=[24, 32, 64],
                    help="MP3 bitrates in kbps to sweep.")
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2
    if not args.sample.exists():
        print(f"ERROR: sample not found: {args.sample}", file=sys.stderr)
        return 2

    run = run_sweep(args.sample, args.model, args.bitrates, api_key)

    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_dir = REPO_ROOT / "evals" / "results" / f"{args.sample.stem}-{ts}"
    write_report(run, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
