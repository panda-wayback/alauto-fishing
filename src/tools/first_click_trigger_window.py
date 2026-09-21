"""声音开钓页 + 命中回测页（嵌入主壳）。"""

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
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from autofish.first_click_trigger.audio_input import AudioInput
from autofish.first_click_trigger.paths import (
    delete_library_template,
    delete_session_dir,
    is_bundled_template,
    list_library_templates,
    list_session_dirs,
    rename_library_template,
    resolve_template_path,
    set_active_template,
    template_source_label,
)
from autofish.first_click_trigger.trigger import FirstClickTrigger
from tools.shell_theme import DANGER, SUCCESS, TEXT_MUTED
from tools.waveform_select import WaveformSelectWidget

if TYPE_CHECKING:
    from autofish.bus import AutofishBus


def _append_log(logs: deque[str], widget: QPlainTextEdit, msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    parts = str(msg).splitlines() or [""]
    block = f"{ts}  {parts[0]}"
    if len(parts) > 1:
        pad = " " * (len(ts) + 2)
        block = block + "\n" + "\n".join(f"{pad}{p}" for p in parts[1:])
    logs.append(block)
    widget.setPlainText("\n".join(logs))
    bar = widget.verticalScrollBar()
    bar.setValue(bar.maximum())


class FirstClickTriggerPanel(QWidget):
    """声音页：设备 / 监听 / 当前模板 / 阈值。会话启停由主控 A 驱动。"""

    def __init__(
        self,
        parent=None,
        *,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus: AutofishBus | None = None
        self._trigger: FirstClickTrigger | None = None
        self._logs: deque[str] = deque(maxlen=200)
        self._template_path: Path | None = None
        self._external_log = log_fn
        self._library_cbs: list[Callable[[], None]] = []
        self._threshold_cbs: list[Callable[[float], None]] = []
        self._device_cbs: list[Callable[[str], None]] = []
        self._preferred_device_name = ""

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

    def current_device_name(self) -> str:
        idx = self.cmb_device.currentData()
        if idx is None:
            return ""
        for d in AudioInput.list_devices():
            if d.index == idx:
                return str(d.name)
        # 列表瞬时变化时用下拉显示文案去掉提示后缀
        text = self.cmb_device.currentText().strip()
        if "  ← " in text:
            text = text.split("  ← ", 1)[0]
        return text

    def set_threshold_value(self, threshold: float, *, emit: bool = True) -> None:
        thr = max(0.15, min(0.80, float(threshold)))
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
        device = self.cmb_device.currentData()
        if device is None:
            raise RuntimeError("没有可用音频设备：请先到「声音开钓配置」页选择设备")
        if self._trigger is None or not self._trigger.is_running():
            self._start_listen(device)
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
        self.cmb_template.blockSignals(True)
        self.cmb_template.clear()
        active = resolve_template_path()
        sel = 0
        for i, p in enumerate(list_library_templates()):
            self.cmb_template.addItem(template_source_label(p), p)
            try:
                if active is not None and p.resolve() == active.resolve():
                    sel = i
            except OSError:
                if active is not None and p == active:
                    sel = i
        if self.cmb_template.count() > 0:
            self.cmb_template.setCurrentIndex(sel)
        self.cmb_template.blockSignals(False)
        path = self.cmb_template.currentData()
        if isinstance(path, Path):
            self._apply_selected_template(path, log=False)

    def set_session_enabled(self, enabled: bool) -> None:
        if enabled:
            path = resolve_template_path()
            device = self.cmb_device.currentData()
            if device is None:
                raise RuntimeError("没有可用音频设备")
            if self._trigger is None or not self._trigger.is_running():
                self._start_listen(device)
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
        self.sld_threshold.setRange(15, 80)
        self.sld_threshold.setValue(70)
        self.sld_threshold.valueChanged.connect(self._on_threshold_changed)
        row_thr.addWidget(self.sld_threshold, 1)
        self.lbl_threshold = QLabel("0.70")
        self.lbl_threshold.setMinimumWidth(36)
        row_thr.addWidget(self.lbl_threshold)
        self.lbl_mode = QLabel("模式：—")
        self.lbl_mode.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        row_thr.addWidget(self.lbl_mode)
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
        fallback_i = 0
        for i, d in enumerate(devices):
            label = d.name
            if d.is_virtual_capture:
                label = f"{d.name}  ← 录游戏声用这个"
            self.cmb_device.addItem(label, d.index)
            name_l = d.name.lower()
            if preferred and name_l == preferred:
                exact_i = i
            elif preferred and preferred in name_l and fuzzy_i is None:
                fuzzy_i = i
            if d.is_virtual_capture or d.is_loopback:
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
                sel = fallback_i
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
            self.lbl_device_hint.setText("选带 (Loopback) 的输出设备")
        else:
            self.lbl_device_hint.setText("选择正确的输入/监听设备")

    def _set_template_label(self, path: Path | None) -> None:
        self._template_path = path
        self.lbl_template.setText(f"模板：{template_source_label(path)}")

    def _sync_combo_to_path(self, path: Path) -> None:
        self.cmb_template.blockSignals(True)
        for i in range(self.cmb_template.count()):
            p = self.cmb_template.itemData(i)
            if not isinstance(p, Path):
                continue
            try:
                if p.resolve() == path.resolve():
                    self.cmb_template.setCurrentIndex(i)
                    break
            except OSError:
                if p == path:
                    self.cmb_template.setCurrentIndex(i)
                    break
        self.cmb_template.blockSignals(False)

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
            device = self.cmb_device.currentData()
            threshold = self.sld_threshold.value() / 100.0
            self._trigger = FirstClickTrigger(
                bus=self._bus,
                device=device,
                threshold=threshold,
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
        device = self.cmb_device.currentData()
        if device is None:
            self._log("没有可用音频设备")
            return
        try:
            self._start_listen(device)
        except Exception as exc:  # noqa: BLE001
            self._log(f"监听失败：{exc}")

    def _start_listen(self, device: int | str) -> None:
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
            self._trigger.set_session_enabled(False)
            self._trigger.stop()
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

    def _update_state(self) -> None:
        if self._trigger is not None:
            for line in self._trigger.drain_logs(channel="sound"):
                self._log(line)
            self.lbl_session.setText(f"会话：{self._trigger.session_state.value}")
        if self._trigger is None or not self._trigger.is_running():
            self.lbl_status.setText("未监听")
            self.lbl_status.setStyleSheet(f"font-weight:600; color:{DANGER};")
            self.lbl_level.setText("音量：—")
            self.lbl_mode.setText("模式：—")
            self.lbl_score.setText("相似：—")
            return
        self.lbl_status.setText("监听中")
        self.lbl_status.setStyleSheet(f"font-weight:600; color:{SUCCESS};")
        self.lbl_level.setText(f"音量：{self._trigger.level_db:.0f} dB")
        self.lbl_mode.setText(f"模式：{self._trigger.running_mode}")
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
        _append_log(self._logs, self.log, msg)

    def shutdown(self) -> None:
        self._timer.stop()
        if self._trigger is not None:
            self._trigger.set_session_enabled(False)
            self._trigger.stop()
            self._trigger = None


class AudioBacktestPanel(QWidget):
    """回测页：长录音、会话列表、模板库、波形回测。"""

    def __init__(
        self,
        host: FirstClickTriggerPanel,
        parent=None,
        *,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._external_log = log_fn
        self._logs: deque[str] = deque(maxlen=200)
        self._last_session_root: Path | None = None
        self._last_session_wave: object | None = None
        self._last_session_sr: int = 0
        self._last_session_ranges: list[tuple[float, float]] = []

        self._build_ui()
        self.refresh_lists()
        host.on_library_changed(self.refresh_lists)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(200)

    def refresh_lists(self) -> None:
        self._refresh_sessions()
        self._refresh_templates()

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

        row_sess = QHBoxLayout()
        self.btn_sess_rec = QPushButton("开始长录音")
        self.btn_sess_rec.setToolTip("需先在「声音开钓配置」页监听（未监听会自动尝试开启）")
        self.btn_sess_rec.clicked.connect(self._on_session_rec_clicked)
        row_sess.addWidget(self.btn_sess_rec)
        row_sess.addWidget(QLabel("会话"))
        self.cmb_session = QComboBox()
        self.cmb_session.currentIndexChanged.connect(self._on_session_combo)
        row_sess.addWidget(self.cmb_session, 1)
        self.btn_sess_refresh = QPushButton("刷新")
        self.btn_sess_refresh.clicked.connect(self.refresh_lists)
        row_sess.addWidget(self.btn_sess_refresh)
        self.btn_sess_del = QPushButton("删除会话")
        self.btn_sess_del.setToolTip("删除当前选中的长录音会话")
        self.btn_sess_del.clicked.connect(self._delete_session)
        row_sess.addWidget(self.btn_sess_del)
        layout.addLayout(row_sess)

        row_tmpl = QHBoxLayout()
        row_tmpl.addWidget(QLabel("模板库"))
        self.cmb_template = QComboBox()
        self.cmb_template.currentIndexChanged.connect(self._on_template_combo)
        row_tmpl.addWidget(self.cmb_template, 1)
        self.btn_tmpl_play = QPushButton("试听")
        self.btn_tmpl_play.clicked.connect(self._play_template)
        row_tmpl.addWidget(self.btn_tmpl_play)
        self.btn_tmpl_rename = QPushButton("改名")
        self.btn_tmpl_rename.clicked.connect(self._rename_template)
        row_tmpl.addWidget(self.btn_tmpl_rename)
        self.btn_tmpl_del = QPushButton("删除")
        self.btn_tmpl_del.clicked.connect(self._delete_template)
        row_tmpl.addWidget(self.btn_tmpl_del)
        layout.addLayout(row_tmpl)

        self.wave = WaveformSelectWidget()
        self.wave.setMinimumHeight(110)
        self.wave.selection_changed.connect(self._on_wave_selection)
        layout.addWidget(self.wave)

        row_act = QHBoxLayout()
        self.btn_zoom_sel = QPushButton("缩放到选区")
        self.btn_zoom_sel.clicked.connect(self.wave.zoom_to_selection)
        row_act.addWidget(self.btn_zoom_sel)
        self.btn_zoom_all = QPushButton("显示全部")
        self.btn_zoom_all.clicked.connect(self.wave.zoom_all)
        row_act.addWidget(self.btn_zoom_all)
        self.btn_play_sel = QPushButton("试听选区")
        self.btn_play_sel.clicked.connect(self._play_selection)
        row_act.addWidget(self.btn_play_sel)
        self.btn_add_tpl = QPushButton("选区入库为模板")
        self.btn_add_tpl.setToolTip("自动命名并设为当前模板")
        self.btn_add_tpl.clicked.connect(self._add_template_from_selection)
        row_act.addWidget(self.btn_add_tpl)
        self.btn_backtest = QPushButton("回测查找")
        self.btn_backtest.clicked.connect(self._backtest_session)
        row_act.addWidget(self.btn_backtest)
        row_act.addStretch(1)
        self.lbl_sel = QLabel("选区：—")
        self.lbl_sel.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        row_act.addWidget(self.lbl_sel)
        layout.addLayout(row_act)

        row_mark = QHBoxLayout()
        self.btn_add_range = QPushButton("标注水花")
        self.btn_add_range.clicked.connect(self._add_selection_as_mark)
        row_mark.addWidget(self.btn_add_range)
        self.btn_clear_marks = QPushButton("清空标注")
        self.btn_clear_marks.clicked.connect(self._clear_marks)
        row_mark.addWidget(self.btn_clear_marks)
        row_mark.addStretch(1)
        layout.addLayout(row_mark)

        self.lbl_sess = QLabel("蓝=选区 · 绿=人工水花 · 橙=回测命中")
        self.lbl_sess.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        layout.addWidget(self.lbl_sess)
        layout.addStretch(1)

        top_scroll = QScrollArea()
        top_scroll.setWidgetResizable(True)
        top_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        top_scroll.setWidget(top)
        splitter.addWidget(top_scroll)

        log_wrap = QWidget()
        log_l = QVBoxLayout(log_wrap)
        log_l.setContentsMargins(0, 4, 0, 0)
        log_title = QLabel("日志（可拖边上沿改高度）")
        log_title.setStyleSheet(f"font-weight:600; color:{TEXT_MUTED}; font-size:12px;")
        log_l.addWidget(log_title)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(100)
        log_l.addWidget(self.log, 1)
        splitter.addWidget(log_wrap)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([420, 200])
        root.addWidget(splitter)

    def _refresh_sessions(self) -> None:
        cur = self.cmb_session.currentData()
        self.cmb_session.blockSignals(True)
        self.cmb_session.clear()
        self.cmb_session.addItem("（未选择）", None)
        sel = 0
        for i, p in enumerate(list_session_dirs(), start=1):
            self.cmb_session.addItem(p.name, p)
            if cur is not None and isinstance(cur, Path) and p == cur:
                sel = i
            elif self._last_session_root is not None and p == self._last_session_root:
                sel = i
        self.cmb_session.setCurrentIndex(sel)
        self.cmb_session.blockSignals(False)

    def _refresh_templates(self) -> None:
        active = resolve_template_path()
        self.cmb_template.blockSignals(True)
        self.cmb_template.clear()
        sel = 0
        for i, p in enumerate(list_library_templates()):
            self.cmb_template.addItem(template_source_label(p), p)
            try:
                if active is not None and p.resolve() == active.resolve():
                    sel = i
            except OSError:
                pass
        if self.cmb_template.count():
            self.cmb_template.setCurrentIndex(sel)
        self.cmb_template.blockSignals(False)
        bundled = False
        path = self.cmb_template.currentData()
        if isinstance(path, Path):
            bundled = is_bundled_template(path)
        self.btn_tmpl_rename.setEnabled(not bundled and path is not None)
        self.btn_tmpl_del.setEnabled(not bundled and path is not None)

    def _on_session_combo(self, _idx: int) -> None:
        root = self.cmb_session.currentData()
        if not isinstance(root, Path):
            return
        if self._last_session_root == root and self._last_session_wave is not None:
            return
        try:
            from autofish.first_click_trigger.session_eval import load_session

            wave, sr, ranges = load_session(root)
            self._apply_loaded_session(root, wave, sr, ranges)
            self._log(f"已加载会话 {root.name}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"加载会话失败：{exc}")

    def _delete_session(self) -> None:
        root = self.cmb_session.currentData()
        if not isinstance(root, Path):
            self._log("请先选择要删除的会话")
            return
        t = self._host.trigger
        if t is not None and t.is_session_recording:
            self._log("长录音进行中，请先停止再删除")
            return
        if (
            QMessageBox.question(self, "删除会话", f"删除 {root.name}？不可恢复")
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            delete_session_dir(root)
            if self._last_session_root == root:
                self._last_session_root = None
                self._last_session_wave = None
                self._last_session_ranges = []
                self.wave.clear()
                self.lbl_sess.setText("蓝=选区 · 绿=人工水花 · 橙=回测命中")
            self.refresh_lists()
            self._log(f"已删除会话 {root.name}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "删除失败", str(exc))
            self._log(f"删除会话失败：{exc}")

    def _on_template_combo(self, _idx: int) -> None:
        path = self.cmb_template.currentData()
        if not isinstance(path, Path):
            return
        try:
            set_active_template(path)
            self._host.ensure_trigger().load_template(path)
            self._host.refresh_template_list()
            self._log(f"当前模板：{template_source_label(path)}")
            bundled = is_bundled_template(path)
            self.btn_tmpl_rename.setEnabled(not bundled)
            self.btn_tmpl_del.setEnabled(not bundled)
        except Exception as exc:  # noqa: BLE001
            self._log(f"切换模板失败：{exc}")

    def _on_session_rec_clicked(self) -> None:
        try:
            trigger = self._host.start_listen_if_needed()
        except Exception as exc:  # noqa: BLE001
            self._log(str(exc))
            return
        try:
            if trigger.is_session_recording:
                out = trigger.stop_session_recording()
                paths = out["paths"]
                self._apply_loaded_session(
                    paths.root,
                    out["wave"],
                    int(out["samplerate"]),
                    list(out["ranges"]),
                )
                report = out.get("report")
                if isinstance(report, dict) and report.get("hits"):
                    self.wave.set_hits(list(report["hits"]))
                    self.lbl_sess.setText(
                        f"已保存 · 回测命中 {len(report['hits'])} 处（橙）"
                    )
                text = str(out.get("report_text") or "")
                if text:
                    self._log(text)
                elif not trigger.has_template:
                    self._log("已保存录音；选区入库后再回测")
                self.btn_sess_rec.setText("开始长录音")
                self.refresh_lists()
                # 选中刚保存的会话
                for i in range(self.cmb_session.count()):
                    if self.cmb_session.itemData(i) == paths.root:
                        self.cmb_session.setCurrentIndex(i)
                        break
            else:
                trigger.start_session_recording()
                self.btn_sess_rec.setText("停止并保存")
                self.wave.clear()
                self.lbl_sess.setText("长录音中…")
        except Exception as exc:  # noqa: BLE001
            self._log(f"长录音失败：{exc}")

    def _tick(self) -> None:
        t = self._host.trigger
        if t is not None:
            for line in t.drain_logs(channel="backtest"):
                self._log(line)
        if t is None or not t.is_session_recording:
            return
        dur = t.session_record_duration_s
        self.lbl_sess.setText(f"长录音中 · {dur:.1f}s")
        self.btn_sess_rec.setText("停止并保存")
        if int(dur * 5) != getattr(self, "_wave_preview_tick", -1):
            self._wave_preview_tick = int(dur * 5)
            prev, sr, ranges = t.session_recording_preview()
            if prev is not None and prev.size > 0:
                self.wave.set_audio(prev, sr, keep_view=True)
                self.wave.set_marks(ranges)

    def _on_wave_selection(self, start_s: float, end_s: float) -> None:
        self.lbl_sel.setText(f"选区：[{start_s:.2f}, {end_s:.2f}]s")

    def _persist_ranges(self, ranges: list[tuple[float, float]]) -> None:
        if self._last_session_root is None or self._last_session_wave is None:
            raise RuntimeError("没有已加载的会话")
        import numpy as np
        from autofish.first_click_trigger.session_eval import SessionPaths, save_session

        wave = np.asarray(self._last_session_wave, dtype=np.float32)
        paths = SessionPaths(
            root=self._last_session_root,
            audio=self._last_session_root / "audio.npy",
            meta=self._last_session_root / "meta.json",
            marks=self._last_session_root / "marks.json",
        )
        save_session(wave, self._last_session_sr, ranges, paths=paths)
        self._last_session_ranges = list(ranges)
        self.wave.set_marks(ranges)

    def _add_selection_as_mark(self) -> None:
        if self._last_session_wave is None:
            self._log("请先长录音或选择会话")
            return
        a, b = self.wave.selection
        if b - a < 0.05:
            self._log("选区太短")
            return
        try:
            ranges = list(self._last_session_ranges) + [(a, b)]
            self._persist_ranges(ranges)
            self._log(f"已标注水花 [{a:.2f},{b:.2f}]s")
        except Exception as exc:  # noqa: BLE001
            self._log(f"标注失败：{exc}")

    def _clear_marks(self) -> None:
        if self._last_session_root is None:
            return
        try:
            self._persist_ranges([])
            self._log("已清空标注")
        except Exception as exc:  # noqa: BLE001
            self._log(f"清空失败：{exc}")

    def _add_template_from_selection(self) -> None:
        if self._last_session_wave is None:
            self._log("请先加载会话并拖选")
            return
        a, b = self.wave.selection
        if b - a < 0.05:
            self._log("选区太短")
            return
        try:
            import numpy as np

            trigger = self._host.ensure_trigger()
            wave = np.asarray(self._last_session_wave, dtype=np.float32)
            trigger.replace_template_from_range(
                wave, self._last_session_sr, a, b, save_user=True
            )
            self._host.refresh_template_list()
            self.refresh_lists()
            self._log(f"选区已入库 [{a:.2f},{b:.2f}]s")
        except Exception as exc:  # noqa: BLE001
            self._log(f"入库失败：{exc}")

    def _play_selection(self) -> None:
        if self._last_session_wave is None:
            return
        a, b = self.wave.selection
        if b - a < 0.02:
            return
        try:
            import numpy as np
            import sounddevice as sd

            wave = np.asarray(self._last_session_wave, dtype=np.float32)
            i0 = int(a * self._last_session_sr)
            i1 = int(b * self._last_session_sr)
            device = FirstClickTrigger._playback_device()
            from autofish.first_click_trigger.trigger import _audition_wave

            sd.stop()
            sd.play(
                _audition_wave(wave[i0:i1]),
                samplerate=self._last_session_sr,
                device=device,
                blocking=False,
            )
            self._log(f"试听选区 [{a:.2f},{b:.2f}]s")
        except Exception as exc:  # noqa: BLE001
            self._log(f"试听失败：{exc}")

    def _play_template(self) -> None:
        try:
            t = self._host.ensure_trigger()
            path = self.cmb_template.currentData()
            if isinstance(path, Path):
                t.load_template(path)
            if not t.has_template:
                raise RuntimeError("没有模板")
            t.play_template()
            self._log("正在播放模板")
        except Exception as exc:  # noqa: BLE001
            self._log(f"播放失败：{exc}")

    def _rename_template(self) -> None:
        path = self.cmb_template.currentData()
        if not isinstance(path, Path) or is_bundled_template(path):
            return
        name, ok = QInputDialog.getText(
            self, "改名模板", "新名称（不含扩展名）", text=path.stem
        )
        if not ok or not name.strip():
            return
        try:
            rename_library_template(path, name)
            self._host.refresh_template_list()
            self.refresh_lists()
            self._log(f"已改名 → {name.strip()}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "改名失败", str(exc))

    def _delete_template(self) -> None:
        path = self.cmb_template.currentData()
        if not isinstance(path, Path) or is_bundled_template(path):
            return
        if (
            QMessageBox.question(self, "删除模板", f"删除 {path.name}？")
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            delete_library_template(path)
            self._host.reload_active_template()
            self._host.refresh_template_list()
            self.refresh_lists()
            self._log(f"已删除 {path.name}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "删除失败", str(exc))

    def _apply_loaded_session(
        self,
        root: Path,
        wave,
        samplerate: int,
        ranges: list[tuple[float, float]],
    ) -> None:
        import numpy as np

        self._last_session_root = root
        self._last_session_wave = np.asarray(wave, dtype=np.float32)
        self._last_session_sr = int(samplerate)
        self._last_session_ranges = list(ranges)
        dur = float(len(wave) / max(samplerate, 1))
        self.wave.set_audio(self._last_session_wave, self._last_session_sr)
        self.wave.set_marks(ranges)
        self.wave.set_hits([])
        if ranges:
            self.wave.set_selection(ranges[-1][0], ranges[-1][1])
        self.lbl_sess.setText(
            f"{root.name} · {dur:.1f}s · 人工水花 {len(ranges)} 段"
        )

    def _backtest_session(self) -> None:
        if self._last_session_root is None or self._last_session_wave is None:
            self._log("请先长录音或选择会话")
            return
        try:
            if self._last_session_ranges:
                self._persist_ranges(self._last_session_ranges)
        except Exception:
            pass
        try:
            trigger = self._host.ensure_trigger()
            path = resolve_template_path()
            if not trigger.has_template and path is not None:
                trigger.load_template(path)
            if not trigger.has_template:
                self._log("没有模板：请从选区入库")
                return
            report = trigger.backtest_last_or_dir(self._last_session_root)
            hits = list(report.get("hits") or [])
            self.wave.set_hits(hits)
            self.lbl_sess.setText(
                f"回测命中 {len(hits)} 处（橙）· 人工水花 {len(self._last_session_ranges)} 段"
            )
            text = str(report.get("report_text") or "")
            if text:
                self._log(text)
        except Exception as exc:  # noqa: BLE001
            self._log(f"回测失败：{exc}")

    def _log(self, msg: str) -> None:
        # 只写本页日志，不转发主控
        _append_log(self._logs, self.log, msg)

    def shutdown(self) -> None:
        self._timer.stop()
