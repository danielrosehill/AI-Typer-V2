"""Audio processing: AGC, compression, VAD integration."""

import io
import wave
from pydub import AudioSegment

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1

# Skip VAD for recordings shorter than this (overhead not worth it)
VAD_MIN_DURATION_SECS = 5.0

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

    # Export as MP3 — 32kbps mono 16kHz is the accuracy/bandwidth sweet spot
    # for speech dictation through OpenRouter audio-LLMs (see docs/openrouter-audio-api.md).
    output = io.BytesIO()
    audio.export(output, format="mp3", bitrate="32k")
    return output.getvalue(), original_duration, vad_duration


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
