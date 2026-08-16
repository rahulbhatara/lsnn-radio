import sys
import os
import time
import asyncio
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QTableWidget, QTableWidgetItem,
    QLineEdit, QTextEdit, QFrame, QHeaderView, QMessageBox, QSizePolicy
)

from yt_downloader import download_youtube_opus

def format_duration(seconds: float) -> str:
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    sec = total_sec % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"

def format_bytes(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    else:
        return f"{num_bytes / (1024 * 1024):.1f} MB"

# ── Minimal Dark Theme ──────────────────────────────────────────────
MINIMAL_QSS = """
* {
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}
QMainWindow, QWidget {
    background-color: #111318;
    color: #d1d5db;
}

/* ── Cards ── */
QFrame#card {
    background-color: #191c24;
    border: 1px solid #262a35;
    border-radius: 10px;
}

/* ── Progress Bar ── */
QProgressBar {
    border: none;
    border-radius: 3px;
    background-color: #262a35;
    color: transparent;
    max-height: 6px;
}
QProgressBar::chunk {
    background-color: #6366f1;
    border-radius: 3px;
}

/* ── Buttons ── */
QPushButton {
    background-color: transparent;
    color: #9ca3af;
    border: 1px solid #2d3240;
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #1e2230;
    color: #e5e7eb;
    border-color: #4b5072;
}
QPushButton:pressed {
    background-color: #161923;
}

/* ── Media Control Buttons ── */
QPushButton#btnPlay {
    background-color: #6366f1;
    color: #ffffff;
    font-size: 18px;
    min-width: 44px; max-width: 44px;
    min-height: 44px; max-height: 44px;
    border-radius: 22px;
    border: none;
}
QPushButton#btnPlay:hover {
    background-color: #818cf8;
}
QPushButton.ctrl {
    font-size: 15px;
    min-width: 36px; max-width: 36px;
    min-height: 36px; max-height: 36px;
    border-radius: 18px;
    padding: 0;
}

/* ── Input ── */
QLineEdit {
    background-color: #14161e;
    border: 1px solid #262a35;
    border-radius: 8px;
    padding: 7px 10px;
    color: #e5e7eb;
    selection-background-color: #6366f1;
}
QLineEdit:focus {
    border-color: #6366f1;
}

/* ── Table ── */
QTableWidget {
    background-color: #14161e;
    gridline-color: #1e2230;
    border: 1px solid #262a35;
    border-radius: 8px;
    selection-background-color: #1e2240;
    selection-color: #a5b4fc;
    outline: 0;
}
QTableWidget::item {
    padding: 4px 8px;
}
QHeaderView::section {
    background-color: #191c24;
    color: #6b7280;
    padding: 6px 8px;
    border: none;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
}

/* ── Log Area ── */
QTextEdit#logPanel {
    background-color: #14161e;
    border: 1px solid #262a35;
    border-radius: 8px;
    color: #6b7280;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 11px;
    padding: 6px;
}

/* ── Status Bar Labels ── */
QLabel#statusItem {
    color: #6b7280;
    font-size: 11px;
}
QLabel#statusDot {
    font-size: 8px;
}

/* ── Scrollbar ── */
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #2d3240;
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0;
}

/* ── Tooltip ── */
QToolTip {
    background-color: #1e2230;
    color: #e5e7eb;
    border: 1px solid #363d54;
    padding: 4px 8px;
    border-radius: 6px;
    font-size: 12px;
}
"""


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

    def __init__(self, track, whip_client, hls_streamer, music_dir=".."):
        super().__init__()
        self.track = track
        self.whip_client = whip_client
        self.hls_streamer = hls_streamer
        self.music_dir = music_dir

        self.setWindowTitle("MeshCast Streaming")
        self.resize(820, 580)
        self.setStyleSheet(MINIMAL_QSS)

        self.download_in_progress = False
        self._log_visible = False

        self._init_ui()

        self.log_signal.connect(self._append_log)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._update_gui_stats)
        self.timer.start()

        self.log_event("[System] GUI ready.")

    def log_event(self, text: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_signal.emit(f"[{timestamp}] {text}")

    @Slot(str)
    def _append_log(self, msg: str):
        self.logTextEdit.append(msg)

    # ── Build UI ────────────────────────────────────────────────────
    def _init_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 10)

        layout.addWidget(self._build_now_playing())
        layout.addWidget(self._build_playlist(), stretch=1)
        layout.addWidget(self._build_youtube_row())
        layout.addWidget(self._build_log_section())
        layout.addLayout(self._build_status_bar())

    # ── 1. Now Playing Card ─────────────────────────────────────────
    def _build_now_playing(self):
        card = QWidget()
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(16, 6, 16, 6)
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

        # Control buttons
        self.btnPrev = self._media_btn("⏮", "Previous track")
        self.btnPrev.clicked.connect(self._on_prev_track)
        row.addWidget(self.btnPrev)

        self.btnPlay = QPushButton("▶")
        self.btnPlay.setObjectName("btnPlay")
        self.btnPlay.setToolTip("Play / Pause")
        self.btnPlay.clicked.connect(self._on_toggle_play)
        row.addWidget(self.btnPlay)

        self.btnNext = self._media_btn("⏭", "Next track")
        self.btnNext.clicked.connect(self._on_next_track)
        row.addWidget(self.btnNext)

        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: #262a35;")
        sep.setFixedHeight(28)
        row.addWidget(sep)

        self.btnMute = self._media_btn("🔊", "Mute / Unmute")
        self.btnMute.clicked.connect(self._on_toggle_mute)
        row.addWidget(self.btnMute)

        self.btnShuffle = self._media_btn("🔀", "Reshuffle playlist")
        self.btnShuffle.clicked.connect(self._on_reshuffle)
        row.addWidget(self.btnShuffle)

        self.btnRescan = self._media_btn("🔄", "Rescan folder")
        self.btnRescan.clicked.connect(self._on_rescan_folder)
        row.addWidget(self.btnRescan)

        vbox.addLayout(row)
        return card

    def _media_btn(self, icon: str, tooltip: str) -> QPushButton:
        btn = QPushButton(icon)
        btn.setProperty("class", "ctrl")
        btn.setToolTip(tooltip)
        return btn

    # ── 2. Playlist ─────────────────────────────────────────────────
    def _build_playlist(self):
        card = QFrame()
        card.setObjectName("card")
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(6)

        # Search row
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        self.txtSearch = QLineEdit()
        self.txtSearch.setPlaceholderText("Search tracks...")
        self.txtSearch.setClearButtonEnabled(True)
        self.txtSearch.textChanged.connect(self._filter_playlist)
        search_row.addWidget(self.txtSearch, stretch=1)

        btnPlaySel = QPushButton("▶ Play")
        btnPlaySel.setToolTip("Play selected track")
        btnPlaySel.clicked.connect(self._play_selected_track)
        search_row.addWidget(btnPlaySel)

        vbox.addLayout(search_row)

        # Table
        self.tablePlaylist = QTableWidget()
        self.tablePlaylist.setColumnCount(3)
        self.tablePlaylist.setHorizontalHeaderLabels(["#", "Track Name", "Status"])
        self.tablePlaylist.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tablePlaylist.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tablePlaylist.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tablePlaylist.verticalHeader().setVisible(False)
        self.tablePlaylist.setSelectionBehavior(QTableWidget.SelectRows)
        self.tablePlaylist.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tablePlaylist.setShowGrid(False)
        self.tablePlaylist.setAlternatingRowColors(False)
        self.tablePlaylist.itemDoubleClicked.connect(self._on_table_double_clicked)
        vbox.addWidget(self.tablePlaylist, stretch=1)

        self._populate_playlist_table()
        return card

    # ── 3. YouTube Download Row ─────────────────────────────────────
    def _build_youtube_row(self):
        card = QFrame()
        card.setObjectName("card")
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)

        lbl = QLabel("YouTube")
        lbl.setStyleSheet("color: #6b7280; font-weight: 600; font-size: 12px;")
        row.addWidget(lbl)

        self.txtYtUrl = QLineEdit()
        self.txtYtUrl.setPlaceholderText("Paste YouTube URL here...")
        row.addWidget(self.txtYtUrl, stretch=1)

        self.btnYtDownload = QPushButton("⬇ Download")
        self.btnYtDownload.setToolTip("Download audio & add as next track")
        self.btnYtDownload.clicked.connect(self._start_youtube_download)
        row.addWidget(self.btnYtDownload)

        self.lblYtStatus = QLabel("")
        self.lblYtStatus.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.lblYtStatus.setFixedWidth(180)
        row.addWidget(self.lblYtStatus)

        return card

    # ── 4. Collapsible Log Panel ────────────────────────────────────
    def _build_log_section(self):
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)

        self.btnToggleLog = QPushButton("▸ Show Log")
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
            self.btnToggleLog.setText("▾ Hide Log")
        else:
            self.logTextEdit.setFixedHeight(0)
            self.logTextEdit.setVisible(False)
            self.btnToggleLog.setText("▸ Show Log")

    # ── 5. Compact Status Bar ───────────────────────────────────────
    def _build_status_bar(self):
        row = QHBoxLayout()
        row.setSpacing(16)
        row.setContentsMargins(4, 2, 4, 0)

        self.dotWhip = QLabel("●")
        self.dotWhip.setObjectName("statusDot")
        self.dotWhip.setStyleSheet("color: #ef4444; font-size: 8px;")
        row.addWidget(self.dotWhip)

        self.lblWhipStatus = QLabel("WebRTC: connecting")
        self.lblWhipStatus.setObjectName("statusItem")
        row.addWidget(self.lblWhipStatus)

        self.dotHls = QLabel("●")
        self.dotHls.setObjectName("statusDot")
        self.dotHls.setStyleSheet("color: #22c55e; font-size: 8px;")
        row.addWidget(self.dotHls)

        self.lblHlsStatus = QLabel("HLS: active")
        self.lblHlsStatus.setObjectName("statusItem")
        row.addWidget(self.lblHlsStatus)

        row.addStretch()

        self.lblUptime = QLabel("Uptime: 00:00:00")
        self.lblUptime.setObjectName("statusItem")
        row.addWidget(self.lblUptime)

        self.lblBitrate = QLabel("0.0 kbps")
        self.lblBitrate.setObjectName("statusItem")
        row.addWidget(self.lblBitrate)

        self.lblDataSent = QLabel("0 B sent")
        self.lblDataSent.setObjectName("statusItem")
        row.addWidget(self.lblDataSent)

        btnCopyUrl = QPushButton("📋 Copy HLS URL")
        btnCopyUrl.setStyleSheet(
            "border: none; color: #4b5563; font-size: 11px; padding: 2px 6px;"
        )
        btnCopyUrl.setCursor(Qt.PointingHandCursor)
        btnCopyUrl.setToolTip("Copy public HLS URL to clipboard")
        btnCopyUrl.clicked.connect(self._copy_hls_url)
        row.addWidget(btnCopyUrl)

        return row

    # ── Actions / Slots ─────────────────────────────────────────────
    def _on_toggle_play(self):
        is_playing = self.track.toggle_play()
        self.btnPlay.setText("▶" if is_playing else "⏸")
        if is_playing:
            self.btnPlay.setStyleSheet("")  # reset to QSS default (indigo)
        else:
            self.btnPlay.setStyleSheet(
                "background-color: #f59e0b; color: #000; border: none; "
                "font-size: 18px; min-width: 44px; max-width: 44px; "
                "min-height: 44px; max-height: 44px; border-radius: 22px;"
            )
        self.log_event(f"Playback {'PLAYING' if is_playing else 'PAUSED'}")

    def _on_toggle_mute(self):
        is_muted = self.track.toggle_mute()
        if is_muted:
            self.btnMute.setText("🔇")
            self.btnMute.setStyleSheet(
                "background-color: #dc2626; color: #fff; border: none; "
                "font-size: 15px; min-width: 36px; max-width: 36px; "
                "min-height: 36px; max-height: 36px; border-radius: 18px; padding: 0;"
            )
        else:
            self.btnMute.setText("🔊")
            self.btnMute.setStyleSheet("")  # reset
        self.log_event(f"Mute {'ON' if is_muted else 'OFF'}")

    def _on_next_track(self):
        self.track.next_track()
        self._populate_playlist_table()
        self.log_event("Next track")

    def _on_prev_track(self):
        self.track.prev_track()
        self._populate_playlist_table()
        self.log_event("Previous track")

    def _on_reshuffle(self):
        self.track.reshuffle_remaining()
        self._populate_playlist_table()
        self.log_event("Playlist reshuffled")

    def _on_rescan_folder(self):
        new_added, total = self.track.refresh_playlist(self.music_dir)
        self._populate_playlist_table()
        self.log_event(f"Rescan: +{new_added} new (total {total})")

    def _copy_hls_url(self):
        url = self.hls_streamer.public_url
        QApplication.clipboard().setText(url)
        self.log_event(f"Copied HLS URL: {url}")

    def _populate_playlist_table(self):
        query = self.txtSearch.text().lower().strip()
        self.tablePlaylist.setRowCount(0)

        for i, path in enumerate(self.track.playlist):
            name = os.path.basename(path)
            if query and query not in name.lower():
                continue

            row = self.tablePlaylist.rowCount()
            self.tablePlaylist.insertRow(row)

            is_current = (i == self.track.current_index)

            item_num = QTableWidgetItem(str(i + 1))
            item_num.setTextAlignment(Qt.AlignCenter)
            item_name = QTableWidgetItem(name)
            item_status = QTableWidgetItem("▶ Playing" if is_current else "")

            if is_current:
                accent = QtGui.QColor("#a5b4fc")
                item_name.setForeground(QtGui.QBrush(accent))
                item_status.setForeground(QtGui.QBrush(accent))
                item_name.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold))

            # Store original index for playback
            item_num.setData(Qt.UserRole, i)

            self.tablePlaylist.setItem(row, 0, item_num)
            self.tablePlaylist.setItem(row, 1, item_name)
            self.tablePlaylist.setItem(row, 2, item_status)

    def _filter_playlist(self):
        self._populate_playlist_table()

    def _play_selected_track(self):
        current_row = self.tablePlaylist.currentRow()
        if current_row < 0:
            return
        item_num = self.tablePlaylist.item(current_row, 0)
        if not item_num:
            return
        idx = item_num.data(Qt.UserRole)
        if idx is not None and 0 <= idx < len(self.track.playlist):
            self.track.play_track_at_index(idx)
            self._populate_playlist_table()
            self.log_event(f"Playing: {os.path.basename(self.track.playlist[idx])}")

    def _on_table_double_clicked(self, item):
        self._play_selected_track()

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
        self.lblYtStatus.setText("⏳ Downloading...")
        self.lblYtStatus.setStyleSheet("color: #f59e0b; font-size: 11px;")
        self.log_event(f"YouTube download: {url}")

        asyncio.create_task(self._async_youtube_download(url))

    async def _async_youtube_download(self, url: str):
        try:
            output_path = await download_youtube_opus(url, output_dir=self.music_dir)
            file_name = os.path.basename(output_path)
            pos = self.track.insert_next_track(output_path)

            self.lblYtStatus.setText(f"✅ {file_name}")
            self.lblYtStatus.setStyleSheet("color: #22c55e; font-size: 11px;")
            self.txtYtUrl.clear()
            self._populate_playlist_table()
            self.log_event(f"Downloaded: {file_name} → #{pos}")
        except Exception as e:
            self.lblYtStatus.setText(f"❌ Failed")
            self.lblYtStatus.setStyleSheet("color: #ef4444; font-size: 11px;")
            self.log_event(f"YouTube error: {e}")
        finally:
            self.download_in_progress = False
            self.btnYtDownload.setEnabled(True)

    # ── Stats Refresh (1 Hz) ────────────────────────────────────────
    def _update_gui_stats(self):
        try:
            status = self.track.get_status()
            pacer = self.track.get_pacer_stats()
            hls = self.hls_streamer.get_hls_stats() if self.hls_streamer else None

            # Now Playing
            name = status["track"]
            idx = status["index"]
            total = status["total"]
            self.lblTrack.setText(f"{idx}/{total}  ·  {name}")

            elapsed = status.get("track_elapsed_sec", 0.0)
            duration = status.get("track_duration_sec", 0.0)
            self.lblTime.setText(
                f"{format_duration(elapsed)} / {format_duration(duration) if duration > 0 else '00:00'}"
            )

            if duration > 0:
                self.trackProgress.setValue(int((elapsed / duration) * 1000))
            else:
                self.trackProgress.setValue(0)

            # WebRTC status
            conn = self.whip_client.pc.connectionState if (self.whip_client and self.whip_client.pc) else "closed"
            self.lblWhipStatus.setText(f"WebRTC: {conn}")
            if conn == "connected":
                self.dotWhip.setStyleSheet("color: #22c55e; font-size: 8px;")
            else:
                self.dotWhip.setStyleSheet("color: #ef4444; font-size: 8px;")

            # HLS status
            if hls and hls["is_running"]:
                self.lblHlsStatus.setText(f"HLS: active ({hls['http_requests']:,} req)")
                self.dotHls.setStyleSheet("color: #22c55e; font-size: 8px;")
            else:
                self.lblHlsStatus.setText("HLS: offline")
                self.dotHls.setStyleSheet("color: #ef4444; font-size: 8px;")

            # Footer stats
            self.lblUptime.setText(f"Uptime: {format_duration(pacer['uptime_sec'])}")
            self.lblBitrate.setText(f"{pacer['instant_bitrate_kbps']:.1f} kbps")
            self.lblDataSent.setText(f"{format_bytes(pacer['total_bytes'])} sent")

        except Exception:
            pass
