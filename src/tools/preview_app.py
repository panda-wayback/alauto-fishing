"""调试壳（PySide6）：监控 / 策略 / 操作勾选；模拟器手玩嵌窗；无快捷键。"""

from __future__ import annotations

import os
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

# 模拟器离屏渲染，避免与 Qt 抢显示
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap, QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import pygame

from sim import config as sim_config
from sim.game import FishingGame, State
from ui.render import Renderer
from autofish.act.mouse import os_left_down
from autofish.detect.api import get_detector
from autofish.detect.bobber import BobberHit
from autofish.capture.screen import (
    DEFAULT_SCREEN_PATH,
    ScreenGrab,
    grab_primary,
    load_screen,
    save_screen,
)
from autofish.locate.roi import DEFAULT_ROI_PATH, Roi, load_roi, save_roi
from autofish.pipeline import AutofishPipeline
from autofish.topics import (
    ActionIntentEvent,
    FishingState,
    FrameEvent,
    PosEvent,
    PressIntervalEvent,
    Topic,
)
from common import permissions as perms
from tools.dual_range_axis import DualRangeAxis

IDLE = "idle"
SELECT = "select"
READY = "ready"


def _rgb_to_pixmap(rgb: np.ndarray) -> QPixmap:
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    h, w = rgb.shape[:2]
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


def _draw_rect(
    rgb: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    color: tuple[int, int, int],
    thickness: int = 1,
) -> None:
    fh, fw = rgb.shape[:2]
    x0 = max(0, min(fw - 1, x))
    y0 = max(0, min(fh - 1, y))
    x1 = max(0, min(fw - 1, x + max(w, 1) - 1))
    y1 = max(0, min(fh - 1, y + max(h, 1) - 1))
    if x1 <= x0 or y1 <= y0:
        return
    t = max(1, thickness)
    rgb[y0 : y0 + t, x0 : x1 + 1] = color
    rgb[y1 - t + 1 : y1 + 1, x0 : x1 + 1] = color
    rgb[y0 : y1 + 1, x0 : x0 + t] = color
    rgb[y0 : y1 + 1, x1 - t + 1 : x1 + 1] = color


def _overlay_hit(rgb: np.ndarray, hit: BobberHit | None) -> np.ndarray:
    """叠层：Pos 范围框 + 命中点。无 hit 时不在 UI 线程再跑 find_bar。"""
    if hit is None:
        return rgb
    if hit.bar_width <= 0:
        return rgb
    vis = rgb.copy()
    zx, zy = int(hit.bar_left), int(hit.bar_top)
    zw, zh = int(hit.bar_width), int(hit.bar_height)
    fh, fw = vis.shape[:2]
    _draw_rect(vis, zx, zy, zw, zh, (0, 230, 120), thickness=2)
    y0 = max(0, zy - max(6, zh // 2))
    y1 = min(fh, zy + zh + 2)
    x0, x1 = max(0, zx), min(fw, zx + zw)
    _draw_rect(vis, x0, y0, x1 - x0, y1 - y0, (255, 200, 40), thickness=1)
    mid_y0 = zy
    mid_y1 = min(fh - 1, zy + max(zh, 1) - 1)
    if 0 <= zx < fw:
        vis[mid_y0 : mid_y1 + 1, zx] = (0, 255, 180)
    right = min(fw - 1, zx + max(zw, 1) - 1)
    if 0 <= right < fw:
        vis[mid_y0 : mid_y1 + 1, right] = (0, 255, 180)
    x, y = int(hit.x), int(hit.y)
    vis[max(0, y - 4) : y + 5, max(0, x - 4) : x + 5] = (0, 210, 230)
    return vis


class BusBridge(QObject):
    """后台线程 → UI 线程。"""

    frame = Signal(object)
    pos = Signal(object)
    intent = Signal(object)


class ImageCanvas(QLabel):
    """显示 RGB；框选模式下拖拽出 ROI。"""

    selection_changed = Signal()

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self.setMinimumSize(320, 200)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#1c1e22; color:#888; border:1px solid #373a40;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._rgb: np.ndarray | None = None
        self._pixmap = QPixmap()
        self._selecting = False
        self._drag_start: QPoint | None = None
        self._drag_end: QPoint | None = None
        self._scale = 1.0
        self._offset = QPoint(0, 0)
        self.setText(title)

    def set_rgb(self, rgb: np.ndarray | None) -> None:
        self._rgb = None if rgb is None else np.ascontiguousarray(rgb)
        self._rebuild()

    def set_selecting(self, on: bool) -> None:
        self._selecting = on
        if not on:
            self._drag_start = self._drag_end = None
        self.update()

    def selection_in_image(self) -> tuple[int, int, int, int] | None:
        """返回图像坐标 (left, top, width, height)。"""
        if self._rgb is None or self._drag_start is None or self._drag_end is None:
            return None
        a = self._widget_to_image(self._drag_start)
        b = self._widget_to_image(self._drag_end)
        if a is None or b is None:
            return None
        x0, y0 = min(a[0], b[0]), min(a[1], b[1])
        x1, y1 = max(a[0], b[0]), max(a[1], b[1])
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        return x0, y0, x1 - x0, y1 - y0

    def _rebuild(self) -> None:
        if self._rgb is None:
            self._pixmap = QPixmap()
            self.setText(self._title)
            return
        self.setText("")
        self._pixmap = _rgb_to_pixmap(self._rgb)
        self._layout_pixmap()
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._pixmap.isNull():
            self._layout_pixmap()

    def _layout_pixmap(self) -> None:
        if self._pixmap.isNull():
            return
        pw, ph = self._pixmap.width(), self._pixmap.height()
        cw, ch = max(1, self.width()), max(1, self.height())
        self._scale = min(cw / pw, ch / ph, 1.0)
        nw, nh = max(1, int(pw * self._scale)), max(1, int(ph * self._scale))
        self._offset = QPoint((cw - nw) // 2, (ch - nh) // 2)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._pixmap.isNull():
            return
        p = QPainter(self)
        nw = max(1, int(self._pixmap.width() * self._scale))
        nh = max(1, int(self._pixmap.height() * self._scale))
        target = QRect(self._offset.x(), self._offset.y(), nw, nh)
        p.drawPixmap(target, self._pixmap)
        if self._selecting and self._drag_start and self._drag_end:
            pen = QPen(QColor(70, 160, 230), 2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRect(QRect(self._drag_start, self._drag_end).normalized())
        p.end()

    def _widget_to_image(self, pos: QPoint) -> tuple[int, int] | None:
        if self._rgb is None or self._scale <= 0:
            return None
        x = int((pos.x() - self._offset.x()) / self._scale)
        y = int((pos.y() - self._offset.y()) / self._scale)
        h, w = self._rgb.shape[:2]
        if x < 0 or y < 0 or x >= w or y >= h:
            return None
        return x, y

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._selecting and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = self._drag_end = event.position().toPoint()
            self.update()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._selecting and self._drag_start is not None:
            self._drag_end = event.position().toPoint()
            self.update()
            self.selection_changed.emit()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._selecting and event.button() == Qt.MouseButton.LeftButton:
            self._drag_end = event.position().toPoint()
            self.update()
            self.selection_changed.emit()
        else:
            super().mouseReleaseEvent(event)


class SimCanvas(QLabel):
    """模拟器画面；仅 PLAYING 时出图；按下开始/拉杆。"""

    press = Signal()
    release = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 200)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#1c1e22; color:#888; border:1px solid #373a40;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._last_rgb: np.ndarray | None = None
        self._accept_input = True
        self.show_idle("点击开始手玩")

    def set_accept_input(self, ok: bool) -> None:
        self._accept_input = ok

    def show_idle(self, text: str = "点击开始手玩") -> None:
        self._last_rgb = None
        self.setPixmap(QPixmap())
        self.setText(text)

    def set_rgb(self, rgb: np.ndarray) -> None:
        self._last_rgb = rgb
        self.setText("")
        pm = _rgb_to_pixmap(rgb)
        self.setPixmap(
            pm.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._last_rgb is not None:
            self.set_rgb(self._last_rgb)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (
            self._accept_input
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.press.emit()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.release.emit()
        else:
            super().mouseReleaseEvent(event)


def _hold_word(on: bool | None) -> str:
    if on is None:
        return "—"
    return "按下" if on else "松开"


class PreviewApp(QMainWindow):
    def __init__(self, roi_path: Path = DEFAULT_ROI_PATH) -> None:
        super().__init__()
        self.setWindowTitle("Albion 拉鱼 · 调试壳 (PySide6)")
        self.resize(1280, 760)

        self.roi_path = roi_path
        self.roi: Roi | None = None
        self.hit: BobberHit | None = None
        self.frame: np.ndarray | None = None
        self.phase = IDLE
        self.screen_grab: ScreenGrab | None = None
        self._pipe: AutofishPipeline | None = None
        self._holding: bool | None = None
        self._intent_reason = ""
        self._last_detect_ms: float = 0.0
        self._ms_window: deque[float] = deque(maxlen=60)
        self._ms_log_ts: float = 0.0
        self._mon_ui_ts: float = 0.0
        self._mon_ui_min_dt: float = 1.0 / 15.0  # 预览最多 ~15fps，避免 Windows 卡死
        self._mouse_mismatch_logged = False
        self._logs: deque[str] = deque(maxlen=80)
        self._bridge = BusBridge()
        self._bridge.frame.connect(self._on_frame_ui)
        self._bridge.pos.connect(self._on_pos_ui)
        self._bridge.intent.connect(self._on_intent_ui)

        pygame.init()
        pygame.display.set_mode((1, 1))
        self.game = FishingGame()
        self._sim_buf = pygame.Surface(
            (sim_config.WINDOW_WIDTH, sim_config.WINDOW_HEIGHT)
        ).convert()
        self._sim_renderer = Renderer(self._sim_buf)
        self._sim_holding = False

        self._build_ui()
        self._reload_roi()
        self._sync_buttons()
        # 策略 / 操作默认开启
        self.chk_decide.setChecked(True)
        self.chk_act.setChecked(True)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(int(1000 / max(1, sim_config.FPS)))

        self._perm_timer = QTimer(self)
        self._perm_timer.timeout.connect(self._refresh_permissions)
        self._perm_timer.start(2000)
        self._refresh_permissions()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        # —— 权限：macOS 隐私 / Windows 截屏探测+管理员 ——
        perm = QGroupBox("权限")
        perm_l = QHBoxLayout(perm)
        self.lbl_perm_screen = QLabel("屏幕…")
        self.lbl_perm_screen.setMinimumWidth(140)
        perm_l.addWidget(self.lbl_perm_screen)
        self.btn_perm_screen = QPushButton("授权屏幕")
        self.btn_perm_screen.clicked.connect(self._on_perm_screen)
        perm_l.addWidget(self.btn_perm_screen)
        self.lbl_perm_input = QLabel("控鼠…")
        self.lbl_perm_input.setMinimumWidth(180)
        perm_l.addWidget(self.lbl_perm_input)
        self.btn_perm_input = QPushButton("授权控鼠")
        self.btn_perm_input.clicked.connect(self._on_perm_input)
        perm_l.addWidget(self.btn_perm_input)
        self.btn_perm_refresh = QPushButton("刷新")
        self.btn_perm_refresh.clicked.connect(self._refresh_permissions)
        perm_l.addWidget(self.btn_perm_refresh)
        perm_l.addStretch(1)
        layout.addWidget(perm)

        # —— 感知：POS + 监控 + 框选 ——
        sense = QGroupBox("感知")
        sense_l = QHBoxLayout(sense)
        self.lbl_pos = QLabel("无漂")
        self.lbl_pos.setStyleSheet("font-size:28px; font-weight:600; color:#d24e46;")
        self.lbl_pos.setMinimumWidth(100)
        sense_l.addWidget(QLabel("POS"))
        sense_l.addWidget(self.lbl_pos)
        self.chk_monitor = QCheckBox("监控")
        self.chk_monitor.toggled.connect(self._on_monitor_toggled)
        sense_l.addWidget(self.chk_monitor)
        sense_l.addStretch(1)
        self.btn_capture = QPushButton("截屏框选")
        self.btn_rebox = QPushButton("重框")
        self.btn_confirm = QPushButton("确认框选")
        self.btn_cancel = QPushButton("取消框选")
        self.btn_capture.clicked.connect(self._capture_fullscreen)
        self.btn_rebox.clicked.connect(self._load_screen_for_select)
        self.btn_confirm.clicked.connect(self._confirm_selection)
        self.btn_cancel.clicked.connect(self._cancel_selection)
        for b in (self.btn_capture, self.btn_rebox, self.btn_confirm, self.btn_cancel):
            sense_l.addWidget(b)
        layout.addWidget(sense)

        # —— 策略：范围抽样阈值 + 实时意图 ——
        strat = QGroupBox("策略（只决策，不点鼠标）")
        strat_l = QVBoxLayout(strat)
        row1 = QHBoxLayout()
        self.chk_decide = QCheckBox("启用策略")
        self.chk_decide.toggled.connect(self._on_decide_toggled)
        row1.addWidget(self.chk_decide)
        self.btn_apply_policy = QPushButton("应用")
        self.btn_apply_policy.clicked.connect(self._apply_policy)
        row1.addWidget(self.btn_apply_policy)
        row1.addWidget(QLabel("拖动数轴调范围 · 两段不重叠且间隔≥1 · 精度0.1 · 切换后重抽"))
        row1.addStretch(1)
        strat_l.addLayout(row1)
        self.range_axis = DualRangeAxis(
            press=(70.6, 74.4), release=(76.6, 79.2), min_gap=1.0
        )
        strat_l.addWidget(self.range_axis)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("实时输出："))
        self.lbl_intent = QLabel("未启用")
        self.lbl_intent.setStyleSheet("font-size:18px; font-weight:600; color:#787c80;")
        self.lbl_intent.setMinimumWidth(160)
        row2.addWidget(self.lbl_intent)
        self.lbl_strat_detail = QLabel("")
        self.lbl_strat_detail.setStyleSheet("color:#787c80;")
        row2.addWidget(self.lbl_strat_detail, 1)
        self.lbl_perf = QLabel("")
        self.lbl_perf.setStyleSheet("color:#787c80;")
        self.lbl_perf.setMinimumWidth(90)
        row2.addWidget(self.lbl_perf)
        strat_l.addLayout(row2)
        layout.addWidget(strat)

        # —— 操作：执行策略 → 真鼠标 ——
        act = QGroupBox("操作（执行策略：控制鼠标）")
        act_l = QVBoxLayout(act)
        row_act = QHBoxLayout()
        self.chk_act = QCheckBox("启用操作")
        self.chk_act.setToolTip("勾选后按策略意图对当前光标按下/松开左键")
        self.chk_act.toggled.connect(self._on_act_toggled)
        row_act.addWidget(self.chk_act)
        row_act.addWidget(QLabel("实时："))
        self.lbl_mouse = QLabel("…")
        self.lbl_mouse.setStyleSheet("font-size:16px; font-weight:600; color:#787c80;")
        self.lbl_mouse.setMinimumWidth(420)
        row_act.addWidget(self.lbl_mouse, 1)
        row_act.addWidget(QLabel("（光标请放在游戏窗口上）"))
        act_l.addLayout(row_act)
        row_gap = QHBoxLayout()
        row_gap.addWidget(QLabel("按下间隔"))
        self.sld_press_interval = QSlider(Qt.Orientation.Horizontal)
        self.sld_press_interval.setRange(0, 300)  # 0～0.3s，毫秒
        self.sld_press_interval.setSingleStep(10)
        self.sld_press_interval.setPageStep(50)
        self.sld_press_interval.setValue(20)
        self.sld_press_interval.setToolTip("两次程序按下的最短间隔；松开立刻")
        self.sld_press_interval.valueChanged.connect(self._on_press_interval_changed)
        self.sld_press_interval.sliderReleased.connect(self._on_press_interval_released)
        row_gap.addWidget(self.sld_press_interval, 1)
        self.lbl_press_interval = QLabel("0.02s")
        self.lbl_press_interval.setMinimumWidth(48)
        row_gap.addWidget(self.lbl_press_interval)
        row_gap.addWidget(QLabel("（0～0.3s）"))
        act_l.addLayout(row_gap)
        self.lbl_mouse_diag = QLabel("")
        self.lbl_mouse_diag.setStyleSheet("color:#787c80;")
        act_l.addWidget(self.lbl_mouse_diag)
        layout.addWidget(act)

        # —— 中栏：监控 | 模拟 ——
        mid = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("MONITOR"))
        self.monitor = ImageCanvas("MONITOR · 等待截屏/监控")
        left.addWidget(self.monitor, 1)
        mid.addLayout(left, 1)

        right = QVBoxLayout()
        sim_bar = QHBoxLayout()
        sim_bar.addWidget(QLabel("SIMULATOR · 手玩（点按才出画面）"))
        self.lbl_sim_pos = QLabel("—")
        self.lbl_sim_pos.setStyleSheet("color:#48b46e; font-weight:600;")
        sim_bar.addWidget(self.lbl_sim_pos)
        self.cmb_tier = QComboBox()
        for t in range(1, 9):
            self.cmb_tier.addItem(f"T{t}", t)
        self.cmb_tier.setCurrentIndex(3)
        self.cmb_tier.currentIndexChanged.connect(self._on_tier_changed)
        sim_bar.addWidget(self.cmb_tier)
        self.btn_sim_reset = QPushButton("关局")
        self.btn_sim_reset.clicked.connect(self._sim_reset)
        self.btn_sim_reset.setToolTip("结束手玩并关闭画面（操作启用时建议关掉手玩）")
        sim_bar.addWidget(self.btn_sim_reset)
        right.addLayout(sim_bar)
        self.sim = SimCanvas()
        self.sim.press.connect(self._sim_press)
        self.sim.release.connect(self._sim_release)
        right.addWidget(self.sim, 1)
        mid.addLayout(right, 1)
        layout.addLayout(mid, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        self.log.setStyleSheet("background:#101114; color:#dcdeda;")
        layout.addWidget(self.log)

        self.lbl_hint = QLabel("截屏框选 → 确认（自动监控）→ 策略 → 操作")
        self.lbl_hint.setStyleSheet("color:#787c80;")
        layout.addWidget(self.lbl_hint)

    def _log(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')}  {msg}"
        self._logs.appendleft(line)
        self.log.setPlainText("\n".join(self._logs))

    @staticmethod
    def _perm_style(ok: bool | None) -> str:
        if ok is True:
            return "color:#48b46e; font-weight:600;"
        if ok is False:
            return "color:#d24e46; font-weight:600;"
        return "color:#787c80;"

    def _refresh_permissions(self) -> None:
        st = perms.current_status()
        self.lbl_perm_screen.setText(st.screen_label)
        self.lbl_perm_screen.setStyleSheet(self._perm_style(st.screen_ok))
        self.lbl_perm_input.setText(st.input_label)
        # Windows 非管理员标黄提示，不算硬失败
        if st.platform == "win32" and st.is_admin is False:
            self.lbl_perm_input.setStyleSheet("color:#c9a227; font-weight:600;")
        else:
            self.lbl_perm_input.setStyleSheet(self._perm_style(st.input_ok))
        if st.platform == "darwin":
            self.btn_perm_screen.setText("授权屏幕录制")
            self.btn_perm_input.setText("授权辅助功能")
            self.btn_perm_input.setEnabled(True)
        elif st.platform == "win32":
            self.btn_perm_screen.setText("测试截屏")
            if st.is_admin:
                self.btn_perm_input.setText("已是管理员")
                self.btn_perm_input.setEnabled(False)
            else:
                self.btn_perm_input.setText("以管理员重启")
                self.btn_perm_input.setEnabled(True)
        else:
            self.btn_perm_screen.setText("屏幕")
            self.btn_perm_input.setText("控鼠")

    def _on_perm_screen(self) -> None:
        msg = perms.request_screen_access()
        self._log(msg)
        self.lbl_hint.setText(msg)
        self._refresh_permissions()

    def _on_perm_input(self) -> None:
        was_admin = perms.current_status().is_admin
        msg = perms.request_input_access()
        self._log(msg)
        self.lbl_hint.setText(msg)
        self._refresh_permissions()
        # Windows 提权重启成功：退出本进程，避免双开
        if (
            sys.platform == "win32"
            and was_admin is False
            and "重新启动" in msg
            and "失败" not in msg
        ):
            QApplication.instance().quit()

    def _reload_roi(self) -> None:
        try:
            self.roi = load_roi(self.roi_path) if self.roi_path.exists() else None
            if self.roi is not None:
                self.phase = READY
                self.lbl_hint.setText("ROI 已载入 · 可勾选监控")
                self._log(f"载入 ROI {self.roi.width}x{self.roi.height}")
        except Exception as exc:  # noqa: BLE001
            self.roi = None
            self.lbl_hint.setText(f"ROI 失败：{exc}")

    def _ensure_pipe(self) -> AutofishPipeline:
        if self._pipe is None:
            pipe = AutofishPipeline(auto_locate=False, capture_fps=30.0)
            pipe.subscribe(Topic.FRAME, self._on_frame_bus)
            pipe.subscribe(Topic.POS, self._on_pos_bus)
            pipe.subscribe(Topic.ACTION_INTENT, self._on_intent_bus)
            self._pipe = pipe
            self._publish_press_interval()
        return self._pipe

    def _publish_press_interval(self) -> None:
        pipe = self._pipe
        if pipe is None:
            return
        ms = int(self.sld_press_interval.value())
        interval = ms / 1000.0
        self.lbl_press_interval.setText(f"{interval:.2f}s")
        pipe.bus.publish_press_interval(
            PressIntervalEvent(interval_s=interval, ts=time.time())
        )

    def _on_press_interval_changed(self, _value: int) -> None:
        self._ensure_pipe()
        self._publish_press_interval()

    def _on_press_interval_released(self) -> None:
        self._log(f"按下间隔 {self.lbl_press_interval.text()}")

    def _on_frame_bus(self, event: FrameEvent) -> None:
        self._bridge.frame.emit(event)

    def _on_pos_bus(self, event: PosEvent) -> None:
        self._bridge.pos.emit(event)

    def _on_intent_bus(self, event: ActionIntentEvent) -> None:
        self._bridge.intent.emit(event)

    def _on_frame_ui(self, event: FrameEvent) -> None:
        if self.phase == SELECT:
            return
        # 只缓存帧；MONITOR 由 Pos 同频刷新。
        # Frame 约 30fps 全量转 QPixmap 会在 Windows 上严重卡 UI。
        self.frame = event.frame

    def _on_pos_ui(self, event: PosEvent) -> None:
        if event.frame is not None and self.phase != SELECT:
            self.frame = event.frame
        self.hit = event.hit
        self._last_detect_ms = event.detect_ms
        self._note_detect_ms(event.detect_ms)
        self._refresh_pos()
        self._maybe_refresh_monitor()
        if self._pipe is not None and self._pipe.decide_on:
            self._refresh_strategy(event.pos, self._intent_reason)

    def _maybe_refresh_monitor(self, *, force: bool = False) -> None:
        now = time.perf_counter()
        if not force and (now - self._mon_ui_ts) < self._mon_ui_min_dt:
            return
        self._mon_ui_ts = now
        self._refresh_monitor()

    def _note_detect_ms(self, ms: float) -> None:
        """累计识别耗时；每 2s 记一条日志，便于看效率。"""
        if ms <= 0:
            return
        self._ms_window.append(ms)
        now = time.time()
        if now - self._ms_log_ts < 2.0 or not self._ms_window:
            return
        self._ms_log_ts = now
        vals = list(self._ms_window)
        avg = sum(vals) / len(vals)
        fps = 1000.0 / avg if avg > 0 else 0.0
        name = get_detector().name
        self._log(
            f"识别 {name} 均 {avg:.1f}ms 最大 {max(vals):.1f}ms"
            f" 最小 {min(vals):.1f}ms ≈{fps:.0f} FPS"
        )

    def _on_intent_ui(self, event: ActionIntentEvent) -> None:
        self._holding = event.holding
        self._intent_reason = event.reason
        self._refresh_strategy(event.pos, event.reason)
        pos_s = "—" if event.pos is None else f"{event.pos:.1f}"
        want = "要按住" if event.holding else "要松开"
        self._log(f"策略 {want} pos={pos_s} {event.reason}")
        self._refresh_mouse()

    def _refresh_strategy(
        self, pos: float | None = None, reason: str = ""
    ) -> None:
        pipe = self._pipe
        if pipe is None or not pipe.decide_on:
            self.lbl_intent.setText("未启用")
            self.lbl_intent.setStyleSheet(
                "font-size:18px; font-weight:600; color:#787c80;"
            )
            self.lbl_strat_detail.setText("")
            return
        if self._holding is None:
            self.lbl_intent.setText("等待…")
            self.lbl_intent.setStyleSheet(
                "font-size:18px; font-weight:600; color:#787c80;"
            )
        elif self._holding:
            self.lbl_intent.setText("要按住（点击）")
            self.lbl_intent.setStyleSheet(
                "font-size:18px; font-weight:600; color:#ff8c28;"
            )
        else:
            self.lbl_intent.setText("要松开")
            self.lbl_intent.setStyleSheet(
                "font-size:18px; font-weight:600; color:#48b46e;"
            )
        low, high = self._current_policy_thresholds()
        pos_s = "—" if pos is None else f"{pos:.1f}"
        plo, phi, rlo, rhi = self.range_axis.ranges()
        detail = (
            f"POS={pos_s} · 当前 <{low:.1f} 按住 / >{high:.1f} 松开"
            f" · 范围 U({plo:.1f}～{phi:.1f})/U({rlo:.1f}～{rhi:.1f})"
        )
        if reason:
            detail += f" · {reason}"
        self.lbl_strat_detail.setText(detail)

    def _current_policy_thresholds(self) -> tuple[float, float]:
        pipe = self._pipe
        if pipe is not None and pipe.decide_on:
            return pipe.decide.current_thresholds
        plo, phi, rlo, rhi = self.range_axis.ranges()
        return (plo + phi) / 2.0, (rlo + rhi) / 2.0

    def _refresh_pos(self) -> None:
        if self.hit is not None:
            self.lbl_pos.setText(f"{self.hit.pos:.1f}")
            self.lbl_pos.setStyleSheet(
                "font-size:28px; font-weight:600; color:#48b46e;"
            )
        else:
            self.lbl_pos.setText("无漂")
            self.lbl_pos.setStyleSheet(
                "font-size:28px; font-weight:600; color:#d24e46;"
            )
        ms = getattr(self, "_last_detect_ms", 0.0)
        self.lbl_perf.setText(f"{ms:.1f} ms")

    def _refresh_monitor(self) -> None:
        if self.phase == SELECT and self.screen_grab is not None:
            self.monitor.set_rgb(self.screen_grab.rgb)
            self.monitor.set_selecting(True)
            return
        self.monitor.set_selecting(False)
        if self.frame is None:
            self.monitor.set_rgb(None)
            return
        self.monitor.set_rgb(_overlay_hit(self.frame, self.hit))

    def _sync_buttons(self) -> None:
        selecting = self.phase == SELECT
        self.btn_confirm.setEnabled(selecting)
        self.btn_cancel.setEnabled(selecting)
        self.btn_capture.setEnabled(not selecting)
        self.btn_rebox.setEnabled(not selecting and DEFAULT_SCREEN_PATH.exists())

    def _block_checks(self, block: bool) -> None:
        for chk in (self.chk_monitor, self.chk_decide, self.chk_act):
            chk.blockSignals(block)

    def _on_monitor_toggled(self, checked: bool) -> None:
        if self.roi is None:
            self._block_checks(True)
            self.chk_monitor.setChecked(False)
            self._block_checks(False)
            self.lbl_hint.setText("先截屏框选 ROI")
            return
        pipe = self._ensure_pipe()
        if checked and not pipe.monitor_on:
            pipe.set_roi_manual(self.roi)
            pipe.start_monitor()
            self._log("监控 ON · Capture+Detect")
            self.lbl_hint.setText("监控中")
        elif not checked and pipe.monitor_on:
            pipe.stop_monitor()
            self.frame = None
            self.hit = None
            self._refresh_pos()
            self._refresh_monitor()
            self._log("监控 OFF")
            self.lbl_hint.setText("监控已关")

    def _on_decide_toggled(self, checked: bool) -> None:
        pipe = self._ensure_pipe()
        if checked and not pipe.decide_on:
            if not self._apply_policy():
                self._block_checks(True)
                self.chk_decide.setChecked(False)
                self._block_checks(False)
                return
            if not pipe.monitor_on:
                self.lbl_hint.setText("建议先开监控")
            pipe.start_decide()
            self._refresh_strategy(
                None if self.hit is None else self.hit.pos
            )
            low, high = self._current_policy_thresholds()
            plo, phi, rlo, rhi = self.range_axis.ranges()
            self._log(
                f"策略 ON · 当前 <{low:.1f} / >{high:.1f} · "
                f"范围 U({plo:.1f}～{phi:.1f})/U({rlo:.1f}～{rhi:.1f})"
            )
        elif not checked and pipe.decide_on:
            pipe.stop_decide()
            self._holding = None
            self._refresh_strategy()
            self._log("策略 OFF")
            self._refresh_mouse()

    def _on_act_toggled(self, checked: bool) -> None:
        pipe = self._ensure_pipe()
        if checked and not pipe.act_on:
            if not pipe.decide_on:
                self.lbl_hint.setText("建议先开策略")
            pipe.start_act()
            self._log("操作 ON · 非钓鱼态自由；单帧无漂不松；光标放游戏上")
        elif not checked and pipe.act_on:
            pipe.stop_act()
            self._log("操作 OFF")
        self._refresh_mouse()

    def _apply_policy(self) -> bool:
        plo, phi, rlo, rhi = self.range_axis.ranges()
        if plo > phi or rlo > rhi:
            self.lbl_hint.setText("策略无效：区间上下限颠倒")
            QMessageBox.warning(self, "策略", "区间上下限无效")
            return False
        if rlo - phi < 1.0 - 1e-9:
            self.lbl_hint.setText("策略无效：两段间隔须 ≥ 1")
            QMessageBox.warning(self, "策略", "按住与松开区间至少间隔 1 个百分点")
            return False
        pipe = self._ensure_pipe()
        pipe.set_decide_ranges(plo, phi, rlo, rhi)
        low, high = pipe.decide.current_thresholds
        self._log(
            f"策略已应用 · 当前 <{low:.1f} / >{high:.1f} · "
            f"范围 U({plo:.1f}～{phi:.1f})/U({rlo:.1f}～{rhi:.1f})"
        )
        self.lbl_hint.setText(
            f"策略范围 U({plo:.1f}～{phi:.1f}) 按住 / "
            f"U({rlo:.1f}～{rhi:.1f}) 松开"
        )
        if pipe.decide_on:
            pos = None if self.hit is None else self.hit.pos
            self._refresh_strategy(pos, self._intent_reason)
        return True

    def _refresh_mouse(self) -> None:
        pipe = self._pipe
        act_on = pipe is not None and pipe.act_on
        if act_on and pipe is not None:
            pipe.act.poll()
        prog = None if pipe is None else pipe.act.pressed
        yielding = bool(act_on and pipe is not None and pipe.act.yielding)
        os_down = os_left_down()
        intent = self._holding
        snap = None if pipe is None else pipe.bus.snapshot()
        fishing = bool(
            snap is not None and snap.fishing_state == FishingState.FISHING
        )
        free = act_on and not fishing and not yielding

        if not act_on:
            prog_s = "未启用"
        elif yielding:
            prog_s = "让位"
        elif free:
            prog_s = "自由"
        else:
            prog_s = _hold_word(prog)

        parts = [
            f"意图 {_hold_word(intent) if intent is not None else '—'}",
            f"程序 {prog_s}",
            f"系统 {_hold_word(os_down)}",
        ]
        self.lbl_mouse.setText(" · ".join(parts))

        issues: list[str] = []
        controlling = act_on and not free and not yielding
        if (
            controlling
            and intent is not None
            and prog is not None
            and intent != prog
        ):
            issues.append("意图≠程序")
        if (
            controlling
            and prog is not None
            and os_down is not None
            and prog != os_down
        ):
            issues.append("程序≠系统")
        if os_down is None:
            if sys.platform == "darwin":
                issues.append("系统态不可读（检查辅助功能权限）")
            elif sys.platform == "win32":
                # Windows 无「辅助功能」开关；旧包才会长期 None
                issues.append("系统态不可读（请用最新 Windows 包，或检查杀软）")
            else:
                issues.append("系统态不可读")

        if issues:
            self.lbl_mouse.setStyleSheet(
                "font-size:16px; font-weight:600; color:#d24e46;"
            )
            self.lbl_mouse_diag.setText("异常：" + " / ".join(issues))
            self.lbl_mouse_diag.setStyleSheet("color:#d24e46;")
            if not self._mouse_mismatch_logged:
                self._mouse_mismatch_logged = True
                self._log(
                    "鼠标异常 "
                    + " / ".join(issues)
                    + f" · 意图={_hold_word(intent)}"
                    + f" 程序={prog_s}"
                    + f" 系统={_hold_word(os_down)}"
                )
        else:
            if yielding:
                color = "#c9a227"
            elif free:
                color = "#787c80"
            elif act_on and prog:
                color = "#ff8c28"
            elif act_on:
                color = "#48b46e"
            else:
                color = "#787c80"
            self.lbl_mouse.setStyleSheet(
                f"font-size:16px; font-weight:600; color:{color};"
            )
            if not act_on:
                diag = "操作未启用 · 仍监视系统左键"
            elif yielding:
                diag = "系统优先 · 等你松开鼠标后程序再接管"
            elif free:
                diag = "自由态 · 非钓鱼态，不碰你的鼠标"
            else:
                diag = "控鼠中 · 钓鱼态，按策略按/松"
            self.lbl_mouse_diag.setText(diag)
            self.lbl_mouse_diag.setStyleSheet("color:#787c80;")
            self._mouse_mismatch_logged = False

    def _capture_fullscreen(self) -> None:
        if self._pipe and self._pipe.monitor_on:
            self._block_checks(True)
            self.chk_monitor.setChecked(False)
            self._block_checks(False)
            self._pipe.stop_monitor()
            self._log("监控 OFF · 准备框选")
        self.lbl_hint.setText("截屏中…")
        QApplication.processEvents()
        try:
            grab = grab_primary()
            save_screen(grab)
            self.screen_grab = grab
            self.phase = SELECT
            self.monitor.set_rgb(grab.rgb)
            self.monitor.set_selecting(True)
            self.lbl_hint.setText("拖拽框选张力条 → 确认框选")
            self._log("已截全屏 · 请手框 ROI")
        except Exception as exc:  # noqa: BLE001
            self.lbl_hint.setText(f"截图失败：{exc}")
            QMessageBox.warning(self, "截屏失败", str(exc))
        self._sync_buttons()

    def _load_screen_for_select(self) -> None:
        if self._pipe and self._pipe.monitor_on:
            self._block_checks(True)
            self.chk_monitor.setChecked(False)
            self._block_checks(False)
            self._pipe.stop_monitor()
            self.frame = None
            self.hit = None
            self._log("监控 OFF · 准备重框")
        try:
            self.screen_grab = load_screen(DEFAULT_SCREEN_PATH)
            self.phase = SELECT
            self.monitor.set_rgb(self.screen_grab.rgb)
            self.monitor.set_selecting(True)
            self.lbl_hint.setText("拖拽框选 → 确认框选")
        except Exception as exc:  # noqa: BLE001
            self.lbl_hint.setText(f"读截图失败：{exc}")
        self._sync_buttons()

    def _confirm_selection(self) -> None:
        sel = self.monitor.selection_in_image()
        if sel is None or self.screen_grab is None:
            self.lbl_hint.setText("框太小")
            return
        left, top, w, h = sel
        g = self.screen_grab
        roi = Roi(
            left=g.origin_left + left,
            top=g.origin_top + top,
            width=w,
            height=h,
        )
        save_roi(roi, self.roi_path)
        self.roi = roi
        self.phase = READY
        self.monitor.set_selecting(False)
        pipe = self._ensure_pipe()
        pipe.set_roi_manual(roi)
        self._log(f"手框 {roi.width}x{roi.height} · 已存盘并同步 mss")
        self._sync_buttons()
        self._refresh_monitor()
        self._ensure_monitor_on()

    def _ensure_monitor_on(self) -> None:
        """确认手框后自动开监控（勾选与流水线对齐）。"""
        if self.roi is None:
            return
        pipe = self._ensure_pipe()
        pipe.set_roi_manual(self.roi)
        if not pipe.monitor_on:
            pipe.start_monitor()
            self._log("监控 ON · Capture+Detect（确认框选后自动）")
        if not self.chk_monitor.isChecked():
            self._block_checks(True)
            self.chk_monitor.setChecked(True)
            self._block_checks(False)
        self.lbl_hint.setText("监控中")

    def _cancel_selection(self) -> None:
        self.phase = READY if self.roi is not None else IDLE
        self.monitor.set_selecting(False)
        self.lbl_hint.setText("已取消框选")
        self._sync_buttons()
        self._refresh_monitor()

    def _sim_pos(self) -> float:
        span = float(sim_config.SAFE_RIGHT - sim_config.SAFE_LEFT)
        if span <= 1e-6:
            return 50.0
        return max(
            0.0,
            min(
                100.0,
                100.0
                * (self.game.bobber_x - sim_config.SAFE_LEFT)
                / span,
            ),
        )

    def _on_tier_changed(self) -> None:
        tier = int(self.cmb_tier.currentData())
        self.game.set_tier(tier)

    def _sim_close(self, idle_text: str = "点击开始手玩") -> None:
        """结束手玩并关闭画面，松开本地按住态。"""
        self._sim_holding = False
        self.game.set_holding(False)
        self.game.reset()
        self.sim.set_accept_input(True)
        self.sim.show_idle(idle_text)
        self.lbl_sim_pos.setText(f"—  T{self.game.tier}")

    def _sim_reset(self) -> None:
        self._sim_close("点击开始手玩")
        self._log("手玩已关")

    def _sim_press(self) -> None:
        if self.game.state == State.PLAYING:
            self.game.set_holding(True)
        else:
            self.game.start()
            self.game.set_holding(True)
        self._sim_holding = True

    def _sim_release(self) -> None:
        if self._sim_holding:
            self.game.set_holding(False)
            self._sim_holding = False

    def _on_tick(self) -> None:
        dt = 1.0 / max(1, sim_config.FPS)
        was_playing = self.game.state == State.PLAYING
        self.game.update(dt)
        if self.game.state == State.PLAYING:
            self._sim_renderer.draw(self.game)
            raw = pygame.surfarray.array3d(self._sim_buf)
            rgb = np.transpose(raw, (1, 0, 2)).copy()
            self.sim.set_rgb(rgb)
            self.lbl_sim_pos.setText(
                f"{self._sim_pos():.1f}  T{self.game.tier}"
            )
        elif was_playing:
            # 成功/失败：立刻关画面，避免按住态继续吃鼠标
            ended = (
                "成功" if self.game.state == State.SUCCESS else "失败"
            )
            self._sim_close(f"{ended} · 点击再开")
            self._log(f"手玩{ended} · 画面已关")
        else:
            self.lbl_sim_pos.setText(f"—  T{self.game.tier}")
        self._refresh_mouse()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._pipe is not None:
            self._pipe.unsubscribe(Topic.FRAME, self._on_frame_bus)
            self._pipe.unsubscribe(Topic.POS, self._on_pos_bus)
            self._pipe.unsubscribe(Topic.ACTION_INTENT, self._on_intent_bus)
            self._pipe.stop()
            self._pipe = None
        self._timer.stop()
        pygame.quit()
        super().closeEvent(event)

    def run(self) -> int:
        self.show()
        return QApplication.instance().exec()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = PreviewApp()
    win.show()
    return app.exec()


AutofishApp = PreviewApp


if __name__ == "__main__":
    raise SystemExit(main())
