"""TTS voice announcements for recording/transcription events.

Plays pre-generated WAV files from assets/tts/ for status changes.
Uses a single voice (Ryan — Edge TTS British male).
"""

import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional, Tuple

from .audio_feedback import generate_beep

try:
    import simpleaudio as sa
    HAS_SIMPLEAUDIO = True
except ImportError:
    HAS_SIMPLEAUDIO = False

try:
    import pyaudio
    import wave
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False


def _get_assets_dir() -> Path:
    """Get the path to TTS assets directory."""
    src_dir = Path(__file__).parent
    for candidate in [
        src_dir.parent / "assets" / "tts",
        src_dir / "assets" / "tts",
        Path("/opt/ai-typer-v2/assets/tts"),
    ]:
        if candidate.exists():
            return candidate
    return src_dir.parent / "assets" / "tts"


class TTSAnnouncer:
    """Plays pre-generated TTS announcements with anti-collision queue."""

    def __init__(self):
        self._assets_dir = _get_assets_dir()
        self._audio_cache: dict[str, object] = {}
        self._sample_rate = 16000

        self._announcement_queue: deque[Tuple[str, bool, Optional[int]]] = deque()
        self._queue_lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_played_time = 0.0
        self._min_pause_ms = 300
        self._is_playing = False

        self._recording_beep = generate_beep(frequency=880, duration_ms=60, volume=0.18)
        self._beep_sample_rate = 44100

        self._preload_audio()
        self._start_worker()

    def _preload_audio(self) -> None:
        announcements = [
            "recording", "stopped", "paused", "resumed", "discarded",
            "cached", "transcribing", "complete", "error",
            "clipboard", "copied_to_clipboard",
            "format_updated", "tone_updated",
            "tts_activated", "tts_deactivated",
            "appending", "appended",
            "vad_enabled", "vad_disabled",
            "app_enabled", "app_disabled",
            "clipboard_enabled", "clipboard_disabled",
            "inject_enabled", "inject_disabled",
            "cleared",
        ]
        for name in announcements:
            wav_path = self._assets_dir / f"{name}.wav"
            if wav_path.exists():
                try:
                    if HAS_SIMPLEAUDIO:
                        self._audio_cache[name] = sa.WaveObject.from_wave_file(str(wav_path))
                    elif HAS_PYAUDIO:
                        with wave.open(str(wav_path), 'rb') as wf:
                            self._audio_cache[name] = wf.readframes(wf.getnframes())
                    else:
                        self._audio_cache[name] = None
                except Exception:
                    self._audio_cache[name] = None

    def _start_worker(self) -> None:
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_event.clear()
            self._worker_thread = threading.Thread(target=self._queue_worker, daemon=True)
            self._worker_thread.start()

    def _queue_worker(self) -> None:
        while not self._stop_event.is_set():
            announcement = None
            with self._queue_lock:
                if self._announcement_queue:
                    announcement = self._announcement_queue.popleft()
            if announcement is None:
                time.sleep(0.05)
                continue

            name, blocking, buffer_ms = announcement
            current_time = time.time()
            time_since_last = (current_time - self._last_played_time) * 1000
            if time_since_last < self._min_pause_ms:
                time.sleep((self._min_pause_ms - time_since_last) / 1000.0)

            self._is_playing = True
            audio = self._audio_cache.get(name)
            if audio is not None:
                self._play_audio(audio)
            self._last_played_time = time.time()
            self._is_playing = False

            if buffer_ms and buffer_ms > 0:
                time.sleep(buffer_ms / 1000.0)

    def _play_async(self, name: str) -> None:
        if self._audio_cache.get(name) is None:
            return
        with self._queue_lock:
            self._announcement_queue.append((name, False, None))

    def _play_audio(self, audio) -> None:
        if HAS_SIMPLEAUDIO and isinstance(audio, sa.WaveObject):
            try:
                play_obj = audio.play()
                play_obj.wait_done()
                return
            except Exception:
                pass
        if HAS_PYAUDIO and isinstance(audio, bytes):
            try:
                p = pyaudio.PyAudio()
                stream = p.open(format=pyaudio.paInt16, channels=1, rate=self._sample_rate, output=True)
                stream.write(audio)
                stream.stop_stream()
                stream.close()
                p.terminate()
            except Exception:
                pass

    def _play_recording_beep(self) -> None:
        """Play quick beep for recording start (blocking, faster than TTS)."""
        if HAS_SIMPLEAUDIO:
            try:
                wave_obj = sa.WaveObject(self._recording_beep, 1, 2, self._beep_sample_rate)
                play_obj = wave_obj.play()
                play_obj.wait_done()
                return
            except Exception:
                pass
        if HAS_PYAUDIO:
            try:
                p = pyaudio.PyAudio()
                stream = p.open(format=pyaudio.paInt16, channels=1, rate=self._beep_sample_rate, output=True)
                stream.write(self._recording_beep)
                stream.stop_stream()
                stream.close()
                p.terminate()
            except Exception:
                pass

    # --- Announcements ---

    def announce_recording(self):
        """Quick beep for recording start (blocks to prevent mic capture)."""
        self._play_recording_beep()

    def announce_stopped(self):
        self._play_async("stopped")

    def announce_paused(self):
        self._play_async("paused")

    def announce_resumed(self):
        self._play_async("resumed")

    def announce_discarded(self):
        self._play_async("discarded")

    def announce_cached(self):
        self._play_async("cached")

    def announce_transcribing(self):
        self._play_async("transcribing")

    def announce_complete(self):
        self._play_async("complete")

    def announce_error(self):
        self._play_async("error")

    def announce_clipboard(self):
        self._play_async("clipboard")

    def announce_format_updated(self):
        self._play_async("format_updated")

    def announce_tone_updated(self):
        self._play_async("tone_updated")

    def announce_appending(self):
        self._play_async("appending")

    def announce_cleared(self):
        self._play_async("cleared")


_announcer: Optional[TTSAnnouncer] = None
_announcer_lock = threading.Lock()


def get_announcer() -> TTSAnnouncer:
    global _announcer
    if _announcer is None:
        with _announcer_lock:
            if _announcer is None:
                _announcer = TTSAnnouncer()
    return _announcer
