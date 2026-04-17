"""Encode a source WAV into MP3 variants at multiple bitrates.

Produces one MP3 per bitrate next to the source, so you can inspect file sizes
and listen to quality differences before running the bitrate sweep.

Usage:
    python3 -m evals.encode_variants --sample evals/samples/auth-middleware-note.wav
    python3 -m evals.encode_variants --sample <path> --bitrates 16 24 32 48 64

Writes (next to the source):
    <name>.16kbps.mp3
    <name>.24kbps.mp3
    <name>.32kbps.mp3
    <name>.64kbps.mp3
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pydub import AudioSegment  # noqa: E402

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1


def encode(wav_path: Path, bitrates: list[int]) -> list[Path]:
    audio = AudioSegment.from_wav(wav_path)
    orig_kb = wav_path.stat().st_size / 1024
    orig_rate = audio.frame_rate
    orig_channels = audio.channels

    if audio.channels > 1:
        audio = audio.set_channels(TARGET_CHANNELS)
    if audio.frame_rate != TARGET_SAMPLE_RATE:
        audio = audio.set_frame_rate(TARGET_SAMPLE_RATE)

    print(f"Source: {wav_path.name}")
    print(f"  original: {orig_kb:.1f} KB, {orig_rate}Hz, {orig_channels}ch")
    print(f"  normalized to: {TARGET_SAMPLE_RATE}Hz mono before encoding")
    print(f"  duration: {len(audio) / 1000:.1f}s")
    print()

    outputs = []
    for br in sorted(bitrates):
        out_path = wav_path.with_suffix(f".{br}kbps.mp3")
        audio.export(out_path, format="mp3", bitrate=f"{br}k")
        size_kb = out_path.stat().st_size / 1024
        ratio = orig_kb / size_kb if size_kb > 0 else 0
        print(f"  {out_path.name}: {size_kb:.1f} KB ({ratio:.1f}x smaller than WAV)")
        outputs.append(out_path)
    return outputs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=Path, required=True, help="Source WAV file.")
    ap.add_argument("--bitrates", type=int, nargs="+", default=[16, 24, 32, 48, 64],
                    help="MP3 bitrates in kbps.")
    args = ap.parse_args()

    if not args.sample.exists():
        print(f"ERROR: sample not found: {args.sample}", file=sys.stderr)
        return 2

    encode(args.sample, args.bitrates)
    return 0


if __name__ == "__main__":
    sys.exit(main())
