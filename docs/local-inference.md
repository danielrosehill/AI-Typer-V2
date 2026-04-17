# Local Inference — Future Direction

## Status

**Not planned for near-term implementation.** This app is a personal productivity utility; hosted API latency and cost are acceptable at current usage. Local inference is on the horizon but not currently worth the setup effort and quality regression.

This note captures what was surveyed so the analysis isn't re-done from scratch later.

## Hardware baseline

- AMD GPU, ~12 GB VRAM
- ROCm stack (not CUDA)

## Relevant model class

Audio-in → text-out **multimodal LLMs** — i.e. models that ingest raw audio and return cleaned, formatted text in a single pass, the same shape as the hosted backends this app uses. Pure ASR models (Whisper etc.) are out of scope — they only transcribe, they don't clean up.

## Candidates that fit in ~12 GB VRAM

| Model | Size | Fits at | Notes |
|---|---|---|---|
| **Voxtral Mini 3B** (Mistral) | 3B | FP16 comfortably, 4-bit trivially | Same family as the hosted Voxtral. Lowest friction. |
| Voxtral Mini 4B Realtime | 4B | FP16/4-bit | Optimized for streaming / sub-200ms latency. |
| Qwen2-Audio-7B-Instruct | 7B | 4-bit (~5 GB) | Good audio understanding. |
| Phi-4-multimodal | 5.6B | 4-bit | Audio + vision + text. |
| Gemma 3n (E2B/E4B) | 2–5B | Easily | Small, audio-capable. Quality trails the larger options. |
| Ultravox (Llama-3-8B + audio encoder) | 8B | 4-bit, tight | |
| MiniCPM-o 2.6 | 8B | 4-bit | Omni-modal. |

## ROCm reality check

- ROCm inference is workable but rougher than CUDA.
- vLLM has ROCm support for several of these (Voxtral Mini Realtime is explicitly documented).
- HF Transformers works but slower than vLLM.
- Quality will be noticeably below the hosted Gemini 3 path the app uses today — especially for the cleanup/formatting step, which rewards the larger hosted models.

## If/when this happens

Most practical starting point: **Voxtral Mini 3B (or 4B Realtime) via vLLM-ROCm**. Same model family already used through the hosted Mistral API, so prompts and behavior transfer. Integration would be a new backend alongside the OpenRouter client, selected from settings.

## Why not now

- Setup overhead (vLLM-ROCm, model weights, local server management) outweighs the benefit for a personal util.
- Quality regression is real — hosted Gemini 3 produces meaningfully cleaner output.
- Latency of the hosted path is being addressed separately via streaming transcription.
- Privacy is already acceptable (audio goes to a trusted provider; no sensitive data routinely dictated).

Revisit if: ROCm tooling matures further, Voxtral-class models close the quality gap, or the app's use case shifts to scenarios where local-only is a hard requirement.

## References

- [Voxtral Mini 4B Realtime (Hugging Face)](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602)
- [vLLM + ROCm + Voxtral guide (Red Hat)](https://developers.redhat.com/articles/2026/02/06/run-voxtral-mini-4b-realtime-vllm-red-hat-ai)
- [Mistral realtime transcription docs](https://docs.mistral.ai/capabilities/audio/speech_to_text/realtime_transcription)
