"""Voice Activity Detection (VAD) using TEN VAD.

Detects speech segments and removes silence before API upload.
https://github.com/TEN-framework/ten-vad
"""

import io
from typing import Tuple, Optional

try:
    from ten_vad import TenVad
    TEN_VAD_AVAILABLE = True
except ImportError:
    TenVad = None
    TEN_VAD_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    np = None
    NUMPY_AVAILABLE = False

from pydub import AudioSegment

SAMPLE_RATE = 16000
HOP_SIZE = 256
THRESHOLD = 0.5
MIN_SPEECH_DURATION_MS = 250
MIN_SILENCE_DURATION_MS = 100
SPEECH_PAD_MS = 30


class VADProcessor:
    """Voice Activity Detection processor using TEN VAD."""

    def __init__(self):
        self._vad: Optional[TenVad] = None

    def _get_vad(self) -> Optional[TenVad]:
        if self._vad is not None:
            return self._vad
        if not TEN_VAD_AVAILABLE or not NUMPY_AVAILABLE:
            return None
        try:
            self._vad = TenVad(hop_size=HOP_SIZE, threshold=THRESHOLD)
            return self._vad
        except Exception as e:
            print(f"VAD: Failed to initialize: {e}")
            return None

    def _get_speech_timestamps_from_audio(self, audio: AudioSegment) -> list[dict]:
        """Get timestamps of speech segments from prepared 16kHz mono audio."""
        vad = self._get_vad()
        if vad is None:
            return []

        samples = np.array(audio.get_array_of_samples(), dtype=np.int16)

        speech_probs = []
        for i in range(0, len(samples), HOP_SIZE):
            chunk = samples[i:i + HOP_SIZE]
            if len(chunk) < HOP_SIZE:
                chunk = np.pad(chunk, (0, HOP_SIZE - len(chunk)))
            prob, flag = vad.process(chunk)
            speech_probs.append(prob)

        triggered = False
        speeches = []
        current_speech = {}
        min_speech_samples = int(MIN_SPEECH_DURATION_MS * SAMPLE_RATE / 1000)
        min_silence_samples = int(MIN_SILENCE_DURATION_MS * SAMPLE_RATE / 1000)
        speech_pad_samples = int(SPEECH_PAD_MS * SAMPLE_RATE / 1000)

        for i, prob in enumerate(speech_probs):
            sample_pos = i * HOP_SIZE

            if prob >= THRESHOLD and not triggered:
                triggered = True
                current_speech = {'start': max(0, sample_pos - speech_pad_samples)}
            elif prob < THRESHOLD and triggered:
                look_ahead = speech_probs[i:i + (min_silence_samples // HOP_SIZE) + 1]
                if all(p < THRESHOLD for p in look_ahead) or i >= len(speech_probs) - 1:
                    triggered = False
                    current_speech['end'] = min(len(samples), sample_pos + speech_pad_samples)
                    if current_speech['end'] - current_speech['start'] >= min_speech_samples:
                        speeches.append(current_speech)

        if triggered and current_speech:
            current_speech['end'] = len(samples)
            if current_speech['end'] - current_speech['start'] >= min_speech_samples:
                speeches.append(current_speech)

        return speeches

    def remove_silence(self, audio_data: bytes) -> Tuple[bytes, float, float]:
        """Remove silence from audio using VAD."""
        audio = AudioSegment.from_wav(io.BytesIO(audio_data))
        if audio.channels > 1:
            audio = audio.set_channels(1)
        if audio.frame_rate != SAMPLE_RATE:
            audio = audio.set_frame_rate(SAMPLE_RATE)

        original_duration = len(audio) / 1000.0
        speeches = self._get_speech_timestamps_from_audio(audio)

        if not speeches:
            return audio_data, original_duration, original_duration

        combined = AudioSegment.empty()
        for speech in speeches:
            start_ms = int(speech['start'] * 1000 / SAMPLE_RATE)
            end_ms = int(speech['end'] * 1000 / SAMPLE_RATE)
            combined += audio[start_ms:end_ms]

        if len(combined) == 0:
            return audio_data, original_duration, original_duration

        output = io.BytesIO()
        combined.export(output, format="wav")
        return output.getvalue(), original_duration, len(combined) / 1000.0


_vad: Optional[VADProcessor] = None


def get_vad() -> VADProcessor:
    global _vad
    if _vad is None:
        _vad = VADProcessor()
    return _vad


def is_vad_available() -> bool:
    return TEN_VAD_AVAILABLE and NUMPY_AVAILABLE
