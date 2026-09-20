"""声音开钓设置面板（可嵌入主壳「声音」页）。"""

from __future__ import annotations

import sys
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from autofish.first_click_trigger.audio_input import AudioInput
from autofish.first_click_trigger.paths import (
    resolve_template_path,
    template_source_label,
    user_template_dir,
    user_template_path,
)
from autofish.first_click_trigger.trigger import FirstClickTrigger

if TYPE_CHECKING:
    from autofish.bus import AutofishBus


class FirstClickTriggerPanel(QWidget):
    """设备 / 模板 / 阈值；会话启停由主控 A 勾选驱动。"""

    def __init__(
        self,
        parent=None,
        *,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus: AutofishBus | None = None
        self._trigger: FirstClickTrigger | None = None
        self._logs: deque[str] = deque(maxlen=80)
        self._template_path: Path | None = None
        self._external_log = log_fn

        self._build_ui()
        self._refresh_devices()
        self._load_resolved_template()
        self._update_state()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_state)
        self._timer.start(200)

    def attach_bus(self, bus: "AutofishBus | None") -> None:
        self._bus = bus

    @property
    def trigger(self) -> FirstClickTrigger | None:
        return self._trigger

    def set_session_enabled(self, enabled: bool) -> None:
        """主控 A：开则确保监听 + 会话 WAIT；关则禁用会话（可仍监听便于标记）。"""
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
                    raise RuntimeError("没有模板：请先在本页监听并标记水花")
            self._trigger.set_session_enabled(True)
            self._log("声音开钓 ON · 会话 WAIT")
        else:
            if self._trigger is not None:
                self._trigger.set_session_enabled(False)
            self._log("声音开钓 OFF")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        row_listen = QHBoxLayout()
        self.btn_listen = QPushButton("开始监听")
        self.btn_listen.setToolTip("开始记下最近 5 秒声音，便于事后标记水花")
        self.btn_listen.clicked.connect(self._on_listen_clicked)
        row_listen.addWidget(self.btn_listen)
        row_listen.addStretch(1)
        layout.addLayout(row_listen)

        dev = QGroupBox("音频设备")
        dev_l = QVBoxLayout(dev)
        row = QHBoxLayout()
        row.addWidget(QLabel("设备"))
        self.cmb_device = QComboBox()
        self.cmb_device.setEnabled(False)
        row.addWidget(self.cmb_device, 1)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_devices)
        row.addWidget(self.btn_refresh)
        dev_l.addLayout(row)
        self.lbl_device_hint = QLabel("")
        self.lbl_device_hint.setStyleSheet("color:#6e6e73; font-size:11px;")
        self.lbl_device_hint.setWordWrap(True)
        dev_l.addWidget(self.lbl_device_hint)
        layout.addWidget(dev)

        tmpl = QGroupBox("模板")
        tmpl_l = QVBoxLayout(tmpl)
        row_tmpl = QHBoxLayout()
        self.btn_mark = QPushButton("标记水花声")
        self.btn_mark.setToolTip(
            "听到水花后点：按能量截取有效段（去前空白、尾部多留一点）"
        )
        self.btn_mark.clicked.connect(self._mark_splash)
        row_tmpl.addWidget(self.btn_mark)
        self.btn_play = QPushButton("播放模板")
        self.btn_play.setToolTip("试听当前模板，确认是否录到水花声（从扬声器播放）")
        self.btn_play.clicked.connect(self._play_template)
        row_tmpl.addWidget(self.btn_play)
        self.btn_load = QPushButton("加载模板")
        self.btn_load.clicked.connect(self._load_template)
        row_tmpl.addWidget(self.btn_load)
        self.btn_save = QPushButton("保存模板")
        self.btn_save.clicked.connect(self._save_template)
        row_tmpl.addWidget(self.btn_save)
        tmpl_l.addLayout(row_tmpl)
        self.lbl_template = QLabel("模板：无")
        self.lbl_template.setStyleSheet("color:#6e6e73; font-size:11px;")
        tmpl_l.addWidget(self.lbl_template)
        self.lbl_mark_hint = QLabel(
            "先开始监听；听到水花后点「标记」。开钓开关在主控「声音开钓」。"
        )
        self.lbl_mark_hint.setStyleSheet("color:#6e6e73; font-size:11px;")
        self.lbl_mark_hint.setWordWrap(True)
        tmpl_l.addWidget(self.lbl_mark_hint)
        layout.addWidget(tmpl)

        match = QGroupBox("匹配参数")
        match_l = QVBoxLayout(match)
        row_thr = QHBoxLayout()
        row_thr.addWidget(QLabel("相似度阈值"))
        self.sld_threshold = QSlider(Qt.Orientation.Horizontal)
        self.sld_threshold.setRange(30, 95)
        self.sld_threshold.setValue(72)
        self.sld_threshold.setSingleStep(1)
        self.sld_threshold.valueChanged.connect(self._on_threshold_changed)
        row_thr.addWidget(self.sld_threshold, 1)
        self.lbl_threshold = QLabel("0.72")
        self.lbl_threshold.setMinimumWidth(40)
        row_thr.addWidget(self.lbl_threshold)
        match_l.addLayout(row_thr)
        self.lbl_thr_hint = QLabel("建议 0.68～0.80；已用滑动对齐+起跳门控")
        self.lbl_thr_hint.setStyleSheet("color:#6e6e73; font-size:11px;")
        match_l.addWidget(self.lbl_thr_hint)
        layout.addWidget(match)

        stat = QGroupBox("状态")
        stat_l = QVBoxLayout(stat)
        self.lbl_status = QLabel("未监听")
        self.lbl_status.setStyleSheet("font-weight:600;")
        stat_l.addWidget(self.lbl_status)
        self.lbl_session = QLabel("会话：disabled")
        stat_l.addWidget(self.lbl_session)
        self.lbl_level = QLabel("音量：—")
        stat_l.addWidget(self.lbl_level)
        self.lbl_mode = QLabel("模式：—")
        stat_l.addWidget(self.lbl_mode)
        self.lbl_score = QLabel("最新相似度：—")
        stat_l.addWidget(self.lbl_score)
        self.lbl_last = QLabel("最后触发：—")
        stat_l.addWidget(self.lbl_last)
        self.lbl_count = QLabel("触发次数：0")
        stat_l.addWidget(self.lbl_count)
        layout.addWidget(stat)

        layout.addStretch(1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(80)
        self.log.setMaximumHeight(120)
        layout.addWidget(self.log)

    def _refresh_devices(self) -> None:
        self.cmb_device.clear()
        devices = AudioInput.list_devices()
        current_index = 0
        for i, d in enumerate(devices):
            self.cmb_device.addItem(f"{d.name}", d.index)
            if d.is_loopback:
                current_index = i
        self.cmb_device.setEnabled(len(devices) > 0 and (
            self._trigger is None or not self._trigger.is_running()
        ))
        if len(devices) > 0:
            self.cmb_device.setCurrentIndex(current_index)
        self._update_device_hint()

    def _update_device_hint(self) -> None:
        if sys.platform == "darwin":
            self.lbl_device_hint.setText(
                "1) 系统「输出」选「多输出设备」（扬声器+BlackHole）\n"
                "2) 本页设备选 BlackHole 2ch\n"
                "3) 隐私 → 麦克风：允许本程序\n"
                "音量若一直 -120：先停再开监听，并播一段音乐试音量。"
            )
        elif sys.platform == "win32":
            self.lbl_device_hint.setText(
                "Windows 选择带 (Loopback) 的输出设备即可录制系统声音。"
            )
        else:
            self.lbl_device_hint.setText("选择正确的输入/监听设备以捕获游戏声音。")

    def _set_template_label(self, path: Path | None) -> None:
        self._template_path = path
        self.lbl_template.setText(f"模板：{template_source_label(path)}")

    def _load_resolved_template(self) -> None:
        path = resolve_template_path()
        if path is None:
            self._set_template_label(None)
            return
        try:
            self._ensure_trigger().load_template(path)
            self._set_template_label(path)
            self._log(f"已加载模板：{template_source_label(path)}")
        except Exception as exc:  # noqa: BLE001
            self.lbl_template.setText(f"模板：加载失败 {exc}")

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
        self._log(f"开始监听 · {self.cmb_device.currentText()}")

    def _stop_listen(self) -> None:
        if self._trigger is not None:
            self._trigger.set_session_enabled(False)
            self._trigger.stop()
        self.btn_listen.setText("开始监听")
        self.cmb_device.setEnabled(True)
        self._log("已停止监听")

    def _mark_splash(self) -> None:
        if self._trigger is None or not self._trigger.is_running():
            self._log("请先开始监听，听到水花后再标记")
            return
        try:
            wave = self._trigger.mark_splash()
            path = user_template_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            self._trigger.save_template(path)
            self._set_template_label(path)
            dur = wave.size / max(1, self._trigger._audio.samplerate)
            self._log(f"已截取有效段 {dur:.2f}s 并写入用户覆盖；可点「播放模板」试听")
        except Exception as exc:  # noqa: BLE001
            self._log(f"标记失败：{exc}")

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
            self._log("正在播放模板（扬声器）")
        except Exception as exc:  # noqa: BLE001
            self._log(f"播放失败：{exc}")
            QMessageBox.warning(self, "播放失败", str(exc))

    def _load_template(self) -> None:
        start_dir = user_template_dir()
        start_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self, "加载模板", str(start_dir), "Numpy (*.npy)"
        )
        if not path:
            return
        try:
            trigger = self._ensure_trigger()
            trigger.load_template(path)
            self._set_template_label(Path(path))
            self._log(f"已加载模板：{path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "加载失败", str(exc))
            self._log(f"加载模板失败：{exc}")

    def _save_template(self) -> None:
        path = user_template_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "保存模板（用户覆盖）",
            str(path),
            "Numpy (*.npy)",
        )
        if not chosen:
            return
        try:
            trigger = self._ensure_trigger()
            trigger.save_template(chosen)
            self._set_template_label(Path(chosen))
            self._log(f"已保存模板：{chosen}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "保存失败", str(exc))
            self._log(f"保存模板失败：{exc}")

    def _update_state(self) -> None:
        if self._trigger is not None:
            for line in self._trigger.drain_logs():
                self._log(line)
            self.lbl_session.setText(f"会话：{self._trigger.session_state.value}")
        if self._trigger is None or not self._trigger.is_running():
            self.lbl_status.setText("未监听")
            self.lbl_status.setStyleSheet("font-weight:600; color:#c62828;")
            self.lbl_level.setText("音量：—")
            self.lbl_mode.setText("模式：—")
            self.lbl_score.setText("最新相似度：—")
            return
        self.lbl_status.setText("监听中")
        self.lbl_status.setStyleSheet("font-weight:600; color:#2e7d32;")
        self.lbl_level.setText(f"音量：{self._trigger.level_db:.0f} dB")
        self.lbl_mode.setText(f"模式：{self._trigger.running_mode}")
        self.lbl_score.setText(f"最新相似度：{self._trigger.last_score:.2f}")
        if self._trigger.last_trigger_at > 0:
            ago = time.time() - self._trigger.last_trigger_at
            self.lbl_last.setText(f"最后触发：{ago:.1f}s 前")
        self.lbl_count.setText(f"触发次数：{self._trigger.trigger_count}")

    def _log(self, msg: str) -> None:
        if self._external_log is not None:
            self._external_log(msg)
        line = f"{time.strftime('%H:%M:%S')}  {msg}"
        self._logs.appendleft(line)
        self.log.setPlainText("\n".join(self._logs))
        self.log.verticalScrollBar().setValue(0)

    def shutdown(self) -> None:
        self._timer.stop()
        if self._trigger is not None:
            self._trigger.set_session_enabled(False)
            self._trigger.stop()
            self._trigger = None
