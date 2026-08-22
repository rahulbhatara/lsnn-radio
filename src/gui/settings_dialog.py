import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QFileDialog, QFrame, QWidget,
    QFormLayout, QMessageBox
)
from ..config import AppConfig

class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Settings")
        self.resize(520, 480)
        self.setModal(True)
        self._init_ui()
        self._load_values()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        lbl_title = QLabel("Application Settings")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f3f4f6;")
        layout.addWidget(lbl_title)

        # ── Section 1: Music Library ────────────────────────────────
        sec_lib = QLabel("MUSIC LIBRARY")
        sec_lib.setStyleSheet("font-size: 11px; font-weight: 700; color: #6b7280; letter-spacing: 0.5px;")
        layout.addWidget(sec_lib)

        row_dir = QHBoxLayout()
        row_dir.setSpacing(8)
        self.txtMusicDir = QLineEdit()
        self.txtMusicDir.setPlaceholderText("Path to music directory...")
        row_dir.addWidget(self.txtMusicDir, stretch=1)

        btnBrowseDir = QPushButton("Browse...")
        btnBrowseDir.clicked.connect(self._browse_music_dir)
        row_dir.addWidget(btnBrowseDir)
        layout.addLayout(row_dir)

        # ── Section 2: WebRTC / WHIP Streaming ──────────────────────
        sec_whip = QLabel("WEBRTC / WHIP INGEST")
        sec_whip.setStyleSheet("font-size: 11px; font-weight: 700; color: #6b7280; letter-spacing: 0.5px; margin-top: 6px;")
        layout.addWidget(sec_whip)

        self.txtWhipUrl = QLineEdit()
        self.txtWhipUrl.setPlaceholderText("https://cn1.meshcast.io/whip/YOUR_CHANNEL")
        layout.addWidget(self.txtWhipUrl)

        # ── Section 3: HLS Server & Cloudflare Tunnel ───────────────
        sec_hls = QLabel("HLS SERVER & CLOUDFLARE TUNNEL")
        sec_hls.setStyleSheet("font-size: 11px; font-weight: 700; color: #6b7280; letter-spacing: 0.5px; margin-top: 6px;")
        layout.addWidget(sec_hls)

        form_hls = QFormLayout()
        form_hls.setSpacing(8)

        self.comboTunnelMode = QComboBox()
        self.comboTunnelMode.addItem("Quick Tunnel (Auto trycloudflare.com)", "quick")
        self.comboTunnelMode.addItem("Custom Tunnel (Named Cloudflare Tunnel)", "custom")
        self.comboTunnelMode.addItem("Local Only (No Tunnel)", "none")
        self.comboTunnelMode.currentIndexChanged.connect(self._on_tunnel_mode_changed)
        form_hls.addRow("Tunnel Mode:", self.comboTunnelMode)

        self.txtHlsPort = QLineEdit()
        self.txtHlsPort.setPlaceholderText("8000")
        form_hls.addRow("Local Port:", self.txtHlsPort)

        self.txtPublicUrl = QLineEdit()
        self.txtPublicUrl.setPlaceholderText("https://radio.samf.fun/live.m3u8")
        form_hls.addRow("Public CDN URL:", self.txtPublicUrl)

        layout.addLayout(form_hls)

        # Custom tunnel sub-panel
        self.customTunnelWidget = QWidget()
        form_custom = QFormLayout(self.customTunnelWidget)
        form_custom.setContentsMargins(0, 0, 0, 0)
        form_custom.setSpacing(8)

        row_cfg = QHBoxLayout()
        self.txtCustomConfig = QLineEdit()
        self.txtCustomConfig.setPlaceholderText("~/.cloudflared/config.yml")
        row_cfg.addWidget(self.txtCustomConfig, stretch=1)
        btnBrowseCfg = QPushButton("Browse...")
        btnBrowseCfg.clicked.connect(self._browse_custom_config)
        row_cfg.addWidget(btnBrowseCfg)
        form_custom.addRow("Config File:", row_cfg)

        self.txtTunnelId = QLineEdit()
        self.txtTunnelId.setPlaceholderText("Tunnel ID or name (optional)")
        form_custom.addRow("Tunnel ID:", self.txtTunnelId)

        layout.addWidget(self.customTunnelWidget)

        layout.addStretch()

        # ── Buttons ─────────────────────────────────────────────────
        row_btns = QHBoxLayout()
        row_btns.setSpacing(10)
        row_btns.addStretch()

        btnCancel = QPushButton("Cancel")
        btnCancel.clicked.connect(self.reject)
        row_btns.addWidget(btnCancel)

        btnSave = QPushButton("Save & Apply")
        btnSave.setStyleSheet("background-color: #4f46e5; color: #ffffff; border-color: #6366f1; font-weight: 700; padding: 7px 16px;")
        btnSave.clicked.connect(self._save_and_close)
        row_btns.addWidget(btnSave)

        layout.addLayout(row_btns)

    def _load_values(self):
        self.txtMusicDir.setText(self.config.music_dir)
        self.txtWhipUrl.setText(self.config.whip_url)
        self.txtHlsPort.setText(str(self.config.hls_port))
        self.txtPublicUrl.setText(self.config.public_hls_url)

        # Tunnel mode
        idx = self.comboTunnelMode.findData(self.config.tunnel_mode)
        if idx >= 0:
            self.comboTunnelMode.setCurrentIndex(idx)
        else:
            self.comboTunnelMode.setCurrentIndex(0)

        self.txtCustomConfig.setText(self.config.cloudflared_config_path)
        self.txtTunnelId.setText(self.config.cloudflared_tunnel_id)
        self._on_tunnel_mode_changed()

    def _on_tunnel_mode_changed(self):
        mode = self.comboTunnelMode.currentData()
        self.customTunnelWidget.setVisible(mode == "custom")
        if mode == "quick":
            self.txtPublicUrl.setEnabled(False)
            self.txtPublicUrl.setPlaceholderText("Auto-generated when tunnel starts")
        else:
            self.txtPublicUrl.setEnabled(True)

    def _browse_music_dir(self):
        cur = self.txtMusicDir.text().strip() or os.path.abspath(".")
        folder = QFileDialog.getExistingDirectory(self, "Select Music Directory", cur)
        if folder:
            self.txtMusicDir.setText(folder)

    def _browse_custom_config(self):
        cur = self.txtCustomConfig.text().strip() or os.path.expanduser("~/.cloudflared")
        fpath, _ = QFileDialog.getOpenFileName(self, "Select Cloudflared Config", cur, "YAML Files (*.yml *.yaml);;All Files (*.*)")
        if fpath:
            self.txtCustomConfig.setText(fpath)

    def _save_and_close(self):
        port_str = self.txtHlsPort.text().strip()
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValueError()
        except ValueError:
            QMessageBox.warning(self, "Invalid Port", "Please enter a valid port number between 1 and 65535.")
            return

        self.config.music_dir = self.txtMusicDir.text().strip() or ".."
        self.config.whip_url = self.txtWhipUrl.text().strip() or "https://cn1.meshcast.io/whip/lsnn_radio"
        self.config.hls_port = port
        self.config.tunnel_mode = self.comboTunnelMode.currentData()
        self.config.public_hls_url = self.txtPublicUrl.text().strip() or "https://radio.samf.fun/live.m3u8"
        self.config.cloudflared_config_path = self.txtCustomConfig.text().strip()
        self.config.cloudflared_tunnel_id = self.txtTunnelId.text().strip()

        self.config.save()
        self.accept()
