"""Audio feedback sounds — PTT walkie-talkie style beeps.

Generates procedural click-chirps for recording events.
Also loads WAV sound effects from assets/sfx/ when available.
"""

import math
import random
import struct
import threading
import wave
from pathlib import Path
from typing import Optional

try:
    import simpleaudio as sa
    HAS_SIMPLEAUDIO = True
except ImportError:
    HAS_SIMPLEAUDIO = False

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False

SAMPLE_RATE = 44100
_LEAD_IN_MS = 30
_SFX_DIR = Path(__file__).parent.parent / "assets" / "sfx"


def _lead_in_bytes(duration_ms: float = _LEAD_IN_MS) -> bytes:
    return b'\x00\x00' * int(SAMPLE_RATE * duration_ms / 1000)

_LEAD_IN = _lead_in_bytes()


def _load_wav_pcm(filename: str) -> bytes:
    path = _SFX_DIR / filename
    if not path.exists():
        return b""
    with wave.open(str(path), "rb") as wf:
        return _LEAD_IN + wf.readframes(wf.getnframes())


def _white_noise(num_samples: int, volume: float, rng: random.Random) -> list[float]:
    return [rng.uniform(-1.0, 1.0) * volume for _ in range(num_samples)]


def _sine(num_samples: int, frequency: float, volume: float) -> list[float]:
    return [math.sin(2 * math.pi * frequency * i / SAMPLE_RATE) * volume for i in range(num_samples)]


def _apply_envelope(samples: list[float], attack_ms: float, decay_ms: float) -> list[float]:
    n = len(samples)
    attack_samples = int(SAMPLE_RATE * attack_ms / 1000)
    decay_samples = int(SAMPLE_RATE * decay_ms / 1000)
    result = list(samples)
    for i in range(n):
        if i < attack_samples:
            env = i / max(attack_samples, 1)
        elif i >= n - decay_samples:
            env = (n - i) / max(decay_samples, 1)
        else:
            env = 1.0
        result[i] *= env
    return result


def _mix(*layers: list[float]) -> list[float]:
    length = max(len(l) for l in layers)
    result = [0.0] * length
    for layer in layers:
        for i in range(len(layer)):
            result[i] += layer[i]
    return result


def _to_bytes(samples: list[float], master_volume: float = 1.0) -> bytes:
    out = [_LEAD_IN]
    for s in samples:
        val = int(s * master_volume * 32767)
        val = max(-32767, min(32767, val))
        out.append(struct.pack('<h', val))
    return b''.join(out)


def _silence_bytes(duration_ms: float) -> bytes:
    return b'\x00\x00' * int(SAMPLE_RATE * duration_ms / 1000)


def _attenuate(pcm_data: bytes, volume: float) -> bytes:
    """Scale 16-bit signed PCM data by a volume factor (0.0–1.0)."""
    if volume >= 1.0 or not pcm_data:
        return pcm_data
    out = []
    for i in range(0, len(pcm_data) - 1, 2):
        sample = struct.unpack('<h', pcm_data[i:i+2])[0]
        sample = int(sample * volume)
        sample = max(-32767, min(32767, sample))
        out.append(struct.pack('<h', sample))
    return b''.join(out)


def generate_beep(frequency: float = 880, duration_ms: int = 60, volume: float = 0.18) -> bytes:
    data = _load_wav_pcm("ptt-send.wav")
    if data:
        return data
    return generate_ptt_click_chirp(volume=volume)


def generate_ptt_click_chirp(volume: float = 0.15) -> bytes:
    rng = random.Random(42)
    click_len = int(SAMPLE_RATE * 0.008)
    click_noise = _white_noise(click_len, 0.7, rng)
    click_noise = _apply_envelope(click_noise, attack_ms=0.5, decay_ms=3.0)

    chirp_len = int(SAMPLE_RATE * 0.050)
    chirp = []
    for i in range(chirp_len):
        t = i / SAMPLE_RATE
        progress = i / chirp_len
        freq = 1200 + (2800 - 1200) * progress
        noise_val = rng.uniform(-1.0, 1.0) * 0.15
        tone_val = math.sin(2 * math.pi * freq * t) * 0.6
        chirp.append(tone_val + noise_val)
    chirp = _apply_envelope(chirp, attack_ms=1.0, decay_ms=15.0)
    return _to_bytes(click_noise + chirp, master_volume=volume)


def generate_ptt_release(volume: float = 0.15) -> bytes:
    rng = random.Random(99)
    chirp_len = int(SAMPLE_RATE * 0.040)
    chirp = []
    for i in range(chirp_len):
        t = i / SAMPLE_RATE
        progress = i / chirp_len
        freq = 2400 - (2400 - 800) * progress
        noise_val = rng.uniform(-1.0, 1.0) * 0.12
        tone_val = math.sin(2 * math.pi * freq * t) * 0.6
        chirp.append(tone_val + noise_val)
    chirp = _apply_envelope(chirp, attack_ms=1.0, decay_ms=12.0)
    tail_len = int(SAMPLE_RATE * 0.015)
    tail = _white_noise(tail_len, 0.5, rng)
    tail = _apply_envelope(tail, attack_ms=0.5, decay_ms=8.0)
    return _to_bytes(chirp + tail, master_volume=volume)


def generate_rising_chirp(volume: float = 0.12) -> bytes:
    rng = random.Random(55)
    chirp_len = int(SAMPLE_RATE * 0.045)
    chirp = []
    for i in range(chirp_len):
        t = i / SAMPLE_RATE
        progress = i / chirp_len
        freq = 1000 + (3200 - 1000) * (progress ** 0.8)
        noise_val = rng.uniform(-1.0, 1.0) * 0.10
        tone_val = math.sin(2 * math.pi * freq * t) * 0.55
        chirp.append(tone_val + noise_val)
    chirp = _apply_envelope(chirp, attack_ms=0.5, decay_ms=12.0)
    return _to_bytes(chirp, master_volume=volume)


def generate_falling_chirp(volume: float = 0.12) -> bytes:
    rng = random.Random(66)
    chirp_len = int(SAMPLE_RATE * 0.045)
    chirp = []
    for i in range(chirp_len):
        t = i / SAMPLE_RATE
        progress = i / chirp_len
        freq = 3200 - (3200 - 1000) * (progress ** 0.8)
        noise_val = rng.uniform(-1.0, 1.0) * 0.10
        tone_val = math.sin(2 * math.pi * freq * t) * 0.55
        chirp.append(tone_val + noise_val)
    chirp = _apply_envelope(chirp, attack_ms=0.5, decay_ms=12.0)
    return _to_bytes(chirp, master_volume=volume)


def generate_cached_thunk(volume: float = 0.14) -> bytes:
    rng = random.Random(33)
    thunk_len = int(SAMPLE_RATE * 0.050)
    samples = []
    for i in range(thunk_len):
        t = i / SAMPLE_RATE
        progress = i / thunk_len
        freq = 800 - 200 * progress
        tone_val = math.sin(2 * math.pi * freq * t) * 0.6
        noise_val = rng.uniform(-1.0, 1.0) * 0.25 * max(0, 1 - progress * 4)
        samples.append(tone_val + noise_val)
    samples = _apply_envelope(samples, attack_ms=0.5, decay_ms=20.0)
    return _to_bytes(samples, master_volume=volume)


def generate_double_click(volume: float = 0.14) -> bytes:
    rng = random.Random(77)
    def _single_click():
        click_len = int(SAMPLE_RATE * 0.012)
        noise = _white_noise(click_len, 0.6, rng)
        tone = _sine(click_len, 3000, 0.3)
        mixed = _mix(noise, tone)
        return _apply_envelope(mixed, attack_ms=0.3, decay_ms=6.0)
    click1 = _single_click()
    click2 = _single_click()
    return _to_bytes(click1, volume) + _silence_bytes(25) + _to_bytes(click2, volume)


class AudioFeedback:
    """Manages audio feedback sounds."""

    def __init__(self):
        self._enabled = True
        # Start beep softened to 45% volume — original was too jarring
        self._start_beep = _attenuate(_load_wav_pcm("ptt-send.wav") or generate_ptt_click_chirp(), 0.45)
        self._stop_beep = _load_wav_pcm("stop.wav") or generate_ptt_release()
        self._clipboard_beep = generate_double_click()
        self._toggle_on_beep = generate_rising_chirp()
        self._toggle_off_beep = generate_falling_chirp()
        self._cached_beep = generate_cached_thunk()
        self._complete_beep = _load_wav_pcm("ding-complete.wav") or generate_ptt_release()
        self._pause_beep = _load_wav_pcm("pause.wav") or generate_double_click()
        self._resume_beep = _load_wav_pcm("resume.wav") or generate_rising_chirp()
        self._clear_beep = _load_wav_pcm("clear.wav") or generate_falling_chirp()
        self._transcribe_beep = _attenuate(_load_wav_pcm("transcribe.wav") or generate_rising_chirp(), 0.5)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    def play_start(self):
        if self._enabled: self._play_async(self._start_beep)

    def play_stop(self):
        if self._enabled: self._play_async(self._stop_beep)

    def play_clipboard(self):
        if self._enabled: self._play_async(self._clipboard_beep)

    def play_toggle_on(self):
        if self._enabled: self._play_async(self._toggle_on_beep)

    def play_toggle_off(self):
        if self._enabled: self._play_async(self._toggle_off_beep)

    def play_cached(self):
        if self._enabled: self._play_async(self._cached_beep)

    def play_complete(self):
        if self._enabled: self._play_async(self._complete_beep)

    def play_pause(self):
        if self._enabled: self._play_async(self._pause_beep)

    def play_resume(self):
        if self._enabled: self._play_async(self._resume_beep)

    def play_clear(self):
        if self._enabled: self._play_async(self._clear_beep)

    def play_transcribe(self):
        if self._enabled: self._play_async(self._transcribe_beep)

    def _play_async(self, audio_data: bytes):
        threading.Thread(target=self._play_audio, args=(audio_data,), daemon=True).start()

    def _play_audio(self, audio_data: bytes):
        if HAS_SIMPLEAUDIO:
            try:
                wave_obj = sa.WaveObject(audio_data, 1, 2, SAMPLE_RATE)
                play_obj = wave_obj.play()
                play_obj.wait_done()
                return
            except Exception:
                pass

        if HAS_PYAUDIO:
            pa = None
            try:
                pa = pyaudio.PyAudio()
                stream = pa.open(
                    format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, output=True
                )
                stream.write(audio_data)
                stream.stop_stream()
                stream.close()
                return
            except Exception:
                pass
            finally:
                if pa is not None:
                    try:
                        pa.terminate()
                    except Exception:
                        pass


_feedback: Optional[AudioFeedback] = None
_feedback_lock = threading.Lock()


def get_feedback() -> AudioFeedback:
    global _feedback
    if _feedback is None:
        with _feedback_lock:
            if _feedback is None:
                _feedback = AudioFeedback()
    return _feedback
