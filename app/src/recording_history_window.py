"""Dialog showing persistent recording history (last 24 hours)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .recording_store import RecordingStore, StoredEntry


_STATUS_BADGE = {
    "completed": "✓",      # ✓
    "partial": "⚠ recovered",  # ⚠
    "failed": "✗ failed",  # ✗
}


def _format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "—"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


class RecordingHistoryWindow(QDialog):
    """Browser for on-disk recordings. Emits `retranscribe_requested` with a
    WAV path when the user asks to re-transcribe a past entry."""

    retranscribe_requested = pyqtSignal(str)  # path to audio.wav

    def __init__(self, store: RecordingStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Recording History")
        self.resize(760, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        info = QLabel(
            "Audio and transcripts from the last 24 hours are saved for "
            "crash recovery and re-transcription. Older entries are "
            "auto-deleted."
        )
        info.setStyleSheet("color: #888; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_select)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._copy())
        layout.addWidget(self.list_widget, 1)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Select a recording to preview its transcript")
        self.preview.setMaximumHeight(160)
        layout.addWidget(self.preview)

        btn_row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy Transcript")
        self.copy_btn.clicked.connect(self._copy)
        self.retrans_btn = QPushButton("Re-transcribe")
        self.retrans_btn.clicked.connect(self._retrans)
        self.play_btn = QPushButton("Open Audio")
        self.play_btn.clicked.connect(self._play)
        self.reveal_btn = QPushButton("Show in Folder")
        self.reveal_btn.clicked.connect(self._reveal)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete)

        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.retrans_btn)
        btn_row.addWidget(self.play_btn)
        btn_row.addWidget(self.reveal_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.delete_btn)
        layout.addLayout(btn_row)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self._refresh()
        self._update_buttons()

    # ── data ─────────────────────────────────────────────────────────────
    def _refresh(self) -> None:
        self.list_widget.clear()
        for entry in self.store.list_entries():
            ts = entry.created_at.strftime("%H:%M:%S")
            date = entry.created_at.strftime("%Y-%m-%d")
            dur = _format_duration(entry.duration_seconds)
            badge = _STATUS_BADGE.get(entry.status, entry.status)
            transcript = entry.transcript or ""
            first_line = transcript.split("\n", 1)[0].strip() if transcript else ""
            if len(first_line) > 70:
                first_line = first_line[:67] + "..."
            if not first_line:
                first_line = "(no transcript)" if entry.status != "completed" else ""
            label = f"{date}  {ts}    {dur:>5}    {badge:<12}    {first_line}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            self.list_widget.addItem(item)
        self.preview.clear()

    def _selected(self) -> Optional[StoredEntry]:
        item = self.list_widget.currentItem()
        if not item:
            return None
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        return self.store.get_entry(entry_id) if entry_id else None

    def _on_select(self) -> None:
        entry = self._selected()
        if not entry:
            self.preview.clear()
        else:
            self.preview.setPlainText(entry.transcript or "(no transcript available)")
        self._update_buttons()

    def _update_buttons(self) -> None:
        entry = self._selected()
        has_entry = entry is not None
        has_audio = bool(entry and entry.wav_path.exists())
        has_transcript = bool(entry and entry.transcript)
        self.copy_btn.setEnabled(has_transcript)
        self.retrans_btn.setEnabled(has_audio)
        self.play_btn.setEnabled(has_audio)
        self.reveal_btn.setEnabled(has_entry)
        self.delete_btn.setEnabled(has_entry)

    # ── actions ──────────────────────────────────────────────────────────
    def _copy(self) -> None:
        entry = self._selected()
        if not entry or not entry.transcript:
            return
        QApplication.clipboard().setText(entry.transcript)

    def _retrans(self) -> None:
        entry = self._selected()
        if not entry or not entry.wav_path.exists():
            return
        self.retranscribe_requested.emit(str(entry.wav_path))
        self.accept()

    def _play(self) -> None:
        entry = self._selected()
        if not entry or not entry.wav_path.exists():
            return
        try:
            subprocess.Popen(["xdg-open", str(entry.wav_path)])
        except Exception as e:
            QMessageBox.warning(self, "Open Audio", f"Could not open audio file:\n{e}")

    def _reveal(self) -> None:
        entry = self._selected()
        if not entry:
            return
        try:
            subprocess.Popen(["xdg-open", str(entry.path)])
        except Exception as e:
            QMessageBox.warning(self, "Show in Folder", f"Could not open folder:\n{e}")

    def _delete(self) -> None:
        entry = self._selected()
        if not entry:
            return
        confirm = QMessageBox.question(
            self,
            "Delete recording",
            f"Delete this recording and its transcript?\n\n{entry.path.name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_entry(entry.id)
        self._refresh()
        self._update_buttons()
