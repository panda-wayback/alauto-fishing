"""调试壳（PySide6）：竖列可滚 + 底栏独立日志；设置可收起；无快捷键。"""

from __future__ import annotations

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
from autofish.detect.api import apply_manual_bar, get_detector
from autofish.detect.bobber import BobberHit
from autofish.capture.screen import (
    DEFAULT_SCREEN_PATH,
    ScreenGrab,
    grab_primary,
    load_screen,
    save_screen,
)
from autofish.locate.roi import (
    DEFAULT_ROI_PATH,
    ROI_SOURCE_DEFAULT,
    ROI_SOURCE_MANUAL,
    BarMark,
    Roi,
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
from autofish.pipeline import AutofishPipeline
from autofish.topics import (
    ActionIntentEvent,
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
    load_shell_settings,
    save_bundled_shell_settings,
    save_shell_settings,
)
from tools.shell_theme import (
    DANGER,
    SUCCESS,
    TEXT_FAINT,
    TEXT_MUTED,
    WARN,
    global_qss,
)
from tools.macos_overlay import elevate_over_fullscreen, restore_window_level
from tools.status_hud import StatusHudPanel
from tools.shell_log import append_log
from tools.image_canvas import overlay_hit
from tools.sound_panel import FirstClickTriggerPanel
from tools.backtest_panel import AudioBacktestPanel
from tools.main_page import build_main_page
from tools.calibrate_page import build_calibrate_page
from tools.more_page import build_more_page

IDLE = "idle"
SELECT = "select"
READY = "ready"


class BusBridge(QObject):
    """后台线程 → UI 线程。"""

    frame = Signal(object)
    pos = Signal(object)
    intent = Signal(object)


def _hold_word(on: bool | None) -> str:
    if on is None:
        return "—"
    return "按下" if on else "松开"


class PreviewApp(QMainWindow):
    def __init__(self, roi_path: Path = DEFAULT_ROI_PATH) -> None:
        super().__init__()
        self.setWindowTitle("Albion 拉鱼")
        self.resize(460, 800)
        self.setStyleSheet(global_qss())
        self._settings = load_shell_settings()
        # 默认置顶：点到游戏窗口时调试壳不被盖住（可被持久化覆盖）
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint, bool(self._settings.stay_on_top)
        )

        self.roi_path = roi_path
        self.roi: Roi | None = None
        self.hit: BobberHit | None = None
        self.frame: np.ndarray | None = None
        self.phase = IDLE
        self.screen_grab: ScreenGrab | None = None
        self._pipe: AutofishPipeline | None = None
        self._holding: bool | None = None
        self._last_cast_session: CastSessionState | None = None
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
        self._sound_panel: FirstClickTriggerPanel | None = None
        self._backtest_panel: AudioBacktestPanel | None = None
        self._bar_ref_saved = False
        self._bar_ref_wait_bobber = False
        self._bridge = BusBridge()
        self._bridge.frame.connect(self._on_frame_ui)
        self._bridge.pos.connect(self._on_pos_ui)
        self._bridge.intent.connect(self._on_intent_ui)

        self._compact = False
        self._full_geo = None
        self._build_ui()
        self._apply_saved_window_geometry()
        self._reload_roi()
        self._sync_buttons()
        # 恢复持久化 A/B；有 ROI 则常开 Capture/Detect
        self._restore_ab_from_settings()
        if self.roi is not None:
            self._ensure_monitor_on()
            self.lbl_hint.setText("ROI 就绪 · 监控中")
            self._cal_log("启动 · Capture/Detect 常开")
        self._refresh_hud_steady()
        if self._settings.compact_mode:
            self._set_compact_mode(True, persist=False, from_startup=True)

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

        # 导航：主控 | 自动拉漂配置 | 声音开钓配置 | 回测 | 更多
        nav = QHBoxLayout()
        nav.setSpacing(2)
        self._nav_btns: list[QPushButton] = []
        self.stack = QStackedWidget()
        nav_items = (
            ("主控", "日常开关与状态"),
            ("拉漂配置", "自动拉漂配置 · ROI / 条界 / 策略"),
            ("开钓配置", "声音开钓配置 · 设备 / 模板 / 阈值"),
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

        # —— 声音开钓配置 ——
        page_sound = QWidget()
        sound_l = QVBoxLayout(page_sound)
        sound_l.setContentsMargins(0, 0, 0, 0)
        self._sound_panel = FirstClickTriggerPanel(self)
        self._sound_panel.set_preferred_device_name(self._settings.audio_device_name)
        self._sound_panel.set_threshold_value(
            self._settings.sound_threshold, emit=False
        )
        self._sound_panel.set_click_timing(
            self._settings.click_delay_lo_s,
            self._settings.click_delay_hi_s,
            self._settings.click_hold_lo_s,
            self._settings.click_hold_hi_s,
            self._settings.click_after_lo_s,
            self._settings.click_after_hi_s,
        )
        self._sound_panel.on_threshold_changed(self._on_sound_threshold_persist)
        self._sound_panel.on_device_changed(self._on_sound_device_persist)
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

    def _refresh_session_label(self) -> None:
        pipe = self._pipe
        if pipe is None:
            self.lbl_session.setText("会话：—")
            return
        snap = pipe.bus.snapshot()
        cs = snap.cast_session
        if cs == CastSessionState.DISABLED:
            self.lbl_session.setText("会话：关")
        else:
            self.lbl_session.setText(f"会话：{cs.value}")
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

    def _main_log(self, msg: str) -> None:
        """主控状态日志（最新在上）。"""
        if getattr(self, "log", None) is not None:
            append_log(self._logs, self.log, msg)

    def _cal_log(self, msg: str) -> None:
        """自动拉漂配置页日志（最新在上）。"""
        if getattr(self, "cal_log", None) is not None:
            append_log(self._cal_logs, self.cal_log, msg)

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
        """启动时恢复 A/B 勾选并应用。"""
        s = self._settings
        want_b = bool(s.auto_bobber_enabled)
        want_a = bool(s.sound_enabled)
        # 先把勾选摆到目标态，再应用逻辑——避免 B 落盘时把 A 偏好写成 false
        self._block_checks(True)
        self.chk_b.setChecked(want_b)
        self.chk_a.setChecked(want_a)
        self._block_checks(False)
        self._on_b_toggled(want_b)
        if want_a:
            # 延后一拍：声音面板设备列表已就绪后再开会话
            QTimer.singleShot(0, self._restore_sound_enabled)

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
        self._apply_click_timing_from_ui()
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

    def _apply_click_timing_from_ui(self) -> None:
        d_lo, d_hi = self.bar_delay.range()
        h_lo, h_hi = self.bar_hold.range()
        a_lo, a_hi = self.bar_after.range()
        if self._sound_panel is not None:
            self._sound_panel.set_click_timing(
                d_lo, d_hi, h_lo, h_hi, a_lo, a_hi
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
            self.setMinimumSize(200, 100)
            # 就地缩小：保留左上角；仅「启动即紧凑」才用上次拖动落点
            anchor = self.geometry().topLeft()
            self.resize(220, 120)
            if from_startup:
                s = self._settings
                if s.hud_x >= 0 and s.hud_y >= 0:
                    anchor = self._clamp_to_screens(
                        s.hud_x, s.hud_y, self.width(), self.height()
                    )
            self.move(anchor)
            # 紧凑态强制置顶；macOS 再抬原生层级以便压过全屏游戏
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.show()
            self._refresh_hud_steady()
            QTimer.singleShot(0, self._apply_compact_overlay)
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
                self.resize(460, 800)
            self.move(anchor)
            # 恢复用户置顶偏好
            self.setWindowFlag(
                Qt.WindowType.WindowStaysOnTopHint,
                bool(self.chk_stay_on_top.isChecked()),
            )
            self.show()
            self.raise_()
            self.activateWindow()
            QTimer.singleShot(0, self._restore_normal_overlay)
        if persist:
            self._persist_settings()

    def _apply_compact_overlay(self) -> None:
        if not self._compact:
            return
        self.raise_()
        elevate_over_fullscreen(self)

    def _restore_normal_overlay(self) -> None:
        if self._compact:
            return
        restore_window_level(
            self, floating=bool(self.chk_stay_on_top.isChecked())
        )

    def _refresh_hud_steady(self) -> None:
        hud = getattr(self, "_hud", None)
        if hud is None:
            return
        a_on = bool(self.chk_a.isChecked())
        b_on = bool(self.chk_b.isChecked())
        if not a_on and not b_on:
            hud.set_steady("idle")
            return
        if self._had_bobber:
            if self._holding is True:
                hud.set_steady("pull")
            else:
                hud.set_steady("release")
            return
        pipe = self._pipe
        cs = CastSessionState.DISABLED
        if pipe is not None:
            cs = pipe.bus.snapshot().cast_session
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
        if was_visible:
            self.show()
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
        self.lbl_hint.setText("已恢复默认框 · 监控中")
        self._cal_log("已恢复默认居中框并开监控")

    def _apply_saved_bar_mark(self) -> None:
        mark = load_bar_mark(self.roi_path)
        box = mark.as_box() if mark is not None else None
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
            self.bar_canvas.set_rgb(rgb)
            self._bar_ref_saved = True
            det = get_detector()
            self.bar_canvas.set_program_bar(getattr(det, "program_bar", None))
        except Exception as exc:  # noqa: BLE001
            self._cal_log(f"参考图载入失败：{exc}")

    def _save_bar_ref(self, rgb: np.ndarray) -> None:
        import cv2

        ref = bar_ref_path(self.roi_path)
        ref.parent.mkdir(parents=True, exist_ok=True)
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        cv2.imwrite(str(ref), bgr)
        self.bar_canvas.set_rgb(rgb)
        self._bar_ref_saved = True

    def _refresh_bar_ref(self) -> None:
        """不立即截空图：挂起等待，下一帧有漂再落参考图。"""
        if self._bar_ref_wait_bobber:
            self._bar_ref_wait_bobber = False
            self.btn_bar_refresh.setText("刷新参考图")
            self._cal_log("已取消等待参考图")
            self.lbl_hint.setText("已取消等待参考图")
            return
        self._bar_ref_wait_bobber = True
        self.btn_bar_refresh.setText("等待鱼漂…")
        self._cal_log("刷新参考图：等待下一次鱼漂识别")
        self.lbl_hint.setText("等待鱼漂出现后自动更新参考图")

    def _maybe_commit_bar_ref_wait(self, event: PosEvent) -> None:
        if not self._bar_ref_wait_bobber:
            return
        if event.hit is None or event.frame is None:
            return
        self._save_bar_ref(event.frame)
        det = get_detector()
        if hasattr(det, "program_bar"):
            self.bar_canvas.set_program_bar(det.program_bar)
        self._bar_ref_wait_bobber = False
        self.btn_bar_refresh.setText("刷新参考图")
        self._cal_log("已刷新条界参考图（等漂命中）")
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
        mark = BarMark(
            left=float(left),
            right=float(left) + float(bw),
            top=float(top),
            height=float(bh),
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
            pipe = AutofishPipeline(capture_fps=30.0)
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
        prog = getattr(det, "program_bar", None)
        if prog is not None:
            self.bar_canvas.set_program_bar(prog)
        elif (
            event.hit is not None
            and event.hit.bar_width > 0
            and getattr(det, "manual_bar", None) is None
        ):
            h = event.hit
            self.bar_canvas.set_program_bar(
                (h.bar_left, h.bar_top, h.bar_width, h.bar_height)
            )
        # 有漂即出参考图（含有漂无条），便于手动标左右界
        if event.hit is not None and event.frame is not None and not self._bar_ref_saved:
            self._save_bar_ref(event.frame)
            if event.hit.bar_width <= 0:
                self._cal_log("已出条界参考图（有漂·无条，可手动标左右）")
            else:
                self._cal_log("已自动保存条界参考图")
        self._maybe_commit_bar_ref_wait(event)
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
        pipe = self._pipe
        if pipe is None or not pipe.decide_on:
            self.lbl_strat_detail.setText("")
            self._refresh_mouse()
            return
        low, high = self._current_policy_thresholds()
        detail = f"· <{low:.1f}按 / >{high:.1f}松"
        if reason:
            detail += f" · {reason}"
        self.lbl_strat_detail.setText(detail)
        self._refresh_mouse()

    def _current_policy_thresholds(self) -> tuple[float, float]:
        pipe = self._pipe
        if pipe is not None and pipe.decide_on:
            return pipe.decide.current_thresholds
        plo, phi, rlo, rhi = self.range_axis.ranges()
        return (plo + phi) / 2.0, (rlo + rhi) / 2.0

    def _refresh_pos(self) -> None:
        if self.hit is None:
            self.lbl_pos.setText("POS: 无漂")
            self.lbl_pos.setStyleSheet(
                f"font-size:16px; font-weight:700; color:{DANGER};"
            )
        elif self.hit.bar_width <= 0:
            self.lbl_pos.setText("POS: 有漂·无条")
            self.lbl_pos.setStyleSheet(
                f"font-size:16px; font-weight:700; color:{WARN};"
            )
        else:
            self.lbl_pos.setText(f"POS: {self.hit.pos:.1f}")
            self.lbl_pos.setStyleSheet(
                f"font-size:16px; font-weight:700; color:{SUCCESS};"
            )
        ms = getattr(self, "_last_detect_ms", 0.0)
        self.lbl_perf.setText(f"{ms:.0f}ms")

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
        for chk in (self.chk_b, self.chk_a):
            chk.blockSignals(block)

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
            self._main_log(f"自动拉漂 ON · 配置 <{low:.1f}按 / >{high:.1f}松")
        else:
            if pipe.act_on:
                pipe.stop_act()
            if pipe.decide_on:
                pipe.stop_decide()
            self._holding = None
            self._refresh_strategy()
            self._main_log("自动拉漂 OFF")
        self._refresh_mouse()
        self._refresh_hud_steady()
        self._persist_settings()

    def _on_a_toggled(self, checked: bool) -> None:
        """声音开钓 = 会话机。勾选即偏好；启动失败不取消勾选，以免抹掉持久化。"""
        if not checked:
            if self._sound_panel is not None:
                self._sound_panel.set_session_enabled(False)
            self.lbl_hint.setText("声音开钓已关")
            self._main_log("声音开钓 OFF")
            self._refresh_hud_steady()
            self._persist_settings()
            return
        self._activate_sound_session(persist=True)

    def _activate_sound_session(self, *, persist: bool) -> bool:
        """尝试开监听+会话。成功 True；失败保留勾选，只提示。"""
        pipe = self._ensure_pipe()
        if self._sound_panel is None:
            self.lbl_hint.setText("声音开钓失败：面板未就绪")
            self._main_log("声音开钓失败：面板未就绪")
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
                    "声音开钓未就绪：请到「开钓配置」确认设备与模板后重试"
                )
                self._main_log("声音开钓未就绪 · 已保留勾选")
                self._refresh_hud_steady()
                if persist:
                    self._persist_settings()
                return False
            self.lbl_hint.setText("声音开钓中")
            self._main_log("声音开钓 ON")
            self._refresh_hud_steady()
            if persist:
                self._persist_settings()
            return True
        except Exception as exc:  # noqa: BLE001
            try:
                self._sound_panel.set_session_enabled(False)
            except Exception:  # noqa: BLE001
                pass
            self.lbl_hint.setText(f"声音开钓失败：{exc}")
            self._main_log(f"声音开钓失败：{exc} · 已保留勾选")
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
        if snap is not None:
            if snap.cast_session == CastSessionState.DISABLED:
                may_pull = snap.fishing_state == FishingState.FISHING
            else:
                may_pull = snap.cast_session == CastSessionState.FISHING
        free = act_on and not may_pull and not yielding

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
                f"font-size:14px; font-weight:600; color:{DANGER};"
            )
            self.lbl_mouse_diag.setText("异常：" + " / ".join(issues))
            self.lbl_mouse_diag.setStyleSheet(f"color:{DANGER};")
            if not self._mouse_mismatch_logged:
                self._mouse_mismatch_logged = True
                self._cal_log(
                    "鼠标异常 "
                    + " / ".join(issues)
                    + f" · 意图={_hold_word(intent)}"
                    + f" 程序={prog_s}"
                    + f" 系统={_hold_word(os_down)}"
                )
        else:
            if yielding:
                color = WARN
            elif free:
                color = TEXT_FAINT
            elif act_on and prog:
                color = WARN
            elif act_on:
                color = SUCCESS
            else:
                color = TEXT_FAINT
            self.lbl_mouse.setStyleSheet(
                f"font-size:14px; font-weight:600; color:{color};"
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
            self.lbl_mouse_diag.setStyleSheet(f"color:{TEXT_MUTED};")
            self._mouse_mismatch_logged = False

    def _capture_fullscreen(self) -> None:
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
            self.lbl_hint.setText(f"截图失败：{exc}")
            QMessageBox.warning(self, "截屏失败", str(exc))
        self._sync_buttons()

    def _load_screen_for_select(self) -> None:
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
        save_roi(roi, self.roi_path, source=ROI_SOURCE_MANUAL)
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

    def _ensure_monitor_on(self) -> None:
        """有 ROI 则常开 Capture+Detect。"""
        if self.roi is None:
            return
        pipe = self._ensure_pipe()
        pipe.set_roi_manual(self.roi)
        self._apply_saved_bar_mark()
        if not pipe.monitor_on:
            pipe.start_monitor()
            self._cal_log("Capture+Detect 常开")
        self.lbl_hint.setText("监控中")

    def _cancel_selection(self) -> None:
        self.phase = READY if self.roi is not None else IDLE
        self.monitor.set_selecting(False)
        self.lbl_hint.setText("已取消框选")
        self._sync_buttons()
        self._refresh_monitor()
        if self.roi is not None:
            self._ensure_monitor_on()

    def closeEvent(self, event) -> None:  # noqa: N802
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
        super().closeEvent(event)

    def run(self) -> int:
        self.show()
        return QApplication.instance().exec()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    # Fusion：让 QSS 按钮字色在 macOS 上可靠生效
    from PySide6.QtWidgets import QStyleFactory

    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)
    win = PreviewApp()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
