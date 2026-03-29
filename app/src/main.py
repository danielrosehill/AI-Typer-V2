#!/usr/bin/env python3
"""Multimodal Voice Typer — Voice dictation with multimodal AI cleanup.

Single-window UI: record, transcribe, done. Format detection is automatic.
"""

import sys
import os
import time
import threading
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
    QListWidget, QListWidgetItem, QSplitter, QSystemTrayIcon, QMenu,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QAction, QIcon

from .config import (
    Config, load_config, save_config, build_cleanup_prompt,
    FORMAT_PRESETS, TONE_PRESETS, MODELS, DEFAULT_MODEL, DEFAULT_BUDGET_MODEL,
    REVIEW_MODEL, REVIEW_PROMPT, HOTKEY_OPTIONS, TRANSLATION_LANGUAGES,
    get_language_display_name, get_manufacturers, get_models_for_manufacturer,
    get_model_by_id, APP_VERSION,
)
from PyQt6.QtWidgets import QTabWidget
from .audio_recorder import AudioRecorder
from .audio_processor import prepare_audio_for_api, combine_wav_segments
from .transcription import get_client
from .hotkeys import create_hotkey_listener
from .clipboard import copy_to_clipboard
from .vad_processor import is_vad_available
from .audio_feedback import get_feedback
from .tts_announcer import get_announcer
from .history import TranscriptionHistory


class TranscriptionWorker(QThread):
    """Background thread for audio processing + transcription API call."""
    finished = pyqtSignal(str, float)  # text, elapsed_seconds
    error = pyqtSignal(str)
    status = pyqtSignal(str)  # status updates for UI

    def __init__(self, api_key, model, raw_audio_data, prompt,
                 review_enabled=False, vad_enabled=False):
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.raw_audio_data = raw_audio_data
        self.prompt = prompt
        self.review_enabled = review_enabled
        self.vad_enabled = vad_enabled

    def run(self):
        try:
            start = time.time()

            # Audio processing (VAD + AGC + MP3 compression) — runs off main thread
            self.status.emit("Processing audio...")
            processed, orig_dur, vad_dur = prepare_audio_for_api(
                self.raw_audio_data,
                vad_enabled=self.vad_enabled,
            )

            self.status.emit("Transcribing...")
            client = get_client(self.api_key, self.model)
            result = client.transcribe(processed, self.prompt)
            text = result.text

            # Second-pass review
            if self.review_enabled and text and len(text.strip()) > 20:
                try:
                    self.status.emit("Reviewing...")
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


class _ModelPicker(QWidget):
    """Cascading Provider → Model selector widget."""

    def __init__(self, current_model_id: str, category_filter: str = "", parent=None):
        super().__init__(parent)
        self._category_filter = category_filter
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.provider_combo = QComboBox()
        self.provider_combo.setMinimumWidth(120)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(200)

        layout.addWidget(self.provider_combo)
        layout.addWidget(self.model_combo)

        # Populate providers
        for mfr in get_manufacturers(category_filter):
            self.provider_combo.addItem(mfr, mfr)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

        # Set to current model's provider, then select the model
        current = get_model_by_id(current_model_id)
        if current:
            idx = self.provider_combo.findData(current["manufacturer"])
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)
            self._on_provider_changed()
            idx = self.model_combo.findData(current_model_id)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
        else:
            self._on_provider_changed()

    def _on_provider_changed(self):
        self.model_combo.clear()
        mfr = self.provider_combo.currentData()
        if not mfr:
            return
        for m in get_models_for_manufacturer(mfr, self._category_filter):
            self.model_combo.addItem(m["label"], m["id"])

    def selected_model_id(self) -> str:
        return self.model_combo.currentData() or ""


class SettingsDialog(QDialog):
    """Tabbed settings dialog."""

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)

        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs)

        # ── Tab 1: General ──
        general = QWidget()
        gl = QFormLayout(general)
        gl.setSpacing(12)

        # API Key
        self.api_key_edit = QLineEdit(config.openrouter_api_key)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-or-...")
        gl.addRow("OpenRouter API Key:", self.api_key_edit)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        gl.addRow(sep)

        # Default model (all models)
        self.default_picker = _ModelPicker(config.default_model)
        gl.addRow("Default model:", self.default_picker)

        # Budget model (budget only)
        self.budget_picker = _ModelPicker(config.default_budget_model, category_filter="Budget")
        gl.addRow("Budget model:", self.budget_picker)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        gl.addRow(sep2)

        # Personalization
        self.user_name_edit = QLineEdit(config.user_name)
        self.user_name_edit.setPlaceholderText("Your name (for email sign-offs)")
        gl.addRow("Name:", self.user_name_edit)

        self.email_edit = QLineEdit(config.email_address)
        self.email_edit.setPlaceholderText("your@email.com")
        gl.addRow("Email:", self.email_edit)

        self.signature_edit = QLineEdit(config.email_signature)
        gl.addRow("Sign-off:", self.signature_edit)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.Shape.HLine)
        gl.addRow(sep3)

        # Output modes
        self.out_app = QCheckBox("Show in app")
        self.out_app.setChecked(config.output_to_app)
        self.out_clipboard = QCheckBox("Copy to clipboard")
        self.out_clipboard.setChecked(config.output_to_clipboard)
        self.out_inject = QCheckBox("Type at cursor (ydotool)")
        self.out_inject.setChecked(config.output_to_inject)
        gl.addRow("Output:", self.out_app)
        gl.addRow("", self.out_clipboard)
        gl.addRow("", self.out_inject)

        tabs.addTab(general, "General")

        # ── Tab 2: Advanced ──
        advanced = QWidget()
        al = QFormLayout(advanced)
        al.setSpacing(12)

        # Features
        self.vad_check = QCheckBox("Voice Activity Detection (remove silence)")
        self.vad_check.setChecked(config.vad_enabled)
        if not is_vad_available():
            self.vad_check.setEnabled(False)
            self.vad_check.setToolTip("ten-vad not installed")
        al.addRow(self.vad_check)

        self.review_check = QCheckBox("Second-pass review (catches misheard words)")
        self.review_check.setChecked(config.review_enabled)
        al.addRow(self.review_check)

        sep4 = QFrame(); sep4.setFrameShape(QFrame.Shape.HLine)
        al.addRow(sep4)

        # Translation
        self.translation_combo = QComboBox()
        for code, name in TRANSLATION_LANGUAGES:
            self.translation_combo.addItem(name, code)
        idx = self.translation_combo.findData(config.translation_target)
        if idx >= 0:
            self.translation_combo.setCurrentIndex(idx)
        al.addRow("Translate to:", self.translation_combo)

        # Audio feedback
        self.feedback_combo = QComboBox()
        self.feedback_combo.addItem("Beeps", "beeps")
        self.feedback_combo.addItem("Voice (TTS)", "tts")
        self.feedback_combo.addItem("Silent", "silent")
        idx = self.feedback_combo.findData(config.audio_feedback_mode)
        if idx >= 0:
            self.feedback_combo.setCurrentIndex(idx)
        al.addRow("Audio feedback:", self.feedback_combo)

        sep5 = QFrame(); sep5.setFrameShape(QFrame.Shape.HLine)
        al.addRow(sep5)

        # Hotkeys
        self.hotkey_toggle_combo = QComboBox()
        self.hotkey_tap_combo = QComboBox()
        self.hotkey_transcribe_combo = QComboBox()
        self.hotkey_clear_combo = QComboBox()
        self.hotkey_append_combo = QComboBox()
        self.hotkey_pause_combo = QComboBox()
        self.hotkey_retake_combo = QComboBox()

        hotkey_combos = [
            (self.hotkey_toggle_combo, config.hotkey_toggle, "Toggle (start/stop):"),
            (self.hotkey_tap_combo, config.hotkey_tap_toggle, "Tap toggle (cache):"),
            (self.hotkey_transcribe_combo, config.hotkey_transcribe, "Transcribe cached:"),
            (self.hotkey_clear_combo, config.hotkey_clear, "Clear:"),
            (self.hotkey_append_combo, config.hotkey_append, "Append:"),
            (self.hotkey_pause_combo, config.hotkey_pause, "Pause/Resume:"),
            (self.hotkey_retake_combo, config.hotkey_retake, "Retake:"),
        ]
        for combo, current_value, label_text in hotkey_combos:
            for key_id, display_name in HOTKEY_OPTIONS:
                combo.addItem(display_name, key_id)
            idx = combo.findData(current_value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            al.addRow(label_text, combo)

        tabs.addTab(advanced, "Advanced")

        # ── Buttons ──
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        outer.addLayout(btn_layout)

    def get_config(self) -> Config:
        """Return updated config from dialog values."""
        self.config.openrouter_api_key = self.api_key_edit.text().strip()
        self.config.default_model = self.default_picker.selected_model_id()
        self.config.default_budget_model = self.budget_picker.selected_model_id()
        self.config.user_name = self.user_name_edit.text().strip()
        self.config.email_address = self.email_edit.text().strip()
        self.config.email_signature = self.signature_edit.text().strip()
        self.config.vad_enabled = self.vad_check.isChecked()
        self.config.review_enabled = self.review_check.isChecked()
        self.config.translation_target = self.translation_combo.currentData()
        self.config.output_to_app = self.out_app.isChecked()
        self.config.output_to_clipboard = self.out_clipboard.isChecked()
        self.config.output_to_inject = self.out_inject.isChecked()
        self.config.audio_feedback_mode = self.feedback_combo.currentData()
        self.config.hotkey_toggle = self.hotkey_toggle_combo.currentData()
        self.config.hotkey_tap_toggle = self.hotkey_tap_combo.currentData()
        self.config.hotkey_transcribe = self.hotkey_transcribe_combo.currentData()
        self.config.hotkey_clear = self.hotkey_clear_combo.currentData()
        self.config.hotkey_append = self.hotkey_append_combo.currentData()
        self.config.hotkey_pause = self.hotkey_pause_combo.currentData()
        self.config.hotkey_retake = self.hotkey_retake_combo.currentData()
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
    _retake_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.recorder = AudioRecorder()
        self.recorder.on_error = self._on_recording_error
        self.hotkey_listener = None
        self.worker = None
        self._cached_segments: list[bytes] = []
        self._raw_text: str = ""  # Raw markdown text (for clipboard/append)
        self._history = TranscriptionHistory(max_items=20)
        self._duration_timer = QTimer()
        self._duration_timer.timeout.connect(self._update_duration)

        self._setup_ui()
        self._setup_tray()
        self._setup_hotkeys()
        self._connect_signals()

        # Check API key on startup
        if not self.config.openrouter_api_key:
            QTimer.singleShot(500, self._prompt_api_key)

    def _setup_ui(self):
        self.setWindowTitle("Multimodal Voice Typer")
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
        self.format_combo.setMinimumWidth(140)
        last_category = None
        for key, data in FORMAT_PRESETS.items():
            cat = data.get("category", "")
            if cat != last_category and last_category is not None:
                self.format_combo.insertSeparator(self.format_combo.count())
            last_category = cat
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

        # Translation indicator (visible when translation is active)
        self.translation_label = QLabel("")
        self.translation_label.setStyleSheet(
            "color: #0d6efd; font-size: 11px; font-weight: bold; padding: 0 8px;"
        )
        controls.addWidget(self.translation_label)
        self._update_translation_indicator()

        # Model selector (Default / Budget / individual models)
        model_label = QLabel("Model:")
        model_label.setStyleSheet("color: #888; font-size: 12px;")
        controls.addWidget(model_label)

        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(200)
        self._populate_model_combo()
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        controls.addWidget(self.model_combo)

        layout.addLayout(controls)

        # ── Main area: text editor + history sidebar ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Text editor (left, main)
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(
            "Press the record button or your hotkey to start dictating.\n\n"
            "Your transcription will appear here."
        )
        self.text_edit.setFont(QFont("Sans Serif", 12))
        self.text_edit.setAcceptRichText(False)
        splitter.addWidget(self.text_edit)

        # History panel (right, collapsible accordion)
        self.history_widget = QWidget()
        history_layout = QVBoxLayout(self.history_widget)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(4)

        history_header = QHBoxLayout()
        self.history_toggle_btn = QPushButton("▶ Recent")
        self.history_toggle_btn.setStyleSheet(
            "font-weight: bold; font-size: 12px; color: #888; "
            "border: none; text-align: left; padding: 2px 4px;"
        )
        self.history_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_toggle_btn.clicked.connect(self._toggle_history)
        history_header.addWidget(self.history_toggle_btn)
        history_header.addStretch()
        history_clear_btn = QPushButton("Clear")
        history_clear_btn.setFixedHeight(22)
        history_clear_btn.setStyleSheet("font-size: 10px; padding: 2px 8px;")
        history_clear_btn.clicked.connect(self._clear_history)
        history_header.addWidget(history_clear_btn)
        history_layout.addLayout(history_header)

        self.history_list = QListWidget()
        self.history_list.setMaximumWidth(250)
        self.history_list.setStyleSheet(
            "QListWidget { font-size: 11px; border: 1px solid #ddd; }"
            "QListWidget::item { padding: 4px 6px; }"
            "QListWidget::item:hover { background-color: #f0f0f0; }"
        )
        self.history_list.itemClicked.connect(self._on_history_item_clicked)
        self.history_list.setVisible(False)  # Hidden by default
        history_layout.addWidget(self.history_list)

        splitter.addWidget(self.history_widget)

        # Set initial sizes: text area gets all space, history header only
        splitter.setSizes([700, 0])
        splitter.setCollapsible(0, False)  # Text area can't be collapsed
        splitter.setCollapsible(1, True)   # History can be collapsed

        layout.addWidget(splitter)

        # ── Recording controls bar (always visible) ──
        rec_bar = QHBoxLayout()
        rec_bar.setSpacing(6)

        # Record button (large, prominent)
        self.record_btn = QPushButton("\u25cf  Record")
        self.record_btn.setMinimumHeight(42)
        self.record_btn.setMinimumWidth(140)
        self.record_btn.setFont(QFont("Sans Serif", 13, QFont.Weight.Bold))
        self.record_btn.setStyleSheet(self._record_btn_style(False))
        self.record_btn.clicked.connect(self._toggle_recording)
        rec_bar.addWidget(self.record_btn)

        # Pause button (always visible, disabled when not recording)
        self.pause_btn = QPushButton("\u23f8  Pause")
        self.pause_btn.setMinimumHeight(36)
        self.pause_btn.setMinimumWidth(80)
        self.pause_btn.setStyleSheet(self._secondary_btn_style("#ffc107", "black", "#e0a800"))
        self.pause_btn.clicked.connect(self._pause_resume)
        self.pause_btn.setEnabled(False)
        rec_bar.addWidget(self.pause_btn)

        # Stop button (always visible, disabled when not recording)
        self.stop_btn = QPushButton("\u23f9  Stop")
        self.stop_btn.setMinimumHeight(36)
        self.stop_btn.setMinimumWidth(80)
        self.stop_btn.setStyleSheet(self._secondary_btn_style("#6c757d", "white", "#5a6268"))
        self.stop_btn.clicked.connect(self._stop_and_cache)
        self.stop_btn.setEnabled(False)
        rec_bar.addWidget(self.stop_btn)

        # Retake button (visible when recording — discard + restart)
        self.retake_btn = QPushButton("\u21bb  Retake")
        self.retake_btn.setMinimumHeight(36)
        self.retake_btn.setMinimumWidth(80)
        self.retake_btn.setStyleSheet(self._secondary_btn_style("#fd7e14", "white", "#e8690b"))
        self.retake_btn.clicked.connect(self._retake)
        self.retake_btn.setEnabled(False)
        rec_bar.addWidget(self.retake_btn)

        # Transcribe button (visible when cached segments exist)
        self.transcribe_btn = QPushButton("\u25b6  Transcribe")
        self.transcribe_btn.setMinimumHeight(36)
        self.transcribe_btn.setMinimumWidth(100)
        self.transcribe_btn.setStyleSheet(self._secondary_btn_style("#0d6efd", "white", "#0b5ed7"))
        self.transcribe_btn.clicked.connect(self._transcribe_cached)
        self.transcribe_btn.setVisible(False)
        rec_bar.addWidget(self.transcribe_btn)

        # Discard button (visible when cached segments exist)
        self.discard_btn = QPushButton("\U0001f5d1  Discard")
        self.discard_btn.setMinimumHeight(36)
        self.discard_btn.setMinimumWidth(80)
        self.discard_btn.setStyleSheet(self._secondary_btn_style("#dc3545", "white", "#c82333"))
        self.discard_btn.clicked.connect(self._discard_cached)
        self.discard_btn.setVisible(False)
        rec_bar.addWidget(self.discard_btn)

        # Segment indicator label
        self.segment_label = QLabel("")
        self.segment_label.setStyleSheet("color: #6c757d; font-weight: bold; font-size: 11px;")
        rec_bar.addWidget(self.segment_label)

        # Duration label
        self.duration_label = QLabel("")
        self.duration_label.setStyleSheet("color: #888; font-size: 13px; font-family: monospace;")
        self.duration_label.setMinimumWidth(50)
        rec_bar.addWidget(self.duration_label)

        rec_bar.addStretch()

        layout.addLayout(rec_bar)

        # ── Output controls bar ──
        output_bar = QHBoxLayout()
        output_bar.setSpacing(6)

        # Clipboard toggle
        self.clipboard_check = QCheckBox("\U0001f4cb  Clipboard")
        self.clipboard_check.setChecked(self.config.output_to_clipboard)
        self.clipboard_check.setToolTip("Auto-copy transcription to clipboard")
        self.clipboard_check.toggled.connect(self._on_clipboard_toggled)
        output_bar.addWidget(self.clipboard_check)

        # Text injection toggle
        self.inject_check = QCheckBox("\u2328  Type at cursor")
        self.inject_check.setChecked(self.config.output_to_inject)
        self.inject_check.setToolTip("Type transcription at cursor position (ydotool)")
        self.inject_check.toggled.connect(self._on_inject_toggled)
        output_bar.addWidget(self.inject_check)

        output_bar.addStretch()

        # Copy button
        copy_btn = QPushButton("\U0001f4cb  Copy")
        copy_btn.setMinimumHeight(32)
        copy_btn.clicked.connect(self._copy_text)
        output_bar.addWidget(copy_btn)

        # Clear text button
        clear_btn = QPushButton("\U0001f5d1  Clear")
        clear_btn.setMinimumHeight(32)
        clear_btn.clicked.connect(self._clear_text)
        output_bar.addWidget(clear_btn)

        layout.addLayout(output_bar)

        # ── Status bar ──
        status_bar = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #888; font-size: 11px;")
        status_bar.addWidget(self.status_label)
        status_bar.addStretch()

        # Beeps indicator (clickable toggle)
        self.beep_label = QLabel("")
        self.beep_label.setStyleSheet("color: #888; font-size: 11px; cursor: pointer;")
        self.beep_label.setToolTip("Click to cycle: Beeps → Voice → Silent")
        self.beep_label.mousePressEvent = lambda e: self._cycle_audio_feedback()
        status_bar.addWidget(self.beep_label)
        self._update_beep_indicator()

        layout.addLayout(status_bar)

        # ── Subtitle ──
        subtitle = QLabel("Multimodal AI transcription and reformatting with OpenRouter API")
        subtitle.setStyleSheet("color: #888; font-size: 10px; font-style: italic;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

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

        help_menu = menu.addMenu("&Help")
        models_action = QAction("&Supported Models...", self)
        models_action.triggered.connect(self._show_models_info)
        help_menu.addAction(models_action)
        help_menu.addSeparator()
        about_action = QAction("&About...", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

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

    def _secondary_btn_style(self, bg: str, fg: str, hover: str) -> str:
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:disabled {{ background-color: #ccc; color: #888; }}
        """

    def _effective_model(self) -> str:
        """Return the model ID that will actually be used for transcription."""
        if self.config.active_model:
            return self.config.active_model
        return self.config.default_model

    def _model_display_name(self, model_id: str = "") -> str:
        model_id = model_id or self._effective_model()
        m = get_model_by_id(model_id)
        return m["label"] if m else model_id

    def _populate_model_combo(self):
        """Fill the main UI model combo with Default, Budget, then all models."""
        self.model_combo.blockSignals(True)
        self.model_combo.clear()

        default_label = self._model_display_name(self.config.default_model)
        budget_label = self._model_display_name(self.config.default_budget_model)
        self.model_combo.addItem(f"Default ({default_label})", "__default__")
        self.model_combo.addItem(f"Budget ({budget_label})", "__budget__")
        self.model_combo.insertSeparator(self.model_combo.count())

        # All models grouped by category
        last_cat = None
        for model in MODELS:
            cat = model["category"]
            if cat != last_cat and last_cat is not None:
                self.model_combo.insertSeparator(self.model_combo.count())
            if cat != last_cat:
                self.model_combo.addItem(f"── {cat} ──")
                self.model_combo.model().item(self.model_combo.count() - 1).setEnabled(False)
            last_cat = cat
            self.model_combo.addItem(f"  {model['label']}", model["id"])

        # Select current
        active = self.config.active_model
        if not active or active == self.config.default_model:
            self.model_combo.setCurrentIndex(0)  # Default
        elif active == self.config.default_budget_model:
            self.model_combo.setCurrentIndex(1)  # Budget
        else:
            idx = self.model_combo.findData(active)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.setCurrentIndex(0)

        self.model_combo.blockSignals(False)

    def _on_model_changed(self):
        data = self.model_combo.currentData()
        if data == "__default__":
            self.config.active_model = ""
        elif data == "__budget__":
            self.config.active_model = self.config.default_budget_model
        elif data:
            self.config.active_model = data

    def _setup_tray(self):
        """Set up system tray icon with context menu."""
        self.tray = QSystemTrayIcon(self)
        self._tray_state = "idle"

        # Icons from theme (fallback to standard pixmaps)
        app_icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "icon.png")
        if os.path.exists(app_icon_path):
            self._tray_icon_idle = QIcon(app_icon_path)
        else:
            self._tray_icon_idle = QIcon.fromTheme("audio-input-microphone")
        self._tray_icon_recording = QIcon.fromTheme(
            "media-record", self.style().standardIcon(self.style().StandardPixmap.SP_DialogNoButton))
        self._tray_icon_transcribing = QIcon.fromTheme(
            "emblem-synchronizing", self.style().standardIcon(self.style().StandardPixmap.SP_BrowserReload))
        self._tray_icon_complete = QIcon.fromTheme(
            "emblem-ok", self.style().standardIcon(self.style().StandardPixmap.SP_DialogApplyButton))

        self.tray.setIcon(self._tray_icon_idle)
        self.setWindowIcon(self._tray_icon_idle)

        # Context menu
        tray_menu = QMenu()
        tray_menu.addAction("Show/Hide", self._tray_toggle_window)
        tray_menu.addSeparator()
        self._tray_record_action = tray_menu.addAction("Record", self._toggle_recording)
        self._tray_transcribe_action = tray_menu.addAction("Transcribe Cached", self._transcribe_cached)
        self._tray_transcribe_action.setEnabled(False)
        tray_menu.addSeparator()
        tray_menu.addAction("Settings...", self._open_settings)
        tray_menu.addAction("Quit", self.close)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.setToolTip("Multimodal Voice Typer — Ready")
        self.tray.show()

    def _update_tray_state(self, state: str):
        """Update tray icon and tooltip based on app state."""
        self._tray_state = state
        if state == "idle":
            self.tray.setIcon(self._tray_icon_idle)
            self.tray.setToolTip("Multimodal Voice Typer — Ready")
            self._tray_record_action.setText("Record")
        elif state == "recording":
            self.tray.setIcon(self._tray_icon_recording)
            self.tray.setToolTip("Multimodal Voice Typer — Recording...")
            self._tray_record_action.setText("Stop + Transcribe")
        elif state == "transcribing":
            self.tray.setIcon(self._tray_icon_transcribing)
            self.tray.setToolTip("Multimodal Voice Typer — Transcribing...")
        elif state == "complete":
            self.tray.setIcon(self._tray_icon_complete)
            self.tray.setToolTip("Multimodal Voice Typer — Done")
            # Revert to idle after 3 seconds
            QTimer.singleShot(3000, lambda: self._update_tray_state("idle")
                              if self._tray_state == "complete" else None)
        elif state == "cached":
            self.tray.setIcon(self._tray_icon_idle)
            n = len(self._cached_segments)
            self.tray.setToolTip(f"Multimodal Voice Typer — {n} segment{'s' if n != 1 else ''} cached")
            self._tray_record_action.setText("Record")
        self._tray_transcribe_action.setEnabled(bool(self._cached_segments))

    def _tray_toggle_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._tray_toggle_window()

    def _update_translation_indicator(self):
        """Update the translation indicator label."""
        if self.config.translation_target:
            name = get_language_display_name(self.config.translation_target)
            self.translation_label.setText(f"\u2192 {name}")
            self.translation_label.setToolTip(f"Translation mode: output will be in {name}")
            self.translation_label.show()
        else:
            self.translation_label.setText("")
            self.translation_label.hide()

    def _update_segment_indicator(self):
        """Update segment count and transcribe/discard button visibility."""
        n = len(self._cached_segments)
        has_cached = n > 0
        if has_cached:
            self.segment_label.setText(f"{n} seg{'s' if n > 1 else ''}")
        else:
            self.segment_label.setText("")
        self.transcribe_btn.setVisible(has_cached)
        self.discard_btn.setVisible(has_cached)

    def _discard_cached(self):
        """Discard all cached audio segments."""
        self._cached_segments = []
        self._update_segment_indicator()
        self._audio_feedback("play_clear", "announce_discarded")
        self.duration_label.setText("")
        self.status_label.setText("Discarded")
        self._update_tray_state("idle")

    def _connect_signals(self):
        self._toggle_signal.connect(self._toggle_recording)
        self._clear_signal.connect(self._clear_recording)
        self._tap_toggle_signal.connect(self._tap_toggle)
        self._transcribe_signal.connect(self._transcribe_cached)
        self._append_signal.connect(self._start_append)
        self._pause_signal.connect(self._pause_resume)
        self._retake_signal.connect(self._retake)

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
        if hk.hotkey_retake:
            self.hotkey_listener.register("retake", hk.hotkey_retake,
                                          lambda: self._retake_signal.emit())

        self.hotkey_listener.start()

    # ── Audio feedback ──

    def _play_beep(self, beep_method: str):
        """Play a beep sound if in beeps mode."""
        if self.config.audio_feedback_mode == "beeps":
            getattr(get_feedback(), beep_method)()

    def _play_tts(self, announce_method: str):
        """Play a TTS announcement if in tts mode."""
        if self.config.audio_feedback_mode == "tts":
            getattr(get_announcer(), announce_method)()

    def _audio_feedback(self, beep_method: str, tts_method: str):
        """Play audio feedback based on current mode."""
        mode = self.config.audio_feedback_mode
        if mode == "beeps":
            getattr(get_feedback(), beep_method)()
        elif mode == "tts":
            getattr(get_announcer(), tts_method)()

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
        # Play feedback BEFORE starting recording (so mic doesn't capture it)
        self._audio_feedback("play_start", "announce_recording")
        QTimer.singleShot(200, self._begin_recording)

    def _begin_recording(self):
        if self.recorder.is_recording:
            return
        if self.recorder.start_recording():
            self.text_edit.clear()
            self._raw_text = ""
            self.record_btn.setText("\u23f9  Transcribe")
            self.record_btn.setStyleSheet(self._record_btn_style(True))
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText("\u23f8  Pause")
            self.stop_btn.setEnabled(True)
            self.retake_btn.setEnabled(True)
            self.transcribe_btn.setVisible(False)
            self.status_label.setText("Recording...")
            self.duration_label.setText("0:00")
            self._duration_timer.start(500)
            self._update_tray_state("recording")

    def _stop_and_transcribe(self):
        if not self.recorder.is_recording:
            return
        self._duration_timer.stop()
        audio_data = self.recorder.stop_recording()
        self._audio_feedback("play_stop", "announce_stopped")
        self._reset_record_buttons()

        # If we have cached segments, combine them with this recording
        if self._cached_segments:
            self._cached_segments.append(audio_data)
            audio_data = combine_wav_segments(self._cached_segments)
            self._cached_segments = []
            self._update_segment_indicator()

        self._transcribe(audio_data)

    def _stop_and_cache(self):
        """Stop recording and cache audio without transcribing."""
        if not self.recorder.is_recording:
            return
        self._duration_timer.stop()
        audio_data = self.recorder.stop_recording()
        self._cached_segments.append(audio_data)
        self._audio_feedback("play_cached", "announce_cached")
        self._reset_record_buttons()
        self._update_segment_indicator()
        n = len(self._cached_segments)
        self.status_label.setText(f"Stopped — {n} segment{'s' if n > 1 else ''} cached")
        self._update_tray_state("cached")

    def _reset_record_buttons(self):
        """Reset recording buttons to idle state."""
        self.record_btn.setText("\u25cf  Record")
        self.record_btn.setStyleSheet(self._record_btn_style(False))
        self.pause_btn.setText("\u23f8  Pause")
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.retake_btn.setEnabled(False)

    def _tap_toggle(self):
        """Tap toggle: start recording, or stop and cache (for append workflow)."""
        if self.recorder.is_recording:
            self._stop_and_cache()
        else:
            self._start_recording()

    def _transcribe_cached(self):
        """Transcribe all cached audio segments."""
        if not self._cached_segments:
            self.status_label.setText("No cached audio to transcribe")
            return
        self._audio_feedback("play_transcribe", "announce_transcribing")
        audio_data = combine_wav_segments(self._cached_segments)
        self._cached_segments = []
        self._update_segment_indicator()
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
            self._audio_feedback("play_resume", "announce_resumed")
            self.pause_btn.setText("\u23f8  Pause")
            self.status_label.setText("Recording...")
        else:
            self.recorder.pause_recording()
            self._audio_feedback("play_pause", "announce_paused")
            self.pause_btn.setText("\u25b6  Resume")
            self.status_label.setText("Paused")

    def _retake(self):
        """Discard current recording and immediately start a new one."""
        if self.recorder.is_recording:
            self._duration_timer.stop()
            self.recorder.stop_recording()  # Discard the audio
        self._reset_record_buttons()
        self._audio_feedback("play_clear", "announce_cleared")
        self.status_label.setText("Retake...")
        self._start_recording()

    def _clear_recording(self):
        """Clear current recording and cache."""
        if self.recorder.is_recording:
            self._duration_timer.stop()
            self.recorder.stop_recording()
        self._reset_record_buttons()
        self._cached_segments = []
        self._update_segment_indicator()
        self._audio_feedback("play_clear", "announce_cleared")
        self.duration_label.setText("")
        self.status_label.setText("Cleared")
        self._update_tray_state("idle")

    def _update_duration(self):
        secs = self.recorder.get_duration()
        mins = int(secs) // 60
        sec = int(secs) % 60
        self.duration_label.setText(f"{mins}:{sec:02d}")

    # ── Transcription ──

    def _transcribe(self, audio_data: bytes):
        if not self.config.openrouter_api_key:
            self.status_label.setText("No OpenRouter API key — open Settings")
            return

        self.status_label.setText("Processing audio...")
        self.record_btn.setEnabled(False)
        self._update_tray_state("transcribing")

        # Build prompt with current UI settings (estimate duration from raw WAV)
        from .audio_processor import get_audio_duration
        prompt = build_cleanup_prompt(self.config,
                                      audio_duration_seconds=get_audio_duration(audio_data))

        # Audio processing + transcription both run in background thread
        self.worker = TranscriptionWorker(
            api_key=self.config.openrouter_api_key,
            model=self._effective_model(),
            raw_audio_data=audio_data,
            prompt=prompt,
            review_enabled=self.config.review_enabled,
            vad_enabled=self.config.vad_enabled,
        )
        self.worker.status.connect(self.status_label.setText)
        self.worker.finished.connect(self._on_transcription_done)
        self.worker.error.connect(self._on_transcription_error)
        self.worker.start()

    def _on_transcription_done(self, text: str, elapsed: float):
        self.record_btn.setEnabled(True)
        self._audio_feedback("play_complete", "announce_complete")
        self._update_tray_state("complete")

        # Add to session history
        self._history.add(text, elapsed_seconds=elapsed,
                          format_preset=self.config.format_preset)
        self._refresh_history_list()

        if self.config.output_to_app:
            # Replace previous transcript — each transcription is a fresh job
            self._raw_text = text
            self.text_edit.setMarkdown(self._raw_text)
            # Scroll to bottom
            cursor = self.text_edit.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.text_edit.setTextCursor(cursor)

        if self.config.output_to_clipboard:
            copy_to_clipboard(text)
            # Play clipboard sound after the completion ding
            self._play_beep("play_clipboard")

        if self.config.output_to_inject:
            self._inject_text(text)

        # Status
        parts = [f"Done in {elapsed:.1f}s"]
        if self.config.output_to_clipboard:
            parts.append("On clipboard")
        if self.config.output_to_inject:
            parts.append("injected")
        self.status_label.setText(" | ".join(parts))

    def _on_transcription_error(self, error: str):
        self.record_btn.setEnabled(True)
        self.status_label.setText(f"Error: {error}")
        self._update_tray_state("idle")

    def _on_recording_error(self, error: str):
        self._duration_timer.stop()
        self.record_btn.setText("\u25cf  Record")
        self.record_btn.setStyleSheet(self._record_btn_style(False))
        self.status_label.setText(f"Mic error: {error}")

    def _inject_text(self, text: str):
        """Paste text at cursor position via clipboard + Ctrl+V."""
        try:
            # Save current clipboard
            old_clip = None
            try:
                result = subprocess.run(
                    ["wl-paste", "--no-newline"],
                    capture_output=True, timeout=2,
                )
                if result.returncode == 0:
                    old_clip = result.stdout
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

            # Set clipboard to transcribed text and paste
            copy_to_clipboard(text)
            subprocess.run(
                ["ydotool", "key", "ctrl+v"],
                timeout=5, capture_output=True,
            )

            # Restore previous clipboard after paste completes
            if old_clip is not None:
                def _restore():
                    time.sleep(0.3)
                    try:
                        proc = subprocess.Popen(
                            ["wl-copy"], stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                        )
                        proc.communicate(input=old_clip, timeout=5)
                    except Exception:
                        pass
                threading.Thread(target=_restore, daemon=True).start()

        except FileNotFoundError:
            self.status_label.setText("ydotool not installed — can't inject text")
        except Exception as e:
            self.status_label.setText(f"Inject error: {e}")

    # ── UI Actions ──

    def _copy_text(self):
        text = self._raw_text if self._raw_text.strip() else self.text_edit.toPlainText()
        if text.strip():
            copy_to_clipboard(text)
            self.status_label.setText("Copied to clipboard")
        else:
            self.status_label.setText("Nothing to copy")

    def _clear_text(self):
        self._raw_text = ""
        self.text_edit.clear()
        self.status_label.setText("Cleared")

    def _on_format_changed(self):
        self.config.format_preset = self.format_combo.currentData()
        save_config(self.config)

    def _on_tone_changed(self):
        self.config.tone = self.tone_combo.currentData()
        save_config(self.config)

    def _on_clipboard_toggled(self, checked: bool):
        self.config.output_to_clipboard = checked
        save_config(self.config)

    def _on_inject_toggled(self, checked: bool):
        self.config.output_to_inject = checked
        save_config(self.config)

    def _cycle_audio_feedback(self):
        """Cycle through audio feedback modes: beeps -> tts -> silent -> beeps."""
        modes = ["beeps", "tts", "silent"]
        idx = modes.index(self.config.audio_feedback_mode) if self.config.audio_feedback_mode in modes else 0
        self.config.audio_feedback_mode = modes[(idx + 1) % len(modes)]
        save_config(self.config)
        self._update_beep_indicator()

    def _update_beep_indicator(self):
        """Update the audio feedback indicator in status bar."""
        mode = self.config.audio_feedback_mode
        if mode == "beeps":
            self.beep_label.setText("\U0001f514 Beeps")
        elif mode == "tts":
            self.beep_label.setText("\U0001f50a Voice")
        else:
            self.beep_label.setText("\U0001f507 Silent")

    # ── History ──

    def _toggle_history(self):
        """Toggle history list visibility (accordion)."""
        visible = not self.history_list.isVisible()
        self.history_list.setVisible(visible)
        self.history_toggle_btn.setText("▼ Recent" if visible else "▶ Recent")

    def _refresh_history_list(self):
        """Update the history list widget."""
        self.history_list.clear()
        for entry in self._history.get_all():
            item = QListWidgetItem(f"{entry.time_str}  {entry.preview}")
            item.setToolTip(entry.text[:500])
            item.setData(Qt.ItemDataRole.UserRole, entry.text)
            self.history_list.addItem(item)

    def _on_history_item_clicked(self, item: QListWidgetItem):
        """Load a history entry into the text editor."""
        text = item.data(Qt.ItemDataRole.UserRole)
        if text:
            self._raw_text = text
            self.text_edit.setMarkdown(text)
            self.status_label.setText("Loaded from history")

    def _clear_history(self):
        """Clear session history."""
        self._history.clear()
        self.history_list.clear()
        self.status_label.setText("History cleared")

    def _show_models_info(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Supported Models")
        dialog.setMinimumSize(750, 450)
        layout = QVBoxLayout(dialog)

        intro = QLabel(
            "<p>All models are accessed via the <a href='https://openrouter.ai'>OpenRouter API</a>. "
            "Pricing is approximate and may change — check OpenRouter for current rates.</p>"
        )
        intro.setOpenExternalLinks(True)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        approx_costs = {
            "google/gemini-3.1-flash-lite-preview": "~$0.02/M",
            "openai/gpt-audio-mini": "~$0.40/M",
            "google/gemini-3-flash-preview": "~$0.10/M",
            "openai/gpt-audio": "~$2.50/M",
            "openai/gpt-4o-audio-preview": "~$2.50/M",
            "xiaomi/mimo-v2-omni": "~$0.27/M",
            "mistralai/voxtral-small-24b-2507": "~$0.40/M",
            "openrouter/healer-alpha": "~$0.10/M",
        }

        for category in ["Budget", "Standard"]:
            cat_label = QLabel(f"<h3>{category} Tier</h3>")
            layout.addWidget(cat_label)

            models_in_cat = [m for m in MODELS if m["category"] == category]
            table = QTableWidget(len(models_in_cat), 4)
            table.setHorizontalHeaderLabels(["Model", "Provider", "Description", "Cost (input)"])
            table.horizontalHeader().setStretchLastSection(False)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.setAlternatingRowColors(True)

            for row, m in enumerate(models_in_cat):
                table.setItem(row, 0, QTableWidgetItem(m["label"].split(" (")[0]))
                table.setItem(row, 1, QTableWidgetItem(m["manufacturer"]))
                table.setItem(row, 2, QTableWidgetItem(m["description"]))
                table.setItem(row, 3, QTableWidgetItem(approx_costs.get(m["id"], "—")))

            table.setMaximumHeight(36 + len(models_in_cat) * 30)
            layout.addWidget(table)

        layout.addStretch()

        note = QLabel("<i>Costs shown are approximate input token prices. Audio tokens vary by model and encoding.</i>")
        note.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(note)

        dialog.exec()

    def _show_about(self):
        QMessageBox.about(
            self,
            "About Multimodal Voice Typer",
            f"<h3>Multimodal Voice Typer</h3>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p><i>Multimodal AI transcription and reformatting with OpenRouter API</i></p>"
            f"<p>Voice dictation powered by multimodal AI models. "
            f"Audio is sent directly to audio-capable models which handle "
            f"both transcription and text cleanup in a single pass.</p>"
            f"<p><a href='https://openrouter.ai'>openrouter.ai</a></p>",
        )

    def _open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.config = dialog.get_config()
            save_config(self.config)
            self._populate_model_combo()
            self._update_translation_indicator()
            self._setup_hotkeys()

    def _prompt_api_key(self):
        """Prompt for API key if not configured."""
        msg = QMessageBox(self)
        msg.setWindowTitle("API Key Required")
        msg.setText(
            "No OpenRouter API key found.\n\n"
            "You need an API key from openrouter.ai to use Multimodal Voice Typer.\n"
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
    app.setApplicationName("Multimodal Voice Typer")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
