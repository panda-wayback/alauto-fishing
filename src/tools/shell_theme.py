"""调试壳柔暗仪表色板与全局 QSS。"""

from __future__ import annotations

# —— 色板（柔暗仪表）——
BG = "#16191e"
SURFACE = "#1e2329"
SURFACE_2 = "#262c34"
BORDER = "#3a424c"
BORDER_SOFT = "#2e353e"
TEXT = "#e6e8eb"
TEXT_MUTED = "#9aa3ad"
TEXT_FAINT = "#6b7380"
ACCENT = "#3db8a0"
ACCENT_DIM = "#2a7d6c"
ACCENT_ON = "#ffffff"  # 强调底上的字（禁止再用深色字）
SUCCESS = "#4caf82"
WARN = "#d4a24c"
DANGER = "#d96b6b"
LOG_BG = "#12151a"
PREVIEW_BG = "#0f1216"
NAV_ACTIVE_BG = "#252b33"


def global_qss() -> str:
    return f"""
    QMainWindow, QWidget {{
        background: {BG};
        color: {TEXT};
    }}
    QGroupBox {{
        font-weight: 600;
        border: 1px solid {BORDER_SOFT};
        border-radius: 8px;
        margin-top: 10px;
        padding: 10px 8px 8px 8px;
        background: {SURFACE};
        color: {TEXT};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: {TEXT_MUTED};
    }}
    QFrame#readout {{
        background: {SURFACE};
        border: 1px solid {BORDER_SOFT};
        border-radius: 8px;
    }}
    QPlainTextEdit {{
        background: {LOG_BG};
        color: {TEXT_MUTED};
        border: 1px solid {BORDER_SOFT};
        border-radius: 8px;
        padding: 8px;
        font-family: "SF Mono", "Menlo", "Consolas", "Courier New", monospace;
        font-size: 11px;
        selection-background-color: {ACCENT_DIM};
        selection-color: {TEXT};
    }}
    QPlainTextEdit#mainLog, QPlainTextEdit#calLog {{
        background: {LOG_BG};
        color: {TEXT};
        border: 1px solid {BORDER_SOFT};
        border-left: 2px solid {ACCENT_DIM};
    }}
    QPushButton {{
        background: {SURFACE_2};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 12px;
        min-height: 22px;
    }}
    QPushButton:hover {{
        background: {BORDER_SOFT};
        border-color: {TEXT_FAINT};
    }}
    QPushButton:pressed {{
        background: {BORDER};
    }}
    QPushButton:disabled {{
        color: {TEXT_FAINT};
        background: {SURFACE};
        border-color: {BORDER_SOFT};
    }}
    QPushButton#btnPrimary {{
        background-color: {ACCENT};
        color: {ACCENT_ON};
        border: 1px solid {ACCENT};
        font-weight: 600;
    }}
    QPushButton#btnPrimary:hover {{
        background-color: #4ac9b0;
        color: {ACCENT_ON};
        border-color: #4ac9b0;
    }}
    QPushButton#btnPrimary:pressed {{
        background-color: {ACCENT_DIM};
        color: {ACCENT_ON};
        border-color: {ACCENT_DIM};
    }}
    QPushButton#btnPrimary:disabled,
    QPushButton#btnPrimary:!enabled {{
        background-color: {SURFACE_2};
        color: {TEXT_FAINT};
        border: 1px solid {BORDER_SOFT};
        font-weight: 600;
    }}
    QPushButton#btnGhost {{
        background-color: transparent;
        border: 1px solid {BORDER_SOFT};
        color: {TEXT_MUTED};
    }}
    QPushButton#btnGhost:hover {{
        color: {TEXT};
        border-color: {BORDER};
        background-color: {SURFACE_2};
    }}
    QPushButton#btnGhost:disabled,
    QPushButton#btnGhost:!enabled {{
        color: {TEXT_FAINT};
        border-color: {BORDER_SOFT};
        background-color: transparent;
    }}
    QPushButton#navBtn {{
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0;
        color: {TEXT_FAINT};
        padding: 8px 8px 10px 8px;
        min-height: 18px;
        font-size: 12px;
    }}
    QPushButton#navBtn:hover {{
        color: {TEXT_MUTED};
        background: {SURFACE};
    }}
    QPushButton#navBtn:checked {{
        color: {TEXT};
        border-bottom: 2px solid {ACCENT};
        background: {NAV_ACTIVE_BG};
        font-weight: 600;
    }}
    QCheckBox {{
        color: {TEXT};
        spacing: 10px;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        max-width: 18px;
        max-height: 18px;
        border: 1.5px solid {TEXT_FAINT};
        border-radius: 4px;
        background: {SURFACE_2};
    }}
    QCheckBox::indicator:hover {{
        border-color: {ACCENT};
    }}
    QCheckBox::indicator:checked,
    QCheckBox::indicator:checked:hover,
    QCheckBox::indicator:checked:pressed,
    QCheckBox::indicator:checked:disabled,
    QCheckBox:!active::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}
    QCheckBox#switchRow {{
        background: {SURFACE};
        border: 1px solid {BORDER_SOFT};
        border-radius: 8px;
        padding: 12px 14px;
        font-size: 14px;
        font-weight: 600;
    }}
    QCheckBox#switchRow:checked {{
        border-color: {ACCENT_DIM};
        background: {SURFACE_2};
    }}
    QLabel {{
        color: {TEXT};
        background: transparent;
    }}
    QLabel#sectionTitle {{
        color: {TEXT_MUTED};
        font-weight: 600;
        font-size: 12px;
    }}
    QLabel#hint {{
        color: {TEXT_FAINT};
        font-size: 11px;
    }}
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: {BORDER};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
        background: {ACCENT};
        border: none;
    }}
    QSlider::sub-page:horizontal {{
        background: {ACCENT_DIM};
        border-radius: 2px;
    }}
    QComboBox {{
        background: {SURFACE_2};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 4px 8px;
        min-height: 24px;
    }}
    QComboBox:hover {{
        border-color: {TEXT_FAINT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT_DIM};
        selection-color: {TEXT};
    }}
    QSplitter::handle {{
        background: {BORDER_SOFT};
        height: 2px;
    }}
    QListWidget, QTreeWidget, QTableWidget {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER_SOFT};
        border-radius: 6px;
        outline: none;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {ACCENT_DIM};
        color: {TEXT};
    }}
    QMessageBox {{
        background: {SURFACE};
        color: {TEXT};
    }}
    QToolTip {{
        background: {SURFACE_2};
        color: {TEXT};
        border: 1px solid {BORDER};
        padding: 4px 8px;
    }}
    """


def preview_canvas_qss() -> str:
    return (
        f"background:{PREVIEW_BG}; color:{TEXT_MUTED}; "
        f"border:1px solid {BORDER_SOFT}; border-radius:8px;"
    )
