"""Record an eval sample — countdown, capture mic, save WAV + reference text.

Usage:
    python3 -m evals.record_sample --name quick-email --duration 30 \\
        --text "Hi team, just circling back on the Q2 proposal..."

Writes:
    evals/samples/<name>.wav
    evals/samples/<name>.reference.txt

The reference text is the ground truth passed via --text (or --text-file).
Display it on screen during the countdown so you can read it aloud verbatim.
"""
import argparse
import sys
import time
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pyaudio  # noqa: E402

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 1024
FORMAT = pyaudio.paInt16
SAMPLES_DIR = REPO_ROOT / "evals" / "samples"


def countdown(seconds: int) -> None:
    for i in range(seconds, 0, -1):
        print(f"  Starting in {i}...", end="\r", flush=True)
        time.sleep(1)
    print(" " * 40, end="\r")


def record(duration_s: float, out_path: Path) -> None:
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=FORMAT, channels=CHANNELS, rate=SAMPLE_RATE,
        input=True, frames_per_buffer=CHUNK,
    )
    frames: list[bytes] = []
    total_chunks = int(SAMPLE_RATE / CHUNK * duration_s)
    start = time.time()
    try:
        for i in range(total_chunks):
            frames.append(stream.read(CHUNK, exception_on_overflow=False))
            elapsed = time.time() - start
            remaining = max(0, duration_s - elapsed)
            bar_len = 30
            filled = int(bar_len * (elapsed / duration_s))
            bar = "█" * filled + "░" * (bar_len - filled)
            print(f"  [{bar}] {remaining:4.1f}s left", end="\r", flush=True)
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
    print(" " * 60, end="\r")

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(pa.get_sample_size(FORMAT))
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"".join(frames))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True, help="Sample name (no extension).")
    ap.add_argument("--duration", type=float, default=30.0, help="Record length in seconds.")
    ap.add_argument("--countdown", type=int, default=5, help="Countdown seconds before recording.")
    text_group = ap.add_mutually_exclusive_group(required=True)
    text_group.add_argument("--text", help="Reference text to read aloud.")
    text_group.add_argument("--text-file", type=Path, help="File containing reference text.")
    ap.add_argument("--force", action="store_true", help="Overwrite existing sample.")
    args = ap.parse_args()

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    wav_path = SAMPLES_DIR / f"{args.name}.wav"
    ref_path = SAMPLES_DIR / f"{args.name}.reference.txt"

    if wav_path.exists() and not args.force:
        print(f"ERROR: {wav_path} already exists. Use --force to overwrite.", file=sys.stderr)
        return 2

    reference = args.text_file.read_text().strip() if args.text_file else args.text.strip()

    print()
    print("=" * 60)
    print("  READ THIS ALOUD (verbatim):")
    print("=" * 60)
    print()
    print(reference)
    print()
    print("=" * 60)
    print(f"  Recording {args.duration:.0f}s into {wav_path.name}")
    print("=" * 60)
    print()

    countdown(args.countdown)
    print("  RECORDING NOW — speak!")
    print()
    record(args.duration, wav_path)

    ref_path.write_text(reference + "\n")

    size_kb = wav_path.stat().st_size / 1024
    print(f"  ✓ Saved {wav_path.name} ({size_kb:.1f} KB)")
    print(f"  ✓ Saved {ref_path.name}")
    print()
    print("  Next: python3 -m evals.bitrate_sweep --sample " + str(wav_path.relative_to(REPO_ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
