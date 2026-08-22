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

/* ── VU Meter Progress Bar ── */
QProgressBar#vuMeter {
    border: none;
    border-radius: 3px;
    background-color: #1e2230;
    color: transparent;
    max-height: 8px;
    min-height: 8px;
}
QProgressBar#vuMeter::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #22c55e, stop:0.7 #eab308, stop:1.0 #ef4444);
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

/* ── Mode Switch Segmented Buttons ── */
QPushButton#btnModeMusic, QPushButton#btnModeMic {
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 700;
    font-size: 12px;
}

/* ── Play Button ── */
QPushButton#btnPlay {
    background-color: #6366f1;
    color: #ffffff;
    font-size: 12px;
    font-weight: 700;
    min-width: 56px; max-width: 56px;
    min-height: 30px; max-height: 30px;
    border-radius: 6px;
    border: none;
}
QPushButton#btnPlay:hover {
    background-color: #818cf8;
}

/* ── Input & ComboBox ── */
QLineEdit, QComboBox {
    background-color: #14161e;
    border: 1px solid #262a35;
    border-radius: 8px;
    padding: 6px 10px;
    color: #e5e7eb;
    selection-background-color: #6366f1;
}
QLineEdit:focus, QComboBox:focus {
    border-color: #6366f1;
}
QComboBox {
    padding-right: 20px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: none;
}
QComboBox QAbstractItemView {
    background-color: #191c24;
    border: 1px solid #2d3240;
    selection-background-color: #4f46e5;
    selection-color: #ffffff;
    color: #d1d5db;
    outline: 0;
    padding: 4px;
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

/* ── Context Menu ── */
QMenu {
    background-color: #191c24;
    border: 1px solid #2d3240;
    border-radius: 8px;
    padding: 6px;
    color: #e5e7eb;
}
QMenu::item {
    padding: 6px 22px 6px 10px;
    border-radius: 6px;
    font-size: 12px;
}
QMenu::item:selected {
    background-color: #4f46e5;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #4b5563;
}
QMenu::separator {
    height: 1px;
    background-color: #262a35;
    margin: 4px 6px;
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
