"""Audio processing: AGC, compression, VAD integration."""

import io
import wave
from pydub import AudioSegment

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1

# Skip VAD for recordings shorter than this (overhead not worth it)
VAD_MIN_DURATION_SECS = 5.0

# Upload-size budget for the OpenRouter audio request body.
#
# OpenRouter follows the OpenAI `input_audio` schema (wav/mp3 only — Opus is
# NOT supported through the OpenAI-compatible wrapper even though Gemini
# natively accepts it). The payload is base64-encoded inside a JSON body, so
# the on-wire size is ~1.33× the raw MP3.
#
# OpenRouter doesn't publish a hard request-body cap, but in practice ~25 MB
# of base64 payload is the safe ceiling before proxies start rejecting. We
# budget 20 MB of raw MP3 (≈ 26.6 MB base64) as the "everything is fine" zone
# and fall back to more aggressive bitrates above that.
#
# At the default 32 kbps mono 16 kHz, 20 MB of MP3 == ~83 min of speech. With
# the 16 kbps fallback, the same budget covers ~2h 45min. Recordings longer
# than that should be split; for now we surface a clear error.
MAX_MP3_BYTES = 20 * 1024 * 1024  # 20 MB

# Bitrate ladder for fallback compression, in order of preference. 32 kbps is
# the accuracy sweet spot per docs/openrouter-audio-api.md; 24 and 16 kbps are
# only used if the raw output exceeds MAX_MP3_BYTES.
BITRATE_LADDER = ["32k", "24k", "16k"]

# AGC settings
AGC_TARGET_PEAK_DBFS = -3.0
AGC_MIN_PEAK_DBFS = -40.0
AGC_MAX_GAIN_DB = 20.0


def apply_agc(audio: AudioSegment) -> tuple[AudioSegment, dict]:
    """Apply automatic gain control to normalize audio levels."""
    stats = {
        "original_peak_dbfs": audio.max_dBFS,
        "gain_applied_db": 0.0,
        "agc_applied": False,
    }

    current_peak = audio.max_dBFS

    if current_peak < AGC_MIN_PEAK_DBFS:
        return audio, stats

    gain_needed = AGC_TARGET_PEAK_DBFS - current_peak
    if gain_needed <= 0:
        return audio, stats

    gain_to_apply = min(gain_needed, AGC_MAX_GAIN_DB)
    audio = audio + gain_to_apply

    stats["gain_applied_db"] = round(gain_to_apply, 1)
    stats["final_peak_dbfs"] = audio.max_dBFS
    stats["agc_applied"] = True

    return audio, stats


def prepare_audio_for_api(
    audio_data: bytes,
    vad_enabled: bool = False,
    apply_gain_control: bool = True,
) -> tuple[bytes, float | None, float | None]:
    """Fused audio pipeline: VAD + AGC + compression in a single pass.

    Returns:
        Tuple of (compressed_wav_bytes, original_duration_secs, vad_duration_secs).
    """
    from .vad_processor import get_vad, is_vad_available

    audio = AudioSegment.from_wav(io.BytesIO(audio_data))
    original_duration = len(audio) / 1000.0
    vad_duration = None

    # Convert to 16kHz mono once
    if audio.channels > 1:
        audio = audio.set_channels(TARGET_CHANNELS)
    if audio.frame_rate != TARGET_SAMPLE_RATE:
        audio = audio.set_frame_rate(TARGET_SAMPLE_RATE)

    # Apply VAD (skip for short recordings — overhead not worth it)
    if vad_enabled and is_vad_available() and original_duration >= VAD_MIN_DURATION_SECS:
        vad = get_vad()
        speeches = vad._get_speech_timestamps_from_audio(audio)
        if speeches:
            combined = AudioSegment.empty()
            for speech in speeches:
                start_ms = int(speech['start'] * 1000 / TARGET_SAMPLE_RATE)
                end_ms = int(speech['end'] * 1000 / TARGET_SAMPLE_RATE)
                combined += audio[start_ms:end_ms]
            if len(combined) > 0:
                vad_duration = len(combined) / 1000.0
                audio = combined
            else:
                vad_duration = original_duration
        else:
            vad_duration = original_duration

    # Apply AGC
    if apply_gain_control:
        audio, agc_stats = apply_agc(audio)
        if agc_stats["agc_applied"]:
            print(f"AGC: Applied {agc_stats['gain_applied_db']}dB gain "
                  f"(peak: {agc_stats['original_peak_dbfs']:.1f}dB -> {agc_stats['final_peak_dbfs']:.1f}dB)")

    # Export as MP3. 32 kbps mono 16 kHz is the accuracy/bandwidth sweet spot
    # for speech dictation through OpenRouter audio-LLMs (see
    # docs/openrouter-audio-api.md). For very long recordings the resulting
    # file may still exceed MAX_MP3_BYTES — in that case we step down the
    # bitrate. Speech remains intelligible at 16 kbps; this only kicks in
    # for recordings longer than ~80 min.
    mp3_bytes = b""
    for bitrate in BITRATE_LADDER:
        output = io.BytesIO()
        audio.export(output, format="mp3", bitrate=bitrate)
        mp3_bytes = output.getvalue()
        if len(mp3_bytes) <= MAX_MP3_BYTES:
            break
        print(f"Audio: MP3 at {bitrate} is {len(mp3_bytes) / 1_048_576:.1f} MB "
              f"(> {MAX_MP3_BYTES / 1_048_576:.0f} MB budget) — stepping down bitrate")

    if len(mp3_bytes) > MAX_MP3_BYTES:
        raise ValueError(
            f"Audio is too long to upload: {len(mp3_bytes) / 1_048_576:.1f} MB "
            f"MP3 at the lowest supported bitrate (16 kbps) exceeds the "
            f"{MAX_MP3_BYTES / 1_048_576:.0f} MB API budget. "
            f"Recording duration: {original_duration / 60:.1f} min. "
            f"Split the recording into shorter segments and try again."
        )

    return mp3_bytes, original_duration, vad_duration


def combine_wav_segments(segments: list[bytes]) -> bytes:
    """Combine multiple WAV audio segments into a single WAV file."""
    if not segments:
        raise ValueError("No audio segments to combine")
    if len(segments) == 1:
        return segments[0]

    combined = AudioSegment.from_wav(io.BytesIO(segments[0]))
    for segment in segments[1:]:
        combined += AudioSegment.from_wav(io.BytesIO(segment))

    output = io.BytesIO()
    combined.export(output, format="wav")
    return output.getvalue()


def get_audio_duration(audio_data: bytes) -> float:
    """Get duration of WAV audio in seconds."""
    with wave.open(io.BytesIO(audio_data), 'rb') as wf:
        return wf.getnframes() / wf.getframerate()
