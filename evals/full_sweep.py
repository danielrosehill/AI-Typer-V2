"""Full sweep — every OpenRouter audio model × every sample × every bitrate.

Produces:
    evals/results/<DDMM>/
        summary.md              # master comparison table (model × bitrate, avg WER + latency)
        all.csv                 # machine-readable: model, sample, bitrate, payload_kb, elapsed_s, wer
        <model-slug>/
            <sample-name>/
                <bitrate>kbps.txt    # raw transcription output
                report.md            # per-sample breakdown for this model

Every transcription is timed (wall-clock API round-trip) and scored against the
paired reference text. Results are tracked in the repo so we can diff runs over time.

Usage:
    python3 -m evals.full_sweep
    python3 -m evals.full_sweep --samples 1 2 --bitrates 32 64
    python3 -m evals.full_sweep --models google/gemini-3.1-flash-lite-preview openai/gpt-audio-mini
"""
import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.src.config import MODELS  # noqa: E402
from app.src.transcription import get_client  # noqa: E402
from evals.bitrate_sweep import VERBATIM_PROMPT, encode_mp3, word_error_rate  # noqa: E402

SAMPLES_DIR = REPO_ROOT / "evals" / "samples"
RESULTS_DIR = REPO_ROOT / "evals" / "results"


def slugify_model(model_id: str) -> str:
    return model_id.replace("/", "__")


def find_samples(sample_filter: list[str] | None) -> list[Path]:
    all_wavs = sorted(SAMPLES_DIR.glob("*.wav"))
    if not sample_filter:
        return all_wavs
    wanted = set(sample_filter)
    return [w for w in all_wavs if w.stem in wanted]


def run_one(client, mp3: bytes, prompt: str, reference: str | None) -> dict:
    start = time.time()
    try:
        result = client.transcribe(mp3, prompt, audio_format="mp3")
        elapsed = time.time() - start
        text = result.text
        err = None
    except Exception as e:  # noqa: BLE001
        elapsed = time.time() - start
        text = ""
        err = str(e)
    wer = word_error_rate(reference, text) if reference and text else None
    return {
        "elapsed_s": round(elapsed, 3),
        "text": text,
        "error": err,
        "wer": wer,
    }


def write_sample_report(model_id: str, sample: Path, rows: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for r in rows:
        (out_dir / f"{r['bitrate_kbps']}kbps.txt").write_text(r["text"] or "")

    reference_path = sample.with_suffix(".reference.txt")
    reference_text = reference_path.read_text().strip() if reference_path.exists() else ""

    lines = [
        f"# {model_id} — {sample.stem}",
        "",
        "| Bitrate | Payload | Latency | WER | Notes |",
        "|---|---:|---:|---:|---|",
    ]
    for r in rows:
        wer = f"{r['wer']:.3f}" if r["wer"] is not None else "—"
        note = r["error"] or ""
        lines.append(
            f"| {r['bitrate_kbps']} kbps | {r['payload_kb']} KB | "
            f"{r['elapsed_s']} s | {wer} | {note} |"
        )
    if reference_text:
        lines += ["", "## Reference", "", "```", reference_text, "```"]
    lines += ["", "## Transcriptions", ""]
    for r in rows:
        lines += [f"### {r['bitrate_kbps']} kbps", "", "```", r["text"] or "(empty)", "```", ""]
    (out_dir / "report.md").write_text("\n".join(lines))


def write_summary(all_rows: list[dict], models: list[dict], bitrates: list[int],
                  samples: list[Path], out_dir: Path) -> None:
    # CSV
    with (out_dir / "all.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "model", "sample", "bitrate_kbps", "payload_kb", "elapsed_s", "wer", "error",
        ])
        writer.writeheader()
        for row in all_rows:
            writer.writerow({k: row.get(k, "") for k in writer.fieldnames})

    # Aggregate: for each (model, bitrate), average WER + latency across samples
    agg: dict[tuple[str, int], dict] = {}
    for row in all_rows:
        key = (row["model"], row["bitrate_kbps"])
        agg.setdefault(key, {"wers": [], "elapseds": [], "errors": 0})
        if row.get("wer") is not None:
            agg[key]["wers"].append(row["wer"])
        agg[key]["elapseds"].append(row["elapsed_s"])
        if row.get("error"):
            agg[key]["errors"] += 1

    lines = [
        f"# Full Audio-Model Sweep — {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
        f"- **Samples**: {len(samples)} ({', '.join(s.stem for s in samples)})",
        f"- **Models**: {len(models)}",
        f"- **Bitrates**: {', '.join(f'{b}kbps' for b in bitrates)}",
        f"- **Total calls**: {len(all_rows)}",
        "",
        "WER = word-error-rate vs. reference text (lower is better, 0.000 = perfect).",
        "Latency = wall-clock API round-trip including network.",
        "",
        "## WER × Latency by (model, bitrate)",
        "",
        "Each cell: `WER_avg / latency_avg_s`. Averaged across all samples.",
        "",
    ]
    header = "| Model | " + " | ".join(f"{b} kbps" for b in bitrates) + " |"
    sep = "|---|" + "|".join("---:" for _ in bitrates) + "|"
    lines += [header, sep]
    for m in models:
        row = [f"`{m['id']}`"]
        for b in bitrates:
            data = agg.get((m["id"], b))
            if not data or not data["elapseds"]:
                row.append("—")
                continue
            wer_str = (
                f"{sum(data['wers']) / len(data['wers']):.3f}"
                if data["wers"] else "err"
            )
            lat_str = f"{sum(data['elapseds']) / len(data['elapseds']):.2f}s"
            cell = f"{wer_str} / {lat_str}"
            if data["errors"]:
                cell += f" ⚠×{data['errors']}"
            row.append(cell)
        lines.append("| " + " | ".join(row) + " |")

    # Per-sample breakdown pointers
    lines += ["", "## Per-sample reports", ""]
    for m in models:
        lines.append(f"### `{m['id']}`")
        for s in samples:
            rel = f"{slugify_model(m['id'])}/{s.stem}/report.md"
            lines.append(f"- [{s.stem}]({rel})")
        lines.append("")

    (out_dir / "summary.md").write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", nargs="*", help="Sample stems to include (default: all).")
    ap.add_argument("--models", nargs="*", help="Model IDs to include (default: all in MODELS).")
    ap.add_argument("--bitrates", type=int, nargs="+", default=[16, 24, 32, 48, 64])
    ap.add_argument("--dry-run", action="store_true", help="Print plan, skip API calls.")
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    samples = find_samples(args.samples)
    if not samples:
        print(f"ERROR: no samples found in {SAMPLES_DIR}", file=sys.stderr)
        return 2

    models = MODELS if not args.models else [m for m in MODELS if m["id"] in args.models]
    if not models:
        print("ERROR: no matching models", file=sys.stderr)
        return 2

    total_calls = len(models) * len(samples) * len(args.bitrates)
    print(f"Plan: {len(models)} models × {len(samples)} samples × {len(args.bitrates)} bitrates = {total_calls} API calls")
    for m in models:
        print(f"  - {m['id']}")
    print(f"Samples: {[s.stem for s in samples]}")
    print(f"Bitrates: {args.bitrates} kbps")
    if args.dry_run:
        print("(dry run — exiting)")
        return 0

    ddmm = datetime.now().strftime("%d%m")
    ts = datetime.now().strftime("%d%m-%H%M%S")
    out_dir = RESULTS_DIR / f"full-sweep-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput: {out_dir}")
    print()

    # Pre-encode every (sample, bitrate) once; reused across all models
    print("Encoding MP3 variants...")
    encoded: dict[tuple[Path, int], tuple[bytes, float]] = {}
    references: dict[Path, str | None] = {}
    for s in samples:
        ref_path = s.with_suffix(".reference.txt")
        references[s] = ref_path.read_text().strip() if ref_path.exists() else None
        for b in args.bitrates:
            mp3 = encode_mp3(s, b)
            encoded[(s, b)] = (mp3, len(mp3) / 1024)
    print(f"  {len(encoded)} variants cached\n")

    all_rows: list[dict] = []
    call_idx = 0
    for model in models:
        client = get_client(api_key, model["id"])
        model_dir = out_dir / slugify_model(model["id"])
        for sample in samples:
            sample_rows: list[dict] = []
            for bitrate in args.bitrates:
                call_idx += 1
                mp3, payload_kb = encoded[(sample, bitrate)]
                print(f"[{call_idx}/{total_calls}] {model['id']} | {sample.stem} | {bitrate}kbps ... ",
                      end="", flush=True)
                result = run_one(client, mp3, VERBATIM_PROMPT, references[sample])
                row = {
                    "model": model["id"],
                    "sample": sample.stem,
                    "bitrate_kbps": bitrate,
                    "payload_kb": round(payload_kb, 1),
                    **result,
                }
                sample_rows.append(row)
                all_rows.append(row)

                wer_s = f"WER={result['wer']:.3f}" if result["wer"] is not None else "WER=—"
                status = f"{result['elapsed_s']}s | {wer_s}"
                if result["error"]:
                    status += f" | ERROR: {result['error'][:80]}"
                print(status)

            write_sample_report(model["id"], sample, sample_rows, model_dir / sample.stem)

    write_summary(all_rows, models, args.bitrates, samples, out_dir)
    print(f"\n✓ Summary: {out_dir / 'summary.md'}")
    print(f"✓ CSV:     {out_dir / 'all.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
