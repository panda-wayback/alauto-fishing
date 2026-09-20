"""FirstClickTrigger：开钓会话机 + 音频监听 + 第一下。"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from autofish.act.mouse import MouseActuator
from autofish.first_click_trigger.audio_input import AudioInput
from autofish.first_click_trigger.detector import AudioDetector
from autofish.first_click_trigger.ring_buffer import AudioRingBuffer
from autofish.first_click_trigger.template_matcher import TemplateMatcher
from autofish.topics import CastSessionEvent, CastSessionState, PosEvent, Topic
from autofish.worker_base import WorkerBase

if TYPE_CHECKING:
    import numpy.typing as npt

    from autofish.bus import AutofishBus


_MIN_HOLD_S = 0.1
_MAX_HOLD_S = 1.0
_MIN_DELAY_BEFORE_CLICK_S = 0.2
_MAX_DELAY_BEFORE_CLICK_S = 1.5
_WAIT_BOBBER_TIMEOUT_S = 3.0
_LOST_BOBBER_END_S = 1.0
_DEFAULT_THRESHOLD = 0.72
_RING_SECONDS = 5.0
_MARK_SECONDS = 1.0
_SILENT_DB = -55.0


def _db(rms: float) -> float:
    if rms <= 0:
        return -120.0
    return 20.0 * float(np.log10(max(rms, 1e-12)))


class FirstClickTrigger(WorkerBase):
    """
    开钓会话（A）：
    WAIT →（水声）→ FIRST_CLICK（等 0.2～1.5s + 按住 0.1～1.0s）
         → WAIT_BOBBER →（出漂）→ FISHING →（丢漂满 1s）→ WAIT
    仅 WAIT 听声；A 关为 DISABLED。不订 ActionIntent。
    """

    def __init__(
        self,
        bus: "AutofishBus | None",
        device: int | str | None = None,
        threshold: float = _DEFAULT_THRESHOLD,
        use_energy_fallback: bool = False,
        energy_threshold_db: float = -30.0,
        template_path: str | Path | None = None,
    ) -> None:
        super().__init__(bus, name="FirstClickTrigger")
        self._mouse = MouseActuator()
        self._audio = AudioInput(device=device)
        self._ring = AudioRingBuffer(int(self._audio.samplerate * _RING_SECONDS))
        self._matcher = TemplateMatcher(
            samplerate=self._audio.samplerate,
            template_duration_s=2.0,
            threshold=threshold,
        )
        self._detector = AudioDetector(
            samplerate=self._audio.samplerate,
            threshold_db=energy_threshold_db,
            cooldown_ms=0.0,
        )
        self._use_fallback = use_energy_fallback
        self._session_enabled = False
        self._session = CastSessionState.DISABLED
        self._lock = threading.Lock()
        self._log_lock = threading.Lock()
        self._pending_logs: deque[str] = deque(maxlen=40)
        self._last_trigger_at = 0.0
        self._trigger_count = 0
        self._last_score = 0.0
        self._level_db = -120.0
        self._running_mode = "等待标记"
        self._wait_bobber_since: float | None = None
        self._miss_since: float | None = None
        self._pos_subscribed = False
        if template_path is not None:
            self.load_template(template_path)

    @property
    def trigger_count(self) -> int:
        return self._trigger_count

    @property
    def last_trigger_at(self) -> float:
        return self._last_trigger_at

    @property
    def last_score(self) -> float:
        return self._last_score

    @property
    def level_db(self) -> float:
        return self._level_db

    @property
    def running_mode(self) -> str:
        return self._running_mode

    @property
    def session_state(self) -> CastSessionState:
        return self._session

    @property
    def has_template(self) -> bool:
        return self._matcher.has_template

    @property
    def template_wave(self) -> "npt.NDArray[np.float32] | None":
        wave = self._matcher._template_wave
        return None if wave is None else wave.copy()

    def set_click_enabled(self, enabled: bool) -> None:
        """兼容旧名：等同 set_session_enabled。"""
        self.set_session_enabled(enabled)

    def set_session_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        with self._lock:
            if enabled == self._session_enabled:
                return
            self._session_enabled = enabled
            if enabled:
                self._set_session(CastSessionState.WAIT, "a_on")
            else:
                if self._session == CastSessionState.FIRST_CLICK:
                    try:
                        self._mouse.force_release()
                    except Exception:  # noqa: BLE001
                        pass
                self._set_session(CastSessionState.DISABLED, "a_off")

    def set_threshold(self, threshold: float) -> None:
        self._matcher.threshold = threshold

    def set_energy_threshold(self, db: float) -> None:
        self._detector.threshold_db = db
        self._detector.threshold_linear = 10 ** (db / 20.0)

    def load_template(self, path: str | Path) -> None:
        self._matcher.load_template(path)
        self._running_mode = "频谱模板匹配"

    def save_template(self, path: str | Path) -> None:
        self._matcher.save_template(path)

    def set_template(self, wave) -> None:
        self._matcher.set_template(wave)
        self._running_mode = "频谱模板匹配"

    def play_template(self) -> None:
        """用扬声器试听当前模板（避免仍走 BlackHole 听不见）。"""
        wave = self.template_wave
        if wave is None or wave.size == 0:
            raise RuntimeError("没有模板可播放")
        import sounddevice as sd

        sd.stop()
        device = self._playback_device()
        sd.play(
            wave,
            samplerate=self._audio.samplerate,
            device=device,
            blocking=False,
        )

    @staticmethod
    def _playback_device() -> int | None:
        """优先扬声器/耳机，跳过 BlackHole 等虚拟设备。"""
        import sounddevice as sd

        skip = ("blackhole", "loopback", "oray", "soundflower", "aggregate", "多输出")
        prefer = ("扬声器", "speaker", "headphone", "耳机", "外置耳机")
        devices = list(sd.query_devices())
        preferred: int | None = None
        fallback: int | None = None
        for i, d in enumerate(devices):
            if int(d.get("max_output_channels") or 0) <= 0:
                continue
            name = str(d.get("name") or "").lower()
            if any(s in name for s in skip):
                continue
            fallback = i if fallback is None else fallback
            if any(p in name for p in prefer):
                preferred = i
                break
        return preferred if preferred is not None else fallback

    def mark_splash(self, seconds: float = _MARK_SECONDS) -> "npt.NDArray[np.float32]":
        """在最近 5 秒里按能量截取有效段（去前空白、尾部多留一点）。"""
        _ = seconds
        with self._lock:
            if self._ring.size < self._audio.samplerate // 4:
                raise RuntimeError(
                    f"录音还太短（仅 {self._ring.size / self._audio.samplerate:.2f}s），"
                    "请先听几秒游戏声再标记"
                )
            wave, rms = self._ring.extract_active_segment(self._audio.samplerate)
            db = _db(rms)
            if wave.size == 0 or db < _SILENT_DB:
                raise RuntimeError(
                    f"最近几秒几乎没声音（峰值 {db:.0f} dB）。"
                    "请确认选的是虚拟音频设备，且系统输出已切到该设备"
                )
            self.set_template(wave)
        return wave

    def start(self) -> None:
        self._subscribe_pos(True)
        super().start()

    def stop(self) -> None:
        self._subscribe_pos(False)
        with self._lock:
            if self._session_enabled:
                self._set_session(CastSessionState.WAIT, "stopped")
            else:
                self._set_session(CastSessionState.DISABLED, "stopped")
        super().stop()

    def _subscribe_pos(self, on: bool) -> None:
        if self.bus is None:
            return
        if on and not self._pos_subscribed:
            self.bus.subscribe(Topic.POS, self._on_pos)
            self._pos_subscribed = True
        elif not on and self._pos_subscribed:
            self.bus.unsubscribe(Topic.POS, self._on_pos)
            self._pos_subscribed = False

    def _set_session(self, state: CastSessionState, detail: str = "") -> None:
        if state == self._session and not detail:
            return
        prev = self._session
        self._session = state
        if state == CastSessionState.WAIT_BOBBER:
            self._wait_bobber_since = time.time()
            self._miss_since = None
        elif state == CastSessionState.FISHING:
            self._wait_bobber_since = None
            self._miss_since = None
        elif state in (CastSessionState.WAIT, CastSessionState.DISABLED):
            self._wait_bobber_since = None
            self._miss_since = None
        if self.bus is not None:
            self.bus.publish_cast_session(
                CastSessionEvent(state=state, ts=time.time(), detail=detail)
            )
        if prev != state:
            self._emit_log(f"会话 {prev.value} → {state.value}" + (f" · {detail}" if detail else ""))

    def _on_pos(self, event: PosEvent) -> None:
        with self._lock:
            if not self._session_enabled:
                return
            if self._session == CastSessionState.WAIT_BOBBER:
                if event.pos is not None:
                    self._set_session(CastSessionState.FISHING, "bobber")
                return
            if self._session == CastSessionState.FISHING:
                if event.pos is not None:
                    self._miss_since = None
                elif self._miss_since is None:
                    self._miss_since = time.time()

    def _check_timeouts(self) -> None:
        now = time.time()
        with self._lock:
            if not self._session_enabled:
                return
            if (
                self._session == CastSessionState.WAIT_BOBBER
                and self._wait_bobber_since is not None
                and now - self._wait_bobber_since >= _WAIT_BOBBER_TIMEOUT_S
            ):
                self._set_session(CastSessionState.WAIT, "bobber_timeout")
                return
            if (
                self._session == CastSessionState.FISHING
                and self._miss_since is not None
                and now - self._miss_since >= _LOST_BOBBER_END_S
            ):
                self._set_session(CastSessionState.WAIT, "lost_1s")

    def _run(self) -> None:
        self._audio.start()
        try:
            while not self._stop.is_set():
                self._check_timeouts()
                block = self._audio.read()
                if block is None:
                    time.sleep(0.005)
                    continue

                mono = block.mean(axis=1) if block.ndim > 1 else block
                mono = np.asarray(mono, dtype=np.float32)
                rms = float(np.sqrt(np.mean(mono**2))) if mono.size else 0.0
                level_db = 20 * np.log10(rms) if rms > 0 else -120.0

                triggered = False
                score = 0.0
                can_listen = False
                with self._lock:
                    self._ring.extend(mono)
                    self._level_db = level_db
                    can_listen = (
                        self._session_enabled
                        and self._session == CastSessionState.WAIT
                    )
                    if can_listen and self._matcher.has_template:
                        triggered, score = self._matcher.feed(mono)
                        self._last_score = score
                    elif can_listen and self._use_fallback:
                        triggered = self._detector.feed(mono)
                        score = float(rms)
                        self._last_score = rms
                    elif self._matcher.has_template:
                        # 非 WAIT：仍喂匹配器以免内部状态陈旧，但忽略命中
                        _, score = self._matcher.feed(mono)
                        self._last_score = score

                if triggered and can_listen:
                    self._do_first_click(score)
        finally:
            self._audio.stop()
            self._mouse.force_release()

    def drain_logs(self) -> list[str]:
        """取出后台线程产生的日志（供 UI 轮询）。"""
        with self._log_lock:
            lines = list(self._pending_logs)
            self._pending_logs.clear()
        return lines

    def _emit_log(self, msg: str) -> None:
        with self._log_lock:
            self._pending_logs.append(msg)

    def _do_first_click(self, score: float = 0.0) -> None:
        with self._lock:
            if (
                not self._session_enabled
                or self._session != CastSessionState.WAIT
            ):
                return
            self._set_session(CastSessionState.FIRST_CLICK, "splash")
            thr = float(self._matcher.threshold)
            delay_s = random.uniform(
                _MIN_DELAY_BEFORE_CLICK_S, _MAX_DELAY_BEFORE_CLICK_S
            )
            self._emit_log(
                f"命中水花 · 相似 {score:.2f} / 阈值 {thr:.2f} · "
                f"等待 {delay_s:.2f}s 后按住"
            )

        try:
            time.sleep(delay_s)
            with self._lock:
                if (
                    not self._session_enabled
                    or self._session != CastSessionState.FIRST_CLICK
                ):
                    return
            hold_s = random.uniform(_MIN_HOLD_S, _MAX_HOLD_S)
            self._emit_log(f"开始按住 · {hold_s:.2f}s")
            self._mouse.set_holding(True)
            time.sleep(hold_s)
            self._mouse.set_holding(False)
            with self._lock:
                if (
                    not self._session_enabled
                    or self._session != CastSessionState.FIRST_CLICK
                ):
                    return
                self._last_trigger_at = time.time()
                self._trigger_count += 1
                self._emit_log(
                    f"已松开 · 本次等待 {delay_s:.2f}s · 按住 {hold_s:.2f}s"
                )
                self._set_session(CastSessionState.WAIT_BOBBER, "clicked")
        except Exception as exc:  # noqa: BLE001
            self._emit_log(f"第一下失败 · {exc}")
            try:
                self._mouse.force_release()
            except Exception:  # noqa: BLE001
                pass
            with self._lock:
                if self._session_enabled:
                    self._set_session(CastSessionState.WAIT, "error")

    def reset_stats(self) -> None:
        self._trigger_count = 0

    def get_devices(self) -> list:
        return AudioInput.list_devices()
