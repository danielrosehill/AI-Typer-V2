"""Ephemeral transcription history — in-memory ring buffer.

Keeps the last N transcriptions for the current session only.
No database, no persistence. Like clipboard history.
"""

from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
from typing import Optional


@dataclass
class HistoryEntry:
    """A single transcription result."""
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    elapsed_seconds: float = 0.0
    format_preset: str = "auto"
    word_count: int = 0

    def __post_init__(self):
        if self.word_count == 0 and self.text:
            self.word_count = len(self.text.split())

    @property
    def preview(self) -> str:
        """First line, truncated to 80 chars."""
        first_line = self.text.split("\n")[0].strip()
        if len(first_line) > 80:
            return first_line[:77] + "..."
        return first_line

    @property
    def time_str(self) -> str:
        return self.timestamp.strftime("%H:%M")


class TranscriptionHistory:
    """In-memory ring buffer of recent transcriptions."""

    def __init__(self, max_items: int = 20):
        self._entries: deque[HistoryEntry] = deque(maxlen=max_items)

    def add(self, text: str, elapsed_seconds: float = 0.0, format_preset: str = "auto"):
        """Add a transcription to history."""
        if not text or not text.strip():
            return
        self._entries.appendleft(HistoryEntry(
            text=text,
            elapsed_seconds=elapsed_seconds,
            format_preset=format_preset,
        ))

    def get_all(self) -> list[HistoryEntry]:
        """Get all entries, newest first."""
        return list(self._entries)

    def get(self, index: int) -> Optional[HistoryEntry]:
        """Get entry by index (0 = most recent)."""
        if 0 <= index < len(self._entries):
            return self._entries[index]
        return None

    def clear(self):
        self._entries.clear()

    def __len__(self):
        return len(self._entries)

    @property
    def latest(self) -> Optional[HistoryEntry]:
        return self._entries[0] if self._entries else None
