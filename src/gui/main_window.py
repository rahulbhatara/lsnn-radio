import sys
import os
import time
import asyncio
import subprocess
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QTableWidget, QTableWidgetItem,
    QLineEdit, QTextEdit, QFrame, QHeaderView, QMessageBox, QComboBox,
    QMenu, QFileDialog
)

from ..yt_downloader import download_youtube_opus
from ..convert_playlist import scan_non_opus_files, batch_convert_files
from ..service_manager import get_tunnel_status, start_cloudflared_tunnel, stop_all_services
from ..config import AppConfig
from .settings_dialog import SettingsDialog
from .theme import MINIMAL_QSS
from .utils import format_duration, format_bytes


class MainWindow(QMainWindow):
    log_signal = Signal(str)
    closed_signal = Signal()

    def closeEvent(self, event):
        try:
            self.timer.stop()
        except Exception:
            pass
        self.closed_signal.emit()
        event.accept()

    def __init__(self, track, whip_client, hls_streamer, config: AppConfig = None, music_dir: str = None, icecast=None):
        super().__init__()
        self.track = track
        self.whip_client = whip_client
        self.hls_streamer = hls_streamer
        self.icecast = icecast
        self.config = config or AppConfig.load()
        self.music_dir = music_dir or self.config.music_dir

        self.setWindowTitle("MeshCast")
        self.resize(980, 720)
        self.setStyleSheet(MINIMAL_QSS)

        self.download_in_progress = False
        self.conversion_in_progress = False
        self._log_visible = False

        self.log_signal.connect(self._append_log)
        self._init_ui()

        # UI stats refresh timer (5 Hz for responsive VU meter & telemetry)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._update_gui_stats)
        self.timer.start()

        self.log_event("[System] Ready")

    def log_event(self, text: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_signal.emit(f"[{timestamp}] {text}")

    @Slot(str)
    def _append_log(self, msg: str):
        if hasattr(self, 'logTextEdit') and self.logTextEdit is not None:
            self.logTextEdit.append(msg)

    # ── Build UI ────────────────────────────────────────────────────
    def _init_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 10)

        layout.addWidget(self._build_source_selector())
        layout.addWidget(self._build_now_playing())
        layout.addWidget(self._build_split_playlist_and_queue(), stretch=1)
        layout.addWidget(self._build_youtube_row())
        layout.addWidget(self._build_log_section())
        layout.addLayout(self._build_status_bar())
        self._update_mode_button_styles()

    # ── 1. Audio Source Switcher ────────────────────────────────────
    def _build_source_selector(self):
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(8)

        # Mode switcher buttons (clean text labels)
        row_mode = QHBoxLayout()
        row_mode.setSpacing(10)

        self.btnModeMusic = QPushButton("Library")
        self.btnModeMusic.setObjectName("btnModeMusic")
        self.btnModeMusic.setCursor(Qt.PointingHandCursor)
        self.btnModeMusic.clicked.connect(lambda: self._set_source_mode("playlist"))
        row_mode.addWidget(self.btnModeMusic)

        self.btnModeMic = QPushButton("Live Input")
        self.btnModeMic.setObjectName("btnModeMic")
        self.btnModeMic.setCursor(Qt.PointingHandCursor)
        self.btnModeMic.clicked.connect(lambda: self._set_source_mode("mic"))
        row_mode.addWidget(self.btnModeMic)

        row_mode.addStretch()
        vbox.addLayout(row_mode)

        # Audio device selector & VU meter (visible only in mic mode)
        self.micControlWidget = QWidget()
        row_device = QHBoxLayout(self.micControlWidget)
        row_device.setContentsMargins(0, 2, 0, 0)
        row_device.setSpacing(8)

        lbl_dev = QLabel("Device")
        lbl_dev.setStyleSheet("color: #6b7280; font-size: 12px; font-weight: 600;")
        row_device.addWidget(lbl_dev)

        self.comboAudioDevices = QComboBox()
        self.comboAudioDevices.setMinimumWidth(280)
        self.comboAudioDevices.currentIndexChanged.connect(self._on_audio_device_changed)
        row_device.addWidget(self.comboAudioDevices, stretch=1)

        self.btnRefreshDevices = QPushButton("Rescan")
        self.btnRefreshDevices.setToolTip("Rescan audio input devices")
        self.btnRefreshDevices.clicked.connect(self._populate_audio_devices)
        row_device.addWidget(self.btnRefreshDevices)

        # VU Meter
        self.vuMeter = QProgressBar()
        self.vuMeter.setObjectName("vuMeter")
        self.vuMeter.setRange(0, 100)
        self.vuMeter.setValue(0)
        self.vuMeter.setFixedWidth(110)
        self.vuMeter.setTextVisible(False)
        row_device.addWidget(self.vuMeter)

        self.lblVuDb = QLabel("-60 dB")
        self.lblVuDb.setStyleSheet("color: #6b7280; font-size: 11px; min-width: 44px;")
        row_device.addWidget(self.lblVuDb)

        vbox.addWidget(self.micControlWidget)

        # Populate audio device list
        self._populate_audio_devices()

        return container

    def _populate_audio_devices(self):
        self.comboAudioDevices.blockSignals(True)
        self.comboAudioDevices.clear()

        devices = self.track.get_available_audio_devices()
        if not devices:
            self.comboAudioDevices.addItem("No audio input device detected", None)
            self.btnModeMic.setEnabled(False)
            self.btnModeMic.setToolTip("No microphone or audio input device detected")
        else:
            self.btnModeMic.setEnabled(True)
            self.btnModeMic.setToolTip("Switch to live microphone input")
            for d in devices:
                self.comboAudioDevices.addItem(d["display_name"], d["id"])

        current_dev = self.track.audio_capture.device_id
        if current_dev is not None:
            found = False
            for idx in range(self.comboAudioDevices.count()):
                if self.comboAudioDevices.itemData(idx) == current_dev:
                    self.comboAudioDevices.setCurrentIndex(idx)
                    found = True
                    break
            if not found and self.comboAudioDevices.count() > 0:
                self.comboAudioDevices.setCurrentIndex(0)
                self.track.audio_capture.device_id = self.comboAudioDevices.itemData(0)
        elif self.comboAudioDevices.count() > 0 and self.comboAudioDevices.itemData(0) is not None:
            self.comboAudioDevices.setCurrentIndex(0)
            self.track.audio_capture.device_id = self.comboAudioDevices.itemData(0)

        self.comboAudioDevices.blockSignals(False)
        self.log_event(f"Found {len(devices)} audio input devices")

    def _on_audio_device_changed(self, idx: int):
        if idx < 0:
            return
        device_id = self.comboAudioDevices.itemData(idx)
        if device_id is None:
            return
        if device_id == self.track.audio_capture.device_id and self.track.audio_capture.is_running:
            return

        dev_name = self.comboAudioDevices.currentText()
        success = self.track.set_audio_device(device_id)
        if success:
            self.log_event(f"Device: {dev_name}")
        else:
            self.log_event(f"Failed to open: {dev_name}")

    def _set_source_mode(self, mode: str):
        if self.track.source_mode == mode:
            return

        if mode == "mic" and self.comboAudioDevices.count() > 0:
            cur_idx = self.comboAudioDevices.currentIndex()
            if cur_idx >= 0:
                dev_id = self.comboAudioDevices.itemData(cur_idx)
                if dev_id is not None:
                    self.track.audio_capture.device_id = dev_id

        self.track.set_source_mode(mode)
        self._update_mode_button_styles()
        self.log_event(f"Source: {mode.upper()}")

    def _update_mode_button_styles(self):
        is_music = (self.track.source_mode == "playlist")
        if is_music:
            self.btnModeMusic.setProperty("class", "active")
            self.btnModeMusic.setStyleSheet("background-color: #4f46e5; color: #ffffff; border-color: #6366f1;")
            self.btnModeMic.setProperty("class", "inactive")
            self.btnModeMic.setStyleSheet("background-color: #14161e; color: #6b7280; border-color: #262a35;")
            self.micControlWidget.setVisible(False)
            if hasattr(self, 'btnPrev'):
                self.btnPrev.setEnabled(True)
                self.btnNext.setEnabled(True)
                self.btnShuffle.setEnabled(True)
                self.btnRescan.setEnabled(True)
        else:
            self.btnModeMusic.setProperty("class", "inactive")
            self.btnModeMusic.setStyleSheet("background-color: #14161e; color: #6b7280; border-color: #262a35;")
            self.btnModeMic.setProperty("class", "active")
            self.btnModeMic.setStyleSheet("background-color: #059669; color: #ffffff; border-color: #10b981;")
            self.micControlWidget.setVisible(True)
            if hasattr(self, 'btnPrev'):
                self.btnPrev.setEnabled(False)
                self.btnNext.setEnabled(False)
                self.btnShuffle.setEnabled(False)
                self.btnRescan.setEnabled(False)

    # ── 2. Now Playing ──────────────────────────────────────────────
    def _build_now_playing(self):
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(10)

        # Track name
        self.lblTrack = QLabel("Loading...")
        self.lblTrack.setStyleSheet("font-size: 15px; font-weight: 700; color: #f3f4f6;")
        vbox.addWidget(self.lblTrack)

        # Progress bar
        self.trackProgress = QProgressBar()
        self.trackProgress.setRange(0, 1000)
        self.trackProgress.setValue(0)
        self.trackProgress.setTextVisible(False)
        vbox.addWidget(self.trackProgress)

        # Time + Controls row
        row = QHBoxLayout()
        row.setSpacing(8)

        self.lblTime = QLabel("00:00 / 00:00")
        self.lblTime.setStyleSheet("color: #6b7280; font-size: 12px; font-weight: 600;")
        row.addWidget(self.lblTime)

        row.addStretch()

        # Transport controls (pure text labels, no icons)
        self.btnPrev = QPushButton("Prev")
        self.btnPrev.setToolTip("Previous track")
        self.btnPrev.clicked.connect(self._on_prev_track)
        row.addWidget(self.btnPrev)

        self.btnPlay = QPushButton("Play")
        self.btnPlay.setObjectName("btnPlay")
        self.btnPlay.setToolTip("Play / Pause broadcast")
        self.btnPlay.clicked.connect(self._on_toggle_play)
        row.addWidget(self.btnPlay)

        self.btnNext = QPushButton("Next")
        self.btnNext.setToolTip("Next track")
        self.btnNext.clicked.connect(self._on_next_track)
        row.addWidget(self.btnNext)

        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: #262a35;")
        sep.setFixedHeight(26)
        row.addWidget(sep)

        self.btnMute = QPushButton("Mute")
        self.btnMute.setToolTip("Mute / Unmute stream")
        self.btnMute.clicked.connect(self._on_toggle_mute)
        row.addWidget(self.btnMute)

        self.btnShuffle = QPushButton("Shuffle")
        self.btnShuffle.setToolTip("Reshuffle playlist")
        self.btnShuffle.clicked.connect(self._on_reshuffle)
        row.addWidget(self.btnShuffle)

        self.btnRescan = QPushButton("Rescan")
        self.btnRescan.setToolTip("Rescan music directory")
        self.btnRescan.clicked.connect(self._on_rescan_folder)
        row.addWidget(self.btnRescan)

        vbox.addLayout(row)
        return container

    # ── 3. Split View: Music Library + Priority Play Queue ──────────
    def _build_split_playlist_and_queue(self):
        container = QWidget()
        hbox = QHBoxLayout(container)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(10)

        # ── LEFT: Music Library ────────────────────────────────────────
        panel_library = QWidget()
        vbox_lib = QVBoxLayout(panel_library)
        vbox_lib.setContentsMargins(0, 0, 0, 0)
        vbox_lib.setSpacing(6)

        # Header
        row_lib_header = QHBoxLayout()
        row_lib_header.setSpacing(6)

        self.lblLibHeader = QLabel("LIBRARY · 0")
        self.lblLibHeader.setStyleSheet("font-weight: 700; font-size: 11px; color: #6b7280; letter-spacing: 0.3px;")
        row_lib_header.addWidget(self.lblLibHeader)

        row_lib_header.addStretch()

        # Batch convert button (visible if non-opus audio found)
        self.btnConvertNonOpus = QPushButton("Convert")
        self.btnConvertNonOpus.setToolTip("Convert non-Opus audio files to standard Opus")
        self.btnConvertNonOpus.setStyleSheet("background-color: #059669; color: #ffffff; border-color: #10b981; font-size: 11px; padding: 3px 8px; font-weight: 700;")
        self.btnConvertNonOpus.setVisible(False)
        self.btnConvertNonOpus.clicked.connect(self._start_batch_conversion)
        row_lib_header.addWidget(self.btnConvertNonOpus)

        # Browse Directory Button
        btnBrowseLib = QPushButton("Browse")
        btnBrowseLib.setToolTip("Change music directory")
        btnBrowseLib.setStyleSheet("font-size: 11px; padding: 3px 8px;")
        btnBrowseLib.clicked.connect(self._browse_and_set_music_dir)
        row_lib_header.addWidget(btnBrowseLib)

        vbox_lib.addLayout(row_lib_header)

        # Search + Actions row
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        self.txtSearch = QLineEdit()
        self.txtSearch.setPlaceholderText("Search tracks...")
        self.txtSearch.setClearButtonEnabled(True)
        self.txtSearch.textChanged.connect(self._filter_library)
        search_row.addWidget(self.txtSearch, stretch=1)

        btnPlaySel = QPushButton("Play")
        btnPlaySel.setToolTip("Play selected track now")
        btnPlaySel.clicked.connect(self._play_selected_library_track)
        search_row.addWidget(btnPlaySel)

        btnAddQueue = QPushButton("Queue")
        btnAddQueue.setToolTip("Add selected track to queue")
        btnAddQueue.clicked.connect(self._add_selected_to_queue)
        search_row.addWidget(btnAddQueue)

        vbox_lib.addLayout(search_row)

        # Library Table
        self.tableLibrary = QTableWidget()
        self.tableLibrary.setColumnCount(3)
        self.tableLibrary.setHorizontalHeaderLabels(["#", "Track Name", "Status"])
        self.tableLibrary.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tableLibrary.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tableLibrary.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tableLibrary.verticalHeader().setVisible(False)
        self.tableLibrary.setSelectionBehavior(QTableWidget.SelectRows)
        self.tableLibrary.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tableLibrary.setShowGrid(False)
        self.tableLibrary.setAlternatingRowColors(False)
        self.tableLibrary.itemDoubleClicked.connect(self._on_library_double_clicked)
        self.tableLibrary.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableLibrary.customContextMenuRequested.connect(self._show_library_context_menu)
        vbox_lib.addWidget(self.tableLibrary, stretch=1)

        hbox.addWidget(panel_library, stretch=6)

        # ── RIGHT: Play Queue ──────────────────────────────────────────
        panel_queue = QWidget()
        vbox_q = QVBoxLayout(panel_queue)
        vbox_q.setContentsMargins(0, 0, 0, 0)
        vbox_q.setSpacing(6)

        # Queue Header & Toolbar
        row_q_header = QHBoxLayout()
        row_q_header.setSpacing(6)

        self.lblQueueHeader = QLabel("QUEUE · 0")
        self.lblQueueHeader.setStyleSheet("font-weight: 700; font-size: 11px; color: #6b7280; letter-spacing: 0.3px;")
        row_q_header.addWidget(self.lblQueueHeader)
        row_q_header.addStretch()

        self.btnAutoDj = QPushButton("Auto-DJ")
        self.btnAutoDj.setObjectName("btnAutoDj")
        self.btnAutoDj.setToolTip("Toggle Auto-DJ fallback when queue is empty")
        self.btnAutoDj.setStyleSheet("background-color: #059669; color: #ffffff; border-color: #10b981; font-size: 11px; padding: 4px 8px; font-weight: 700;")
        self.btnAutoDj.clicked.connect(self._on_toggle_autodj)
        row_q_header.addWidget(self.btnAutoDj)

        self.btnShuffleQ = QPushButton("Shuffle")
        self.btnShuffleQ.setToolTip("Shuffle queue")
        self.btnShuffleQ.setStyleSheet("font-size: 11px; padding: 4px 8px;")
        self.btnShuffleQ.clicked.connect(self._on_shuffle_queue)
        row_q_header.addWidget(self.btnShuffleQ)

        self.btnClearQ = QPushButton("Clear")
        self.btnClearQ.setToolTip("Clear all queued tracks")
        self.btnClearQ.setStyleSheet("font-size: 11px; padding: 4px 8px;")
        self.btnClearQ.clicked.connect(self._on_clear_queue)
        row_q_header.addWidget(self.btnClearQ)

        vbox_q.addLayout(row_q_header)

        # Queue Table
        self.tableQueue = QTableWidget()
        self.tableQueue.setColumnCount(2)
        self.tableQueue.setHorizontalHeaderLabels(["#", "Queued Track"])
        self.tableQueue.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tableQueue.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tableQueue.verticalHeader().setVisible(False)
        self.tableQueue.setSelectionBehavior(QTableWidget.SelectRows)
        self.tableQueue.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tableQueue.setShowGrid(False)
        self.tableQueue.setAlternatingRowColors(False)
        self.tableQueue.itemDoubleClicked.connect(self._on_queue_double_clicked)
        self.tableQueue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableQueue.customContextMenuRequested.connect(self._show_queue_context_menu)
        vbox_q.addWidget(self.tableQueue, stretch=1)

        hbox.addWidget(panel_queue, stretch=4)

        self._populate_all_tables()
        self._check_non_opus_files()
        return container

    # ── 4. YouTube Download Row ─────────────────────────────────────
    def _build_youtube_row(self):
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        lbl = QLabel("YouTube")
        lbl.setStyleSheet("color: #6b7280; font-weight: 600; font-size: 12px;")
        row.addWidget(lbl)

        self.txtYtUrl = QLineEdit()
        self.txtYtUrl.setPlaceholderText("Paste URL to download...")
        row.addWidget(self.txtYtUrl, stretch=1)

        self.btnYtDownload = QPushButton("Download")
        self.btnYtDownload.setToolTip("Download audio and queue as next track")
        self.btnYtDownload.clicked.connect(self._start_youtube_download)
        row.addWidget(self.btnYtDownload)

        self.lblYtStatus = QLabel("")
        self.lblYtStatus.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.lblYtStatus.setFixedWidth(180)
        row.addWidget(self.lblYtStatus)

        return row_widget

    # ── 5. Collapsible Log Panel ────────────────────────────────────
    def _build_log_section(self):
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)

        self.btnToggleLog = QPushButton("Log")
        self.btnToggleLog.setStyleSheet(
            "border: none; color: #4b5563; font-size: 11px; font-weight: 600; "
            "padding: 2px 4px; text-align: left;"
        )
        self.btnToggleLog.setCursor(Qt.PointingHandCursor)
        self.btnToggleLog.clicked.connect(self._toggle_log)
        vbox.addWidget(self.btnToggleLog)

        self.logTextEdit = QTextEdit()
        self.logTextEdit.setObjectName("logPanel")
        self.logTextEdit.setReadOnly(True)
        self.logTextEdit.setFixedHeight(0)
        self.logTextEdit.setVisible(False)
        vbox.addWidget(self.logTextEdit)

        return container

    def _toggle_log(self):
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.logTextEdit.setVisible(True)
            self.logTextEdit.setFixedHeight(120)
            self.btnToggleLog.setText("Hide Log")
        else:
            self.logTextEdit.setFixedHeight(0)
            self.logTextEdit.setVisible(False)
            self.btnToggleLog.setText("Log")

    # ── 6. Status Bar ──────────────────────────────────────────────
    def _build_status_bar(self):
        row = QHBoxLayout()
        row.setSpacing(14)
        row.setContentsMargins(4, 2, 4, 0)

        self.lblWhipStatus = QLabel("WebRTC connecting")
        self.lblWhipStatus.setObjectName("statusItem")
        self.lblWhipStatus.setStyleSheet("color: #ef4444; font-size: 11px;")
        row.addWidget(self.lblWhipStatus)

        self.lblHlsStatus = QLabel("HLS starting")
        self.lblHlsStatus.setObjectName("statusItem")
        self.lblHlsStatus.setStyleSheet("color: #f59e0b; font-size: 11px;")
        row.addWidget(self.lblHlsStatus)

        row.addStretch()

        self.lblUptime = QLabel("00:00:00")
        self.lblUptime.setObjectName("statusItem")
        row.addWidget(self.lblUptime)

        self.lblBitrate = QLabel("0.0 kbps")
        self.lblBitrate.setObjectName("statusItem")
        row.addWidget(self.lblBitrate)

        self.lblDataSent = QLabel("0 B sent")
        self.lblDataSent.setObjectName("statusItem")
        row.addWidget(self.lblDataSent)

        # Toggle relay AAC/Icecast-native (default OFF) untuk pendengar legacy
        if self.icecast is not None:
            self.btnIcecast = QPushButton("AAC Off")
            self.btnIcecast.setToolTip(
                "Enable legacy Icecast-compatible AAC stream at /live\n"
                "(for listeners that cannot play Opus/HLS)"
            )
            self.btnIcecast.setCursor(Qt.PointingHandCursor)
            self.btnIcecast.clicked.connect(self._on_toggle_icecast)
            row.addWidget(self.btnIcecast)

        btnCopyUrl = QPushButton("Copy URL")
        btnCopyUrl.setStyleSheet(
            "border: none; color: #4b5563; font-size: 11px; padding: 2px 6px;"
        )
        btnCopyUrl.setCursor(Qt.PointingHandCursor)
        btnCopyUrl.setToolTip("Copy active public/local HLS URL")
        btnCopyUrl.clicked.connect(self._copy_hls_url)
        row.addWidget(btnCopyUrl)

        btnSettings = QPushButton("Settings")
        btnSettings.setStyleSheet(
            "border: none; color: #6366f1; font-size: 11px; font-weight: 600; padding: 2px 6px;"
        )
        btnSettings.setCursor(Qt.PointingHandCursor)
        btnSettings.setToolTip("Open application settings")
        btnSettings.clicked.connect(self._open_settings_dialog)
        row.addWidget(btnSettings)

        return row

    # ── Actions / Slots ─────────────────────────────────────────────
    def _on_toggle_play(self):
        is_playing = self.track.toggle_play()
        self.btnPlay.setText("Pause" if is_playing else "Play")
        if is_playing:
            self.btnPlay.setStyleSheet("")  # reset to QSS default
        else:
            self.btnPlay.setStyleSheet(
                "background-color: #f59e0b; color: #000; border: none; "
                "font-size: 12px; font-weight: 700; min-width: 56px; max-width: 56px; "
                "min-height: 30px; max-height: 30px; border-radius: 6px;"
            )
        self.log_event(f"Broadcast {'PLAYING' if is_playing else 'PAUSED'}")

    def _on_toggle_mute(self):
        is_muted = self.track.toggle_mute()
        if is_muted:
            self.btnMute.setText("Muted")
            self.btnMute.setStyleSheet(
                "background-color: #dc2626; color: #fff; border-color: #dc2626; "
                "padding: 6px 12px;"
            )
        else:
            self.btnMute.setText("Mute")
            self.btnMute.setStyleSheet("")  # reset
        self.log_event(f"Mute {'ON' if is_muted else 'OFF'}")

    def _on_next_track(self):
        self.track.next_track()
        self._populate_all_tables()
        self.log_event("Next track")

    def _on_prev_track(self):
        self.track.prev_track()
        self._populate_all_tables()
        self.log_event("Previous track")

    def _on_reshuffle(self):
        self.track._refill_shuffled_pool()
        self.log_event("Auto-DJ pool reshuffled")

    def _on_rescan_folder(self):
        new_added, total = self.track.refresh_playlist(self.music_dir)
        self._populate_all_tables()
        self._check_non_opus_files()
        self.log_event(f"Rescan: +{new_added} new ({total} total)")

    def _copy_hls_url(self):
        # Prefer tunnel public URL or active public URL, fallback to local URL
        url = self.hls_streamer.public_url if self.hls_streamer else "http://127.0.0.1:8000/live.m3u8"
        tunnel_info = get_tunnel_status()
        if tunnel_info.get("quick_url"):
            url = f"{tunnel_info['quick_url']}/live.m3u8"
        QApplication.clipboard().setText(url)
        self.log_event(f"Copied: {url}")

    def _live_urls(self) -> tuple:
        """Kembalikan (local_url, public_url) untuk mount point /live AAC."""
        port = self.hls_streamer.port if self.hls_streamer else 8000
        local = f"http://127.0.0.1:{port}/live"
        public = ""
        pub = getattr(self.hls_streamer, "public_url", "") if self.hls_streamer else ""
        if pub and "/" in pub:
            base = pub.rsplit("/", 1)[0]
            public = f"{base}/live"
        tunnel_info = get_tunnel_status()
        quick = tunnel_info.get("quick_url")
        if quick:
            public = f"{quick}/live"
        return local, public

    def _on_toggle_icecast(self):
        if self.icecast is None:
            return
        if self.icecast.enabled:
            self.icecast.disable()
            self.btnIcecast.setText("AAC Off")
            self.btnIcecast.setStyleSheet("")
            self.log_event("AAC/Icecast relay OFF")
        else:
            if self.icecast.enable():
                self.btnIcecast.setStyleSheet(
                    "background-color: #059669; color: #ffffff; border-color: #10b981; "
                    "font-weight: 700; padding: 6px 12px;"
                )
                local, public = self._live_urls()
                self.log_event(f"AAC/Icecast relay ON -> {local}")
                if public:
                    self.log_event(f"AAC/Icecast public: {public}")
            else:
                self.log_event("AAC/Icecast relay FAILED to initialize")

    def _browse_and_set_music_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Music Directory", self.music_dir)
        if folder:
            self.music_dir = os.path.abspath(folder)
            self.config.music_dir = self.music_dir
            self.config.save()
            new_added, total = self.track.refresh_playlist(self.music_dir)
            self._populate_all_tables()
            self._check_non_opus_files()
            self.log_event(f"Directory updated: {self.music_dir} ({total} tracks)")

    def _check_non_opus_files(self):
        try:
            files = scan_non_opus_files(self.music_dir)
            if files:
                self.btnConvertNonOpus.setText(f"Convert ({len(files)})")
                self.btnConvertNonOpus.setVisible(True)
            else:
                self.btnConvertNonOpus.setVisible(False)
        except Exception:
            self.btnConvertNonOpus.setVisible(False)

    def _start_batch_conversion(self):
        if self.conversion_in_progress:
            return
        files = scan_non_opus_files(self.music_dir)
        if not files:
            QMessageBox.information(self, "Convert", "No non-Opus audio files found in directory.")
            return

        self.conversion_in_progress = True
        self.btnConvertNonOpus.setEnabled(False)
        self.log_event(f"Starting conversion of {len(files)} audio files to Opus...")

        async def run_conv():
            def cb(name, cur, tot):
                self.log_event(f"Converting [{cur}/{tot}]: {name}")

            s, t = await asyncio.to_thread(batch_convert_files, files, cb)
            self.log_event(f"Conversion complete! Converted {s}/{t} files to Opus.")
            self.conversion_in_progress = False
            self.btnConvertNonOpus.setEnabled(True)
            self.track.refresh_playlist(self.music_dir)
            self._populate_all_tables()
            self._check_non_opus_files()

        asyncio.create_task(run_conv())

    def _open_settings_dialog(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec():
            # If music directory changed, update it
            if self.config.music_dir != self.music_dir:
                self.music_dir = self.config.music_dir
                self.track.refresh_playlist(self.music_dir)
                self._populate_all_tables()
                self._check_non_opus_files()
                self.log_event(f"Config: Music dir set to {self.music_dir}")

            # If public HLS URL changed
            if self.hls_streamer and self.config.public_hls_url:
                self.hls_streamer.public_url = self.config.public_hls_url

            self.log_event("Settings saved")

    # ── Table Population ────────────────────────────────────
    def _populate_all_tables(self):
        self._populate_library_table()
        self._populate_queue_table()

    def _populate_playlist_table(self):
        self._populate_all_tables()

    def _populate_library_table(self):
        if not hasattr(self, 'tableLibrary'):
            return
        query = self.txtSearch.text().lower().strip()
        self.tableLibrary.setRowCount(0)

        for i, path in enumerate(self.track.library):
            name = os.path.basename(path)
            if query and query not in name.lower():
                continue

            row = self.tableLibrary.rowCount()
            self.tableLibrary.insertRow(row)

            is_current = (path == self.track.current_track) and (self.track.source_mode == "playlist")

            item_num = QTableWidgetItem(str(i + 1))
            item_num.setTextAlignment(Qt.AlignCenter)
            item_name = QTableWidgetItem(name)
            item_status = QTableWidgetItem("Playing" if is_current else "")

            if is_current:
                accent = QtGui.QColor("#a5b4fc")
                item_name.setForeground(QtGui.QBrush(accent))
                item_status.setForeground(QtGui.QBrush(accent))
                f_bold = QtGui.QFont()
                f_bold.setBold(True)
                item_name.setFont(f_bold)

            item_num.setData(Qt.UserRole, i)

            self.tableLibrary.setItem(row, 0, item_num)
            self.tableLibrary.setItem(row, 1, item_name)
            self.tableLibrary.setItem(row, 2, item_status)

        if hasattr(self, 'lblLibHeader'):
            self.lblLibHeader.setText(f"LIBRARY · {len(self.track.library)}")

    def _populate_queue_table(self):
        if not hasattr(self, 'tableQueue'):
            return
        self.tableQueue.setRowCount(0)

        for i, path in enumerate(self.track.user_queue):
            name = os.path.basename(path)
            row = self.tableQueue.rowCount()
            self.tableQueue.insertRow(row)

            item_num = QTableWidgetItem(str(i + 1))
            item_num.setTextAlignment(Qt.AlignCenter)
            item_name = QTableWidgetItem(name)

            if i == 0:
                item_name.setForeground(QtGui.QBrush(QtGui.QColor("#34d399")))
                f_bold = QtGui.QFont()
                f_bold.setBold(True)
                item_name.setFont(f_bold)

            item_num.setData(Qt.UserRole, i)

            self.tableQueue.setItem(row, 0, item_num)
            self.tableQueue.setItem(row, 1, item_name)

        if hasattr(self, 'lblQueueHeader'):
            self.lblQueueHeader.setText(f"QUEUE · {len(self.track.user_queue)}")

    def _filter_library(self):
        self._populate_library_table()

    # ── Library Actions ─────────────────────────────────────────────
    def _play_selected_library_track(self):
        sel = self.tableLibrary.selectedItems()
        if not sel:
            return
        row = sel[0].row()
        item_num = self.tableLibrary.item(row, 0)
        if item_num is None:
            return
        idx = item_num.data(Qt.UserRole)
        if idx is not None and 0 <= idx < len(self.track.library):
            file_path = self.track.library[idx]
            self.track.play_track_direct(file_path)
            self._populate_all_tables()
            self.log_event(f"Playing now: {os.path.basename(file_path)}")

    def _add_selected_to_queue(self):
        sel = self.tableLibrary.selectedItems()
        if not sel:
            return
        row = sel[0].row()
        item_num = self.tableLibrary.item(row, 0)
        if item_num is None:
            return
        idx = item_num.data(Qt.UserRole)
        if idx is not None and 0 <= idx < len(self.track.library):
            file_path = self.track.library[idx]
            pos = self.track.add_to_queue_bottom(file_path)
            self._populate_queue_table()
            self.log_event(f"Queued: {os.path.basename(file_path)} (#{pos})")

    def _on_library_double_clicked(self, item: QTableWidgetItem):
        self._play_selected_library_track()

    def _show_library_context_menu(self, pos):
        item = self.tableLibrary.itemAt(pos)
        if item is None:
            return
        row = item.row()
        item_num = self.tableLibrary.item(row, 0)
        if item_num is None:
            return
        idx = item_num.data(Qt.UserRole)
        if idx is None or idx >= len(self.track.library):
            return

        file_path = self.track.library[idx]
        track_name = os.path.basename(file_path)

        menu = QMenu(self)
        act_play_now = menu.addAction("Play Now")
        act_play_next = menu.addAction("Play Next")
        act_add_queue = menu.addAction("Add to Queue")
        menu.addSeparator()
        act_reveal = menu.addAction("Open in File Explorer")
        act_info = menu.addAction("Properties")

        action = menu.exec(self.tableLibrary.viewport().mapToGlobal(pos))
        if action == act_play_now:
            self.track.play_track_direct(file_path)
            self._populate_all_tables()
            self.log_event(f"Playing now: {track_name}")
        elif action == act_play_next:
            pos_idx = self.track.insert_next_track(file_path)
            self._populate_queue_table()
            self.log_event(f"Queued next: {track_name} (#{pos_idx})")
        elif action == act_add_queue:
            pos_idx = self.track.add_to_queue_bottom(file_path)
            self._populate_queue_table()
            self.log_event(f"Queued: {track_name} (#{pos_idx})")
        elif action == act_reveal:
            self._open_in_explorer(file_path)
        elif action == act_info:
            self._show_track_properties(file_path)

    # ── Queue Actions ───────────────────────────────────────────────
    def _on_queue_double_clicked(self, item: QTableWidgetItem):
        row = item.row()
        if 0 <= row < len(self.track.user_queue):
            file_path = self.track.user_queue[row]
            self.track.remove_from_queue(row)
            self.track.play_track_direct(file_path)
            self._populate_all_tables()
            self.log_event(f"Playing from queue: {os.path.basename(file_path)}")

    def _show_queue_context_menu(self, pos):
        item = self.tableQueue.itemAt(pos)
        if item is None:
            return
        row = item.row()
        if row >= len(self.track.user_queue):
            return

        file_path = self.track.user_queue[row]
        track_name = os.path.basename(file_path)

        menu = QMenu(self)
        act_play_now = menu.addAction("Play Now")
        menu.addSeparator()
        act_move_top = menu.addAction("Move to Top") if row > 0 else None
        act_move_up = menu.addAction("Move Up") if row > 0 else None
        act_move_down = menu.addAction("Move Down") if row < len(self.track.user_queue) - 1 else None
        menu.addSeparator()
        act_remove = menu.addAction("Remove from Queue")

        chosen = menu.exec(self.tableQueue.viewport().mapToGlobal(pos))
        if chosen == act_play_now:
            self.track.remove_from_queue(row)
            self.track.play_track_direct(file_path)
            self._populate_all_tables()
            self.log_event(f"Playing now: {track_name}")

        elif act_move_top and chosen == act_move_top:
            self.track.move_queue_item(row, 0)
            self._populate_queue_table()

        elif act_move_up and chosen == act_move_up:
            self.track.move_queue_item(row, row - 1)
            self._populate_queue_table()

        elif act_move_down and chosen == act_move_down:
            self.track.move_queue_item(row, row + 1)
            self._populate_queue_table()

        elif chosen == act_remove:
            self.track.remove_from_queue(row)
            self._populate_queue_table()
            self.log_event(f"Removed from queue: {track_name}")

    def _on_toggle_autodj(self):
        is_on = self.track.toggle_auto_dj()
        if is_on:
            self.btnAutoDj.setText("Auto-DJ")
            self.btnAutoDj.setStyleSheet("background-color: #059669; color: #ffffff; border-color: #10b981; font-size: 11px; padding: 4px 8px; font-weight: 700;")
            self.log_event("Auto-DJ enabled")
        else:
            self.btnAutoDj.setText("Auto-DJ")
            self.btnAutoDj.setStyleSheet("background-color: #1f2937; color: #9ca3af; border-color: #374151; font-size: 11px; padding: 4px 8px; font-weight: 700;")
            self.log_event("Auto-DJ disabled")

    def _on_shuffle_queue(self):
        self.track.shuffle_queue()
        self._populate_queue_table()
        self.log_event("Queue shuffled")

    def _on_clear_queue(self):
        self.track.clear_queue()
        self._populate_queue_table()
        self.log_event("Queue cleared")

    def _open_in_explorer(self, file_path: str):
        try:
            norm_path = os.path.normpath(file_path)
            if sys.platform == "win32":
                subprocess.Popen(f'explorer /select,"{norm_path}"')
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(norm_path)])
            self.log_event(f"Opened explorer: {os.path.basename(file_path)}")
        except Exception as e:
            self.log_event(f"Explorer error: {e}")

    def _show_track_properties(self, file_path: str):
        try:
            name = os.path.basename(file_path)
            size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            size_str = format_bytes(size_bytes)

            duration_str = "Unknown"
            bitrate_str = "Opus VBR ~192 kbps"
            try:
                import av
                with av.open(file_path) as c:
                    if c.duration is not None:
                        dur_sec = float(c.duration) / 1000000.0
                        duration_str = format_duration(dur_sec)
                    if c.bit_rate:
                        bitrate_str = f"{c.bit_rate / 1000:.1f} kbps"
            except Exception:
                pass

            msg = (
                f"<b>Title:</b> {name}<br><br>"
                f"<b>Duration:</b> {duration_str}<br>"
                f"<b>File Size:</b> {size_str}<br>"
                f"<b>Audio Bitrate:</b> {bitrate_str}<br>"
                f"<b>Codec / Stream:</b> Raw Opus (RFC 7587) @ 48kHz Stereo<br><br>"
                f"<b>File Location:</b><br><span style='color: #a5b4fc; font-family: monospace; font-size: 11px;'>{file_path}</span>"
            )
            QMessageBox.information(self, "Track Properties", msg)
        except Exception as e:
            self.log_event(f"Properties error: {e}")

    def _start_youtube_download(self):
        url = self.txtYtUrl.text().strip()
        if not url:
            QMessageBox.warning(self, "Warning", "Please enter a valid YouTube URL.")
            return
        if self.download_in_progress:
            QMessageBox.warning(self, "Warning", "Download already in progress.")
            return

        self.download_in_progress = True
        self.btnYtDownload.setEnabled(False)
        self.lblYtStatus.setText("Downloading...")
        self.lblYtStatus.setStyleSheet("color: #f59e0b; font-size: 11px;")
        self.log_event(f"YouTube download: {url}")

        asyncio.create_task(self._async_youtube_download(url))

    async def _async_youtube_download(self, url: str):
        try:
            output_path = await download_youtube_opus(url, output_dir=self.music_dir)
            file_name = os.path.basename(output_path)
            pos = self.track.insert_next_track(output_path)

            self.lblYtStatus.setText(f"Done: {file_name}")
            self.lblYtStatus.setStyleSheet("color: #22c55e; font-size: 11px;")
            self.txtYtUrl.clear()
            self._populate_all_tables()
            self.log_event(f"Downloaded and queued: {file_name} (#{pos})")
        except Exception as e:
            self.lblYtStatus.setText("Failed")
            self.lblYtStatus.setStyleSheet("color: #ef4444; font-size: 11px;")
            self.log_event(f"YouTube error: {e}")
        finally:
            self.download_in_progress = False
            self.btnYtDownload.setEnabled(True)

    # ── Stats Refresh (Periodic) ────────────────────────────────────
    def _update_gui_stats(self):
        try:
            status = self.track.get_status()
            pacer = self.track.get_pacer_stats()
            hls = self.hls_streamer.get_hls_stats() if self.hls_streamer else None

            # Source mode & now playing
            is_mic = (status.get("source_mode") == "mic")

            if is_mic:
                dev_name = self.comboAudioDevices.currentText() if self.comboAudioDevices.count() > 0 else "Default"
                self.lblTrack.setText(f"LIVE  ·  {dev_name}")
                self.lblTime.setText("PCM to Opus")
                self.trackProgress.setValue(1000 if status.get("mic_is_running") else 0)

                # Update VU Meter
                level_lin = status.get("mic_level_linear", 0.0)
                level_db = status.get("mic_level_db", -60.0)
                vu_val = int(min(1.0, max(0.0, level_lin * 2.5)) * 100)
                self.vuMeter.setValue(vu_val)
                self.lblVuDb.setText(f"{level_db:.0f} dB")
            else:
                name = status.get("track", "Unknown")
                source = status.get("current_source", "autodj")

                if source == "queue":
                    badge = "QUEUE"
                elif source == "direct":
                    badge = "DIRECT"
                elif source == "autodj":
                    badge = "AUTO-DJ"
                else:
                    badge = "LIBRARY"

                self.lblTrack.setText(f"{badge}  ·  {name}")

                elapsed = status.get("track_elapsed_sec", 0.0)
                duration = status.get("track_duration_sec", 0.0)
                self.lblTime.setText(
                    f"{format_duration(elapsed)} / {format_duration(duration) if duration > 0 else '00:00'}"
                )

                if duration > 0:
                    self.trackProgress.setValue(int((elapsed / duration) * 1000))
                else:
                    self.trackProgress.setValue(0)

                self.vuMeter.setValue(0)
                self.lblVuDb.setText("-60 dB")

            # WebRTC status
            conn = self.whip_client.pc.connectionState if (self.whip_client and self.whip_client.pc) else "closed"
            self.lblWhipStatus.setText(f"WebRTC {conn}")
            if conn == "connected":
                self.lblWhipStatus.setStyleSheet("color: #22c55e; font-size: 11px;")
            else:
                self.lblWhipStatus.setStyleSheet("color: #ef4444; font-size: 11px;")

            # HLS & Tunnel status
            tunnel_info = get_tunnel_status()
            if tunnel_info.get("quick_url"):
                self.lblHlsStatus.setText(f"HLS active (Tunnel: {tunnel_info['quick_url']})")
                self.lblHlsStatus.setStyleSheet("color: #22c55e; font-size: 11px;")
            elif hls and hls["is_running"]:
                req_str = f"{hls['http_requests']:,} req"
                self.lblHlsStatus.setText(f"HLS :{hls['port']} active ({req_str})")
                self.lblHlsStatus.setStyleSheet("color: #22c55e; font-size: 11px;")
            else:
                self.lblHlsStatus.setText("HLS offline")
                self.lblHlsStatus.setStyleSheet("color: #ef4444; font-size: 11px;")

            # Footer stats
            self.lblUptime.setText(format_duration(pacer['uptime_sec']))
            self.lblBitrate.setText(f"{pacer['instant_bitrate_kbps']:.1f} kbps")
            self.lblDataSent.setText(f"{format_bytes(pacer['total_bytes'])} sent")

            # Icecast/AAC toggle label (listener count live update)
            if self.icecast is not None and hasattr(self, 'btnIcecast'):
                ic = self.icecast.get_stats()
                if ic["enabled"]:
                    n = ic["listeners"]
                    self.btnIcecast.setText(f"AAC On · {n} listener" + ("s" if n != 1 else ""))
                else:
                    self.btnIcecast.setText("AAC Off")

        except Exception:
            pass
