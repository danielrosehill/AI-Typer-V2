"""Audio recording functionality using PyAudio."""

import io
import logging
import math
import wave
import threading
import time
from typing import Optional, Callable

import numpy as np
import pyaudio


def _rms_int16(data: bytes) -> float:
    """Compute RMS of int16 little-endian PCM bytes. Returns float (~0..32768)."""
    if not data:
        return 0.0
    samples = np.frombuffer(data, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    # Use float64 to avoid int16 overflow when squaring
    return float(math.sqrt(float(np.mean(samples.astype(np.float64) ** 2))))

logger = logging.getLogger(__name__)


class AudioRecorder:
    """Records audio from microphone."""

    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    # Common sample rates to try, in order of preference
    SAMPLE_RATES = [48000, 44100, 22050, 16000]

    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self.actual_sample_rate = sample_rate
        self.audio = pyaudio.PyAudio()
        self.stream: Optional[pyaudio.Stream] = None
        self.frames: list[bytes] = []
        self.is_recording = False
        self.is_paused = False
        self._record_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.on_error: Optional[Callable[[str], None]] = None
        # Called with a float 0.0-1.0 peak level per chunk (thread-safe callable)
        self.on_level: Optional[Callable[[float], None]] = None
        # Called once after `silence_timeout_seconds` of continuous silence (post-speech)
        self.on_silence_timeout: Optional[Callable[[], None]] = None
        self.silence_timeout_seconds: float = 0.0  # 0 = disabled
        self.silence_rms_threshold: int = 300      # int16 RMS threshold
        self._error_occurred = False
        self._speech_seen: bool = False
        self._silence_started_at: float = 0.0

    def _get_supported_sample_rate(self, device_index: Optional[int]) -> int:
        """Find a supported sample rate for the device."""
        if device_index is not None:
            try:
                info = self.audio.get_device_info_by_index(device_index)
                default_rate = int(info.get("defaultSampleRate", 48000))
                if self._test_sample_rate(device_index, default_rate):
                    return default_rate
            except Exception:
                pass

        for rate in self.SAMPLE_RATES:
            if self._test_sample_rate(device_index, rate):
                return rate
        return 48000

    def _test_sample_rate(self, device_index: Optional[int], rate: int) -> bool:
        """Test if a sample rate is supported."""
        try:
            return self.audio.is_format_supported(
                rate,
                input_device=device_index,
                input_channels=self.CHANNELS,
                input_format=self.FORMAT,
            )
        except ValueError:
            return False

    def start_recording(self) -> bool:
        """Start recording audio. Returns True if successful."""
        if self.is_recording:
            return True

        with self._lock:
            self.frames = []
            self._error_occurred = False

        self.is_recording = True
        self.is_paused = False
        self._speech_seen = False
        self._silence_started_at = 0.0
        self.actual_sample_rate = self._get_supported_sample_rate(None)

        try:
            self.stream = self.audio.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.actual_sample_rate,
                input=True,
                frames_per_buffer=self.CHUNK,
            )
        except Exception as e:
            self.is_recording = False
            if self.on_error:
                self.on_error(f"Failed to open microphone: {e}")
            return False

        self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._record_thread.start()
        return True

    def _record_loop(self) -> None:
        """Recording loop running in separate thread."""
        consecutive_errors = 0
        while self.is_recording:
            if not self.is_paused and self.stream:
                try:
                    data = self.stream.read(self.CHUNK, exception_on_overflow=False)
                    with self._lock:
                        self.frames.append(data)
                    consecutive_errors = 0

                    # Compute RMS for level meter + silence detection
                    try:
                        rms = _rms_int16(data)
                    except Exception:
                        rms = 0.0

                    if self.on_level:
                        # Normalise RMS (~0-32768) to 0.0-1.0 with a log-ish curve
                        level = min(1.0, rms / 8000.0)
                        try:
                            self.on_level(level)
                        except Exception:
                            pass

                    if self.silence_timeout_seconds > 0:
                        now = time.monotonic()
                        if rms >= self.silence_rms_threshold:
                            self._speech_seen = True
                            self._silence_started_at = 0.0
                        elif self._speech_seen:
                            if self._silence_started_at == 0.0:
                                self._silence_started_at = now
                            elif now - self._silence_started_at >= self.silence_timeout_seconds:
                                cb = self.on_silence_timeout
                                self._silence_started_at = 0.0
                                self._speech_seen = False
                                if cb:
                                    try:
                                        cb()
                                    except Exception:
                                        pass
                except OSError:
                    consecutive_errors += 1
                    if consecutive_errors >= 5:
                        self._error_occurred = True
                        if self.on_error:
                            self.on_error("Microphone disconnected during recording")
                        break
                except Exception as e:
                    consecutive_errors += 1
                    if consecutive_errors >= 5:
                        self._error_occurred = True
                        if self.on_error:
                            self.on_error(f"Recording error: {e}")
                        break

    def pause_recording(self) -> None:
        self.is_paused = True

    def resume_recording(self) -> None:
        self.is_paused = False

    def stop_recording(self) -> bytes:
        """Stop recording and return WAV data."""
        self.is_recording = False
        if self._record_thread:
            self._record_thread.join(timeout=1.0)
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        return self._frames_to_wav()

    def _frames_to_wav(self) -> bytes:
        """Convert recorded frames to WAV format."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(self.audio.get_sample_size(self.FORMAT))
            wf.setframerate(self.actual_sample_rate)
            wf.writeframes(b"".join(self.frames))
        return buffer.getvalue()

    def clear(self) -> None:
        with self._lock:
            self.frames = []

    def get_duration(self) -> float:
        """Get current recording duration in seconds."""
        with self._lock:
            if not self.frames:
                return 0.0
            total_samples = len(self.frames) * self.CHUNK
        return total_samples / self.actual_sample_rate

    def had_error(self) -> bool:
        return self._error_occurred

    def cleanup(self) -> None:
        if self.stream:
            self.stream.close()
        self.audio.terminate()
