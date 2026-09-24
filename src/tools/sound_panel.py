"""声音开钓配置页：设备 / 监听 / 模板 / 阈值 / 实时波形。"""

from __future__ import annotations

import sys
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from autofish.first_click_trigger.audio_input import AudioInput
from autofish.first_click_trigger.paths import (
    resolve_template_path,
    set_active_template,
    template_source_label,
)
from autofish.first_click_trigger.trigger import FirstClickTrigger
from tools.shell_log import append_log
from tools.shell_theme import DANGER, SUCCESS, TEXT_MUTED
from tools.template_combo import fill_template_combo, sync_combo_to_path
from tools.waveform_select import WaveformSelectWidget

if TYPE_CHECKING:
    from autofish.bus import AutofishBus


class FirstClickTriggerPanel(QWidget):
    """声音页：设备 / 监听 / 当前模板 / 阈值。会话启停由主控 A 驱动。"""

    def __init__(
        self,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._bus: AutofishBus | None = None
        self._trigger: FirstClickTrigger | None = None
        self._logs: deque[str] = deque(maxlen=200)
        self._template_path: Path | None = None
        self._library_cbs: list[Callable[[], None]] = []
        self._threshold_cbs: list[Callable[[float], None]] = []
        self._device_cbs: list[Callable[[str], None]] = []
        self._preferred_device_name = ""
        self._delay_lo_s = 0.3
        self._delay_hi_s = 1.5
        self._hold_lo_s = 0.7
        self._hold_hi_s = 1.5
        self._after_lo_s = 0.2
        self._after_hi_s = 0.8

        self._build_ui()
        self._refresh_devices()
        self.refresh_template_list()
        self._update_state()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_state)
        self._timer.start(200)

    def attach_bus(self, bus: "AutofishBus | None") -> None:
        self._bus = bus

    @property
    def trigger(self) -> FirstClickTrigger | None:
        return self._trigger

    def on_library_changed(self, cb: Callable[[], None]) -> None:
        self._library_cbs.append(cb)

    def on_threshold_changed(self, cb: Callable[[float], None]) -> None:
        self._threshold_cbs.append(cb)

    def on_device_changed(self, cb: Callable[[str], None]) -> None:
        self._device_cbs.append(cb)

    def set_preferred_device_name(self, name: str) -> None:
        self._preferred_device_name = str(name or "").strip()
        self._refresh_devices()

    def set_click_timing(
        self,
        delay_lo_s: float,
        delay_hi_s: float,
        hold_lo_s: float,
        hold_hi_s: float,
        after_lo_s: float = 0.2,
        after_hi_s: float = 0.8,
    ) -> None:
        self._delay_lo_s = float(delay_lo_s)
        self._delay_hi_s = float(delay_hi_s)
        self._hold_lo_s = float(hold_lo_s)
        self._hold_hi_s = float(hold_hi_s)
        self._after_lo_s = float(after_lo_s)
        self._after_hi_s = float(after_hi_s)
        if self._trigger is not None:
            self._trigger.set_click_timing(
                self._delay_lo_s,
                self._delay_hi_s,
                self._hold_lo_s,
                self._hold_hi_s,
                self._after_lo_s,
                self._after_hi_s,
            )

    def current_device_name(self) -> str:
        key, is_loopback = self._selected_device()
        if key is None:
            return ""
        for d in AudioInput.list_devices():
            if d.key == key:
                if is_loopback is None or d.is_loopback == bool(is_loopback):
                    return str(d.name)
        text = self.cmb_device.currentText().strip()
        if "  ← " in text:
            text = text.split("  ← ", 1)[0]
        return text

    def _selected_device(self) -> tuple[int | str | None, bool | None]:
        """返回 (device_key, is_loopback)。"""
        data = self.cmb_device.currentData()
        if data is None:
            return None, None
        if isinstance(data, (tuple, list)) and len(data) == 2:
            return data[0], bool(data[1])
        return data, None

    def set_threshold_value(self, threshold: float, *, emit: bool = True) -> None:
        thr = max(0.15, min(1.0, float(threshold)))
        self.sld_threshold.blockSignals(True)
        self.sld_threshold.setValue(int(round(thr * 100)))
        self.sld_threshold.blockSignals(False)
        self.lbl_threshold.setText(f"{thr:.2f}")
        if self._trigger is not None:
            self._trigger.set_threshold(thr)
        if emit:
            for cb in self._threshold_cbs:
                try:
                    cb(thr)
                except Exception:  # noqa: BLE001
                    pass

    def current_threshold(self) -> float:
        return self.sld_threshold.value() / 100.0

    def _notify_library(self) -> None:
        for cb in self._library_cbs:
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass

    def ensure_trigger(self) -> FirstClickTrigger:
        return self._ensure_trigger()

    def start_listen_if_needed(self) -> FirstClickTrigger:
        """回测长录音前：未监听则按当前设备开监听。"""
        device, loopback = self._selected_device()
        if device is None:
            raise RuntimeError("没有可用音频设备：请先到「声音开钓配置」页选择设备")
        if self._trigger is None or not self._trigger.is_running():
            self._start_listen(device, loopback=loopback)
        assert self._trigger is not None
        return self._trigger

    def reload_active_template(self) -> None:
        path = resolve_template_path()
        if path is None:
            self._set_template_label(None)
            return
        try:
            self._ensure_trigger().load_template(path)
            self._set_template_label(path)
            self._sync_combo_to_path(path)
        except Exception as exc:  # noqa: BLE001
            self._log(f"加载模板失败：{exc}")

    def refresh_template_list(self) -> None:
        path = fill_template_combo(self.cmb_template)
        if isinstance(path, Path):
            self._apply_selected_template(path, log=False)

    def set_session_enabled(self, enabled: bool) -> None:
        if enabled:
            path = resolve_template_path()
            device, loopback = self._selected_device()
            if device is None:
                raise RuntimeError("没有可用音频设备")
            if self._trigger is None or not self._trigger.is_running():
                self._start_listen(device, loopback=loopback)
            assert self._trigger is not None
            if not self._trigger.has_template:
                if path is not None:
                    self._trigger.load_template(path)
                    self._set_template_label(path)
                else:
                    raise RuntimeError("没有模板：请到「回测」页从选区入库")
            self._trigger.set_session_enabled(True)
            self._log("声音开钓 ON · 会话 WAIT")
        else:
            if self._trigger is not None:
                self._trigger.set_session_enabled(False)
            self._log("声音开钓 OFF")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        top = QWidget()
        layout = QVBoxLayout(top)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(6)

        row_listen = QHBoxLayout()
        self.btn_listen = QPushButton("开始监听")
        self.btn_listen.setToolTip("捕获游戏声；回测长录音前需先监听")
        self.btn_listen.clicked.connect(self._on_listen_clicked)
        row_listen.addWidget(self.btn_listen)
        self.lbl_status = QLabel("未监听")
        self.lbl_status.setStyleSheet(f"font-weight:600;")
        row_listen.addWidget(self.lbl_status)
        self.lbl_session = QLabel("会话：disabled")
        self.lbl_session.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        row_listen.addWidget(self.lbl_session)
        row_listen.addStretch(1)
        self.lbl_level = QLabel("音量：—")
        self.lbl_level.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        row_listen.addWidget(self.lbl_level)
        self.lbl_score = QLabel("相似：—")
        self.lbl_score.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        row_listen.addWidget(self.lbl_score)
        layout.addLayout(row_listen)

        row_dev = QHBoxLayout()
        row_dev.addWidget(QLabel("设备"))
        self.cmb_device = QComboBox()
        self.cmb_device.setEnabled(False)
        self.cmb_device.currentIndexChanged.connect(self._on_device_combo)
        row_dev.addWidget(self.cmb_device, 1)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_devices)
        row_dev.addWidget(self.btn_refresh)
        layout.addLayout(row_dev)
        self.lbl_device_hint = QLabel("")
        self.lbl_device_hint.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        self.lbl_device_hint.setWordWrap(True)
        layout.addWidget(self.lbl_device_hint)

        row_tmpl = QHBoxLayout()
        row_tmpl.addWidget(QLabel("当前模板"))
        self.cmb_template = QComboBox()
        self.cmb_template.currentIndexChanged.connect(self._on_template_combo)
        row_tmpl.addWidget(self.cmb_template, 1)
        self.btn_play = QPushButton("播放")
        self.btn_play.clicked.connect(self._play_template)
        row_tmpl.addWidget(self.btn_play)
        layout.addLayout(row_tmpl)
        self.lbl_template = QLabel("模板：无")
        self.lbl_template.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        layout.addWidget(self.lbl_template)

        row_thr = QHBoxLayout()
        row_thr.addWidget(QLabel("阈值"))
        self.sld_threshold = QSlider(Qt.Orientation.Horizontal)
        self.sld_threshold.setRange(15, 100)
        self.sld_threshold.setValue(70)
        self.sld_threshold.valueChanged.connect(self._on_threshold_changed)
        row_thr.addWidget(self.sld_threshold, 1)
        self.lbl_threshold = QLabel("0.70")
        self.lbl_threshold.setMinimumWidth(36)
        row_thr.addWidget(self.lbl_threshold)
        self.lbl_last = QLabel("触发：—")
        self.lbl_last.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        row_thr.addWidget(self.lbl_last)
        self.lbl_count = QLabel("×0")
        self.lbl_count.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        row_thr.addWidget(self.lbl_count)
        layout.addLayout(row_thr)
        hint = QLabel("下方为最近约 20s 实时波形；橙=命中。长录音/回测 →「回测」页")
        hint.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        layout.addWidget(hint)

        self.live_wave = WaveformSelectWidget()
        self.live_wave.setMinimumHeight(110)
        self.live_wave.setToolTip("监听中滚动显示；命中区域橙色标记")
        layout.addWidget(self.live_wave)
        self.lbl_live_wave = QLabel("未监听 · 无波形")
        self.lbl_live_wave.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        layout.addWidget(self.lbl_live_wave)
        layout.addStretch(1)

        top_scroll = QScrollArea()
        top_scroll.setWidgetResizable(True)
        top_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        top_scroll.setWidget(top)
        splitter.addWidget(top_scroll)

        log_wrap = QWidget()
        log_l = QVBoxLayout(log_wrap)
        log_l.setContentsMargins(0, 4, 0, 0)
        log_l.setSpacing(2)
        log_title = QLabel("日志（可拖边上沿改高度）")
        log_title.setStyleSheet(f"font-weight:600; color:{TEXT_MUTED}; font-size:12px;")
        log_l.addWidget(log_title)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(120)
        log_l.addWidget(self.log, 1)
        splitter.addWidget(log_wrap)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([280, 280])
        root.addWidget(splitter)

    def _refresh_devices(self) -> None:
        self.cmb_device.blockSignals(True)
        self.cmb_device.clear()
        devices = AudioInput.list_devices()
        preferred = self._preferred_device_name.strip().lower()
        exact_i: int | None = None
        fuzzy_i: int | None = None
        fallback_i: int | None = None
        for i, d in enumerate(devices):
            label = d.name
            if d.is_virtual_capture or d.is_loopback:
                label = f"{d.name}  ← 录游戏声用这个"
            self.cmb_device.addItem(label, (d.key, d.is_loopback))
            name_l = d.name.lower()
            # 存档可能是纯扬声器名，或带 (Loopback) 后缀
            bare = name_l.replace(" (loopback)", "").strip()
            if preferred and (name_l == preferred or bare == preferred):
                exact_i = i
            elif preferred and preferred in name_l and fuzzy_i is None:
                fuzzy_i = i
            elif preferred and bare and bare in preferred and fuzzy_i is None:
                fuzzy_i = i
            if (d.is_virtual_capture or d.is_loopback) and fallback_i is None:
                fallback_i = i
        self.cmb_device.setEnabled(
            len(devices) > 0
            and (self._trigger is None or not self._trigger.is_running())
        )
        if len(devices) > 0:
            if exact_i is not None:
                sel = exact_i
            elif fuzzy_i is not None:
                sel = fuzzy_i
            else:
                sel = fallback_i or 0
            self.cmb_device.setCurrentIndex(sel)
        self.cmb_device.blockSignals(False)
        self._update_device_hint()

    def _on_device_combo(self, _idx: int) -> None:
        name = self.current_device_name()
        if name:
            self._preferred_device_name = name
        self._notify_device()

    def _notify_device(self) -> None:
        name = self.current_device_name()
        for cb in self._device_cbs:
            try:
                cb(name)
            except Exception:  # noqa: BLE001
                pass

    def _update_device_hint(self) -> None:
        if sys.platform == "darwin":
            self.lbl_device_hint.setText("多输出时本页选 BlackHole 2ch（悬停看完整设置）")
            self.lbl_device_hint.setToolTip(
                "系统输出选「多输出」时：本页必须选 BlackHole 2ch。\n"
                "音频 MIDI 设置 → 多输出：扬声器+BlackHole；主设备=BlackHole；48 kHz；"
                "扬声器勾「漂移校正」。"
            )
        elif sys.platform == "win32":
            self.lbl_device_hint.setText(
                "选带 Loopback /「录游戏声」的扬声器项（如 DELL），不要选麦克风"
            )
            self.lbl_device_hint.setToolTip(
                "Windows 用 soundcard 枚举 WASAPI 环回：\n"
                "列表里对应你正在播放的那路输出（DELL / Realtek 等）+ Loopback。\n"
                "选麦克风只能录到话筒，录不到游戏声。"
            )

        else:
            self.lbl_device_hint.setText("选择正确的输入/监听设备")

    def _set_template_label(self, path: Path | None) -> None:
        self._template_path = path
        self.lbl_template.setText(f"模板：{template_source_label(path)}")

    def _sync_combo_to_path(self, path: Path) -> None:
        sync_combo_to_path(self.cmb_template, path)

    def _on_template_combo(self, _idx: int) -> None:
        path = self.cmb_template.currentData()
        if isinstance(path, Path):
            self._apply_selected_template(path, log=True)

    def _apply_selected_template(self, path: Path, *, log: bool) -> None:
        try:
            set_active_template(path)
            self._ensure_trigger().load_template(path)
            self._set_template_label(path)
            if log:
                self._log(f"当前模板：{template_source_label(path)}")
            self._notify_library()
        except Exception as exc:  # noqa: BLE001
            self._log(f"切换模板失败：{exc}")

    def _ensure_trigger(self) -> FirstClickTrigger:
        if self._trigger is None:
            device, loopback = self._selected_device()
            threshold = self.sld_threshold.value() / 100.0
            self._trigger = FirstClickTrigger(
                bus=self._bus,
                device=device,
                threshold=threshold,
                loopback=loopback,
            )
            self._trigger.set_click_timing(
                self._delay_lo_s,
                self._delay_hi_s,
                self._hold_lo_s,
                self._hold_hi_s,
                self._after_lo_s,
                self._after_hi_s,
            )
        return self._trigger

    def _on_threshold_changed(self, value: int) -> None:
        threshold = value / 100.0
        self.lbl_threshold.setText(f"{threshold:.2f}")
        if self._trigger is not None:
            self._trigger.set_threshold(threshold)
        for cb in self._threshold_cbs:
            try:
                cb(threshold)
            except Exception:  # noqa: BLE001
                pass

    def _on_listen_clicked(self) -> None:
        if self._trigger is not None and self._trigger.is_running():
            self._stop_listen()
            return
        # 线程已停但按钮未刷（或上次停流超时）：先对齐再开始
        self._sync_listen_button()
        device, loopback = self._selected_device()
        if device is None:
            self._log("没有可用音频设备")
            return
        try:
            self._start_listen(device, loopback=loopback)
        except Exception as exc:  # noqa: BLE001
            self._log(f"监听失败：{exc}")

    def _start_listen(
        self,
        device: int | str,
        *,
        loopback: bool | None = None,
    ) -> None:
        wave = None
        session_on = False
        if self._trigger is not None:
            wave = self._trigger.template_wave
            from autofish.topics import CastSessionState

            session_on = self._trigger.session_state != CastSessionState.DISABLED
            self._trigger.stop()
        threshold = self.sld_threshold.value() / 100.0
        self._trigger = FirstClickTrigger(
            bus=self._bus,
            device=device,
            threshold=threshold,
            loopback=loopback,
        )
        self._trigger.set_click_timing(
            self._delay_lo_s,
            self._delay_hi_s,
            self._hold_lo_s,
            self._hold_hi_s,
            self._after_lo_s,
            self._after_hi_s,
        )
        if wave is not None:
            self._trigger.set_template(wave)
        else:
            path = resolve_template_path()
            if path is not None:
                self._trigger.load_template(path)
                self._set_template_label(path)
        self._trigger.start()
        if session_on:
            self._trigger.set_session_enabled(True)
        self.btn_listen.setText("停止监听")
        self.cmb_device.setEnabled(False)
        self.live_wave.clear()
        self.lbl_live_wave.setText("监听中 · 采集波形…")
        self._log(f"开始监听 · {self.cmb_device.currentText()}")
        name = self.current_device_name()
        if name:
            self._preferred_device_name = name
        self._notify_device()

    def _stop_listen(self) -> None:
        if self._trigger is not None:
            try:
                self._trigger.set_session_enabled(False)
            except Exception as exc:  # noqa: BLE001
                self._log(f"关闭会话失败：{exc}")
            try:
                self._trigger.stop()
            except Exception as exc:  # noqa: BLE001
                self._log(f"停止监听异常：{exc}")
            if self._trigger.is_running():
                self._log("停止信号已发，后台线程尚未退出（将继续等待）")
                # 按钮仍显示停止，等定时器同步；禁止误判为已停再点「开始」叠流
                self.btn_listen.setText("停止中…")
                self.cmb_device.setEnabled(False)
                self.lbl_live_wave.setText("正在停止监听…")
                return
        self.btn_listen.setText("开始监听")
        self.cmb_device.setEnabled(True)
        self.lbl_live_wave.setText("未监听 · 无波形")
        self._log("已停止监听")

    def _play_template(self) -> None:
        try:
            trigger = self._ensure_trigger()
            if not trigger.has_template:
                path = resolve_template_path()
                if path is None:
                    raise RuntimeError("没有模板可播放")
                trigger.load_template(path)
                self._set_template_label(path)
            trigger.play_template()
            self._log("正在播放模板")
        except Exception as exc:  # noqa: BLE001
            self._log(f"播放失败：{exc}")

    def _sync_listen_button(self) -> None:
        """按钮文案与真实 is_running 对齐（防 Windows 停流后 UI 脱节）。"""
        running = self._trigger is not None and self._trigger.is_running()
        if running:
            if self.btn_listen.text() not in ("停止监听", "停止中…"):
                self.btn_listen.setText("停止监听")
            self.cmb_device.setEnabled(False)
        else:
            if self.btn_listen.text() != "开始监听":
                self.btn_listen.setText("开始监听")
            self.cmb_device.setEnabled(True)

    def _update_state(self) -> None:
        self._sync_listen_button()
        if self._trigger is not None:
            for line in self._trigger.drain_logs(channel="sound"):
                self._log(line)
            self.lbl_session.setText(f"会话：{self._trigger.session_state.value}")
        if self._trigger is None or not self._trigger.is_running():
            self.lbl_status.setText("未监听")
            self.lbl_status.setStyleSheet(f"font-weight:600; color:{DANGER};")
            self.lbl_level.setText("音量：—")
            self.lbl_score.setText("相似：—")
            if self.lbl_live_wave.text().startswith("正在停止"):
                self.lbl_live_wave.setText("未监听 · 无波形")
            return
        self.lbl_status.setText("监听中")
        self.lbl_status.setStyleSheet(f"font-weight:600; color:{SUCCESS};")
        self.lbl_level.setText(f"音量：{self._trigger.level_db:.0f} dB")
        self.lbl_score.setText(f"相似：{self._trigger.last_score:.2f}")
        if self._trigger.last_trigger_at > 0:
            ago = time.time() - self._trigger.last_trigger_at
            self.lbl_last.setText(f"触发：{ago:.1f}s前")
        else:
            self.lbl_last.setText("触发：—")
        self.lbl_count.setText(f"×{self._trigger.trigger_count}")
        self._refresh_live_wave()

    def _refresh_live_wave(self) -> None:
        t = self._trigger
        if t is None or not t.is_running():
            return
        try:
            wave = t.recent_monitor_wave(20.0)
            sr = t.samplerate
            if wave.size == 0:
                self.lbl_live_wave.setText("监听中 · 等待音频…")
                return
            dur = float(wave.size) / float(max(sr, 1))
            hits = t.live_hits_for_monitor(dur)
            self.live_wave.set_audio(wave, sr, keep_view=True)
            self.live_wave.set_hits(hits)
            self.lbl_live_wave.setText(
                f"最近 {dur:.1f}s · 橙命中 {len(hits)} · 相似 {t.last_score:.2f}"
            )
        except Exception:  # noqa: BLE001
            pass

    def _log(self, msg: str) -> None:
        # 只写本页日志，不转发主控
        append_log(self._logs, self.log, msg)

    def shutdown(self) -> None:
        self._timer.stop()
        if self._trigger is not None:
            self._trigger.set_session_enabled(False)
            self._trigger.stop()
            self._trigger = None


