# Full Audio-Model Sweep — 17/04/2026 15:13

- **Samples**: 4 (1, 2, 3, 4)
- **Models**: 12
- **Bitrates**: 16kbps, 24kbps, 32kbps, 48kbps, 64kbps
- **Total calls**: 240

WER = word-error-rate vs. reference text (lower is better, 0.000 = perfect).
Latency = wall-clock API round-trip including network.

## WER × Latency by (model, bitrate)

Each cell: `WER_avg / latency_avg_s`. Averaged across all samples.

| Model | 16 kbps | 24 kbps | 32 kbps | 48 kbps | 64 kbps |
|---|---:|---:|---:|---:|---:|
| `google/gemini-2.0-flash-lite-001` | 0.045 / 2.41s | 0.025 / 1.98s | 0.031 / 3.28s | 0.035 / 2.20s | 0.031 / 2.10s |
| `google/gemini-2.0-flash-001` | 0.017 / 2.06s | 0.034 / 1.84s | 0.025 / 2.05s | 0.017 / 2.19s | 0.028 / 2.03s |
| `google/gemini-2.5-flash-lite` | 0.017 / 1.50s | 0.028 / 2.07s | 0.028 / 1.71s | 0.025 / 1.84s | 0.038 / 2.41s |
| `google/gemini-3.1-flash-lite-preview` | 0.021 / 7.97s | 0.017 / 7.97s | 0.028 / 3.62s | 0.011 / 2.70s | 0.031 / 7.61s |
| `mistralai/voxtral-small-24b-2507` | 0.027 / 0.95s | 0.017 / 1.08s | 0.017 / 1.25s | 0.017 / 0.98s | 0.021 / 1.02s |
| `google/gemini-2.5-flash` | 0.027 / 3.02s | 0.024 / 1.77s | 0.017 / 1.67s | 0.021 / 2.66s | 0.020 / 4.85s |
| `google/gemini-3-flash-preview` | 0.018 / 2.22s | 0.007 / 2.66s | 0.021 / 2.20s | 0.010 / 1.97s | 0.014 / 2.09s |
| `xiaomi/mimo-v2-omni` | 0.024 / 5.70s | 0.024 / 4.92s | 0.014 / 4.85s | 0.034 / 3.86s | 0.040 / 3.74s |
| `openai/gpt-audio-mini` | 0.270 / 1.65s | 0.274 / 1.42s | 0.541 / 1.76s | 0.261 / 1.57s | 0.280 / 1.67s |
| `google/gemini-2.5-pro` | 0.024 / 5.87s | 0.014 / 7.03s | 0.014 / 6.64s | 0.024 / 8.40s | 0.017 / 8.01s |
| `openai/gpt-audio` | 0.483 / 1.58s | 0.014 / 1.59s | 0.010 / 1.67s | 0.230 / 1.83s | 0.250 / 1.63s |
| `openai/gpt-4o-audio-preview` | 0.024 / 1.86s | 0.054 / 1.90s | 0.021 / 1.89s | 0.501 / 1.63s | 0.290 / 1.99s |

## Per-sample reports

### `google/gemini-2.0-flash-lite-001`
- [1](google__gemini-2.0-flash-lite-001/1/report.md)
- [2](google__gemini-2.0-flash-lite-001/2/report.md)
- [3](google__gemini-2.0-flash-lite-001/3/report.md)
- [4](google__gemini-2.0-flash-lite-001/4/report.md)

### `google/gemini-2.0-flash-001`
- [1](google__gemini-2.0-flash-001/1/report.md)
- [2](google__gemini-2.0-flash-001/2/report.md)
- [3](google__gemini-2.0-flash-001/3/report.md)
- [4](google__gemini-2.0-flash-001/4/report.md)

### `google/gemini-2.5-flash-lite`
- [1](google__gemini-2.5-flash-lite/1/report.md)
- [2](google__gemini-2.5-flash-lite/2/report.md)
- [3](google__gemini-2.5-flash-lite/3/report.md)
- [4](google__gemini-2.5-flash-lite/4/report.md)

### `google/gemini-3.1-flash-lite-preview`
- [1](google__gemini-3.1-flash-lite-preview/1/report.md)
- [2](google__gemini-3.1-flash-lite-preview/2/report.md)
- [3](google__gemini-3.1-flash-lite-preview/3/report.md)
- [4](google__gemini-3.1-flash-lite-preview/4/report.md)

### `mistralai/voxtral-small-24b-2507`
- [1](mistralai__voxtral-small-24b-2507/1/report.md)
- [2](mistralai__voxtral-small-24b-2507/2/report.md)
- [3](mistralai__voxtral-small-24b-2507/3/report.md)
- [4](mistralai__voxtral-small-24b-2507/4/report.md)

### `google/gemini-2.5-flash`
- [1](google__gemini-2.5-flash/1/report.md)
- [2](google__gemini-2.5-flash/2/report.md)
- [3](google__gemini-2.5-flash/3/report.md)
- [4](google__gemini-2.5-flash/4/report.md)

### `google/gemini-3-flash-preview`
- [1](google__gemini-3-flash-preview/1/report.md)
- [2](google__gemini-3-flash-preview/2/report.md)
- [3](google__gemini-3-flash-preview/3/report.md)
- [4](google__gemini-3-flash-preview/4/report.md)

### `xiaomi/mimo-v2-omni`
- [1](xiaomi__mimo-v2-omni/1/report.md)
- [2](xiaomi__mimo-v2-omni/2/report.md)
- [3](xiaomi__mimo-v2-omni/3/report.md)
- [4](xiaomi__mimo-v2-omni/4/report.md)

### `openai/gpt-audio-mini`
- [1](openai__gpt-audio-mini/1/report.md)
- [2](openai__gpt-audio-mini/2/report.md)
- [3](openai__gpt-audio-mini/3/report.md)
- [4](openai__gpt-audio-mini/4/report.md)

### `google/gemini-2.5-pro`
- [1](google__gemini-2.5-pro/1/report.md)
- [2](google__gemini-2.5-pro/2/report.md)
- [3](google__gemini-2.5-pro/3/report.md)
- [4](google__gemini-2.5-pro/4/report.md)

### `openai/gpt-audio`
- [1](openai__gpt-audio/1/report.md)
- [2](openai__gpt-audio/2/report.md)
- [3](openai__gpt-audio/3/report.md)
- [4](openai__gpt-audio/4/report.md)

### `openai/gpt-4o-audio-preview`
- [1](openai__gpt-4o-audio-preview/1/report.md)
- [2](openai__gpt-4o-audio-preview/2/report.md)
- [3](openai__gpt-4o-audio-preview/3/report.md)
- [4](openai__gpt-4o-audio-preview/4/report.md)
