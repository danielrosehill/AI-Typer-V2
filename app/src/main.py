#!/usr/bin/env python3
"""AI Typer V2 — Voice dictation with multimodal AI cleanup.

Single-window UI: record, transcribe, done. Format detection is automatic.
"""

import sys
import os
import time
import subprocess
from pathlib import Path

# Load .env
for env_path in [Path(__file__).parent / ".env", Path(__file__).parent.parent / ".env"]:
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
        break

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QComboBox, QLabel, QDialog, QFormLayout,
    QLineEdit, QCheckBox, QMessageBox, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QAction, QIcon

from .config import (
    Config, load_config, save_config, build_cleanup_prompt,
    FORMAT_PRESETS, TONE_PRESETS, MODELS, REVIEW_MODEL, REVIEW_PROMPT,
)
from .audio_recorder import AudioRecorder
from .audio_processor import prepare_audio_for_api, combine_wav_segments
from .transcription import get_client
from .hotkeys import create_hotkey_listener
from .clipboard import copy_to_clipboard
from .vad_processor import is_vad_available


class TranscriptionWorker(QThread):
    """Background thread for transcription API call."""
    finished = pyqtSignal(str, float)  # text, elapsed_seconds
    error = pyqtSignal(str)

    def __init__(self, api_key, model, audio_data, prompt, review_enabled=False):
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.audio_data = audio_data
        self.prompt = prompt
        self.review_enabled = review_enabled

    def run(self):
        try:
            start = time.time()
            client = get_client(self.api_key, self.model)
            result = client.transcribe(self.audio_data, self.prompt)
            text = result.text

            # Second-pass review
            if self.review_enabled and text and len(text.strip()) > 20:
                try:
                    review_client = get_client(self.api_key, REVIEW_MODEL)
                    review_result = review_client.review_text(text, REVIEW_PROMPT)
                    if review_result.text and review_result.text.strip():
                        text = review_result.text
                except Exception:
                    pass  # Review failure is non-fatal; use first-pass result

            elapsed = time.time() - start
            self.finished.emit(text, elapsed)
        except Exception as e:
            self.error.emit(str(e))


class SettingsDialog(QDialog):
    """Simple settings dialog — just the essentials."""

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Settings")
        self.setMinimumWidth(450)

        layout = QFormLayout(self)
        layout.setSpacing(12)

        # API Key
        self.api_key_edit = QLineEdit(config.openrouter_api_key)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-or-...")
        layout.addRow("OpenRouter API Key:", self.api_key_edit)

        # Model
        self.model_combo = QComboBox()
        for model_id, display_name in MODELS:
            self.model_combo.addItem(display_name, model_id)
        idx = self.model_combo.findData(config.selected_model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        layout.addRow("Model:", self.model_combo)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        layout.addRow(sep1)

        # Personalization
        self.user_name_edit = QLineEdit(config.user_name)
        self.user_name_edit.setPlaceholderText("Your name (for email sign-offs)")
        layout.addRow("Name:", self.user_name_edit)

        self.email_edit = QLineEdit(config.email_address)
        self.email_edit.setPlaceholderText("your@email.com")
        layout.addRow("Email:", self.email_edit)

        self.signature_edit = QLineEdit(config.email_signature)
        layout.addRow("Sign-off:", self.signature_edit)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        layout.addRow(sep2)

        # Features
        self.vad_check = QCheckBox("Voice Activity Detection (remove silence)")
        self.vad_check.setChecked(config.vad_enabled)
        if not is_vad_available():
            self.vad_check.setEnabled(False)
            self.vad_check.setToolTip("ten-vad not installed")
        layout.addRow(self.vad_check)

        self.review_check = QCheckBox("Second-pass review (catches misheard words)")
        self.review_check.setChecked(config.review_enabled)
        layout.addRow(self.review_check)

        # Separator
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        layout.addRow(sep3)

        # Output modes
        self.out_app = QCheckBox("Show in app")
        self.out_app.setChecked(config.output_to_app)
        self.out_clipboard = QCheckBox("Copy to clipboard")
        self.out_clipboard.setChecked(config.output_to_clipboard)
        self.out_inject = QCheckBox("Type at cursor (ydotool)")
        self.out_inject.setChecked(config.output_to_inject)
        layout.addRow("Output:", self.out_app)
        layout.addRow("", self.out_clipboard)
        layout.addRow("", self.out_inject)

        # Separator
        sep4 = QFrame()
        sep4.setFrameShape(QFrame.Shape.HLine)
        layout.addRow(sep4)

        # Hotkeys
        self.hotkey_toggle_edit = QLineEdit(config.hotkey_toggle)
        self.hotkey_toggle_edit.setPlaceholderText("f15")
        layout.addRow("Toggle (start/stop):", self.hotkey_toggle_edit)

        self.hotkey_clear_edit = QLineEdit(config.hotkey_clear)
        self.hotkey_clear_edit.setPlaceholderText("f18")
        layout.addRow("Clear:", self.hotkey_clear_edit)

        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addRow(btn_layout)

    def get_config(self) -> Config:
        """Return updated config from dialog values."""
        self.config.openrouter_api_key = self.api_key_edit.text().strip()
        self.config.selected_model = self.model_combo.currentData()
        self.config.user_name = self.user_name_edit.text().strip()
        self.config.email_address = self.email_edit.text().strip()
        self.config.email_signature = self.signature_edit.text().strip()
        self.config.vad_enabled = self.vad_check.isChecked()
        self.config.review_enabled = self.review_check.isChecked()
        self.config.output_to_app = self.out_app.isChecked()
        self.config.output_to_clipboard = self.out_clipboard.isChecked()
        self.config.output_to_inject = self.out_inject.isChecked()
        self.config.hotkey_toggle = self.hotkey_toggle_edit.text().strip().lower()
        self.config.hotkey_clear = self.hotkey_clear_edit.text().strip().lower()
        return self.config


class MainWindow(QMainWindow):
    """Main application window — clean single-page layout."""

    # Signals for thread-safe UI updates from hotkey callbacks
    _toggle_signal = pyqtSignal()
    _clear_signal = pyqtSignal()
    _tap_toggle_signal = pyqtSignal()
    _transcribe_signal = pyqtSignal()
    _append_signal = pyqtSignal()
    _pause_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.recorder = AudioRecorder()
        self.recorder.on_error = self._on_recording_error
        self.hotkey_listener = None
        self.worker = None
        self._cached_segments: list[bytes] = []
        self._duration_timer = QTimer()
        self._duration_timer.timeout.connect(self._update_duration)

        self._setup_ui()
        self._setup_hotkeys()
        self._connect_signals()

        # Check API key on startup
        if not self.config.openrouter_api_key:
            QTimer.singleShot(500, self._prompt_api_key)

    def _setup_ui(self):
        self.setWindowTitle("AI Typer V2")
        self.resize(self.config.window_width, self.config.window_height)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # ── Top control bar ──
        controls = QHBoxLayout()
        controls.setSpacing(8)

        # Format selector
        format_label = QLabel("Format:")
        format_label.setStyleSheet("color: #888; font-size: 12px;")
        controls.addWidget(format_label)

        self.format_combo = QComboBox()
        self.format_combo.setMinimumWidth(120)
        for key, data in FORMAT_PRESETS.items():
            self.format_combo.addItem(data["label"], key)
        idx = self.format_combo.findData(self.config.format_preset)
        if idx >= 0:
            self.format_combo.setCurrentIndex(idx)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        controls.addWidget(self.format_combo)

        # Tone selector
        tone_label = QLabel("Tone:")
        tone_label.setStyleSheet("color: #888; font-size: 12px;")
        controls.addWidget(tone_label)

        self.tone_combo = QComboBox()
        self.tone_combo.setMinimumWidth(100)
        for key in TONE_PRESETS:
            self.tone_combo.addItem(key.capitalize(), key)
        idx = self.tone_combo.findData(self.config.tone)
        if idx >= 0:
            self.tone_combo.setCurrentIndex(idx)
        self.tone_combo.currentIndexChanged.connect(self._on_tone_changed)
        controls.addWidget(self.tone_combo)

        controls.addStretch()

        # Model indicator
        self.model_label = QLabel(self._model_display_name())
        self.model_label.setStyleSheet("color: #666; font-size: 11px;")
        controls.addWidget(self.model_label)

        layout.addLayout(controls)

        # ── Text area ──
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(
            "Press the record button or your hotkey to start dictating.\n\n"
            "Your transcription will appear here."
        )
        self.text_edit.setFont(QFont("Sans Serif", 12))
        self.text_edit.setAcceptRichText(False)
        layout.addWidget(self.text_edit)

        # ── Bottom control bar ──
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        # Record button (large, prominent)
        self.record_btn = QPushButton("  Record")
        self.record_btn.setMinimumHeight(42)
        self.record_btn.setMinimumWidth(140)
        self.record_btn.setFont(QFont("Sans Serif", 13, QFont.Weight.Bold))
        self.record_btn.setStyleSheet(self._record_btn_style(False))
        self.record_btn.clicked.connect(self._toggle_recording)
        bottom.addWidget(self.record_btn)

        # Duration label
        self.duration_label = QLabel("")
        self.duration_label.setStyleSheet("color: #888; font-size: 13px; font-family: monospace;")
        self.duration_label.setMinimumWidth(50)
        bottom.addWidget(self.duration_label)

        bottom.addStretch()

        # Copy button
        copy_btn = QPushButton("Copy")
        copy_btn.setMinimumHeight(36)
        copy_btn.clicked.connect(self._copy_text)
        bottom.addWidget(copy_btn)

        # Clear text button
        clear_btn = QPushButton("Clear")
        clear_btn.setMinimumHeight(36)
        clear_btn.clicked.connect(self._clear_text)
        bottom.addWidget(clear_btn)

        layout.addLayout(bottom)

        # ── Status bar ──
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.status_label)

        # ── Menu bar ──
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")

        settings_action = QAction("&Settings...", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _record_btn_style(self, recording: bool) -> str:
        if recording:
            return """
                QPushButton {
                    background-color: #dc3545;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                }
                QPushButton:hover { background-color: #c82333; }
            """
        return """
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover { background-color: #218838; }
        """

    def _model_display_name(self) -> str:
        for model_id, name in MODELS:
            if model_id == self.config.selected_model:
                return name
        return self.config.selected_model

    def _connect_signals(self):
        self._toggle_signal.connect(self._toggle_recording)
        self._clear_signal.connect(self._clear_recording)
        self._tap_toggle_signal.connect(self._tap_toggle)
        self._transcribe_signal.connect(self._transcribe_cached)
        self._append_signal.connect(self._start_append)
        self._pause_signal.connect(self._pause_resume)

    def _setup_hotkeys(self):
        if self.hotkey_listener:
            self.hotkey_listener.stop()

        self.hotkey_listener = create_hotkey_listener()

        hk = self.config
        if hk.hotkey_toggle:
            self.hotkey_listener.register("toggle", hk.hotkey_toggle,
                                          lambda: self._toggle_signal.emit())
        if hk.hotkey_tap_toggle:
            self.hotkey_listener.register("tap_toggle", hk.hotkey_tap_toggle,
                                          lambda: self._tap_toggle_signal.emit())
        if hk.hotkey_transcribe:
            self.hotkey_listener.register("transcribe", hk.hotkey_transcribe,
                                          lambda: self._transcribe_signal.emit())
        if hk.hotkey_clear:
            self.hotkey_listener.register("clear", hk.hotkey_clear,
                                          lambda: self._clear_signal.emit())
        if hk.hotkey_append:
            self.hotkey_listener.register("append", hk.hotkey_append,
                                          lambda: self._append_signal.emit())
        if hk.hotkey_pause:
            self.hotkey_listener.register("pause", hk.hotkey_pause,
                                          lambda: self._pause_signal.emit())

        self.hotkey_listener.start()

    # ── Recording controls ──

    def _toggle_recording(self):
        """Toggle: if recording, stop + transcribe. If idle, start recording."""
        if self.recorder.is_recording:
            self._stop_and_transcribe()
        else:
            self._start_recording()

    def _start_recording(self):
        if self.recorder.is_recording:
            return
        if self.recorder.start_recording():
            self.record_btn.setText("  Stop")
            self.record_btn.setStyleSheet(self._record_btn_style(True))
            self.status_label.setText("Recording...")
            self.duration_label.setText("0:00")
            self._duration_timer.start(500)

    def _stop_and_transcribe(self):
        if not self.recorder.is_recording:
            return
        self._duration_timer.stop()
        audio_data = self.recorder.stop_recording()
        self.record_btn.setText("  Record")
        self.record_btn.setStyleSheet(self._record_btn_style(False))

        # If we have cached segments, combine them with this recording
        if self._cached_segments:
            self._cached_segments.append(audio_data)
            audio_data = combine_wav_segments(self._cached_segments)
            self._cached_segments = []

        self._transcribe(audio_data)

    def _tap_toggle(self):
        """Tap toggle: start recording, or stop and cache (for append workflow)."""
        if self.recorder.is_recording:
            self._duration_timer.stop()
            audio_data = self.recorder.stop_recording()
            self._cached_segments.append(audio_data)
            self.record_btn.setText("  Record")
            self.record_btn.setStyleSheet(self._record_btn_style(False))
            n = len(self._cached_segments)
            self.status_label.setText(f"Cached ({n} segment{'s' if n > 1 else ''})")
            self.duration_label.setText("")
        else:
            self._start_recording()

    def _transcribe_cached(self):
        """Transcribe all cached audio segments."""
        if not self._cached_segments:
            self.status_label.setText("No cached audio to transcribe")
            return
        audio_data = combine_wav_segments(self._cached_segments)
        self._cached_segments = []
        self._transcribe(audio_data)

    def _start_append(self):
        """Start a new recording segment to append to cache."""
        self._start_recording()

    def _pause_resume(self):
        """Pause or resume recording."""
        if not self.recorder.is_recording:
            return
        if self.recorder.is_paused:
            self.recorder.resume_recording()
            self.status_label.setText("Recording...")
        else:
            self.recorder.pause_recording()
            self.status_label.setText("Paused")

    def _clear_recording(self):
        """Clear current recording and cache."""
        if self.recorder.is_recording:
            self._duration_timer.stop()
            self.recorder.stop_recording()
            self.record_btn.setText("  Record")
            self.record_btn.setStyleSheet(self._record_btn_style(False))
        self._cached_segments = []
        self.duration_label.setText("")
        self.status_label.setText("Cleared")

    def _update_duration(self):
        secs = self.recorder.get_duration()
        mins = int(secs) // 60
        sec = int(secs) % 60
        self.duration_label.setText(f"{mins}:{sec:02d}")

    # ── Transcription ──

    def _transcribe(self, audio_data: bytes):
        if not self.config.openrouter_api_key:
            self.status_label.setText("No API key configured — open Settings")
            return

        self.status_label.setText("Processing audio...")
        self.record_btn.setEnabled(False)

        # Process audio (VAD + AGC + compression)
        processed, orig_dur, vad_dur = prepare_audio_for_api(
            audio_data,
            vad_enabled=self.config.vad_enabled,
        )

        if vad_dur is not None and orig_dur:
            saved = (1 - vad_dur / orig_dur) * 100 if orig_dur > 0 else 0
            self.status_label.setText(
                f"Transcribing... (VAD: {orig_dur:.1f}s -> {vad_dur:.1f}s, -{saved:.0f}%)"
            )
        else:
            self.status_label.setText("Transcribing...")

        # Build prompt with current UI settings
        prompt = build_cleanup_prompt(self.config, audio_duration_seconds=orig_dur)

        self.worker = TranscriptionWorker(
            api_key=self.config.openrouter_api_key,
            model=self.config.selected_model,
            audio_data=processed,
            prompt=prompt,
            review_enabled=self.config.review_enabled,
        )
        self.worker.finished.connect(self._on_transcription_done)
        self.worker.error.connect(self._on_transcription_error)
        self.worker.start()

    def _on_transcription_done(self, text: str, elapsed: float):
        self.record_btn.setEnabled(True)

        if self.config.output_to_app:
            # Append to existing text with spacing
            existing = self.text_edit.toPlainText()
            if existing.strip():
                self.text_edit.setPlainText(existing.rstrip() + "\n\n" + text)
            else:
                self.text_edit.setPlainText(text)
            # Scroll to bottom
            cursor = self.text_edit.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.text_edit.setTextCursor(cursor)

        if self.config.output_to_clipboard:
            copy_to_clipboard(text)

        if self.config.output_to_inject:
            self._inject_text(text)

        # Status
        parts = [f"Done in {elapsed:.1f}s"]
        if self.config.output_to_clipboard:
            parts.append("copied")
        if self.config.output_to_inject:
            parts.append("injected")
        self.status_label.setText(" | ".join(parts))

    def _on_transcription_error(self, error: str):
        self.record_btn.setEnabled(True)
        self.status_label.setText(f"Error: {error}")

    def _on_recording_error(self, error: str):
        self._duration_timer.stop()
        self.record_btn.setText("  Record")
        self.record_btn.setStyleSheet(self._record_btn_style(False))
        self.status_label.setText(f"Mic error: {error}")

    def _inject_text(self, text: str):
        """Type text at cursor position using ydotool."""
        try:
            subprocess.run(
                ["ydotool", "type", "--", text],
                timeout=10,
                capture_output=True,
            )
        except FileNotFoundError:
            self.status_label.setText("ydotool not installed — can't inject text")
        except Exception as e:
            self.status_label.setText(f"Inject error: {e}")

    # ── UI Actions ──

    def _copy_text(self):
        text = self.text_edit.toPlainText()
        if text.strip():
            copy_to_clipboard(text)
            self.status_label.setText("Copied to clipboard")
        else:
            self.status_label.setText("Nothing to copy")

    def _clear_text(self):
        self.text_edit.clear()
        self.status_label.setText("Cleared")

    def _on_format_changed(self):
        self.config.format_preset = self.format_combo.currentData()
        save_config(self.config)

    def _on_tone_changed(self):
        self.config.tone = self.tone_combo.currentData()
        save_config(self.config)

    def _open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.config = dialog.get_config()
            save_config(self.config)
            self.model_label.setText(self._model_display_name())
            self._setup_hotkeys()

    def _prompt_api_key(self):
        """Prompt for API key if not configured."""
        msg = QMessageBox(self)
        msg.setWindowTitle("API Key Required")
        msg.setText(
            "No OpenRouter API key found.\n\n"
            "You need an API key from openrouter.ai to use AI Typer.\n"
            "Open Settings to configure it."
        )
        msg.addButton("Open Settings", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        if msg.exec() == 0:
            self._open_settings()

    def closeEvent(self, event):
        # Save window size
        self.config.window_width = self.width()
        self.config.window_height = self.height()
        save_config(self.config)

        if self.hotkey_listener:
            self.hotkey_listener.stop()
        if self.recorder.is_recording:
            self.recorder.stop_recording()
        self.recorder.cleanup()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AI Typer V2")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
