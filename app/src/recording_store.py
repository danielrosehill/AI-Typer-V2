"""Persistent recording store with 24-hour retention and crash recovery.

Each finalized recording becomes a folder under
`~/.local/share/ai-typer-v2/history/` containing:
    audio.wav          — the final audio sent to (or intended for) the API
    transcript.txt     — the cleaned transcription, if one succeeded
    meta.json          — id, timestamps, duration, model, status

An `_active_recording.pcm` + `_active_recording.json` pair lives at the root
while a recording is in progress. The audio recorder appends raw int16 PCM
frames to the .pcm file as they arrive; the JSON sidecar carries the sample
rate so we can wrap the PCM as WAV on recovery. On clean stop these files
are removed. If they still exist on app startup, the previous session
crashed mid-recording and we finalize the orphan PCM as a `partial` entry.

This is independent of the in-memory session history in `history.py`, which
only tracks cleaned text for the sidebar.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".local" / "share" / "ai-typer-v2" / "history"
ACTIVE_PCM_NAME = "_active_recording.pcm"
ACTIVE_META_NAME = "_active_recording.json"
RETENTION_HOURS = 24


@dataclass
class StoredEntry:
    path: Path
    meta: dict

    @property
    def id(self) -> str:
        return self.meta.get("id", self.path.name)

    @property
    def wav_path(self) -> Path:
        return self.path / "audio.wav"

    @property
    def transcript_path(self) -> Path:
        return self.path / "transcript.txt"

    @property
    def transcript(self) -> str:
        p = self.transcript_path
        if not p.exists():
            return ""
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return ""

    @property
    def created_at(self) -> datetime:
        try:
            return datetime.fromisoformat(self.meta["created_at"])
        except Exception:
            try:
                return datetime.fromtimestamp(self.path.stat().st_mtime)
            except Exception:
                return datetime.now()

    @property
    def duration_seconds(self) -> float:
        return float(self.meta.get("duration_seconds", 0.0))

    @property
    def status(self) -> str:
        return self.meta.get("status", "unknown")

    @property
    def model(self) -> str:
        return self.meta.get("model", "")


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class RecordingStore:
    def __init__(self, root: Path = DATA_DIR):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    # ── Active (in-progress) recording ─────────────────────────────────────
    def active_pcm_path(self) -> Path:
        """Return the fixed path for the in-progress PCM spill. Clears any
        pre-existing active files first so we don't accidentally append to
        a prior session's buffer."""
        self._clear_active()
        return self.root / ACTIVE_PCM_NAME

    def mark_active(self, sample_rate: int) -> None:
        """Write the sidecar metadata for the currently-active recording."""
        meta = {
            "sample_rate": int(sample_rate),
            "started_at": datetime.now().isoformat(),
        }
        try:
            (self.root / ACTIVE_META_NAME).write_text(json.dumps(meta))
        except Exception:
            logger.exception("Failed to write active-recording metadata")

    def clear_active(self) -> None:
        self._clear_active()

    def _clear_active(self) -> None:
        for name in (ACTIVE_PCM_NAME, ACTIVE_META_NAME):
            p = self.root / name
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    # ── Finalized entries ──────────────────────────────────────────────────
    def save_entry(
        self,
        audio_wav: bytes,
        *,
        transcript: str = "",
        model: str = "",
        status: str = "completed",
        duration_seconds: float = 0.0,
        error: str = "",
    ) -> StoredEntry:
        entry_id = (
            datetime.now().strftime("%Y-%m-%d_%H-%M-%S_")
            + uuid.uuid4().hex[:6]
        )
        entry_dir = self.root / entry_id
        entry_dir.mkdir(parents=True, exist_ok=True)
        (entry_dir / "audio.wav").write_bytes(audio_wav)
        if transcript:
            (entry_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
        meta = {
            "id": entry_id,
            "created_at": datetime.now().isoformat(),
            "duration_seconds": float(duration_seconds),
            "model": model,
            "status": status,
            "error": error,
        }
        (entry_dir / "meta.json").write_text(json.dumps(meta, indent=2))
        return StoredEntry(entry_dir, meta)

    def attach_transcript(
        self,
        entry_id: str,
        transcript: str,
        model: str = "",
        elapsed_seconds: float = 0.0,
    ) -> None:
        entry_dir = self.root / entry_id
        meta_path = entry_dir / "meta.json"
        if not meta_path.exists():
            return
        try:
            (entry_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
            meta = json.loads(meta_path.read_text())
            meta["status"] = "completed"
            if model:
                meta["model"] = model
            if elapsed_seconds:
                meta["transcription_seconds"] = round(elapsed_seconds, 1)
            meta_path.write_text(json.dumps(meta, indent=2))
        except Exception:
            logger.exception("attach_transcript failed for %s", entry_id)

    def mark_failed(self, entry_id: str, error: str) -> None:
        entry_dir = self.root / entry_id
        meta_path = entry_dir / "meta.json"
        if not meta_path.exists():
            return
        try:
            meta = json.loads(meta_path.read_text())
            meta["status"] = "failed"
            meta["error"] = error
            meta_path.write_text(json.dumps(meta, indent=2))
        except Exception:
            logger.exception("mark_failed failed for %s", entry_id)

    def list_entries(self) -> list[StoredEntry]:
        entries: list[StoredEntry] = []
        try:
            children = list(self.root.iterdir())
        except FileNotFoundError:
            return []
        for child in children:
            if not child.is_dir() or child.name.startswith("_"):
                continue
            meta_path = child / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text())
            except Exception:
                continue
            entries.append(StoredEntry(child, meta))
        entries.sort(key=lambda e: e.meta.get("created_at", ""), reverse=True)
        return entries

    def get_entry(self, entry_id: str) -> Optional[StoredEntry]:
        entry_dir = self.root / entry_id
        meta_path = entry_dir / "meta.json"
        if not meta_path.exists():
            return None
        try:
            return StoredEntry(entry_dir, json.loads(meta_path.read_text()))
        except Exception:
            return None

    def delete_entry(self, entry_id: str) -> None:
        entry_dir = self.root / entry_id
        if entry_dir.is_dir() and not entry_id.startswith("_"):
            shutil.rmtree(entry_dir, ignore_errors=True)

    # ── Housekeeping ───────────────────────────────────────────────────────
    def cleanup_old(self, hours: int = RETENTION_HOURS) -> int:
        """Delete entries older than `hours`. Returns number deleted."""
        cutoff = datetime.now() - timedelta(hours=hours)
        deleted = 0
        for entry in self.list_entries():
            try:
                if entry.created_at < cutoff:
                    shutil.rmtree(entry.path, ignore_errors=True)
                    deleted += 1
            except Exception:
                pass
        return deleted

    def recover_crashed(self) -> Optional[StoredEntry]:
        """If an active PCM spill exists from a crashed prior session,
        finalize it as a `partial` entry. Returns the created entry or None."""
        pcm_path = self.root / ACTIVE_PCM_NAME
        meta_path = self.root / ACTIVE_META_NAME
        if not pcm_path.exists():
            self._clear_active()
            return None
        try:
            sample_rate = 48000
            if meta_path.exists():
                try:
                    sample_rate = int(
                        json.loads(meta_path.read_text()).get("sample_rate", 48000)
                    )
                except Exception:
                    pass
            pcm_bytes = pcm_path.read_bytes()
            if len(pcm_bytes) < sample_rate * 2 * 1:  # <1s of audio — treat as noise
                self._clear_active()
                return None
            wav_bytes = _pcm_to_wav(pcm_bytes, sample_rate)
            duration = len(pcm_bytes) / (sample_rate * 2)
            entry = self.save_entry(
                wav_bytes,
                status="partial",
                duration_seconds=duration,
                error="Recovered from interrupted recording",
            )
            self._clear_active()
            return entry
        except Exception:
            logger.exception("Crash recovery failed")
            self._clear_active()
            return None
