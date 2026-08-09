import sys
import os
import time
import asyncio
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QTableWidget, QTableWidgetItem,
    QLineEdit, QTextEdit, QTabWidget, QGroupBox, QFrame, QHeaderView,
    QSplitter, QMessageBox, QStyle
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
        return f"{num_bytes / 1024:.2f} KB"
    else:
        return f"{num_bytes / (1024 * 1024):.2f} MB"

DARK_QSS = """
QMainWindow, QWidget {
    background-color: #0f111a;
    color: #e0e6ed;
    font-family: 'Segoe UI', Roboto, sans-serif;
    font-size: 13px;
}
QGroupBox {
    background-color: #16192b;
    border: 1px solid #2a2f4c;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 14px;
    font-weight: bold;
    color: #00e5ff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
}
QTabWidget::pane {
    border: 1px solid #2a2f4c;
    background-color: #16192b;
    border-radius: 6px;
}
QTabBar::tab {
    background-color: #101221;
    color: #8a94a6;
    padding: 10px 20px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
    font-weight: bold;
}
QTabBar::tab:selected {
    background-color: #16192b;
    color: #00e676;
    border-bottom: 2px solid #00e676;
}
QTabBar::tab:hover {
    color: #ffffff;
}
QPushButton {
    background-color: #212642;
    color: #ffffff;
    border: 1px solid #363d66;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #2e355c;
    border-color: #00e5ff;
}
QPushButton:pressed {
    background-color: #181c33;
}
QPushButton.mediaBtn {
    font-size: 18px;
    min-width: 42px;
    min-height: 42px;
    max-width: 42px;
    max-height: 42px;
    border-radius: 21px;
}
QPushButton#btnPlay {
    background-color: #00c853;
    color: #000000;
    font-size: 22px;
    min-width: 50px;
    min-height: 50px;
    max-width: 50px;
    max-height: 50px;
    border-radius: 25px;
    border: None;
}
QPushButton#btnPlay:hover {
    background-color: #00e676;
}
QPushButton#btnMute {
    background-color: #37474f;
}
QLineEdit {
    background-color: #0b0d17;
    border: 1px solid #2a2f4c;
    border-radius: 6px;
    padding: 8px;
    color: #ffffff;
    selection-background-color: #00e5ff;
}
QLineEdit:focus {
    border: 1px solid #00e5ff;
}
QTableWidget {
    background-color: #0b0d17;
    gridline-color: #1e233d;
    border: 1px solid #2a2f4c;
    border-radius: 6px;
    selection-background-color: #212d4a;
    selection-color: #00e676;
}
QHeaderView::section {
    background-color: #16192b;
    color: #00e5ff;
    padding: 6px;
    border: none;
    font-weight: bold;
}
QProgressBar {
    border: 1px solid #2a2f4c;
    border-radius: 6px;
    text-align: center;
    background-color: #0b0d17;
    color: #ffffff;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00c853, stop:1 #00e5ff);
    border-radius: 5px;
}
QTextEdit {
    background-color: #0b0d17;
    border: 1px solid #2a2f4c;
    border-radius: 6px;
    color: #00e5ff;
    font-family: 'Consolas', 'Courier New', monospace;
}
QLabel#statusBadge {
    background-color: #1e2438;
    border: 1px solid #00e676;
    border-radius: 4px;
    padding: 4px 8px;
    color: #00e676;
    font-weight: bold;
}
QToolTip {
    background-color: #1e2438;
    color: #ffffff;
    border: 1px solid #00e5ff;
    padding: 4px 8px;
    border-radius: 4px;
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

        self.setWindowTitle("Streaming MeshCast - Modern Opus Dual Broadcast Controller")
        self.resize(1100, 720)
        self.setStyleSheet(DARK_QSS)

        self.download_in_progress = False

        self._init_ui()

        # Signal connection for thread-safe logging
        self.log_signal.connect(self._append_log)

        # Setup 1-second GUI Refresh Timer
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._update_gui_stats)
        self.timer.start()

        self.log_event("[System] Qt GUI initialized successfully.")

    def log_event(self, text: str):
        timestamp = time.strftime("%H:%M:%S")
        msg = f"[{timestamp}] {text}"
        self.log_signal.emit(msg)

    @Slot(str)
    def _append_log(self, msg: str):
        self.logTextEdit.append(msg)
        self.dashboardLogTextEdit.append(msg)

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # ==========================================
        # TOP HEADER: STATUS & NOW PLAYING BAR
        # ==========================================
        header_card = QGroupBox("📻 NOW PLAYING & BROADCAST CONTROL")
        header_layout = QVBoxLayout(header_card)

        top_info_layout = QHBoxLayout()

        self.lblCurrentTrack = QLabel("▶ Loading track...")
        self.lblCurrentTrack.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        top_info_layout.addWidget(self.lblCurrentTrack, stretch=1)

        self.badgeWhip = QLabel("WebRTC: Connecting...")
        self.badgeWhip.setObjectName("statusBadge")
        top_info_layout.addWidget(self.badgeWhip)

        self.badgeHls = QLabel("HLS CDN: Active")
        self.badgeHls.setObjectName("statusBadge")
        top_info_layout.addWidget(self.badgeHls)

        header_layout.addLayout(top_info_layout)

        # Progress bar
        progress_layout = QHBoxLayout()
        self.lblProgressSec = QLabel("00:00 / 00:00")
        self.lblProgressSec.setStyleSheet("color: #8a94a6; font-weight: bold;")
        self.trackProgressBar = QProgressBar()
        self.trackProgressBar.setRange(0, 100)
        self.trackProgressBar.setValue(0)
        progress_layout.addWidget(self.lblProgressSec)
        progress_layout.addWidget(self.trackProgressBar, stretch=1)
        header_layout.addLayout(progress_layout)

        # Control Buttons Row (Pure Icons with Tooltips)
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(12)

        self.btnPrev = QPushButton("⏮")
        self.btnPrev.setProperty("class", "mediaBtn")
        self.btnPrev.setToolTip("Lagu Sebelumnya (Previous)")
        self.btnPrev.clicked.connect(self._on_prev_track)
        ctrl_layout.addWidget(self.btnPrev)

        self.btnPlay = QPushButton("▶")
        self.btnPlay.setObjectName("btnPlay")
        self.btnPlay.setToolTip("Putar / Jeda (Play / Pause)")
        self.btnPlay.clicked.connect(self._on_toggle_play)
        ctrl_layout.addWidget(self.btnPlay)

        self.btnNext = QPushButton("⏭")
        self.btnNext.setProperty("class", "mediaBtn")
        self.btnNext.setToolTip("Lagu Berikutnya (Next)")
        self.btnNext.clicked.connect(self._on_next_track)
        ctrl_layout.addWidget(self.btnNext)

        self.btnMute = QPushButton("🔊")
        self.btnMute.setObjectName("btnMute")
        self.btnMute.setProperty("class", "mediaBtn")
        self.btnMute.setToolTip("Mute / Unmute Suara")
        self.btnMute.clicked.connect(self._on_toggle_mute)
        ctrl_layout.addWidget(self.btnMute)

        self.btnShuffle = QPushButton("🔀")
        self.btnShuffle.setProperty("class", "mediaBtn")
        self.btnShuffle.setToolTip("Acak Ulang Sisa Playlist (Reshuffle)")
        self.btnShuffle.clicked.connect(self._on_reshuffle)
        ctrl_layout.addWidget(self.btnShuffle)

        self.btnRefreshDir = QPushButton("🔄")
        self.btnRefreshDir.setProperty("class", "mediaBtn")
        self.btnRefreshDir.setToolTip("Pindai Ulang Folder Lagu (Rescan Folder)")
        self.btnRefreshDir.clicked.connect(self._on_rescan_folder)
        ctrl_layout.addWidget(self.btnRefreshDir)

        ctrl_layout.addStretch()
        header_layout.addLayout(ctrl_layout)

        main_layout.addWidget(header_card)

        # ==========================================
        # MAIN TABBED CONTAINER
        # ==========================================
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, stretch=1)

        self._build_dashboard_tab()
        self._build_playlist_tab()
        self._build_youtube_tab()
        self._build_logs_tab()

    def _build_dashboard_tab(self):
        tab = QWidget()
        layout = QHBoxLayout(tab)

        left_col = QVBoxLayout()
        right_col = QVBoxLayout()

        # Stream #1 WebRTC Group
        grp_whip = QGroupBox("🚀 STREAM #1: MeshCast WebRTC (WHIP)")
        whip_layout = QVBoxLayout(grp_whip)
        self.lblWhipState = QLabel("Connection State : INITIALIZING")
        self.lblWhipIce = QLabel("ICE State        : -")
        self.lblWhipDtls = QLabel("DTLS State       : -")
        self.lblWhipBitrate = QLabel("Bitrate (Inst)   : 0.0 kbps")
        self.lblWhipData = QLabel("Total Data Sent  : 0 B")

        for lbl in (self.lblWhipState, self.lblWhipIce, self.lblWhipDtls, self.lblWhipBitrate, self.lblWhipData):
            lbl.setStyleSheet("font-size: 13px; color: #d0d7de; font-family: monospace;")
            whip_layout.addWidget(lbl)
        left_col.addWidget(grp_whip)

        # Stream #2 HLS Cloudflare Group
        grp_hls = QGroupBox("🌐 STREAM #2: HLS Cloudflare CDN")
        hls_layout = QVBoxLayout(grp_hls)
        self.lblHlsState = QLabel("HLS Engine State : ACTIVE")
        self.lblHlsUrl = QLabel(f"Public CDN URL   : {self.hls_streamer.public_url}")
        self.lblHlsLocal = QLabel(f"Local Server     : http://{self.hls_streamer.host}:{self.hls_streamer.port}/live.m3u8")
        self.lblHlsData = QLabel("Served Data      : 0 B (0 requests)")

        for lbl in (self.lblHlsState, self.lblHlsUrl, self.lblHlsLocal, self.lblHlsData):
            lbl.setStyleSheet("font-size: 13px; color: #d0d7de; font-family: monospace;")
            hls_layout.addWidget(lbl)

        btnCopyUrl = QPushButton("📋 Salin URL")
        btnCopyUrl.setToolTip("Salin URL Publik HLS ke Clipboard")
        btnCopyUrl.clicked.connect(self._copy_hls_url)
        hls_layout.addWidget(btnCopyUrl)

        left_col.addWidget(grp_hls)
        left_col.addStretch()

        # Pacer Engine Telemetry Group
        grp_pacer = QGroupBox("⚡ AUDIO PACER & TELEMETRY")
        pacer_layout = QVBoxLayout(grp_pacer)

        self.lblPacerUptime = QLabel("Uptime           : 00:00:00")
        self.lblPacerFrames = QLabel("Frames (Total)   : 0 (Audio: 0, Silence: 0)")
        self.lblPacerRate = QLabel("Packet Rate      : 0.0 pps")
        self.lblPacerDrift = QLabel("Realtime Drift   : 0.00 ms (Avg: 0.00 ms)")

        for lbl in (self.lblPacerUptime, self.lblPacerFrames, self.lblPacerRate, self.lblPacerDrift):
            lbl.setStyleSheet("font-size: 13px; color: #d0d7de; font-family: monospace;")
            pacer_layout.addWidget(lbl)

        right_col.addWidget(grp_pacer)

        # Quick Live Log Preview inside Dashboard
        grp_live_log = QGroupBox("📜 LIVE EVENT LOG")
        live_log_layout = QVBoxLayout(grp_live_log)
        self.dashboardLogTextEdit = QTextEdit()
        self.dashboardLogTextEdit.setReadOnly(True)
        live_log_layout.addWidget(self.dashboardLogTextEdit)
        right_col.addWidget(grp_live_log, stretch=1)

        layout.addLayout(left_col, stretch=1)
        layout.addLayout(right_col, stretch=1)
        self.tabs.addTab(tab, "📊 Live Dashboard")

    def _build_playlist_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Search Bar Row
        search_layout = QHBoxLayout()
        lblSearch = QLabel("🔍 Search Track:")
        lblSearch.setStyleSheet("font-weight: bold; color: #00e5ff;")
        self.txtSearch = QLineEdit()
        self.txtSearch.setPlaceholderText("Ketik kata kunci nama lagu...")
        self.txtSearch.textChanged.connect(self._filter_playlist)
        search_layout.addWidget(lblSearch)
        search_layout.addWidget(self.txtSearch, stretch=1)

        btnPlaySelected = QPushButton("▶ Putar Terpilih")
        btnPlaySelected.setToolTip("Memutar lagu yang disorot di tabel")
        btnPlaySelected.clicked.connect(self._play_selected_track)
        search_layout.addWidget(btnPlaySelected)

        layout.addLayout(search_layout)

        # Table Widget
        self.tablePlaylist = QTableWidget()
        self.tablePlaylist.setColumnCount(4)
        self.tablePlaylist.setHorizontalHeaderLabels(["#", "Track Name", "Status", "Full Path"])
        self.tablePlaylist.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tablePlaylist.setSelectionBehavior(QTableWidget.SelectRows)
        self.tablePlaylist.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tablePlaylist.itemDoubleClicked.connect(self._on_table_double_clicked)
        layout.addWidget(self.tablePlaylist, stretch=1)

        self.tabs.addTab(tab, "🎶 Playlist Manager")
        self._populate_playlist_table()

    def _build_youtube_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        grp_yt = QGroupBox("🔻 YOUTUBE / YT MUSIC AUDIO DOWNLOADER")
        yt_layout = QVBoxLayout(grp_yt)

        lbl_inst = QLabel("Masukkan URL YouTube / YT Music untuk diunduh & dikonversi ke standar Opus 48kHz (otomatis menjadi NEXT SONG):")
        lbl_inst.setWordWrap(True)
        yt_layout.addWidget(lbl_inst)

        input_layout = QHBoxLayout()
        self.txtYtUrl = QLineEdit()
        self.txtYtUrl.setPlaceholderText("https://www.youtube.com/watch?v=...")
        input_layout.addWidget(self.txtYtUrl, stretch=1)

        self.btnYtDownload = QPushButton("⬇ Unduh Audio")
        self.btnYtDownload.setToolTip("Unduh audio dari YouTube & jadikan Next Song")
        self.btnYtDownload.clicked.connect(self._start_youtube_download)
        input_layout.addWidget(self.btnYtDownload)

        yt_layout.addLayout(input_layout)

        self.ytProgressBar = QProgressBar()
        self.ytProgressBar.setRange(0, 0)  # Marquee mode
        self.ytProgressBar.setVisible(False)
        yt_layout.addWidget(self.ytProgressBar)

        self.lblYtStatus = QLabel("Ready.")
        self.lblYtStatus.setStyleSheet("font-weight: bold; color: #8a94a6;")
        yt_layout.addWidget(self.lblYtStatus)

        layout.addWidget(grp_yt)

        grp_log = QGroupBox("📜 DOWNLOAD CONSOLE OUTPUT")
        log_layout = QVBoxLayout(grp_log)
        self.ytLogEdit = QTextEdit()
        self.ytLogEdit.setReadOnly(True)
        log_layout.addWidget(self.ytLogEdit)
        layout.addWidget(grp_log, stretch=1)

        self.tabs.addTab(tab, "🔻 YouTube Downloader")

    def _build_logs_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.logTextEdit = QTextEdit()
        self.logTextEdit.setReadOnly(True)
        layout.addWidget(self.logTextEdit)

        btnClearLogs = QPushButton("🧹 Bersihkan Log")
        btnClearLogs.setToolTip("Hapus semua log event di tampilan")
        btnClearLogs.clicked.connect(lambda: self.logTextEdit.clear())
        layout.addWidget(btnClearLogs)

        self.tabs.addTab(tab, "📜 Event Logs")

    # ==========================================
    # SLOTS & ACTIONS
    # ==========================================
    def _on_toggle_play(self):
        is_playing = self.track.toggle_play()
        self.btnPlay.setText("▶" if is_playing else "⏸")
        self.btnPlay.setToolTip("Pause" if is_playing else "Play")
        if is_playing:
            self.btnPlay.setStyleSheet("background-color: #00c853; color: #000000;")
        else:
            self.btnPlay.setStyleSheet("background-color: #ff9100; color: #000000;")
        self.log_event(f"Playback toggled: {'PLAYING' if is_playing else 'PAUSED'}")

    def _on_toggle_mute(self):
        is_muted = self.track.toggle_mute()
        if is_muted:
            self.btnMute.setText("🔇")
            self.btnMute.setToolTip("Unmute Suara")
            self.btnMute.setStyleSheet("background-color: #d50000; color: #ffffff;")
        else:
            self.btnMute.setText("🔊")
            self.btnMute.setToolTip("Mute Suara")
            self.btnMute.setStyleSheet("background-color: #37474f; color: #ffffff;")
        self.log_event(f"Audio mute toggled: Muted={is_muted}")

    def _on_next_track(self):
        self.track.next_track()
        self._populate_playlist_table()
        self.log_event("Skipped to next track.")

    def _on_prev_track(self):
        self.track.prev_track()
        self._populate_playlist_table()
        self.log_event("Returned to previous track.")

    def _on_reshuffle(self):
        self.track.reshuffle_remaining()
        self._populate_playlist_table()
        self.log_event("Playlist reshuffled.")

    def _on_rescan_folder(self):
        new_added, total = self.track.refresh_playlist(self.music_dir)
        self._populate_playlist_table()
        self.log_event(f"Folder rescanned: {new_added} new tracks added (Total: {total}).")

    def _copy_hls_url(self):
        url = self.hls_streamer.public_url
        QApplication.clipboard().setText(url)
        self.log_event(f"Copied HLS URL to clipboard: {url}")

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
            status_str = "▶ Playing" if is_current else "Queued"

            item_num = QTableWidgetItem(str(i + 1))
            item_name = QTableWidgetItem(name)
            item_status = QTableWidgetItem(status_str)
            item_path = QTableWidgetItem(path)

            if is_current:
                brush = QtGui.QBrush(QtGui.QColor("#00e676"))
                item_name.setForeground(brush)
                item_status.setForeground(brush)
                item_name.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold))

            self.tablePlaylist.setItem(row, 0, item_num)
            self.tablePlaylist.setItem(row, 1, item_name)
            self.tablePlaylist.setItem(row, 2, item_status)
            self.tablePlaylist.setItem(row, 3, item_path)

    def _filter_playlist(self):
        self._populate_playlist_table()

    def _play_selected_track(self):
        current_row = self.tablePlaylist.currentRow()
        if current_row < 0:
            return
        item_path = self.tablePlaylist.item(current_row, 3)
        if not item_path:
            return
        path = item_path.text()
        if path in self.track.playlist:
            idx = self.track.playlist.index(path)
            self.track.play_track_at_index(idx)
            self._populate_playlist_table()
            self.log_event(f"Playing selected track: {os.path.basename(path)}")

    def _on_table_double_clicked(self, item):
        self._play_selected_track()

    def _start_youtube_download(self):
        url = self.txtYtUrl.text().strip()
        if not url:
            QMessageBox.warning(self, "Warning", "Please enter a valid YouTube URL.")
            return

        if self.download_in_progress:
            QMessageBox.warning(self, "Warning", "A download is already in progress.")
            return

        self.download_in_progress = True
        self.ytProgressBar.setVisible(True)
        self.btnYtDownload.setEnabled(False)
        self.lblYtStatus.setText("⏳ Downloading track from YouTube...")
        self.ytLogEdit.append(f"Starting download: {url}")
        self.log_event(f"YouTube download started: {url}")

        asyncio.create_task(self._async_youtube_download(url))

    async def _async_youtube_download(self, url: str):
        try:
            output_path = await download_youtube_opus(url, output_dir=self.music_dir)
            file_name = os.path.basename(output_path)
            pos = self.track.insert_next_track(output_path)

            self.lblYtStatus.setText(f"✅ Success! Added '{file_name}' as NEXT SONG (#{pos}).")
            self.ytLogEdit.append(f"Successfully saved to {output_path}")
            self.txtYtUrl.clear()
            self._populate_playlist_table()
            self.log_event(f"YouTube download finished: {file_name}")
        except Exception as e:
            self.lblYtStatus.setText(f"❌ Download failed: {e}")
            self.ytLogEdit.append(f"Error: {e}")
            self.log_event(f"YouTube download error: {e}")
        finally:
            self.download_in_progress = False
            self.ytProgressBar.setVisible(False)
            self.btnYtDownload.setEnabled(True)

    # ==========================================
    # STATS REFRESH TIMER SLOT (1 Hz)
    # ==========================================
    def _update_gui_stats(self):
        try:
            status = self.track.get_status()
            pacer_stats = self.track.get_pacer_stats()
            hls_stats = self.hls_streamer.get_hls_stats() if self.hls_streamer else None

            # Now Playing Header
            cur_name = status["track"]
            cur_idx = status["index"]
            total = status["total"]
            self.lblCurrentTrack.setText(f"▶ [{cur_idx}/{total}] {cur_name}")

            elapsed = status.get("track_elapsed_sec", 0.0)
            duration = status.get("track_duration_sec", 0.0)
            dur_str = format_duration(duration) if duration > 0 else "00:00"
            self.lblProgressSec.setText(f"{format_duration(elapsed)} / {dur_str}")

            if duration > 0:
                pct = int((elapsed / duration) * 100)
                self.trackProgressBar.setValue(min(100, max(0, pct)))
            else:
                self.trackProgressBar.setValue(0)

            # WebRTC (WHIP) Badges & Stats
            conn_state = self.whip_client.pc.connectionState if (self.whip_client and self.whip_client.pc) else "closed"
            ice_state = self.whip_client.pc.iceConnectionState if (self.whip_client and self.whip_client.pc) else "closed"

            self.badgeWhip.setText(f"WebRTC: {conn_state.upper()}")
            if conn_state == "connected":
                self.badgeWhip.setStyleSheet("background-color: #1b4d2e; color: #00e676; border: 1px solid #00e676;")
            else:
                self.badgeWhip.setStyleSheet("background-color: #4a1e1e; color: #ff5252; border: 1px solid #ff5252;")

            self.lblWhipState.setText(f"Connection State : {conn_state}")
            self.lblWhipIce.setText(  f"ICE State        : {ice_state}")
            self.lblWhipBitrate.setText(f"Bitrate (Inst)   : {pacer_stats['instant_bitrate_kbps']:.1f} kbps")
            self.lblWhipData.setText(   f"Total Data Sent  : {format_bytes(pacer_stats['total_bytes'])}")

            # HLS Stats
            if hls_stats and hls_stats["is_running"]:
                self.badgeHls.setText("HLS CDN: ACTIVE 🟢")
                self.badgeHls.setStyleSheet("background-color: #1b4d2e; color: #00e676; border: 1px solid #00e676;")
                self.lblHlsState.setText("HLS Engine State : ACTIVE 🟢")
                self.lblHlsData.setText(f"Served Data      : {format_bytes(hls_stats['total_bytes'])} ({hls_stats['http_requests']:,} requests)")
            else:
                self.badgeHls.setText("HLS CDN: OFFLINE 🔴")
                self.badgeHls.setStyleSheet("background-color: #4a1e1e; color: #ff5252; border: 1px solid #ff5252;")
                self.lblHlsState.setText("HLS Engine State : OFFLINE 🔴")

            # Pacer Stats
            self.lblPacerUptime.setText(f"Uptime           : {format_duration(pacer_stats['uptime_sec'])}")
            self.lblPacerFrames.setText(f"Frames (Total)   : {pacer_stats['total_frames']:,} (Audio: {pacer_stats['audio_frames']:,}, Silence: {pacer_stats['silence_frames']:,})")
            self.lblPacerRate.setText(  f"Packet Rate      : {pacer_stats['instant_pps']:.1f} pps")
            self.lblPacerDrift.setText( f"Realtime Drift   : {pacer_stats['instant_drift_ms']:.2f} ms (Avg: {pacer_stats['avg_drift_ms']:.2f} ms)")

        except Exception:
            pass
