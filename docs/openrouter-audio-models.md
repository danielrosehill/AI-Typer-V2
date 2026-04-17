# OpenRouter — Audio-Input Models

> ⚠️ **Pricing snapshot: 2026-04-17.** OpenRouter pricing and model availability change frequently (new snapshots, deprecations, provider re-rates). Numbers below are point-in-time and will drift. Always re-fetch before relying on the cost column for decisions.

Snapshot of every model on OpenRouter that accepts audio input, fetched from `https://openrouter.ai/api/v1/models` and filtered by `architecture.input_modalities contains "audio"`.

Refresh with:

```bash
curl -s https://openrouter.ai/api/v1/models \
  | jq -r '.data[] | select(.architecture.input_modalities | index("audio")) | "\(.id) | \(.name) | ctx=\(.context_length) | $\(.pricing.prompt|tonumber*1e6 | floor)/\(.pricing.completion|tonumber*1e6 | floor) per 1M"'
```

| Model ID | Name | Context | $/M in | $/M out | In app? |
|---|---|---:|---:|---:|:-:|
| `google/gemini-2.0-flash-lite-001` | Gemini 2.0 Flash Lite | 1M | 0.075 | 0.30 | ✅ |
| `google/gemini-2.0-flash-001` | Gemini 2.0 Flash | 1M | 0.10 | 0.40 | ✅ |
| `google/gemini-2.5-flash-lite` | Gemini 2.5 Flash Lite | 1M | 0.10 | 0.40 | ✅ |
| `google/gemini-2.5-flash-lite-preview-09-2025` | Gemini 2.5 Flash Lite Preview 09-2025 | 1M | 0.10 | 0.40 | (superseded) |
| `mistralai/voxtral-small-24b-2507` | Voxtral Small 24B | 32k | 0.10 | 0.30 | ✅ |
| `google/gemini-3.1-flash-lite-preview` | Gemini 3.1 Flash Lite Preview | 1M | 0.25 | 1.50 | ✅ (default) |
| `google/gemini-2.5-flash` | Gemini 2.5 Flash | 1M | 0.30 | 2.50 | ✅ |
| `xiaomi/mimo-v2-omni` | MiMo V2 Omni | 256k | 0.40 | 2.00 | ✅ |
| `google/gemini-3-flash-preview` | Gemini 3 Flash Preview | 1M | 0.50 | 3.00 | ✅ |
| `openai/gpt-audio-mini` | GPT Audio Mini | 128k | 0.60 | 2.40 | ✅ |
| `google/gemini-2.5-pro` | Gemini 2.5 Pro | 1M | 1.25 | 10.00 | ✅ |
| `google/gemini-2.5-pro-preview` | Gemini 2.5 Pro Preview 06-05 | 1M | 1.25 | 10.00 | (superseded) |
| `google/gemini-2.5-pro-preview-05-06` | Gemini 2.5 Pro Preview 05-06 | 1M | 1.25 | 10.00 | (superseded) |
| `google/gemini-3.1-pro-preview` | Gemini 3.1 Pro Preview | 1M | 2.00 | 12.00 | (overkill for dictation) |
| `google/gemini-3.1-pro-preview-customtools` | Gemini 3.1 Pro Custom Tools | 1M | 2.00 | 12.00 | (tool-routing variant, not useful here) |
| `openai/gpt-audio` | GPT Audio | 128k | 2.50 | 10.00 | ✅ |
| `openai/gpt-4o-audio-preview` | GPT-4o Audio | 128k | 2.50 | 10.00 | ✅ |
| `openrouter/auto` | Auto Router (meta) | 2M | variable | variable | (unsuited — picks arbitrary model) |

## Selection criteria for inclusion in the app

- **Prefer**: low latency + low cost for dictation cleanup; established Google/OpenAI/Mistral tiers; models actively maintained.
- **Skip**: superseded preview snapshots when a stable equivalent exists; premium reasoning models (Gemini Pro tiers) — cleanup doesn't benefit from reasoning, so the extra cost is wasted; meta-routers (`openrouter/auto`) because we need deterministic audio-input behavior; specialty variants (`customtools`).

Previously-listed `openrouter/healer-alpha` is no longer in the OpenRouter catalog and was removed from the app.
