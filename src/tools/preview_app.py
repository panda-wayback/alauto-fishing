"""调试壳（PySide6）：竖列可滚 + 底栏独立日志；抛杆用全局快捷键。"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from collections import deque
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from PySide6.QtCore import QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from autofish.act.mouse import os_left_down
from autofish.detect.api import apply_manual_bar, apply_program_bar, get_detector
from autofish.detect.bobber_anchor import BobberAnchorDetector
from autofish.detect.bobber import BobberHit
from autofish.capture.screen import (
    DEFAULT_SCREEN_PATH,
    ScreenGrab,
    grab_primary,
    load_screen,
    roi_frame_size,
    save_screen,
)
from autofish.locate.roi import (
    DEFAULT_ROI_PATH,
    ROI_SOURCE_DEFAULT,
    ROI_SOURCE_MANUAL,
    BarMark,
    Roi,
    bar_ref_meta_path,
    bar_ref_path,
    clear_bar_mark,
    clear_bar_ref,
    default_center_roi,
    load_bar_mark,
    load_roi,
    load_roi_source,
    primary_screen_size,
    save_roi,
)
from autofish.auto_cast.cursor_arm import CursorArmWatcher
from autofish.pipeline import AutofishPipeline
from autofish.events.topics import (
    ActionIntentEvent,
    CastPhase,
    CastSessionState,
    FishingState,
    FrameEvent,
    PosEvent,
    PressIntervalEvent,
    Topic,
)
from common import permissions as perms
from tools.shell_config import (
    ShellSettings,
    format_cast_count_range,
    load_default_shell_settings,
    load_shell_settings,
    sample_cast_batch_count,
    save_bundled_shell_settings,
    save_shell_settings,
)
from tools.shell_theme import (
    ACCENT,
    BORDER,
    DANGER,
    SUCCESS,
    TEXT_FAINT,
    TEXT_MUTED,
    WARN,
    global_qss,
    paint_tone,
)
from tools.macos_overlay import (
    elevate_over_fullscreen,
    hide_miniaturize_button,
    restore_window_level,
)
from tools.status_hud import StatusHudPanel
from tools.shell_log import append_log
from tools.image_canvas import overlay_hit
from tools.sound_panel import FirstClickTriggerPanel
from tools.backtest_panel import AudioBacktestPanel
from tools.main_page import build_main_page
from tools.calibrate_page import build_calibrate_page
from tools.cast_page import build_cast_page
from tools.cast_hotkeys import CastHotkeyListener, normalize_hotkey
from tools.cast_right_click import CastRightClickListener
from tools.more_page import build_more_page

IDLE = "idle"
SELECT = "select"
READY = "ready"

_CAST_PHASE_LABEL = {
    CastPhase.DISABLED: "关",
    CastPhase.WAIT: "等待",
    CastPhase.AIM: "瞄准",
    CastPhase.CHARGING: "蓄力",
    CastPhase.DONE: "完成",
    CastPhase.ABORT: "中止",
}

# 主控 A 行大号会话文案（短、好扫）
_SESSION_HERO = {
    CastSessionState.DISABLED: "关",
    CastSessionState.WAIT: "听声",
    CastSessionState.FIRST_CLICK: "开钓",
    CastSessionState.WAIT_BOBBER: "等漂",
    CastSessionState.FISHING: "拉漂",
}


class BusBridge(QObject):
    """后台线程 → UI 线程。"""

    frame = Signal(object)
    pos = Signal(object)
    intent = Signal(object)


class HotkeyBridge(QObject):
    """全局热键监听线程 → UI 线程。"""

    start_cast = Signal()
    stop_cast = Signal()


class RightClickBridge(QObject):
    """右键监听线程 → UI 线程。"""

    pressed = Signal()


class ArmBridge(QObject):
    """认漂观察者线程 → UI 线程。"""

    armed_changed = Signal(bool)
    frame = Signal(object, bool)  # rgb ndarray, armed


def _hold_word(on: bool | None) -> str:
    if on is None:
        return "—"
    return "按" if on else "松"


# 主控精简后默认窗高贴内容；过高会在卡下留死白
_DEFAULT_FULL_SIZE = (420, 560)


class PreviewApp(QMainWindow):
    def __init__(self, roi_path: Path = DEFAULT_ROI_PATH) -> None:
        super().__init__()
        self.setWindowTitle("Albion 拉鱼")
        self.resize(*_DEFAULT_FULL_SIZE)
        self.setStyleSheet(global_qss())
        self._settings = load_shell_settings()
        # 启动期间恢复 A/B 会落盘并以当前（完整）态覆盖 compact_mode，须先记下
        start_compact = bool(self._settings.compact_mode)
        # 默认置顶：点到游戏窗口时调试壳不被盖住（可被持久化覆盖）
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint, bool(self._settings.stay_on_top)
        )
        # 去掉最小化：置顶时系统最小化不可靠，隐藏按钮避免点了没反应
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)

        self.roi_path = roi_path
        self.roi: Roi | None = None
        self.hit: BobberHit | None = None
        self.frame: np.ndarray | None = None
        self.phase = IDLE
        self.screen_grab: ScreenGrab | None = None
        self._pipe: AutofishPipeline | None = None
        self._holding: bool | None = None
        self._last_cast_session: CastSessionState | None = None
        self._last_cast_phase: CastPhase | None = None
        self._cast_live = False
        self._had_bobber: bool | None = None
        self._intent_reason = ""
        self._last_detect_ms: float = 0.0
        self._ms_window: deque[float] = deque(maxlen=60)
        self._ms_log_ts: float = 0.0
        self._mon_ui_ts: float = 0.0
        self._mon_ui_min_dt: float = 1.0 / 15.0  # 预览最多 ~15fps，避免 Windows 卡死
        self._mouse_mismatch_logged = False
        self._logs: deque[str] = deque(maxlen=200)
        self._cal_logs: deque[str] = deque(maxlen=200)
        self._cast_logs: deque[str] = deque(maxlen=200)
        self._sound_panel: FirstClickTriggerPanel | None = None
        self._backtest_panel: AudioBacktestPanel | None = None
        self._bar_ref_saved = False
        self._bar_ref_wait_bobber = False
        # 框选期间暂停 Act：停监控后 FSM 可能卡在 FISHING，Windows 上
        # pynput 合成左键按住会导致「确认框选」点不动。
        self._act_paused_for_select = False
        self._cast_paused_for_select = False
        self._cast_paused_remaining = 0
        self._bridge = BusBridge()
        self._bridge.frame.connect(self._on_frame_ui)
        self._bridge.pos.connect(self._on_pos_ui)
        self._bridge.intent.connect(self._on_intent_ui)
        self._hotkey_bridge = HotkeyBridge()
        self._hotkey_bridge.start_cast.connect(self._on_cast_hotkey_start)
        self._hotkey_bridge.stop_cast.connect(self._on_cast_hotkey_stop)
        self._cast_hotkeys = CastHotkeyListener(
            on_start=lambda: self._hotkey_bridge.start_cast.emit(),
            on_stop=lambda: self._hotkey_bridge.stop_cast.emit(),
        )
        self._rclick_bridge = RightClickBridge()
        self._rclick_bridge.pressed.connect(self._on_cast_right_click)
        self._cast_right_click = CastRightClickListener(
            on_press=lambda: self._rclick_bridge.pressed.emit(),
        )
        self._arm_bridge = ArmBridge()
        self._arm_bridge.armed_changed.connect(self._on_cursor_armed_changed)
        self._arm_bridge.frame.connect(self._on_cursor_arm_frame)
        self._cursor_arm: CursorArmWatcher | None = None
        self._last_armed: bool | None = None

        self._compact = False
        self._full_geo = None
        self._build_ui()
        self._apply_saved_window_geometry()
        self._reload_roi()
        self._sync_buttons()
        # 恢复持久化 A/B/C；有 ROI 则常开 Capture/Detect
        self._restore_ab_from_settings()
        if self.roi is not None:
            self._ensure_monitor_on()
            self.lbl_hint.setText("ROI 就绪 · 监控中")
            self._cal_log("启动 · Capture/Detect 常开")
        self._refresh_cast_label()
        self._refresh_hud_steady()
        if start_compact:
            self._set_compact_mode(True, from_startup=True)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(50)

        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(400)
        self._persist_timer.timeout.connect(self._persist_settings)

        self._perm_timer = QTimer(self)
        self._perm_timer.timeout.connect(self._refresh_permissions)
        self._perm_timer.start(2000)
        self._refresh_permissions()
        self._apply_cast_hotkeys_from_settings()
        self._cast_hotkeys.start()
        QTimer.singleShot(0, self._apply_no_minimize)

    def _apply_no_minimize(self) -> None:
        """隐藏最小化：Qt 旗标 + macOS 清 Miniaturizable（延迟再刷，防标题栏重建）。"""
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
        hide_miniaturize_button(self)
        QTimer.singleShot(50, lambda: hide_miniaturize_button(self))
        QTimer.singleShot(200, lambda: hide_miniaturize_button(self))

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.mode_stack = QStackedWidget()
        outer.addWidget(self.mode_stack)

        page_full = QWidget()
        layout = QVBoxLayout(page_full)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 导航：主控 | 自动拉线 | 自动抛竿 | 自动起勾 | 回测 | 更多
        nav = QHBoxLayout()
        nav.setSpacing(2)
        self._nav_btns: list[QPushButton] = []
        self.stack = QStackedWidget()
        nav_items = (
            ("主控", "日常开关与状态"),
            ("自动拉线", "ROI / 条界 / 策略"),
            ("自动抛竿", "次数 · 快捷键 · 满蓄 · 等待"),
            ("自动起勾", "设备 / 模板 / 阈值 / 第一下"),
            ("回测", "长录音与命中回测"),
            ("更多", "权限与置顶"),
        )
        for i, (name, tip) in enumerate(nav_items):
            btn = QPushButton(name)
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, idx=i: self._goto_page(idx))
            nav.addWidget(btn)
            self._nav_btns.append(btn)
        nav.addStretch(1)
        layout.addLayout(nav)

        self.stack.addWidget(build_main_page(self))
        self.stack.addWidget(build_calibrate_page(self))
        self.stack.addWidget(build_cast_page(self))

        # —— 声音开钓配置 ——
        page_sound = QWidget()
        sound_l = QVBoxLayout(page_sound)
        sound_l.setContentsMargins(0, 0, 0, 0)
        self._sound_panel = FirstClickTriggerPanel(
            self,
            click_delay=(
                self._settings.click_delay_lo_s,
                self._settings.click_delay_hi_s,
            ),
            click_hold=(
                self._settings.click_hold_lo_s,
                self._settings.click_hold_hi_s,
            ),
            click_after=(
                self._settings.click_after_lo_s,
                self._settings.click_after_hi_s,
            ),
        )
        self.bar_delay = self._sound_panel.bar_delay
        self.bar_hold = self._sound_panel.bar_hold
        self.bar_after = self._sound_panel.bar_after
        self._sound_panel.set_preferred_device_name(self._settings.audio_device_name)
        self._sound_panel.set_threshold_value(
            self._settings.sound_threshold, emit=False
        )
        self._sound_panel.on_threshold_changed(self._on_sound_threshold_persist)
        self._sound_panel.on_device_changed(self._on_sound_device_persist)
        self._sound_panel.on_click_timing_changed(self._on_click_timing_changed)
        sound_l.addWidget(self._sound_panel)
        self.stack.addWidget(page_sound)

        # —— 回测 ——
        page_backtest = QWidget()
        bt_l = QVBoxLayout(page_backtest)
        bt_l.setContentsMargins(0, 0, 0, 0)
        self._backtest_panel = AudioBacktestPanel(self._sound_panel, self)
        bt_l.addWidget(self._backtest_panel)
        self.stack.addWidget(page_backtest)

        self.stack.addWidget(build_more_page(self))

        layout.addWidget(self.stack, 1)
        self.mode_stack.addWidget(page_full)

        self._hud = StatusHudPanel()
        self._hud.expand_requested.connect(lambda: self._set_compact_mode(False))
        self._hud.opacity_changed.connect(self._on_hud_opacity_changed)
        self._hud.set_opacity_value(float(self._settings.hud_opacity))
        self.mode_stack.addWidget(self._hud)

    def _goto_page(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            btn.blockSignals(True)
            btn.setChecked(i == idx)
            btn.blockSignals(False)

    def _on_tick(self) -> None:
        self._refresh_mouse()
        self._refresh_session_label()
        self._refresh_cast_label()

    def _refresh_session_label(self) -> None:
        pipe = self._pipe
        a_on = bool(getattr(self, "chk_a", None) is not None and self.chk_a.isChecked())
        if pipe is None:
            self.lbl_session.setText("关")
            return
        snap = pipe.bus.snapshot()
        cs = snap.cast_session
        if cs == CastSessionState.DISABLED:
            self.lbl_session.setText("关" if not a_on else "—")
        else:
            self.lbl_session.setText(_SESSION_HERO.get(cs, cs.value))
        prev = self._last_cast_session
        if prev is not None and cs != prev:
            if cs == CastSessionState.FIRST_CLICK:
                splash = snap.cast_splash
                if splash is not None:
                    self._main_log(
                        f"声音触发 · 相似 {splash.score:.2f} · "
                        f"等待 {splash.delay_s:.2f}s · 按住 {splash.hold_s:.2f}s · "
                        f"松开后 {splash.after_s:.2f}s · 阈值 {splash.threshold:.2f}"
                    )
                else:
                    self._main_log("声音触发 · 准备点第一下")
                hud = getattr(self, "_hud", None)
                if hud is not None:
                    hud.flash("heard")
        self._last_cast_session = cs
        self._refresh_hud_steady()

    def _set_cast_remain(
        self, text: str, *, active: bool = False, cap: str = "次数"
    ) -> None:
        rem = getattr(self, "lbl_cast_remain", None)
        if rem is None:
            return
        rem.setText(text)
        # 进行中用强调色，待命用主字色，关闭用弱色
        if active:
            tone = "live"
        elif text in {"—", "-", ""}:
            tone = "faint"
        else:
            tone = "idle"
        paint_tone(rem, tone)
        # lbl_cast_remain_cap 已从主控摘掉，仅保留兼容字段

    def _sync_cast_live(self) -> None:
        """抛竿任务起止：常亮标签 + 开始 / 结束短闪（主控与浮窗同步）。"""
        pipe = self._pipe
        c_on = bool(getattr(self, "chk_c", None) is not None and self.chk_c.isChecked())
        live = bool(c_on and pipe is not None and pipe.auto_cast.active)
        badge = getattr(self, "lbl_cast_badge", None)
        card = getattr(self, "card_cast", None)
        if badge is not None:
            badge.setVisible(c_on)
            badge.setText("抛竿中" if live else "待命")
            self._set_prop(badge, "live", live)
        if card is not None:
            self._set_prop(card, "live", live)
        hud = getattr(self, "_hud", None)
        if hud is not None:
            hud.set_cast_live(live)
        if live == self._cast_live:
            return
        self._cast_live = live
        if live:
            total = max(int(pipe.auto_cast.batch_total), int(pipe.auto_cast.remaining))
            note = f"已开始 · 共 {total} 次"
            key = "cast_start"
        else:
            note = f"已结束 · {self._cast_end_reason(c_on)}"
            key = "cast_end"
        self._flash_cast_card(note)
        if hud is not None:
            hud.flash(key)

    def _cast_end_reason(self, c_on: bool) -> str:
        if not c_on:
            return "关闭自动抛竿"
        pipe = self._pipe
        detail = "" if pipe is None else (pipe.bus.snapshot().cast_phase_detail or "")
        return {
            "batch_done": "次数用尽",
            "right_click": "右键",
            "cancelled": "手动",
        }.get(detail, "中止" if detail else "手动")

    def _flash_cast_card(self, note: str) -> None:
        card = getattr(self, "card_cast", None)
        lbl = getattr(self, "lbl_cast_note", None)
        if card is None or lbl is None:
            return
        lbl.setText(note)
        lbl.show()
        self._set_prop(card, "flash", True)
        timer = getattr(self, "_cast_flash_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self._set_prop(self.card_cast, "flash", False))
            self._cast_flash_timer = timer
        timer.start(1500)

    @staticmethod
    def _set_prop(widget, name: str, on: bool) -> None:
        val = "true" if on else "false"
        if widget.property(name) == val:
            return
        widget.setProperty(name, val)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _refresh_cast_label(self) -> None:
        self._sync_cast_live()
        pipe = self._pipe
        c_on = bool(getattr(self, "chk_c", None) is not None and self.chk_c.isChecked())
        cfg_txt = format_cast_count_range(
            self._settings.cast_count_lo, self._settings.cast_count_hi
        )
        if not c_on:
            self.lbl_cast.setText("关")
            paint_tone(self.lbl_cast, "faint")
            self._set_cast_remain("—", active=False, cap="次数")
            self._set_arm_preview_visible(False)
            if self._last_cast_phase is not None and self._last_cast_phase != CastPhase.DISABLED:
                self._last_cast_phase = CastPhase.DISABLED
            self._refresh_hud_steady()
            return
        self._set_arm_preview_visible(True)
        if pipe is None or not pipe.auto_cast.active:
            armed = bool(
                self._cursor_arm is not None and self._cursor_arm.armed
            )
            arm_txt = "就绪" if armed else "等待认漂"
            self.lbl_cast.setText(arm_txt)
            paint_tone(self.lbl_cast, "ok" if armed else "warn")
            self._set_cast_remain(cfg_txt, active=False, cap="次数")
            self._paint_arm_border(armed)
            if self._last_cast_phase is not None and self._last_cast_phase != CastPhase.DISABLED:
                self._last_cast_phase = CastPhase.DISABLED
            self._refresh_hud_steady()
            return
        snap = pipe.bus.snapshot()
        phase = snap.cast_phase
        label = _CAST_PHASE_LABEL.get(phase, phase.value)
        detail = snap.cast_phase_detail or ""
        rem = pipe.auto_cast.remaining
        total = max(rem, int(pipe.auto_cast.batch_total) or 1)
        self.lbl_cast.setText(label)
        paint_tone(self.lbl_cast, "accent")
        self._set_cast_remain(f"{rem}/{total}", active=True, cap="剩/共")
        armed = bool(self._cursor_arm is not None and self._cursor_arm.armed)
        self._paint_arm_border(armed)
        prev = self._last_cast_phase
        if prev is not None and phase != prev:
            self._main_log(
                f"抛杆 {prev.value} → {phase.value}"
                + (f" · {detail}" if detail else "")
                + f" · 剩 {rem}/{total}"
            )
            self._log_cast_phase(phase, detail, rem=rem)
        self._last_cast_phase = phase
        self._refresh_hud_steady()

    def _log_cast_phase(self, phase: CastPhase, detail: str, *, rem: int) -> None:
        """抛杆配置页：写清第几次、按下多久、拉漂后等待。"""
        d = (detail or "").strip()
        if phase == CastPhase.AIM:
            self._cast_log(f"瞄准 {d} · 剩 {rem}".strip())
        elif phase == CastPhase.CHARGING:
            self._cast_log(f"蓄力按下 {d} · 剩 {rem}".strip())
        elif phase == CastPhase.DONE:
            hold = ""
            pipe = self._pipe
            if pipe is not None and pipe.auto_cast.last_hold_s is not None:
                hold = f" · 已按 {pipe.auto_cast.last_hold_s:.2f}s"
            self._cast_log(f"松杆完成 {d}{hold} · 剩 {rem}".strip())
        elif phase == CastPhase.WAIT:
            if d.startswith("settle"):
                self._cast_log(f"开抛避让 · {d} · 剩 {rem}")
            elif d.startswith("wait_bobber"):
                self._cast_log(f"等鱼漂就绪 · {d} · 剩 {rem}")
            elif d.startswith("after_fish"):
                self._cast_log(f"就绪后再等 · {d} · 剩 {rem}")
            elif d.startswith("retry"):
                self._cast_log(f"本杆失败 · {d} · 剩 {rem}")
            else:
                self._cast_log(f"等待 {d} · 剩 {rem}".strip())
        elif phase == CastPhase.ABORT:
            self._cast_log(f"中止 {d} · 剩 {rem}".strip())
        elif phase == CastPhase.DISABLED:
            if d == "batch_done":
                self._cast_log("本轮次数用尽")
            elif d == "right_click":
                self._cast_log("已结束抛杆任务（系统右键）")
                self._main_log("抛竿结束 · 右键")
            elif d == "cancelled":
                self._cast_log("已结束抛杆任务")
            elif d:
                self._cast_log(f"结束 · {d}")

    def _main_log(self, msg: str) -> None:
        """主控状态日志（最新在上）。"""
        if getattr(self, "log", None) is not None:
            append_log(self._logs, self.log, msg)

    def _cal_log(self, msg: str) -> None:
        """自动拉漂配置页日志（最新在上）。"""
        if getattr(self, "cal_log", None) is not None:
            append_log(self._cal_logs, self.cal_log, msg)

    def _cast_log(self, msg: str) -> None:
        """抛杆配置页日志（最新在上）。"""
        if getattr(self, "cast_log", None) is not None:
            append_log(self._cast_logs, self.cast_log, msg)

    def _schedule_persist(self) -> None:
        """拖动数轴时防抖落盘，避免每像素写文件。"""
        self._persist_timer.start()

    def _sync_geometry_into_settings(self) -> None:
        """窗几何写入内存 settings（落盘前调用）。"""
        hx = self._settings.hud_x
        hy = self._settings.hud_y
        wx = self._settings.window_x
        wy = self._settings.window_y
        ww = self._settings.window_w
        wh = self._settings.window_h
        if self._compact:
            hx, hy = self.x(), self.y()
            if self._full_geo is not None:
                fg = self._full_geo
                wx, wy, ww, wh = fg.x(), fg.y(), fg.width(), fg.height()
        else:
            g = self.geometry()
            wx, wy, ww, wh = g.x(), g.y(), g.width(), g.height()
        self._settings = replace(
            self._settings,
            compact_mode=bool(self._compact),
            hud_x=int(hx),
            hud_y=int(hy),
            window_x=int(wx),
            window_y=int(wy),
            window_w=int(ww),
            window_h=int(wh),
            sound_enabled=bool(self.chk_a.isChecked()),
            auto_bobber_enabled=bool(self.chk_b.isChecked()),
            auto_cast_enabled=bool(self.chk_c.isChecked()),
            stay_on_top=bool(self.chk_stay_on_top.isChecked()),
        )

    def _persist_settings(self) -> None:
        """以内存 self._settings 为唯一源落盘；几何/A·B 从窗同步。"""
        self._sync_geometry_into_settings()
        save_shell_settings(self._settings)

    def _patch_settings(self, **kwargs) -> None:
        """改内存 settings 并防抖落盘。"""
        self._settings = replace(self._settings, **kwargs)
        self._schedule_persist()

    def _apply_saved_window_geometry(self) -> None:
        s = self._settings
        if s.window_w < 360 or s.window_h < 480:
            return
        pt = self._clamp_to_screens(
            s.window_x, s.window_y, s.window_w, s.window_h
        )
        self.setGeometry(pt.x(), pt.y(), s.window_w, s.window_h)
        # Windows：geometry 常是客户区；y=0 时标题栏在屏外，看起来像无边框、拖不动
        self._ensure_frame_on_screen()

    def _ensure_frame_on_screen(self) -> None:
        """保证整窗含标题栏落在某块屏的可用区内。"""
        screens = QApplication.screens()
        if not screens:
            return
        fg = self.frameGeometry()
        host = None
        for scr in screens:
            ag = scr.availableGeometry()
            if ag.intersects(fg):
                host = ag
                break
        if host is None:
            host = screens[0].availableGeometry()
        dx = 0
        dy = 0
        if fg.left() < host.left():
            dx = host.left() - fg.left()
        elif fg.right() > host.right():
            dx = host.right() - fg.right()
        if fg.top() < host.top():
            dy = host.top() - fg.top()
        elif fg.bottom() > host.bottom():
            dy = host.bottom() - fg.bottom()
        if dx or dy:
            self.move(self.x() + dx, self.y() + dy)

    def _restore_ab_from_settings(self) -> None:
        """启动时恢复 A/B/C 勾选并应用。"""
        s = self._settings
        want_b = bool(s.auto_bobber_enabled)
        want_a = bool(s.sound_enabled)
        want_c = bool(s.auto_cast_enabled)
        # 先把勾选摆到目标态，再应用逻辑——避免 B 落盘时把 A 偏好写成 false
        self._block_checks(True)
        self.chk_b.setChecked(want_b)
        self.chk_a.setChecked(want_a)
        self.chk_c.setChecked(want_c)
        self._block_checks(False)
        self._on_b_toggled(want_b)
        self._on_c_toggled(want_c)
        # 工人 / 管线可能已建：再刷一次抛杆次数 / 等待 / 满蓄到控件与 pipe
        self._apply_cast_batch_from_settings()
        if want_a:
            # 延后一拍：声音面板设备列表已就绪后再开会话
            QTimer.singleShot(0, self._restore_sound_enabled)

    def _apply_cast_batch_from_settings(self) -> None:
        s = self._settings
        if getattr(self, "bar_cast_count", None) is not None:
            self.bar_cast_count.setRange(
                float(s.cast_count_lo), float(s.cast_count_hi), emit=False
            )
        self._apply_cast_hotkey_edits(s.cast_start_hotkey, s.cast_stop_hotkey)
        self._apply_cast_wait_from_settings()
        self._apply_cast_full_charge_from_settings()
        self._apply_cast_hotkeys_from_settings()

    def _apply_cast_wait_from_settings(self) -> None:
        s = self._settings
        if getattr(self, "bar_cast_wait", None) is not None:
            self.bar_cast_wait.setRange(s.cast_wait_lo_s, s.cast_wait_hi_s, emit=False)
        pipe = self._pipe
        if pipe is not None:
            pipe.set_cast_wait_range(s.cast_wait_lo_s, s.cast_wait_hi_s)

    def _apply_cast_full_charge_from_settings(self) -> None:
        s = self._settings
        spin = getattr(self, "spin_cast_full_charge", None)
        if spin is not None:
            spin.blockSignals(True)
            spin.setValue(float(s.cast_full_charge_s))
            spin.blockSignals(False)
        pipe = self._pipe
        if pipe is not None:
            pipe.set_cast_full_charge_s(s.cast_full_charge_s)

    def _apply_cast_hotkey_edits(self, start: str, stop: str) -> None:
        if getattr(self, "edit_cast_start", None) is None:
            return
        self.edit_cast_start.blockSignals(True)
        self.edit_cast_stop.blockSignals(True)
        self.edit_cast_start.setKeySequence(QKeySequence(start))
        self.edit_cast_stop.setKeySequence(QKeySequence(stop))
        self.edit_cast_start.blockSignals(False)
        self.edit_cast_stop.blockSignals(False)

    def _apply_cast_hotkeys_from_settings(self) -> None:
        s = self._settings
        self._cast_hotkeys.set_keys(s.cast_start_hotkey, s.cast_stop_hotkey)

    @staticmethod
    def _keyseq_to_hotkey(seq: QKeySequence, *, default: str) -> str:
        if seq.isEmpty():
            return normalize_hotkey(default, default=default)
        text = seq.toString(QKeySequence.SequenceFormat.PortableText).strip()
        if not text:
            return normalize_hotkey(default, default=default)
        key = text.split("+")[-1].strip().upper()
        return normalize_hotkey(key, default=default)

    def _restore_sound_enabled(self) -> None:
        """按已勾选的 A 偏好尝试启动听声；失败不改勾选、不抹掉偏好。"""
        if not self.chk_a.isChecked():
            return
        self._activate_sound_session(persist=True)

    def _on_sound_threshold_persist(self, thr: float) -> None:
        self._patch_settings(sound_threshold=float(thr))

    def _on_sound_device_persist(self, name: str) -> None:
        self._patch_settings(audio_device_name=str(name or ""))

    def _on_click_timing_changed(self, *_args) -> None:
        d_lo, d_hi = self.bar_delay.range()
        h_lo, h_hi = self.bar_hold.range()
        a_lo, a_hi = self.bar_after.range()
        self._patch_settings(
            click_delay_lo_s=d_lo,
            click_delay_hi_s=d_hi,
            click_hold_lo_s=h_lo,
            click_hold_hi_s=h_hi,
            click_after_lo_s=a_lo,
            click_after_hi_s=a_hi,
        )

    def _on_ranges_changed(self, plo: float, phi: float, rlo: float, rhi: float) -> None:
        self._patch_settings(
            press_lo=float(plo),
            press_hi=float(phi),
            release_lo=float(rlo),
            release_hi=float(rhi),
        )

    def _clamp_to_screens(self, x: int, y: int, w: int, h: int) -> QPoint:
        """把左上角夹到某块屏可用区内（避免跨屏幽灵坐标）。"""
        pt = QPoint(int(x), int(y))
        screens = QApplication.screens()
        if not screens:
            return pt
        for scr in screens:
            ag = scr.availableGeometry()
            if ag.contains(pt):
                return pt
        # 落点不在任何屏：夹到最近屏
        best_d: float | None = None
        for scr in screens:
            ag = scr.availableGeometry()
            cx = min(max(pt.x(), ag.left()), ag.right() - max(w, 1))
            cy = min(max(pt.y(), ag.top()), ag.bottom() - max(h, 1))
            d = abs(cx - pt.x()) + abs(cy - pt.y())
            if best_d is None or d < best_d:
                best_d = d
                pt = QPoint(cx, cy)
        return pt

    def _set_compact_mode(
        self,
        compact: bool,
        *,
        persist: bool = True,
        from_startup: bool = False,
    ) -> None:
        """同一窗口：完整态 ↔ 紧凑态（就地缩放，不跨屏瞬移）。"""
        compact = bool(compact)
        if compact == self._compact and self.mode_stack.currentIndex() == (
            1 if compact else 0
        ):
            if persist:
                self._persist_settings()
            return
        if compact:
            if not self._compact:
                self._full_geo = self.geometry()
            self.mode_stack.setCurrentIndex(1)
            self._compact = True
            # 就地缩小：字号不变，窗体贴 content；仅「启动即紧凑」才用上次拖动落点
            anchor = self.geometry().topLeft()
            hud = getattr(self, "_hud", None)
            if hud is not None:
                w, h = hud.preferred_size()
            else:
                w, h = 176, 148
            self.setMinimumSize(160, 120)
            self.resize(w, h)
            if from_startup:
                s = self._settings
                if s.hud_x >= 0 and s.hud_y >= 0:
                    anchor = self._clamp_to_screens(
                        s.hud_x, s.hud_y, self.width(), self.height()
                    )
            self.move(anchor)
            # 紧凑：置顶 + 无边框；半透明用 setWindowOpacity（可调，不发虚）
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
            self.show()
            self._apply_hud_opacity(float(self._settings.hud_opacity))
            self._refresh_hud_steady()
            QTimer.singleShot(0, self._apply_compact_overlay)
            QTimer.singleShot(0, self._apply_no_minimize)
        else:
            if self._compact:
                self._settings.hud_x = self.x()
                self._settings.hud_y = self.y()
            self.mode_stack.setCurrentIndex(0)
            self._compact = False
            self.setMinimumSize(360, 480)
            # 就地放大：保留当前左上角，恢复完整尺寸
            anchor = self.geometry().topLeft()
            if self._full_geo is not None:
                self.resize(self._full_geo.width(), self._full_geo.height())
            else:
                self.resize(*_DEFAULT_FULL_SIZE)
            self.move(anchor)
            # 恢复完整窗框、不透明与用户置顶偏好
            self.setWindowOpacity(1.0)
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)
            self.setWindowFlag(
                Qt.WindowType.WindowStaysOnTopHint,
                bool(self.chk_stay_on_top.isChecked()),
            )
            self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
            self.setStyleSheet(global_qss())
            self.show()
            self.raise_()
            self.activateWindow()
            QTimer.singleShot(0, self._restore_normal_overlay)
            QTimer.singleShot(0, self._apply_no_minimize)
        if persist:
            self._persist_settings()

    def _apply_hud_opacity(self, opacity: float) -> None:
        op = max(0.45, min(1.0, float(opacity)))
        self._settings = replace(self._settings, hud_opacity=op)
        if self._compact:
            self.setWindowOpacity(op)
        hud = getattr(self, "_hud", None)
        if hud is not None:
            hud.set_opacity_value(op)

    def _on_hud_opacity_changed(self, opacity: float) -> None:
        self._apply_hud_opacity(opacity)
        self._persist_settings()

    def _apply_compact_overlay(self) -> None:
        if not self._compact:
            return
        self.raise_()
        elevate_over_fullscreen(self)
        hide_miniaturize_button(self)

    def _restore_normal_overlay(self) -> None:
        if self._compact:
            return
        restore_window_level(
            self, floating=bool(self.chk_stay_on_top.isChecked())
        )
        hide_miniaturize_button(self)

    def _refresh_hud_metrics(self) -> None:
        """紧凑态三行：POS / 抛竿 / 拉线（只显示意图，异常才标「异」）。"""
        hud = getattr(self, "_hud", None)
        if hud is None or not getattr(self, "_compact", False):
            return
        pipe = self._pipe
        if self.hit is None:
            pos_s, pos_c = "—", TEXT_FAINT
        elif self.hit.bar_width <= 0:
            pos_s, pos_c = "无条", WARN
        else:
            pos_s, pos_c = f"{self.hit.pos:.0f}", SUCCESS

        c_on = bool(getattr(self, "chk_c", None) is not None and self.chk_c.isChecked())
        cfg_txt = format_cast_count_range(
            self._settings.cast_count_lo, self._settings.cast_count_hi
        )
        if not c_on:
            cast_s, cast_c = "关", TEXT_FAINT
        elif pipe is not None and pipe.auto_cast.active:
            rem = pipe.auto_cast.remaining
            total = max(rem, int(pipe.auto_cast.batch_total) or 1)
            snap = pipe.bus.snapshot()
            phase = _CAST_PHASE_LABEL.get(snap.cast_phase, snap.cast_phase.value)
            cast_s, cast_c = f"{rem}/{total} · {phase}", ACCENT
        else:
            armed = bool(self._cursor_arm is not None and self._cursor_arm.armed)
            ready = "就绪" if armed else "等待"
            cast_s = f"{cfg_txt} · {ready}"
            cast_c = SUCCESS if armed else WARN

        act_on = pipe is not None and pipe.act_on
        intent = self._holding
        if not act_on:
            pull_s, pull_c = "关", TEXT_FAINT
        elif intent is True:
            pull_s, pull_c = "按", SUCCESS
        elif intent is False:
            pull_s, pull_c = "松", TEXT_MUTED
        else:
            pull_s, pull_c = "—", TEXT_MUTED

        if act_on and pipe is not None:
            pipe.act.poll()
            prog = pipe.act.pressed
            yielding = bool(pipe.act.yielding)
            snap = pipe.bus.snapshot()
            may_pull = False
            if snap.cast_phase != CastPhase.CHARGING:
                if snap.cast_session == CastSessionState.DISABLED:
                    may_pull = snap.fishing_state == FishingState.FISHING
                else:
                    may_pull = snap.cast_session == CastSessionState.FISHING
            free = (not may_pull) and (not yielding)
            os_d = os_left_down()
            controlling = not free and not yielding
            mismatch = False
            if controlling and intent is not None and prog is not None and intent != prog:
                mismatch = True
            if controlling and prog is not None and os_d is not None and prog != os_d:
                mismatch = True
            if mismatch:
                pull_s = f"{pull_s} · 异"
                pull_c = WARN

        hud.set_metrics(
            pos=pos_s,
            cast=cast_s,
            mouse=pull_s,
            pos_color=pos_c,
            cast_color=cast_c,
            mouse_color=pull_c,
        )

    def _refresh_hud_steady(self) -> None:
        hud = getattr(self, "_hud", None)
        if hud is None:
            return
        self._refresh_hud_metrics()
        a_on = bool(self.chk_a.isChecked())
        b_on = bool(self.chk_b.isChecked())
        pipe = self._pipe
        cast_on = bool(pipe is not None and pipe.auto_cast.active)
        snap = None if pipe is None else pipe.bus.snapshot()
        if cast_on and snap is not None:
            cp = snap.cast_phase
            if cp == CastPhase.CHARGING:
                hud.set_steady("cast_charge")
                return
            if cp == CastPhase.AIM:
                hud.set_steady("cast_aim")
                return
            if cp in (CastPhase.WAIT, CastPhase.DONE):
                hud.set_steady("cast_wait")
                return
        if not a_on and not b_on and not cast_on:
            hud.set_steady("idle")
            return
        if self._had_bobber:
            if self._holding is True:
                hud.set_steady("pull")
            else:
                hud.set_steady("release")
            return
        cs = CastSessionState.DISABLED if snap is None else snap.cast_session
        if a_on:
            if cs == CastSessionState.WAIT_BOBBER:
                hud.set_steady("wait_bobber")
            elif cs == CastSessionState.FIRST_CLICK:
                hud.set_steady("heard")
            elif cs == CastSessionState.FISHING:
                hud.set_steady("wait_bobber")
            elif cs == CastSessionState.WAIT:
                hud.set_steady("listen")
            else:
                hud.set_steady("listen")
            return
        if cast_on:
            hud.set_steady("cast_wait")
            return
        hud.set_steady("idle")

    def _policy_cfg_text(self) -> str:
        low, high = self._current_policy_thresholds()
        return f"配置 <{low:.1f}按 / >{high:.1f}松"

    def _pos_text(self, pos: float | None) -> str:
        if pos is None:
            return "pos=无"
        return f"pos={pos:.1f}"

    @staticmethod
    def _perm_style(ok: bool | None) -> str:
        if ok is True:
            return f"color:{SUCCESS}; font-weight:600;"
        if ok is False:
            return f"color:{DANGER}; font-weight:600;"
        return f"color:{TEXT_FAINT};"

    def _refresh_permissions(self) -> None:
        st = perms.current_status()
        self.lbl_perm_screen.setText(st.screen_label)
        self.lbl_perm_screen.setStyleSheet(self._perm_style(st.screen_ok))
        self.lbl_perm_input.setText(st.input_label)
        # Windows 非管理员标黄提示，不算硬失败
        if st.platform == "win32" and st.is_admin is False:
            self.lbl_perm_input.setStyleSheet(f"color:{WARN}; font-weight:600;")
        else:
            self.lbl_perm_input.setStyleSheet(self._perm_style(st.input_ok))
        if st.platform == "darwin":
            self.btn_perm_screen.setText("授权屏幕录制")
            self.btn_perm_input.setText("授权辅助功能")
            self.btn_perm_input.setEnabled(True)
            self.btn_perm_reset.setVisible(True)
        elif st.platform == "win32":
            self.btn_perm_screen.setText("测试截屏")
            self.btn_perm_reset.setVisible(False)
            if st.is_admin:
                self.btn_perm_input.setText("已是管理员")
                self.btn_perm_input.setEnabled(False)
            else:
                self.btn_perm_input.setText("以管理员重启")
                self.btn_perm_input.setEnabled(True)
        else:
            self.btn_perm_screen.setText("屏幕")
            self.btn_perm_input.setText("控鼠")
            self.btn_perm_reset.setVisible(False)

    def _on_stay_on_top_toggled(self, checked: bool) -> None:
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
        if was_visible:
            self.show()
        QTimer.singleShot(0, self._apply_no_minimize)
        self._persist_settings()

    def _on_save_bundled_defaults(self) -> None:
        self._persist_settings()
        try:
            path = save_bundled_shell_settings(self._settings)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "打包默认", str(exc))
            self.lbl_hint.setText(f"写入打包默认失败：{exc}")
            return
        self.lbl_hint.setText(f"已写入打包默认 · {path}")
        self._main_log(f"写入打包默认 · {path}")
        QMessageBox.information(
            self,
            "打包默认",
            f"已写入：\n{path}\n\n提交后打包即可带上当前玩法默认。",
        )

    def _on_restore_defaults(self) -> None:
        reply = QMessageBox.question(
            self,
            "恢复默认",
            "将把抛杆、拉漂、开钓和截图范围恢复为默认，并清空手动条界与参考图。\n"
            "模板、录音和授权会保留。\n\n"
            "继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._apply_factory_defaults()

    def _apply_factory_defaults(self) -> None:
        """用打包默认（否则内建缺省）覆盖壳配置，并恢复截图框。"""
        defaults = load_default_shell_settings()
        self._persist_timer.stop()

        self.chk_stay_on_top.blockSignals(True)
        self.chk_stay_on_top.setChecked(bool(defaults.stay_on_top))
        self.chk_stay_on_top.blockSignals(False)
        self.range_axis.setRanges(
            defaults.press_lo,
            defaults.press_hi,
            defaults.release_lo,
            defaults.release_hi,
            emit=False,
        )
        self.sld_press_interval.blockSignals(True)
        self.sld_press_interval.setValue(int(round(defaults.press_interval_s * 1000)))
        self.sld_press_interval.blockSignals(False)
        self.lbl_press_interval.setText(f"{defaults.press_interval_s:.2f}s")
        self.bar_delay.setRange(
            defaults.click_delay_lo_s, defaults.click_delay_hi_s, emit=False
        )
        self.bar_hold.setRange(
            defaults.click_hold_lo_s, defaults.click_hold_hi_s, emit=False
        )
        self.bar_after.setRange(
            defaults.click_after_lo_s, defaults.click_after_hi_s, emit=False
        )
        if self._sound_panel is not None:
            self._sound_panel.set_threshold_value(defaults.sound_threshold, emit=False)
            self._sound_panel.set_click_timing(
                defaults.click_delay_lo_s,
                defaults.click_delay_hi_s,
                defaults.click_hold_lo_s,
                defaults.click_hold_hi_s,
                defaults.click_after_lo_s,
                defaults.click_after_hi_s,
            )
            self._sound_panel.set_preferred_device_name("")
            trig = self._sound_panel.trigger
            if defaults.sound_enabled and trig is not None:
                trig.stop()

        self._settings = defaults
        self._reset_window_after_restore(bool(defaults.stay_on_top))

        self._block_checks(True)
        self.chk_b.setChecked(bool(defaults.auto_bobber_enabled))
        self.chk_a.setChecked(bool(defaults.sound_enabled))
        self.chk_c.setChecked(bool(defaults.auto_cast_enabled))
        self._block_checks(False)
        self._on_b_toggled(bool(defaults.auto_bobber_enabled))
        self._on_c_toggled(bool(defaults.auto_cast_enabled))
        if defaults.sound_enabled:
            self._activate_sound_session(persist=False)
        else:
            self._on_a_toggled(False)
        self._restore_default_roi()
        self._publish_press_interval()
        self._apply_cast_batch_from_settings()
        pipe = self._pipe
        if pipe is not None:
            pipe.cancel_cast_batch()

        self._persist_timer.stop()
        clean = load_default_shell_settings()
        self._settings = replace(
            clean,
            auto_bobber_enabled=bool(self.chk_b.isChecked()),
            sound_enabled=bool(self.chk_a.isChecked()),
            auto_cast_enabled=bool(self.chk_c.isChecked()),
            stay_on_top=bool(self.chk_stay_on_top.isChecked()),
        )
        save_shell_settings(self._settings)
        self.lbl_hint.setText("已恢复默认")
        self._main_log("已恢复默认")
        self._refresh_cast_label()

    def _reset_window_after_restore(self, stay_on_top: bool) -> None:
        """退出紧凑态，就地回到默认窗口尺寸。"""
        self._full_geo = None
        if self._compact:
            self._set_compact_mode(False, persist=False)
        else:
            anchor = self.geometry().topLeft()
            self.setMinimumSize(360, 480)
            self.resize(*_DEFAULT_FULL_SIZE)
            self.move(anchor)
            self._ensure_frame_on_screen()
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(stay_on_top))
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
        if was_visible:
            self.show()
        QTimer.singleShot(0, self._apply_no_minimize)

    def _on_perm_screen(self) -> None:
        msg = perms.request_screen_access()
        self.lbl_hint.setText(msg)
        self._refresh_permissions()

    def _on_perm_input(self) -> None:
        was_admin = perms.current_status().is_admin
        msg = perms.request_input_access()
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

    def _on_perm_reset(self) -> None:
        if sys.platform != "darwin":
            return
        reply = QMessageBox.question(
            self,
            "清理授权",
            "将尝试清除屏幕录制/辅助功能记录，并打开系统设置。\n"
            "完成后请：删掉旧条目 → 退出本程序 → 再打开并重新授权。\n\n"
            "继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        msg = perms.reset_macos_tcc()
        self.lbl_hint.setText(msg)
        self._refresh_permissions()
        QMessageBox.information(self, "清理授权", msg)

    def _reload_roi(self) -> None:
        try:
            if self.roi_path.exists():
                self.roi = load_roi(self.roi_path)
                src = load_roi_source(self.roi_path)
                self.phase = READY
                tag = "手动" if src == ROI_SOURCE_MANUAL else "默认"
                self.lbl_hint.setText(f"ROI 已载入（{tag}）")
                self._cal_log(
                    f"载入 ROI {self.roi.width}x{self.roi.height} · {tag}"
                )
                self._apply_saved_bar_mark()
                self._load_bar_ref_image()
                if load_bar_mark(self.roi_path) is not None:
                    self._cal_log("已载入上次条界标记")
                return
            # 无存盘：主屏居中 1/4×1/4 默认框
            self._apply_default_roi(persist=True, reason="启动无存盘")
        except Exception as exc:  # noqa: BLE001
            self.roi = None
            self.lbl_hint.setText(f"ROI 失败：{exc}")

    def _apply_default_roi(self, *, persist: bool, reason: str) -> None:
        """写入/应用居中默认框。persist 时存盘 source=default。"""
        sw, sh = primary_screen_size()
        self.roi = default_center_roi(sw, sh)
        if persist:
            save_roi(self.roi, self.roi_path, source=ROI_SOURCE_DEFAULT)
        self.phase = READY
        self.lbl_hint.setText("默认居中框")
        self._cal_log(
            f"{reason} · 默认 ROI {self.roi.width}x{self.roi.height} "
            f"@({self.roi.left},{self.roi.top}) · 屏 {sw}x{sh}"
        )

    def _restore_default_roi(self) -> None:
        """恢复默认框（覆盖手动存盘）；清空条界与参考图。"""
        if self.phase == SELECT:
            self.monitor.set_selecting(False)
        if self._pipe and self._pipe.monitor_on:
            self._pipe.stop_monitor()
            self.frame = None
            self.hit = None
        self._clear_bar_on_rebox()
        self._apply_default_roi(persist=True, reason="恢复默认框")
        pipe = self._ensure_pipe()
        pipe.set_roi_manual(self.roi)
        self._sync_buttons()
        self._refresh_monitor()
        self._ensure_monitor_on()
        self._resume_input_after_select()
        self.lbl_hint.setText("已恢复默认框 · 监控中")
        self._cal_log("已恢复默认居中框并开监控")

    def _apply_saved_bar_mark(self) -> None:
        mark = load_bar_mark(self.roi_path)
        box = None
        if mark is not None and self.roi is not None:
            fw, _fh = roi_frame_size(self.roi)
            box = mark.box_for_frame(fw, self.roi.width)
        apply_manual_bar(box)
        self.bar_canvas.set_manual_bar(box)

    def _load_bar_ref_image(self) -> None:
        ref = bar_ref_path(self.roi_path)
        if not ref.is_file():
            self._bar_ref_saved = False
            return
        try:
            import cv2

            bgr = cv2.imread(str(ref))
            if bgr is None:
                return
            rgb = np.ascontiguousarray(bgr[:, :, ::-1])
            if self.roi is not None:
                fw, fh = roi_frame_size(self.roi)
                if rgb.shape[1] != fw or rgb.shape[0] != fh:
                    rgb = cv2.resize(rgb, (fw, fh), interpolation=cv2.INTER_LINEAR)
            self.bar_canvas.set_rgb(rgb)
            self._bar_ref_saved = True
            # 蓝框：优先读同帧元数据；否则临时识别器（禁止污染直播单例的 follow）
            box = self._load_bar_ref_meta()
            if box is None:
                try:
                    tmp = BobberAnchorDetector()
                    hit = tmp.detect(rgb)
                    box = self._bar_box_from_hit(hit)
                    if box is None:
                        box = tmp.program_bar
                except Exception as det_exc:  # noqa: BLE001
                    self._cal_log(f"参考图条界识别失败：{det_exc}")
            self.bar_canvas.set_program_bar(box)
            # 参考图/meta 只用于显示蓝框；程序锁必须由直播帧定界，禁止注入过期条界
        except Exception as exc:  # noqa: BLE001
            self._cal_log(f"参考图载入失败：{exc}")

    def _load_bar_ref_meta(self) -> tuple[float, float, float, float] | None:
        meta = bar_ref_meta_path(self.roi_path)
        if not meta.is_file():
            return None
        try:
            raw = json.loads(meta.read_text(encoding="utf-8"))
            box = raw.get("program_bar")
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                return None
            left, top, bw, bh = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
            if bw < 8.0 or bh < 0.0:
                return None
            return (left, top, bw, bh)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def _write_bar_ref_meta(
        self, bar_box: tuple[float, float, float, float] | None
    ) -> None:
        meta = bar_ref_meta_path(self.roi_path)
        if bar_box is None:
            if meta.is_file():
                meta.unlink()
            return
        meta.write_text(
            json.dumps({"program_bar": list(bar_box)}, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _bar_box_from_hit(hit: object | None) -> tuple[float, float, float, float] | None:
        if hit is None:
            return None
        bw = float(getattr(hit, "bar_width", 0.0) or 0.0)
        if bw <= 0:
            return None
        return (
            float(hit.bar_left),
            float(hit.bar_top),
            bw,
            float(hit.bar_height),
        )

    def _save_bar_ref(
        self,
        rgb: np.ndarray,
        *,
        bar_box: tuple[float, float, float, float] | None = None,
    ) -> None:
        import cv2

        ref = bar_ref_path(self.roi_path)
        ref.parent.mkdir(parents=True, exist_ok=True)
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        cv2.imwrite(str(ref), bgr)
        self._write_bar_ref_meta(bar_box)
        self.bar_canvas.set_rgb(rgb)
        # 蓝框必须与参考图像素同帧，避免实时锁叠到旧图上错位
        self.bar_canvas.set_program_bar(bar_box)
        self._bar_ref_saved = True
        if bar_box is not None and load_bar_mark(self.roi_path) is None:
            apply_program_bar(bar_box)

    def _clear_manual_marks_only(self) -> None:
        """只清手动黄线（磁盘 + 识别器 + 画布），保留程序锁以便继续跟 pos。"""
        clear_bar_mark(self.roi_path)
        apply_manual_bar(None)
        self.bar_canvas.set_manual_bar(None)

    def _refresh_bar_ref(self) -> None:
        """清旧参考图与手动黄线，等待下一帧「有漂且有条」再落新图。

        故意不清程序锁：全图色种定界不稳，清锁后容易再也锁不上 → pos 永久无。
        """
        if self._bar_ref_wait_bobber:
            self._bar_ref_wait_bobber = False
            self.btn_bar_refresh.setText("刷新参考图")
            self._cal_log("已取消等待参考图")
            self.lbl_hint.setText("已取消等待参考图")
            return
        clear_bar_ref(self.roi_path)
        self._clear_manual_marks_only()
        self.bar_canvas.set_program_bar(None)
        self.bar_canvas.set_rgb(None)
        self._bar_ref_saved = False
        self._bar_ref_wait_bobber = True
        self.btn_bar_refresh.setText("等待鱼漂…")
        self._cal_log("已清除旧参考图与手动标记 · 等待有条的鱼漂帧（保留程序锁）")
        self.lbl_hint.setText("旧图已清 · 等待有条命中后更新参考图")

    def _maybe_commit_bar_ref_wait(self, event: PosEvent) -> None:
        if not self._bar_ref_wait_bobber:
            return
        if event.hit is None or event.frame is None:
            return
        # 必须有条：仅漂帧落盘会导致无蓝框，且打断定界
        box = self._bar_box_from_hit(event.hit)
        if box is None:
            return
        self._clear_manual_marks_only()
        self._save_bar_ref(event.frame, bar_box=box)
        self._bar_ref_wait_bobber = False
        self.btn_bar_refresh.setText("刷新参考图")
        self._cal_log("已刷新条界参考图（有条）· 可拖黄线微调左右界")
        self.lbl_hint.setText("参考图已更新")

    def _clear_manual_bar(self) -> None:
        clear_bar_mark(self.roi_path)
        apply_manual_bar(None)
        self.bar_canvas.clear_manual()
        self._cal_log("已清除手动条界")

    def _on_manual_bar_changed(self, box: object) -> None:
        if self.roi is None:
            return
        if box is None:
            clear_bar_mark(self.roi_path)
            apply_manual_bar(None)
            return
        left, top, bw, bh = box  # type: ignore[misc]
        fw, _fh = roi_frame_size(self.roi)
        mark = BarMark(
            left=float(left),
            right=float(left) + float(bw),
            top=float(top),
            height=float(bh),
            frame_width=float(fw),
        )
        save_roi(self.roi, self.roi_path, bar=mark)
        apply_manual_bar(mark.as_box())

    def _clear_bar_on_rebox(self) -> None:
        clear_bar_mark(self.roi_path)
        clear_bar_ref(self.roi_path)
        apply_manual_bar(None)
        clear = getattr(get_detector(), "clear_bar_lock", None)
        if callable(clear):
            clear()
        self.bar_canvas.set_manual_bar(None)
        self.bar_canvas.set_program_bar(None)
        self.bar_canvas.set_rgb(None)
        self._bar_ref_saved = False
        self._bar_ref_wait_bobber = False
        self.btn_bar_refresh.setText("刷新参考图")

    def _ensure_pipe(self) -> AutofishPipeline:
        if self._pipe is None:
            s = self._settings
            pipe = AutofishPipeline(
                capture_fps=30.0,
                cast_wait_lo_s=s.cast_wait_lo_s,
                cast_wait_hi_s=s.cast_wait_hi_s,
                cast_full_charge_s=s.cast_full_charge_s,
            )
            pipe.subscribe(Topic.FRAME, self._on_frame_bus)
            pipe.subscribe(Topic.POS, self._on_pos_bus)
            pipe.subscribe(Topic.ACTION_INTENT, self._on_intent_bus)
            self._pipe = pipe
            self._publish_press_interval()
            if self._sound_panel is not None:
                self._sound_panel.attach_bus(pipe.bus)
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
        self._settings = replace(
            self._settings,
            press_interval_s=self.sld_press_interval.value() / 1000.0,
        )
        self._persist_settings()
        self._cal_log(f"按下间隔 {self.lbl_press_interval.text()}")

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
        self._update_bar_panel(event)
        if self._pipe is not None and self._pipe.decide_on:
            self._refresh_strategy(event.pos, self._intent_reason)
        # 游戏开始/结束：以是否识别到鱼漂为准
        has_bobber = event.hit is not None
        prev = self._had_bobber
        if prev is not None and has_bobber != prev:
            hud = getattr(self, "_hud", None)
            if has_bobber:
                if event.hit is not None and event.hit.bar_width > 0:
                    self._main_log(
                        f"游戏开始 · 出漂 pos={event.hit.pos:.1f} · {self._policy_cfg_text()}"
                    )
                else:
                    self._main_log(f"游戏开始 · 出漂（暂无条） · {self._policy_cfg_text()}")
                if hud is not None:
                    hud.flash("game_start")
            else:
                self._main_log(f"游戏结束 · 丢漂 · {self._policy_cfg_text()}")
                if hud is not None:
                    hud.flash("game_end")
        self._had_bobber = has_bobber
        self._refresh_hud_steady()

    def _update_bar_panel(self, event: PosEvent) -> None:
        det = get_detector()
        if self._bar_ref_wait_bobber:
            # 刷新等待中：只接受有条帧，避免无条落盘抢走状态
            self._maybe_commit_bar_ref_wait(event)
        elif (
            event.hit is not None
            and event.frame is not None
            and not self._bar_ref_saved
        ):
            # 尚无参考图：有漂即出图；有条则写蓝框并 seed 程序锁
            box = self._bar_box_from_hit(event.hit)
            self._save_bar_ref(event.frame, bar_box=box)
            if box is None:
                self._cal_log("已出条界参考图（有漂·无条，可手动标左右）")
            else:
                self._cal_log("已自动保存条界参考图")
        # 参考图已存但尚无蓝框：用「本帧有条」整体替换，保证蓝框与像素同帧
        if (
            self._bar_ref_saved
            and not self._bar_ref_wait_bobber
            and self.bar_canvas.program_bar is None
            and event.frame is not None
            and event.hit is not None
            and event.hit.bar_width > 0
        ):
            self._save_bar_ref(
                event.frame, bar_box=self._bar_box_from_hit(event.hit)
            )
            self._cal_log("参考图已补蓝框（同帧条界）")
        # 已有冻结参考图时，不用实时 program_bar 覆盖蓝框（会与旧图像素错位）
        man = getattr(det, "manual_bar", None)
        if man is not None:
            self.bar_canvas.set_manual_bar(man)

    def _maybe_refresh_monitor(self, *, force: bool = False) -> None:
        now = time.perf_counter()
        if not force and (now - self._mon_ui_ts) < self._mon_ui_min_dt:
            return
        self._mon_ui_ts = now
        self._refresh_monitor()

    def _note_detect_ms(self, ms: float) -> None:
        """累计识别耗时；每 2s 记一条（仅本窗口，打完清空，避免尖峰粘住）。"""
        if ms <= 0:
            return
        self._ms_window.append(ms)
        now = time.time()
        if now - self._ms_log_ts < 2.0 or not self._ms_window:
            return
        self._ms_log_ts = now
        vals = list(self._ms_window)
        self._ms_window.clear()
        avg = sum(vals) / len(vals)
        fps = 1000.0 / avg if avg > 0 else 0.0
        det = get_detector()
        mode = "条内" if getattr(det, "bar_locked", False) else "全图"
        self._cal_log(
            f"识别 {det.name}[{mode}] 均 {avg:.1f}ms"
            f" 最大 {max(vals):.1f}ms 最小 {min(vals):.1f}ms"
            f" ≈{fps:.0f} FPS（近{len(vals)}帧）"
        )

    def _on_intent_ui(self, event: ActionIntentEvent) -> None:
        prev = self._holding
        self._holding = event.holding
        self._intent_reason = event.reason
        self._refresh_strategy(event.pos, event.reason)
        cfg = self._policy_cfg_text()
        pos_s = self._pos_text(event.pos)
        reason = f" · {event.reason}" if event.reason else ""
        if event.holding and prev is not True:
            self._cal_log(f"开始拉漂 · {pos_s} · {cfg}{reason}")
            hud = getattr(self, "_hud", None)
            if hud is not None and self._had_bobber:
                hud.note_last("拉漂")
        elif (not event.holding) and prev is True:
            self._cal_log(f"结束拉漂 · {pos_s} · {cfg}{reason}")
            hud = getattr(self, "_hud", None)
            if hud is not None and self._had_bobber:
                hud.note_last("松漂")
        self._refresh_mouse()
        self._refresh_hud_steady()

    def _refresh_strategy(
        self, pos: float | None = None, reason: str = ""
    ) -> None:
        self._refresh_b_meta()
        self._refresh_mouse()

    def _current_policy_thresholds(self) -> tuple[float, float]:
        pipe = self._pipe
        if pipe is not None and pipe.decide_on:
            return pipe.decide.current_thresholds
        plo, phi, rlo, rhi = self.range_axis.ranges()
        return (plo + phi) / 2.0, (rlo + rhi) / 2.0

    def _refresh_b_meta(self) -> None:
        """B 行弱说明：策略阈值 + 耗时 + 拉漂态，一行扫完。"""
        parts: list[str] = []
        pipe = self._pipe
        if pipe is not None and pipe.decide_on:
            low, high = self._current_policy_thresholds()
            parts.append(f"<{low:.1f} 按 · >{high:.1f} 松")
        ms = float(getattr(self, "_last_detect_ms", 0.0) or 0.0)
        if ms > 0:
            parts.append(f"{ms:.0f} ms")
        if self._holding is True:
            parts.append("按住")
        elif self._holding is False and pipe is not None and pipe.decide_on:
            parts.append("松开")
        self.lbl_strat_detail.setText(" · ".join(parts))
        perf = getattr(self, "lbl_perf", None)
        if perf is not None:
            perf.setText("")

    def _refresh_pos(self) -> None:
        if self.hit is None:
            self.lbl_pos.setText("—")
            tone = "faint"
        elif self.hit.bar_width <= 0:
            self.lbl_pos.setText("无条")
            tone = "warn"
        else:
            self.lbl_pos.setText(f"{self.hit.pos:.1f}")
            tone = "ok"
        paint_tone(self.lbl_pos, tone)
        self._refresh_b_meta()
        self._refresh_hud_metrics()

    def _refresh_monitor(self) -> None:
        if self.phase == SELECT and self.screen_grab is not None:
            self.monitor.set_rgb(self.screen_grab.rgb)
            self.monitor.set_selecting(True)
            return
        self.monitor.set_selecting(False)
        if self.frame is None:
            self.monitor.set_rgb(None)
            return
        self.monitor.set_rgb(overlay_hit(self.frame, self.hit))

    def _sync_buttons(self) -> None:
        selecting = self.phase == SELECT
        self.btn_confirm.setEnabled(selecting)
        self.btn_cancel.setEnabled(selecting)
        self.btn_capture.setEnabled(not selecting)
        self.btn_rebox.setEnabled(not selecting and DEFAULT_SCREEN_PATH.exists())
        self.btn_roi_default.setEnabled(not selecting)

    def _block_checks(self, block: bool) -> None:
        for chk in (self.chk_b, self.chk_a, self.chk_c):
            chk.blockSignals(block)

    def _on_c_toggled(self, checked: bool) -> None:
        """自动抛杆 = 工人待命 + 光标旁认漂 + 右键 / F8·F9。"""
        if checked:
            pipe = self._ensure_pipe()
            self._apply_cast_wait_from_settings()
            self._apply_cast_full_charge_from_settings()
            if not pipe.auto_cast_on:
                pipe.start_auto_cast()
            self._start_cursor_arm()
            self._cast_right_click.start()
            self._main_log("自动抛竿 ON · 认漂后右键开始 / 再右键结束")
            self._cast_log("自动抛竿模块开")
        else:
            pipe = self._pipe
            if pipe is not None:
                pipe.cancel_cast_batch()
                if pipe.auto_cast_on:
                    pipe.stop_auto_cast()
            self._stop_cursor_arm()
            self._cast_right_click.stop()
            self._cast_paused_for_select = False
            self._cast_paused_remaining = 0
            self._main_log("自动抛竿 OFF")
            self._cast_log("自动抛竿模块关")
        self._refresh_cast_label()
        self._refresh_hud_steady()
        self._persist_settings()

    def _bind_cast_ready(self) -> None:
        """每一杆只有光标是鱼漂（就绪）才抛。"""
        pipe = self._pipe
        if pipe is None:
            return
        arm = self._cursor_arm
        if arm is None or not self.chk_c.isChecked():
            pipe.auto_cast.set_cast_ready(None)
            return
        pipe.auto_cast.set_cast_ready(lambda: bool(arm.armed))

    def _start_cursor_arm(self) -> None:
        if self._cursor_arm is None:
            self._cursor_arm = CursorArmWatcher(
                # 认漂加严后，偏保守的判定会偶尔让单帧漏判；轮询间隔越大，
                # 漏判后等下一帧刷新「就绪」的感知延迟就越明显。读一次系统光标
                # 位图 + 判定共计 <1ms（数量级远小于间隔本身），调低间隔不会
                # 带来明显开销，换取更快跟手。
                interval_s=0.1,
                size=100,
                on_armed_changed=lambda armed: self._arm_bridge.armed_changed.emit(
                    bool(armed)
                ),
                on_frame=lambda rgb, armed: self._arm_bridge.frame.emit(rgb, bool(armed)),
            )
        self._cursor_arm.start()
        self._cursor_arm.set_enabled(True)
        self._bind_cast_ready()
        self._set_arm_preview_visible(True)

    def _stop_cursor_arm(self) -> None:
        if self._cursor_arm is None:
            self._bind_cast_ready()
            self._set_arm_preview_visible(False)
            return
        self._cursor_arm.set_enabled(False)
        self._cursor_arm.stop()
        self._last_armed = None
        self._bind_cast_ready()
        self._set_arm_preview_visible(False)

    def _set_arm_preview_visible(self, visible: bool) -> None:
        prev = getattr(self, "lbl_arm_preview", None)
        if prev is None:
            return
        if visible:
            prev.show()
        else:
            prev.clear()
            prev.hide()

    def _paint_arm_border(self, armed: bool) -> None:
        prev = getattr(self, "lbl_arm_preview", None)
        if prev is None or not prev.isVisible():
            return
        color = SUCCESS if armed else BORDER
        prev.setStyleSheet(
            f"background:{BORDER}; border:2px solid {color}; border-radius:4px;"
        )

    def _on_cursor_arm_frame(self, rgb: object, armed: bool) -> None:
        if not self.chk_c.isChecked():
            return
        prev = getattr(self, "lbl_arm_preview", None)
        if prev is None:
            return
        arr = np.asarray(rgb)
        if arr.ndim != 3 or arr.shape[2] < 3:
            return
        h, w = int(arr.shape[0]), int(arr.shape[1])
        # 系统光标 RGBA：画在深底上，透明处露底
        if arr.shape[2] >= 4:
            rgba = np.ascontiguousarray(arr[..., :4], dtype=np.uint8)
            qimg = QImage(rgba.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()
        else:
            rgb8 = np.ascontiguousarray(arr[..., :3], dtype=np.uint8)
            qimg = QImage(rgb8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg).scaled(
            prev.width(),
            prev.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        prev.setPixmap(pix)
        self._paint_arm_border(bool(armed))

    def _on_cursor_armed_changed(self, armed: bool) -> None:
        """只刷新门闩文案与边框，不写状态日志（避免刷屏）。"""
        armed = bool(armed)
        if self._last_armed is not None and self._last_armed == armed:
            return
        self._last_armed = armed
        if not self.chk_c.isChecked():
            return
        self._paint_arm_border(armed)
        self._refresh_cast_label()

    def _on_cast_right_click(self) -> None:
        """系统右键：任务进行中 → 立刻结束（不要求认漂）；可开抛且空闲 → 开始；否则不抢。"""
        if not self.chk_c.isChecked():
            return
        pipe = self._ensure_pipe()
        # 进行中任意阶段（蓄力 / 等漂 / 等待）右键都停，不依赖认漂
        if pipe.auto_cast.active:
            self._on_cast_hotkey_stop(via="右键")
            return
        armed = bool(self._cursor_arm is not None and self._cursor_arm.armed)
        if not armed:
            return
        self._on_cast_hotkey_start()

    def _on_b_toggled(self, checked: bool) -> None:
        """自动拉漂 = Decide + Act。"""
        pipe = self._ensure_pipe()
        if checked:
            if not self._apply_policy():
                self._block_checks(True)
                self.chk_b.setChecked(False)
                self._block_checks(False)
                self._persist_settings()
                return
            self._ensure_monitor_on()
            if not pipe.decide_on:
                pipe.start_decide()
            if not pipe.act_on:
                pipe.start_act()
            self._refresh_strategy(
                None if self.hit is None else self.hit.pos
            )
            low, high = self._current_policy_thresholds()
            self._main_log(f"自动拉线 ON · 配置 <{low:.1f}按 / >{high:.1f}松")
        else:
            if pipe.act_on:
                pipe.stop_act()
            if pipe.decide_on:
                pipe.stop_decide()
            self._holding = None
            self._refresh_strategy()
            self._main_log("自动拉线 OFF")
        self._refresh_mouse()
        self._refresh_hud_steady()
        self._persist_settings()

    def _on_a_toggled(self, checked: bool) -> None:
        """声音开钓 = 会话机。勾选即偏好；启动失败不取消勾选，以免抹掉持久化。"""
        if not checked:
            if self._sound_panel is not None:
                self._sound_panel.set_session_enabled(False)
            self.lbl_hint.setText("自动起勾已关")
            self._main_log("自动起勾 OFF")
            self._refresh_hud_steady()
            self._persist_settings()
            return
        self._activate_sound_session(persist=True)

    def _activate_sound_session(self, *, persist: bool) -> bool:
        """尝试开监听+会话。成功 True；失败保留勾选，只提示。"""
        pipe = self._ensure_pipe()
        if self._sound_panel is None:
            self.lbl_hint.setText("自动起勾失败：面板未就绪")
            self._main_log("自动起勾失败：面板未就绪")
            self._refresh_hud_steady()
            if persist:
                self._persist_settings()
            return False
        self._sound_panel.attach_bus(pipe.bus)
        try:
            self._sound_panel.set_session_enabled(True)
            t = self._sound_panel.trigger
            if t is None or not t.has_template or not t.is_running():
                self._sound_panel.set_session_enabled(False)
                self.lbl_hint.setText(
                    "自动起勾未就绪：请到「自动起勾」页确认设备与模板后重试"
                )
                self._main_log("自动起勾未就绪 · 已保留勾选")
                self._refresh_hud_steady()
                if persist:
                    self._persist_settings()
                return False
            self.lbl_hint.setText("自动起勾中")
            self._main_log("自动起勾 ON")
            self._refresh_hud_steady()
            if persist:
                self._persist_settings()
            return True
        except Exception as exc:  # noqa: BLE001
            try:
                self._sound_panel.set_session_enabled(False)
            except Exception:  # noqa: BLE001
                pass
            self.lbl_hint.setText(f"自动起勾失败：{exc}")
            self._main_log(f"自动起勾失败：{exc} · 已保留勾选")
            self._refresh_hud_steady()
            if persist:
                self._persist_settings()
            return False

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
        self._persist_settings()
        self._cal_log(
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

    def _paint_mouse_metric(self, lbl: QLabel, text: str, color: str) -> None:
        lbl.setText(text)
        lbl.setStyleSheet(f"font-size:15px; font-weight:700; color:{color};")

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
        may_pull = False
        if snap is not None and snap.cast_phase != CastPhase.CHARGING:
            if snap.cast_session == CastSessionState.DISABLED:
                may_pull = snap.fishing_state == FishingState.FISHING
            else:
                may_pull = snap.cast_session == CastSessionState.FISHING
        free = act_on and not may_pull and not yielding

        if not act_on:
            prog_s, prog_c = "关", TEXT_FAINT
        elif yielding:
            prog_s, prog_c = "让", WARN
        elif free:
            prog_s, prog_c = "闲", TEXT_FAINT
        else:
            prog_s = _hold_word(prog)
            prog_c = WARN if prog else SUCCESS

        intent_s = _hold_word(intent) if intent is not None else "—"
        intent_c = SUCCESS if intent else TEXT_MUTED
        sys_s = _hold_word(os_down)
        sys_c = SUCCESS if os_down else TEXT_MUTED

        intent_lbl = getattr(self, "lbl_mouse_intent", None)
        prog_lbl = getattr(self, "lbl_mouse_prog", None)
        sys_lbl = getattr(self, "lbl_mouse_sys", None)
        if intent_lbl is not None and prog_lbl is not None and sys_lbl is not None:
            self._paint_mouse_metric(intent_lbl, intent_s, intent_c)
            self._paint_mouse_metric(prog_lbl, prog_s, prog_c)
            self._paint_mouse_metric(sys_lbl, sys_s, sys_c)

        act = getattr(self, "lbl_b_act", None)
        if act is not None:
            if not act_on:
                act.setText("关")
                paint_tone(act, "faint")
            elif intent is True:
                act.setText("按住")
                paint_tone(act, "hold")
            elif intent is False:
                act.setText("松开")
                paint_tone(act, "release")
            else:
                act.setText("—")
                paint_tone(act, "idle")

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
            issues.append("系统态不可读")

        if issues:
            if not self._mouse_mismatch_logged:
                self._mouse_mismatch_logged = True
                self._cal_log(
                    "鼠标异常 "
                    + " / ".join(issues)
                    + f" · 意图={intent_s}"
                    + f" 程序={prog_s}"
                    + f" 系统={sys_s}"
                )
        else:
            self._mouse_mismatch_logged = False
        self._refresh_hud_metrics()

    def _pause_input_for_select(self) -> None:
        """框选期间停 Act 并松键（Windows 合成左键按住会吞掉确认点击）。"""
        pipe = self._pipe
        if pipe is not None and pipe.act_on:
            pipe.stop_act()
            self._act_paused_for_select = True
            self._cal_log("框选中 · 已暂停控鼠")
        self._pause_cast_for_select()
        # 已暂停则保持标志，避免重入把恢复机会清掉

    def _pause_cast_for_select(self) -> None:
        pipe = self._pipe
        if pipe is not None and pipe.auto_cast.active:
            self._cast_paused_remaining = max(1, int(pipe.auto_cast.remaining))
            pipe.cancel_cast_batch()
            self._cast_paused_for_select = True
            self._cast_log("框选中 · 已暂停抛杆任务")
            self._refresh_cast_label()

    def _resume_input_after_select(self) -> None:
        """框选结束：若进入前开着自动拉漂，则恢复 Act。"""
        if not self._act_paused_for_select:
            self._resume_cast_after_select()
            return
        self._act_paused_for_select = False
        if not self.chk_b.isChecked():
            self._resume_cast_after_select()
            return
        pipe = self._ensure_pipe()
        if not pipe.act_on:
            pipe.start_act()
            self._cal_log("框选结束 · 已恢复控鼠")
        self._resume_cast_after_select()

    def _resume_cast_after_select(self) -> None:
        if not self._cast_paused_for_select:
            return
        rem = self._cast_paused_remaining
        self._cast_paused_for_select = False
        self._cast_paused_remaining = 0
        if rem <= 0 or not self.chk_c.isChecked():
            return
        pipe = self._ensure_pipe()
        if not pipe.auto_cast_on:
            pipe.start_auto_cast()
        if pipe.start_cast_batch(rem):
            self._cast_log(f"框选结束 · 已恢复抛杆 · 剩 {rem}")
            self._refresh_cast_label()

    def _capture_fullscreen(self) -> None:
        self._pause_input_for_select()
        if self._pipe and self._pipe.monitor_on:
            self._pipe.stop_monitor()
            self._cal_log("暂停截图 · 准备框选")
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
            self._cal_log("已截全屏 · 请手框 ROI")
        except Exception as exc:  # noqa: BLE001
            self._resume_input_after_select()
            self.lbl_hint.setText(f"截图失败：{exc}")
            QMessageBox.warning(self, "截屏失败", str(exc))
        self._sync_buttons()

    def _load_screen_for_select(self) -> None:
        self._pause_input_for_select()
        if self._pipe and self._pipe.monitor_on:
            self._pipe.stop_monitor()
            self.frame = None
            self.hit = None
            self._cal_log("暂停截图 · 准备重框")
            self._clear_bar_on_rebox()
        try:
            self.screen_grab = load_screen(DEFAULT_SCREEN_PATH)
            self.phase = SELECT
            self.monitor.set_rgb(self.screen_grab.rgb)
            self.monitor.set_selecting(True)
            self.lbl_hint.setText("拖拽框选 → 确认框选")
        except Exception as exc:  # noqa: BLE001
            self._resume_input_after_select()
            self.lbl_hint.setText(f"读截图失败：{exc}")
        self._sync_buttons()

    def _confirm_selection(self) -> None:
        sel = self.monitor.selection_in_image()
        if sel is None or self.screen_grab is None:
            self.lbl_hint.setText("框太小或未拖出有效选区")
            return
        left, top, w, h = sel
        g = self.screen_grab
        try:
            roi = Roi(
                left=g.origin_left + left,
                top=g.origin_top + top,
                width=w,
                height=h,
            )
            save_roi(roi, self.roi_path, source=ROI_SOURCE_MANUAL)
        except Exception as exc:  # noqa: BLE001
            self.lbl_hint.setText(f"确认失败：{exc}")
            QMessageBox.warning(self, "确认框选", str(exc))
            return
        self._clear_bar_on_rebox()
        self.roi = roi
        self.phase = READY
        self.monitor.set_selecting(False)
        pipe = self._ensure_pipe()
        pipe.set_roi_manual(roi)
        self._cal_log(f"手动手框 {roi.width}x{roi.height} · 已存盘并同步 mss")
        self._sync_buttons()
        self._refresh_monitor()
        self._ensure_monitor_on()
        self._resume_input_after_select()

    def _ensure_monitor_on(self) -> None:
        """有 ROI 则常开 Capture+Detect（不启抛杆工人；抛杆由 C 勾选控制）。"""
        if self.roi is None:
            return
        pipe = self._ensure_pipe()
        pipe.set_roi_manual(self.roi)
        self._apply_saved_bar_mark()
        if not pipe.monitor_on:
            pipe.start_monitor()
            self._cal_log("Capture+Detect 常开")
        # 等待 / 满蓄可先写入工人，即使 C 未开
        self._apply_cast_wait_from_settings()
        self._apply_cast_full_charge_from_settings()
        self.lbl_hint.setText("监控中")

    def _cancel_selection(self) -> None:
        self.phase = READY if self.roi is not None else IDLE
        self.monitor.set_selecting(False)
        self.lbl_hint.setText("已取消框选")
        self._sync_buttons()
        self._refresh_monitor()
        if self.roi is not None:
            self._ensure_monitor_on()
        self._resume_input_after_select()

    def _on_cast_hotkey_start(self) -> None:
        if not self.chk_c.isChecked():
            return
        pipe = self._ensure_pipe()
        self._apply_cast_wait_from_settings()
        self._apply_cast_full_charge_from_settings()
        if not pipe.auto_cast_on:
            pipe.start_auto_cast()
        self._bind_cast_ready()
        n = sample_cast_batch_count(
            self._settings.cast_count_lo, self._settings.cast_count_hi
        )
        if not pipe.start_cast_batch(n):
            self._cast_log("抛杆任务进行中 · 忽略开始")
        else:
            clo, chi = self._settings.cast_count_lo, self._settings.cast_count_hi
            lo, hi = self._settings.cast_wait_lo_s, self._settings.cast_wait_hi_s
            self._cast_log(
                f"开始抛杆 · {n} 次（配置 {format_cast_count_range(clo, chi)}）"
                f" · 等待 {lo:.1f}～{hi:.1f}s"
            )
            self._main_log(f"抛杆开始 · {n} 次")
        self._refresh_cast_label()

    def _on_cast_hotkey_stop(self, *, via: str = "快捷键") -> None:
        if not self.chk_c.isChecked():
            return
        pipe = self._pipe
        if pipe is None or not pipe.auto_cast.active:
            return
        pipe.cancel_cast_batch()
        self._cast_paused_for_select = False
        self._cast_paused_remaining = 0
        self._cast_log(f"已结束抛竿任务（{via}）")
        self._main_log(f"抛竿结束 · {via}")
        self._refresh_cast_label()

    def _on_cast_count_changed(self, lo: float, hi: float) -> None:
        a, b = int(round(lo)), int(round(hi))
        self._patch_settings(cast_count_lo=a, cast_count_hi=b)
        self._cast_log(f"次数区间 {format_cast_count_range(a, b)}")
        self._refresh_cast_label()

    def _on_cast_start_hotkey_changed(self, seq: QKeySequence) -> None:
        key = self._keyseq_to_hotkey(seq, default=self._settings.cast_start_hotkey)
        stop = self._settings.cast_stop_hotkey
        if key == stop:
            stop = "F9" if key == "F8" else "F8"
        self._patch_settings(cast_start_hotkey=key, cast_stop_hotkey=stop)
        self._apply_cast_hotkey_edits(key, stop)
        self._apply_cast_hotkeys_from_settings()
        self._cast_log(f"开始键 {key}")
        self._refresh_cast_label()

    def _on_cast_stop_hotkey_changed(self, seq: QKeySequence) -> None:
        key = self._keyseq_to_hotkey(seq, default=self._settings.cast_stop_hotkey)
        start = self._settings.cast_start_hotkey
        if key == start:
            start = "F8" if key == "F9" else "F9"
        self._patch_settings(cast_start_hotkey=start, cast_stop_hotkey=key)
        self._apply_cast_hotkey_edits(start, key)
        self._apply_cast_hotkeys_from_settings()
        self._cast_log(f"结束键 {key}")
        self._refresh_cast_label()

    def _on_cast_wait_changed(self, lo: float, hi: float) -> None:
        self._patch_settings(cast_wait_lo_s=float(lo), cast_wait_hi_s=float(hi))
        pipe = self._pipe
        if pipe is not None:
            pipe.set_cast_wait_range(lo, hi)
        self._cast_log(f"等待区间 {lo:.1f}～{hi:.1f}s")

    def _on_cast_full_charge_changed(self, value: float) -> None:
        self._patch_settings(cast_full_charge_s=float(value))
        pipe = self._pipe
        if pipe is not None:
            pipe.set_cast_full_charge_s(float(value))
        self._cast_log(f"满蓄秒数 {float(value):.2f}s")

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cast_hotkeys.stop()
        self._cast_right_click.stop()
        self._stop_cursor_arm()
        if self._persist_timer.isActive():
            self._persist_timer.stop()
        self._persist_settings()
        if self._backtest_panel is not None:
            self._backtest_panel.shutdown()
            self._backtest_panel = None
        if self._sound_panel is not None:
            self._sound_panel.shutdown()
            self._sound_panel = None
        if self._pipe is not None:
            self._pipe.unsubscribe(Topic.FRAME, self._on_frame_bus)
            self._pipe.unsubscribe(Topic.POS, self._on_pos_bus)
            self._pipe.unsubscribe(Topic.ACTION_INTENT, self._on_intent_bus)
            self._pipe.stop()
            self._pipe = None
        self._timer.stop()
        if getattr(self, "_license_timer", None) is not None:
            self._license_timer.stop()
        self._perm_timer.stop()
        super().closeEvent(event)


def _enforce_access() -> bool:
    """包到期 + 密钥门禁。须已有 QApplication。通过 True，应退出 False。"""
    from common.expire import expire_message, is_expired, try_self_delete
    from PySide6.QtWidgets import QMessageBox
    from tools.license_dialog import ensure_licensed

    if is_expired():
        QMessageBox.critical(None, "已过期", expire_message())
        try_self_delete()
        return False
    return ensure_licensed()


def launch_ui(*, roi_path: Path | None = None) -> int:
    """唯一 UI 启动：QApp + Fusion + 门禁 + 主窗。"""
    from PySide6.QtWidgets import QStyleFactory

    app = QApplication.instance() or QApplication(sys.argv)
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)
    if not _enforce_access():
        return 1
    win = PreviewApp() if roi_path is None else PreviewApp(roi_path=Path(roi_path))
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(launch_ui())
