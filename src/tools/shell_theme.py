"""调试壳柔暗仪表色板与全局 QSS。"""

from __future__ import annotations

# —— 色板（柔暗仪表 · 海青绿）——
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
ACCENT_ON = "#ffffff"  # 强调底上的字
SUCCESS = "#4caf82"
WARN = "#d4a24c"
DANGER = "#d96b6b"
LOG_BG = "#12151a"
PREVIEW_BG = "#0f1216"
NAV_ACTIVE_BG = "#252b33"


def paint_tone(widget, tone: str) -> None:
    """用动态属性上色。字号留在样式表里，避免 setStyleSheet 把字号盖掉。"""
    if widget.property("tone") == tone:
        return
    widget.setProperty("tone", tone)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


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
        background: transparent;
        border: none;
    }}
    QFrame#statusCard {{
        background: {SURFACE};
        border: 1px solid {BORDER_SOFT};
        border-radius: 10px;
    }}
    QFrame#capabilityCard, QFrame#capabilityHero {{
        background: {SURFACE};
        border: 1px solid {BORDER_SOFT};
        border-radius: 16px;
    }}
    QFrame#capabilityHero {{
        border-radius: 18px;
    }}
    QFrame#capabilityCard[active="true"], QFrame#capabilityHero[active="true"] {{
        border: 1px solid rgba(61, 184, 160, 0.55);
    }}
    QFrame#capabilityCard[live="true"] {{
        border: 2px solid {ACCENT};
        background: {SURFACE_2};
    }}
    QFrame#capabilityCard[flash="true"] {{
        border: 2px solid {ACCENT};
        background: rgba(61, 184, 160, 0.22);
    }}
    QLabel#castBadge {{
        color: {TEXT_FAINT};
        border: 1px solid {BORDER};
        border-radius: 9px;
        padding: 1px 8px;
        font-size: 12px;
        font-weight: 700;
    }}
    QLabel#castBadge[live="true"] {{
        color: {ACCENT_ON};
        background: {ACCENT};
        border-color: {ACCENT};
    }}
    QLabel#castNote {{
        color: {TEXT};
        font-size: 12px;
        font-weight: 700;
    }}
    QFrame#capabilityCard[active="false"] QCheckBox#capSwitch,
    QFrame#capabilityHero[active="false"] QCheckBox#capSwitch {{
        color: {TEXT_MUTED};
    }}
    QCheckBox#capSwitch {{
        background: transparent;
        border: none;
        padding: 0;
        font-size: 14px;
        font-weight: 700;
        spacing: 8px;
    }}
    QCheckBox#capSwitch::indicator {{
        width: 16px;
        height: 16px;
        max-width: 16px;
        max-height: 16px;
        border-radius: 4px;
    }}
    QCheckBox#capSwitch::indicator:checked,
    QCheckBox#capSwitch::indicator:checked:hover {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}
    QLabel#capKey {{
        color: {TEXT_MUTED};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1.6px;
    }}
    QLabel#capValue {{
        color: {TEXT};
        font-size: 32px;
        font-weight: 700;
        letter-spacing: -0.5px;
    }}
    QFrame#capabilityCard[active="false"] QLabel#capValue {{
        color: {TEXT_FAINT};
    }}
    QLabel#heroPos {{
        color: {TEXT};
        font-size: 56px;
        font-weight: 700;
        letter-spacing: -2px;
    }}
    QLabel#heroPos[tone="faint"] {{
        color: {TEXT_FAINT};
    }}
    QLabel#heroPos[tone="warn"] {{
        color: {WARN};
    }}
    QLabel#capAct {{
        color: {TEXT_MUTED};
        font-size: 15px;
        font-weight: 700;
    }}
    QLabel#capAct[tone="hold"] {{
        color: {SUCCESS};
    }}
    QLabel#capAct[tone="release"] {{
        color: {WARN};
    }}
    QLabel#capAct[tone="faint"] {{
        color: {TEXT_FAINT};
    }}
    QLabel#capMeta {{
        color: {TEXT_MUTED};
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#capMeta[tone="faint"] {{
        color: {TEXT_FAINT};
    }}
    QLabel#capMeta[tone="warn"] {{
        color: {WARN};
    }}
    QLabel#capMeta[tone="ok"] {{
        color: {SUCCESS};
    }}
    QLabel#capMeta[tone="accent"] {{
        color: {ACCENT};
    }}
    QLabel#licenseBanner {{
        color: {TEXT_MUTED};
        font-size: 11px;
        font-weight: 600;
        padding: 4px 8px;
        background: rgba(255,255,255,0.03);
        border: 1px solid {BORDER_SOFT};
        border-radius: 4px;
    }}
    QLabel#licenseBanner[warn="true"] {{
        color: {WARN};
        background: rgba(212,162,76,0.08);
        border: 1px solid rgba(212,162,76,0.28);
    }}
    QLabel#licenseBanner[danger="true"] {{
        color: #c48a8a;
        background: rgba(217,107,107,0.06);
        border: 1px solid rgba(217,107,107,0.22);
    }}
    QFrame#metricCell {{
        background: {SURFACE_2};
        border: 1px solid {BORDER_SOFT};
        border-radius: 6px;
    }}
    QLabel#statusCardTitle {{
        color: {TEXT_FAINT};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1px;
    }}
    QLabel#castRemain {{
        font-size: 32px;
        font-weight: 700;
        letter-spacing: -0.5px;
        color: {TEXT};
    }}
    QLabel#castRemain[tone="faint"] {{
        color: {TEXT_FAINT};
    }}
    QLabel#castRemain[tone="live"] {{
        color: {ACCENT};
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
    QToolButton#logToggle {{
        background: transparent;
        border: none;
        color: {TEXT_MUTED};
        font-weight: 600;
        font-size: 12px;
        padding: 2px 0;
        text-align: left;
    }}
    QToolButton#logToggle:hover {{
        color: {TEXT};
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
    QPushButton#btnFloat {{
        background-color: {ACCENT};
        color: {ACCENT_ON};
        border: 1px solid {ACCENT};
        border-radius: 6px;
        padding: 5px 12px;
        font-size: 11px;
        font-weight: 700;
        min-height: 18px;
    }}
    QPushButton#btnFloat:hover {{
        background-color: #4ac9b0;
        border-color: #4ac9b0;
        color: {ACCENT_ON};
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
        font-size: 10px;
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
