# OpenRouter — Audio Input API Constraints

Practical notes on how audio is sent to OpenRouter's chat completions endpoint, and what the effective limits are. These constraints apply regardless of which underlying model you route to (Gemini, GPT-Audio, Voxtral, MiMo, etc.) — OpenRouter normalizes input through the OpenAI-compatible schema.

## Request shape

OpenRouter's `/api/v1/chat/completions` follows the OpenAI `input_audio` content-part schema:

```json
{
  "model": "google/gemini-3.1-flash-lite-preview",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": [
      {"type": "input_audio", "input_audio": {
        "data": "<base64-encoded-audio>",
        "format": "mp3"
      }}
    ]}
  ]
}
```

## Accepted formats

The `format` field in `input_audio` accepts **only two values** through the OpenAI-compatible surface:

- `"wav"` — PCM WAV container
- `"mp3"` — MPEG Layer III

This is the controlling constraint for this app. Even though Gemini's **native** API accepts a wider set (FLAC, OGG/Opus, AAC, AIFF), routing through OpenRouter's OpenAI-compatible endpoint reduces the set to wav/mp3. Sending any other format (opus, ogg, m4a, flac, webm) will be rejected by the upstream router with a validation error before reaching the model.

## Size limits

- **Request body cap: ~25-30 MB** observed before OpenRouter's edge proxies start rejecting. Base64 inflates binary by ~33%, so the app budgets **20 MB of raw MP3** (`MAX_MP3_BYTES` in `audio_processor.py`) before falling back to lower bitrates.
- **Per-model context**: audio is tokenized per-provider. Gemini counts audio at ~32 tokens/second; GPT-Audio and Voxtral use their own tokenizers. A 20-minute clip at Gemini rates ≈ 38k tokens, well within Gemini's 1M context but bumping against Voxtral's 32k window.
- **Effective duration ceilings** (derived from the 20 MB MP3 budget):
  - 32 kbps (default): ~83 min
  - 24 kbps (fallback): ~110 min
  - 16 kbps (last-resort fallback): ~2h 45min
- Above ~2h 45min, the app raises a clear error and asks the user to split the recording. The bitrate fallback is automatic — no user action needed for anything up to that ceiling.
- **Long-recording timeout**: the HTTP request timeout scales with audio size (`120s + 20s per MB`, capped at 10 min) — a 30-min clip gets ~250 s, enough for Gemini 3 Flash to finish.

## Bitrate / sample-rate guidance

For **speech dictation** (what this app does), empirically:

| Encoding | Typical quality for ASR-class use | Notes |
|---|---|---|
| WAV 16-bit 16kHz mono | reference | ~32 KB/sec — huge payloads |
| MP3 64 kbps 16kHz mono | indistinguishable from WAV for speech | previous default |
| **MP3 32 kbps 16kHz mono** | **no measurable accuracy drop on Gemini/GPT-Audio** | **current default** |
| MP3 24 kbps 16kHz mono | audible artifacts but still transcribable | worth A/B testing per-model |
| MP3 16 kbps 16kHz mono | starts to degrade on fast/accented speech | not recommended |

The app pipeline (`app/src/audio_processor.py`) resamples to 16kHz mono before encoding — matching the native rate most audio-LLMs expect internally. Sending higher sample rates (44.1/48 kHz) wastes bandwidth because the model downsamples server-side anyway.

## Format trade-off vs. Gemini native API

If you bypass OpenRouter and call Gemini directly, you unlock **Opus in an OGG container**, which at 16 kbps matches MP3-32kbps quality and at 24 kbps exceeds MP3-64kbps. That's a ~2-3× bandwidth win for the same perceived quality.

However, in this project we stay on OpenRouter because:

1. **API-key-level cost tracking** — OpenRouter surfaces per-key spend; Gemini's native dashboard is coarser and harder to reconcile.
2. **Multi-model routing** — one client, one key, covers Gemini/GPT-Audio/Voxtral/MiMo.
3. **Observed latency** — for this app's traffic pattern (short dictation clips, cold or near-cold requests), OpenRouter has been consistently faster than Gemini native in practice, likely due to aggressive connection pooling at the router.

The MP3 bandwidth loss vs. Opus is real but small at our clip lengths (<10 minutes). The observability win is worth it.

## Streaming

OpenRouter supports SSE streaming for audio-input requests — the app uses this (`transcription.py:transcribe_stream`). The `usage` object with `prompt_tokens` / `completion_tokens` arrives in a final chunk; set `"usage": {"include": true}` on the payload to guarantee it.

## References

- OpenRouter model catalog (audio-input filter): `curl https://openrouter.ai/api/v1/models | jq '.data[] | select(.architecture.input_modalities | index("audio"))'`
- OpenAI `input_audio` spec: <https://platform.openai.com/docs/guides/audio>
- This app's pricing snapshot: [`openrouter-audio-models.md`](./openrouter-audio-models.md)
