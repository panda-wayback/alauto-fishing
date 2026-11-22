"""FirstClickTrigger：开钓会话机 + 音频监听 + 第一下。"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from autofish.act.mouse import MouseActuator
from autofish.cursor_arm import grab_system_cursor, see_fishing_hook
from autofish.first_click_trigger.audio_input import AudioInput
from autofish.first_click_trigger.ring_buffer import AudioRingBuffer
from autofish.first_click_trigger.template_matcher import TemplateMatcher
from autofish.events.topics import (
    CastPhase,
    CastSessionEvent,
    CastSessionState,
    PosEvent,
    SplashHit,
    Topic,
)
from autofish.events.worker_base import WorkerBase

if TYPE_CHECKING:
    import numpy.typing as npt

    from autofish.events.bus import AutofishBus


_MIN_HOLD_S = 0.7
_MAX_HOLD_S = 1.5
_MIN_DELAY_BEFORE_CLICK_S = 0.3
_MAX_DELAY_BEFORE_CLICK_S = 1.5
_MIN_AFTER_RELEASE_S = 0.2
_MAX_AFTER_RELEASE_S = 0.8
_WAIT_BOBBER_TIMEOUT_S = 3.0
_LOST_BOBBER_END_S = 1.0
_WAIT_LISTEN_COOLDOWN_S = 3.0
# 一次水声识别从采集到按下的最长寿命；超时整次丢掉，不补点
_MAX_SPLASH_AGE_S = 2.0
_DEFAULT_THRESHOLD = 0.70
_RING_SECONDS = 20.0
_LIVE_WAVE_SECONDS = 20.0
# 试听时峰值归一化目标（只影响播放，不改模板文件）
_AUDITION_PEAK = 0.85


def remaining_click_wait(
    delay_s: float,
    queue_lag_s: float,
    match_tail_s: float,
    *,
    max_age_s: float = _MAX_SPLASH_AGE_S,
) -> float | None:
    """按水声采集时刻计算第一下还要等多久。

    年龄 = 队列等待 + 模板结束到最新样本。超过 max_age_s（默认 2 秒）整次丢掉。
    实际再等 = min(delay, max_age) − 年龄（不小于 0），保证按下不晚于采集后 max_age。
    """
    age = max(0.0, float(queue_lag_s)) + max(0.0, float(match_tail_s))
    limit = max(0.0, float(max_age_s))
    if age >= limit:
        return None
    return max(0.0, min(float(delay_s), limit) - age)


def _audition_wave(wave: "npt.NDArray[np.float32]") -> "npt.NDArray[np.float32]":
    """试听用：按峰值放大到可听响度，不改原模板。"""
    mono = np.asarray(wave, dtype=np.float32)
    if mono.ndim > 1:
        mono = mono.mean(axis=1)
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    if peak < 1e-8:
        return mono
    gain = _AUDITION_PEAK / peak
    out = mono * gain
    return np.clip(out, -1.0, 1.0).astype(np.float32)


class FirstClickTrigger(WorkerBase):
    """
    开钓会话（A）：
    WAIT →（水声）→ FIRST_CLICK（等待区间 + 长按区间，可配置）
         → WAIT_BOBBER →（出漂）→ FISHING →（丢漂满 1s）→ WAIT（≥3s 再听）
    仅 WAIT 且冷却已过才听声；A 关为 DISABLED。不订 ActionIntent。
    """

    def __init__(
        self,
        bus: "AutofishBus | None",
        device: int | str | None = None,
        threshold: float = _DEFAULT_THRESHOLD,
        template_path: str | Path | None = None,
        *,
        loopback: bool | None = None,
    ) -> None:
        super().__init__(bus, name="FirstClickTrigger")
        self._mouse = MouseActuator()
        self._audio = AudioInput(device=device, loopback=loopback)
        self._ring = AudioRingBuffer(int(self._audio.samplerate * _RING_SECONDS))
        self._matcher = TemplateMatcher(
            samplerate=self._audio.samplerate,
            template_duration_s=2.0,
            threshold=threshold,
        )
        self._session_enabled = False
        self._session = CastSessionState.DISABLED
        self._lock = threading.Lock()
        self._log_lock = threading.Lock()
        self._pending_logs: deque[tuple[str, str]] = deque(maxlen=80)
        self._last_trigger_at = 0.0
        self._trigger_count = 0
        self._last_score = 0.0
        self._level_db = -120.0
        self._wait_bobber_since: float | None = None
        self._miss_since: float | None = None
        self._listen_after: float = 0.0
        self._pos_subscribed = False
        self._last_reject_log_at = 0.0
        self._session_recording = False
        # 实时波形命中：墙钟时刻 + 分数（展示时映射到最近 20s）
        self._live_hits: deque[dict[str, float]] = deque(maxlen=40)
        self._was_listening = False
        self._next_reconnect_at = 0.0
        self._delay_lo_s = _MIN_DELAY_BEFORE_CLICK_S
        self._delay_hi_s = _MAX_DELAY_BEFORE_CLICK_S
        self._hold_lo_s = _MIN_HOLD_S
        self._hold_hi_s = _MAX_HOLD_S
        self._after_lo_s = _MIN_AFTER_RELEASE_S
        self._after_hi_s = _MAX_AFTER_RELEASE_S
        self._cursor_shape: Callable[[], str] | None = None
        if template_path is not None:
            self.load_template(template_path)

    @property
    def trigger_count(self) -> int:
        return self._trigger_count

    @property
    def samplerate(self) -> int:
        return int(self._audio.samplerate)

    def recent_monitor_wave(self, seconds: float = _LIVE_WAVE_SECONDS) -> np.ndarray:
        """最近 N 秒单声道（供开钓页波形）。"""
        n = int(max(0.5, float(seconds)) * self._audio.samplerate)
        with self._lock:
            return self._ring.last(n)

    def live_hits_for_monitor(
        self, seconds: float = _LIVE_WAVE_SECONDS
    ) -> list[dict[str, float]]:
        """把墙钟命中映射到「最近 N 秒波形」的相对秒。"""
        now = time.time()
        window = max(0.5, float(seconds))
        t0 = now - window
        tpl_s = float(getattr(self._matcher, "template_duration_s", 0.5) or 0.5)
        out: list[dict[str, float]] = []
        with self._lock:
            hits = list(self._live_hits)
        for h in hits:
            end_wall = float(h["t_wall"])
            if end_wall < t0:
                continue
            end_s = end_wall - t0
            start_s = max(0.0, end_s - tpl_s)
            out.append(
                {
                    "start_s": start_s,
                    "end_s": min(window, end_s),
                    "t_s": end_s,
                    "score": float(h.get("score", 0.0)),
                }
            )
        return out

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
    def session_state(self) -> CastSessionState:
        return self._session

    @property
    def has_template(self) -> bool:
        return self._matcher.has_template

    @property
    def is_session_recording(self) -> bool:
        return self._session_recording

    @property
    def session_record_duration_s(self) -> float:
        return self._audio.record_frames / float(max(self._audio.samplerate, 1))

    @property
    def template_wave(self) -> "npt.NDArray[np.float32] | None":
        return self._matcher.template_wave

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

    def set_cursor_shape(self, shape: Callable[[], str] | None) -> None:
        """共享光标外形探针；None 时起钩回退为当场抓光标认钩。"""
        self._cursor_shape = shape

    def set_click_timing(
        self,
        delay_lo_s: float,
        delay_hi_s: float,
        hold_lo_s: float,
        hold_hi_s: float,
        after_lo_s: float = _MIN_AFTER_RELEASE_S,
        after_hi_s: float = _MAX_AFTER_RELEASE_S,
    ) -> None:
        """开钓第一下：等待、长按、松开后停顿区间（秒）。"""
        d0 = float(max(0.0, min(5.0, delay_lo_s)))
        d1 = float(max(0.0, min(5.0, delay_hi_s)))
        h0 = float(max(0.05, min(5.0, hold_lo_s)))
        h1 = float(max(0.05, min(5.0, hold_hi_s)))
        a0 = float(max(0.0, min(5.0, after_lo_s)))
        a1 = float(max(0.0, min(5.0, after_hi_s)))
        if d1 < d0:
            d0, d1 = d1, d0
        if h1 < h0:
            h0, h1 = h1, h0
        if a1 < a0:
            a0, a1 = a1, a0
        self._delay_lo_s = d0
        self._delay_hi_s = d1
        self._hold_lo_s = h0
        self._hold_hi_s = h1
        self._after_lo_s = a0
        self._after_hi_s = a1

    def load_template(self, path: str | Path) -> None:
        self._matcher.load_template(path)

    def set_template(self, wave, *, trim_energy: bool = True) -> None:
        self._matcher.set_template(wave, trim_energy=trim_energy)

    def play_template(self) -> None:
        """用扬声器试听当前模板（避免仍走 BlackHole / Loopback 听不见）。"""
        import sounddevice as sd

        wave = self.template_wave
        if wave is None or wave.size == 0:
            raise RuntimeError("没有模板可播放")
        sd.stop()
        audio = _audition_wave(wave)
        sr = int(self._audio.samplerate)
        device = self._playback_device()
        try:
            sd.play(audio, samplerate=sr, device=device, blocking=False)
        except Exception:
            # 指定设备失败时退回系统默认输出
            sd.play(audio, samplerate=sr, device=None, blocking=False)

    @staticmethod
    def _playback_device() -> int | None:
        """优先系统默认扬声器/耳机，跳过 BlackHole 等虚拟线。"""
        import sounddevice as sd

        skip = (
            "blackhole",
            "soundflower",
            "oray",
            "aggregate",
            "多输出",
            "vb-audio",
            "cable input",
            "cable output",
        )
        prefer = ("扬声器", "speaker", "headphone", "耳机", "外置耳机", "realtek", "headphones")
        try:
            default_out = sd.default.device[1]
            if default_out is not None:
                info = sd.query_devices(default_out)
                name = str(info.get("name") or "").lower()
                if int(info.get("max_output_channels") or 0) > 0 and not any(
                    s in name for s in skip
                ):
                    return int(default_out)
        except Exception:
            pass
        devices = list(sd.query_devices())
        preferred: int | None = None
        fallback: int | None = None
        for i, d in enumerate(devices):
            if int(d.get("max_output_channels") or 0) <= 0:
                continue
            name = str(d.get("name") or "").lower()
            if any(s in name for s in skip):
                continue
            # 名称含 loopback 的虚拟设备跳过；普通扬声器名不含该词
            if "loopback" in name and "wasapi" not in name:
                continue
            fallback = i if fallback is None else fallback
            if any(p in name for p in prefer):
                preferred = i
                break
        return preferred if preferred is not None else fallback

    def session_recording_preview(self) -> tuple["npt.NDArray[np.float32] | None", int, list[tuple[float, float]]]:
        """长录音进行中：返回当前已录波形副本（标注在停录后波形上拖选）。"""
        sr = int(self._audio.samplerate)
        with self._lock:
            recording = self._session_recording
        chunks = self._audio.record_snapshot() if recording else []
        if not chunks:
            return None, sr, []
        raw = np.concatenate(chunks, axis=0)
        wave = raw.mean(axis=1) if raw.ndim > 1 else raw
        return wave.astype(np.float32), sr, []

    def start_session_recording(self) -> None:
        """开始长录音（需已在监听）；与开钓会话无关。"""
        with self._lock:
            if self._session_recording:
                raise RuntimeError("已在长录音中")
            self._session_recording = True
            self._audio.begin_record()
        self._emit_log("长录音开始 · 录完后在波形条上拖选水花区间", channel="backtest")

    def stop_session_recording(self) -> dict:
        """停止长录音并落盘；有模板则自动回测。"""
        from autofish.first_click_trigger.session_eval import (
            backtest_recording,
            format_backtest_report,
            save_session,
        )

        with self._lock:
            if not self._session_recording:
                raise RuntimeError("当前没有长录音")
            self._session_recording = False
        raw = self._audio.end_record()
        if raw is None or raw.size == 0:
            raise RuntimeError("长录音为空")
        wave = (raw.mean(axis=1) if raw.ndim > 1 else raw).astype(np.float32)
        sr = int(self._audio.samplerate)
        ranges: list[tuple[float, float]] = []
        paths = save_session(raw, sr, ranges)
        self._emit_log(
            f"长录音已保存 {paths.root.name} · {len(wave)/sr:.1f}s",
            channel="backtest",
        )
        out: dict = {
            "paths": paths,
            "wave": wave,
            "samplerate": sr,
            "ranges": ranges,
            "report": None,
            "report_text": "",
        }
        if self._matcher.has_template:
            report = backtest_recording(wave, sr, self._matcher, ranges)
            text = format_backtest_report(report)
            out["report"] = report
            out["report_text"] = text
        else:
            self._emit_log(
                "无模板，已保存录音；选区入库后再回测", channel="backtest"
            )
        return out

    def backtest_last_or_dir(self, root: Path | None = None) -> dict:
        from autofish.first_click_trigger.session_eval import (
            backtest_recording,
            format_backtest_report,
            load_session,
        )

        if root is None:
            raise RuntimeError("请指定会话目录")
        wave, sr, ranges = load_session(root)
        if not self._matcher.has_template:
            raise RuntimeError("请先加载模板再回测")
        report = backtest_recording(wave, sr, self._matcher, ranges)
        text = format_backtest_report(report)
        report["report_text"] = text
        return report

    def replace_template_from_range(
        self,
        wave: "npt.NDArray[np.float32]",
        samplerate: int,
        start_s: float,
        end_s: float,
        *,
        save_user: bool = True,
    ) -> "npt.NDArray[np.float32]":
        """用自选区间精确替换模板（不做能量再裁切）；可写入模板库。"""
        from autofish.first_click_trigger.paths import (
            save_wave_as_library_template,
            template_source_label,
        )
        from autofish.first_click_trigger.session_eval import extract_range

        seg = extract_range(wave, samplerate, start_s, end_s)
        self.set_template(seg, trim_energy=False)
        if save_user:
            path = save_wave_as_library_template(seg)
            dur = len(seg) / float(max(samplerate, 1))
            self._emit_log(
                f"模板已入库 {template_source_label(path)} · {dur:.2f}s",
                channel="backtest",
            )
        else:
            dur = len(seg) / float(max(samplerate, 1))
            self._emit_log(f"模板已更新（未入库）· {dur:.2f}s", channel="backtest")
        return seg

    def start(self) -> None:
        self._subscribe_pos(True)
        super().start()

    def stop(self) -> None:
        # 先发停止信号并掐断音频流，避免 UI 卡在 join / 长 sleep 上
        self._stop.set()
        try:
            self._audio.stop()
        except Exception:  # noqa: BLE001
            pass
        self._subscribe_pos(False)
        with self._lock:
            if self._session_enabled:
                self._set_session(CastSessionState.WAIT, "stopped")
            else:
                self._set_session(CastSessionState.DISABLED, "stopped")
        super().stop(timeout=3.0)
        try:
            self._audio.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._mouse.force_release()
        except Exception:  # noqa: BLE001
            pass

    def _sleep_interruptible(self, seconds: float) -> bool:
        """可被 stop 打断的等待；返回 True 表示已要求停止。"""
        return self._stop.wait(timeout=max(0.0, float(seconds)))

    def _drain_capture_queue(self) -> None:
        """丢掉采集队列积压，避免第一下等待期间把水声堆到「超过 2 秒」被误扔。"""
        while self._audio.read() is not None:
            pass

    def _sleep_pump_audio(self, seconds: float) -> bool:
        """等待期间继续排空采集队列；返回 True 表示已要求停止。"""
        deadline = time.monotonic() + max(0.0, float(seconds))
        while True:
            self._drain_capture_queue()
            left = deadline - time.monotonic()
            if left <= 0.0:
                return self._stop.is_set()
            if self._stop.wait(timeout=min(0.05, left)):
                return True

    def _subscribe_pos(self, on: bool) -> None:
        if self.bus is None:
            return
        if on and not self._pos_subscribed:
            self.bus.subscribe(Topic.POS, self._on_pos)
            self._pos_subscribed = True
        elif not on and self._pos_subscribed:
            self.bus.unsubscribe(Topic.POS, self._on_pos)
            self._pos_subscribed = False

    def _set_session(
        self,
        state: CastSessionState,
        detail: str = "",
        *,
        splash: SplashHit | None = None,
    ) -> None:
        if state == self._session and not detail and splash is None:
            return
        prev = self._session
        self._session = state
        if state == CastSessionState.WAIT_BOBBER:
            self._wait_bobber_since = time.time()
            self._miss_since = None
        elif state == CastSessionState.FISHING:
            self._wait_bobber_since = None
            self._miss_since = None
        elif state == CastSessionState.WAIT:
            self._wait_bobber_since = None
            self._miss_since = None
            # 从本轮其它态回到 WAIT：冷却 3s，清匹配缓冲，避免拉鱼尾声误触
            if prev not in (CastSessionState.WAIT, CastSessionState.DISABLED):
                self._listen_after = time.time() + _WAIT_LISTEN_COOLDOWN_S
                self._matcher.reset_buffer()
                self._emit_log(f"听声冷却 {_WAIT_LISTEN_COOLDOWN_S:.0f}s")
            elif prev == CastSessionState.DISABLED:
                self._listen_after = 0.0
        elif state == CastSessionState.DISABLED:
            self._wait_bobber_since = None
            self._miss_since = None
            self._listen_after = 0.0
        if self.bus is not None:
            self.bus.publish_cast_session(
                CastSessionEvent(
                    state=state,
                    ts=time.time(),
                    detail=detail,
                    splash=splash,
                )
            )
        if prev != state:
            self._emit_log(
                f"会话 {prev.value} → {state.value}"
                + (f" · {detail}" if detail else "")
            )

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
        try:
            self._audio.start()
        except Exception as exc:  # noqa: BLE001
            self._emit_log(f"音频启动失败 · {exc}")
            return
        try:
            while not self._stop.is_set():
                try:
                    self._poll_audio_once()
                except Exception as exc:  # noqa: BLE001
                    # 单轮异常（含认钩）不得结束监听；否则 Windows 上像「监控停了」
                    self._emit_log(f"听声循环异常 · {exc}")
                    self._sleep_interruptible(0.05)
        finally:
            try:
                self._audio.stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._mouse.force_release()
            except Exception:  # noqa: BLE001
                pass

    def _poll_audio_once(self) -> None:
        self._check_timeouts()
        parts: list[npt.NDArray[np.float32]] = []
        t_end = 0.0
        saw_gap = False
        while True:
            block = self._audio.read()
            if block is None:
                break
            # 队列丢过旧块：缺口之前的声音作废，只留缺口之后的连续段
            if self._audio.capture_gap:
                parts.clear()
                saw_gap = True
            parts.append(block)
            t_end = float(self._audio.capture_t)
        if not parts:
            if not self._audio.capture_ok():
                now = time.monotonic()
                if now < self._next_reconnect_at:
                    self._sleep_interruptible(0.05)
                    return
                self._next_reconnect_at = now + 2.0
                err = self._audio.take_capture_error() or "采集线程已退出"
                self._emit_log(f"音频采集中断 · {err} · 正在重连")
                try:
                    self._audio.stop()
                    self._audio.start()
                    self._emit_log("音频采集已重连")
                    self._next_reconnect_at = 0.0
                except Exception as exc:  # noqa: BLE001
                    self._emit_log(f"音频重连失败 · {exc}")
                    self._sleep_interruptible(1.0)
            else:
                self._sleep_interruptible(0.005)
            return
        block = parts[0] if len(parts) == 1 else np.concatenate(parts, axis=0)

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
                and time.time() >= self._listen_after
            )
            if can_listen and not self._was_listening:
                # 进入听声：基线归零，与回测独立匹配器一致
                self._matcher.reset_score_baseline()
            self._was_listening = can_listen
            if saw_gap:
                self._matcher.reset_buffer()
            if can_listen and self._matcher.has_template:
                triggered, score = self._matcher.feed(
                    mono, update_baseline=True
                )
                self._last_score = score
                if (
                    not triggered
                    and self._matcher.last_reject
                    and time.time() - self._last_reject_log_at >= 1.0
                ):
                    self._last_reject_log_at = time.time()
                    self._emit_log(
                        f"未触发 · 相似 {score:.2f} · "
                        f"环境≈{self._matcher.last_ambient:.2f} · "
                        f"{self._matcher.last_reject}"
                    )
            elif self._matcher.has_template:
                # 非听声态：只填缓冲，不更新抬升基线（与回测独立匹配器一致）
                _, score = self._matcher.feed(
                    mono, update_baseline=False
                )
                self._last_score = score
                if (
                    self._session == CastSessionState.WAIT
                    and time.time() < self._listen_after
                    and score >= self._matcher.threshold
                    and time.time() - self._last_reject_log_at >= 1.5
                ):
                    left = max(0.0, self._listen_after - time.time())
                    self._last_reject_log_at = time.time()
                    self._emit_log(
                        f"听声冷却中 · 剩余 {left:.1f}s · 相似 {score:.2f}"
                    )

        if triggered and can_listen and not self._stop.is_set():
            tail = max(0.0, self._matcher.last_match_tail_s)
            # 传入采集时刻；认钩耗时在点前再算年龄，避免慢抓光标把 2s 寿命算松
            self._do_first_click(score, capture_t=t_end, match_tail=tail)

    def drain_logs(self, channel: str | None = None) -> list[str]:
        """取出后台日志；channel 为 sound|backtest，None 表示全部。"""
        with self._log_lock:
            if channel is None:
                lines = [m for _ch, m in self._pending_logs]
                self._pending_logs.clear()
                return lines
            kept: deque[tuple[str, str]] = deque(maxlen=self._pending_logs.maxlen)
            out: list[str] = []
            for ch, msg in self._pending_logs:
                if ch == channel:
                    out.append(msg)
                else:
                    kept.append((ch, msg))
            self._pending_logs = kept
            return out

    def _emit_log(self, msg: str, *, channel: str = "sound") -> None:
        with self._log_lock:
            self._pending_logs.append((channel, msg))

    def _cast_charging(self) -> bool:
        """自动抛杆（C）正在蓄力时，A 不点第一下、让出鼠标。"""
        if self.bus is None:
            return False
        return self.bus.snapshot().cast_phase == CastPhase.CHARGING

    def _cursor_is_hook(self) -> bool:
        """读光标是否鱼钩。优先共享外形探针；失败当否，绝不抛到听声线程。"""
        try:
            fn = self._cursor_shape
            if fn is not None:
                return str(fn()).strip().lower() == "hook"
            cursor = grab_system_cursor()
            if cursor is None:
                return False
            return bool(see_fishing_hook(cursor))
        except Exception:  # noqa: BLE001
            return False

    def _discard_splash(self, score: float, log: str, *, detail: str | None = None) -> None:
        """丢掉本次起钩，听声继续。"""
        with self._lock:
            self._matcher.reset_buffer()
            self._matcher.bump_score_baseline(score)
            if (
                detail is not None
                and self._session_enabled
                and self._session == CastSessionState.FIRST_CLICK
            ):
                self._set_session(CastSessionState.WAIT, detail)
            self._emit_log(log)

    def _do_first_click(
        self, score: float = 0.0, *, capture_t: float = 0.0, match_tail: float = 0.0
    ) -> None:
        # 整段包住：认钩/读光标异常只丢掉本次，不能打死听声监控
        try:
            with self._lock:
                if (
                    not self._session_enabled
                    or self._session != CastSessionState.WAIT
                ):
                    return
                if self._cast_charging():
                    self._emit_log("自动抛竿蓄力中 · 让鼠不点第一下")
                    return
            # 锁外认钩：慢/失败都不挡采集；不是鱼钩则起钩不生效，监控照旧
            if not self._cursor_is_hook():
                self._discard_splash(score, "非鱼钩 · 起钩未生效 · 丢掉等下次")
                return
            with self._lock:
                if (
                    not self._session_enabled
                    or self._session != CastSessionState.WAIT
                ):
                    return
                thr = float(self._matcher.threshold)
                delay_s = random.uniform(self._delay_lo_s, self._delay_hi_s)
                hold_s = random.uniform(self._hold_lo_s, self._hold_hi_s)
                after_s = random.uniform(self._after_lo_s, self._after_hi_s)
                # 认钩之后再算年龄，把抓光标耗时算进 2s 寿命
                queue_lag = (
                    max(0.0, time.monotonic() - float(capture_t))
                    if capture_t > 0.0
                    else 0.0
                )
                acoustic_lag = queue_lag + max(0.0, match_tail)
                wait_s = remaining_click_wait(delay_s, queue_lag, match_tail)
                if wait_s is None:
                    self._matcher.reset_buffer()
                    self._matcher.bump_score_baseline(score)
                    self._emit_log(
                        f"水声已过期 · 晚了 {acoustic_lag:.2f}s · "
                        f"上限 {_MAX_SPLASH_AGE_S:.0f}s · 丢掉等下次"
                    )
                    return
                splash = SplashHit(
                    score=float(score),
                    delay_s=float(delay_s),
                    hold_s=float(hold_s),
                    after_s=float(after_s),
                    threshold=thr,
                )
                self._live_hits.append(
                    {"t_wall": time.time(), "score": float(score)}
                )
                self._set_session(
                    CastSessionState.FIRST_CLICK, "splash", splash=splash
                )
                self._emit_log(
                    f"命中水花 · 相似 {score:.2f} / 阈值 {thr:.2f} · "
                    f"水声已过 {acoustic_lag:.2f}s · 再等 {wait_s:.2f}s · "
                    f"按住 {hold_s:.2f}s · 松开后 {after_s:.2f}s"
                )
                press_deadline = time.monotonic() + max(
                    0.0, _MAX_SPLASH_AGE_S - acoustic_lag
                )

            if self._sleep_pump_audio(wait_s):
                with self._lock:
                    if self._session_enabled:
                        self._set_session(CastSessionState.WAIT, "stopped")
                return
            with self._lock:
                if (
                    not self._session_enabled
                    or self._session != CastSessionState.FIRST_CLICK
                    or self._stop.is_set()
                ):
                    return
            if time.monotonic() >= press_deadline:
                self._discard_splash(
                    score,
                    f"水声已过期 · 上限 {_MAX_SPLASH_AGE_S:.0f}s · 丢掉等下次",
                    detail="splash_expired",
                )
                return
            if not self._cursor_is_hook():
                self._discard_splash(
                    score, "到点非鱼钩 · 丢掉等下次", detail="no_hook"
                )
                return
            # 二次认钩也可能很慢：过期就丢掉，绝不超时补点
            if time.monotonic() >= press_deadline:
                self._discard_splash(
                    score,
                    f"水声已过期 · 上限 {_MAX_SPLASH_AGE_S:.0f}s · 丢掉等下次",
                    detail="splash_expired",
                )
                return
            self._emit_log(f"开始按住 · {hold_s:.2f}s")
            self._mouse.set_holding(True)
            if self._sleep_pump_audio(hold_s):
                self._mouse.force_release()
                with self._lock:
                    if self._session_enabled:
                        self._set_session(CastSessionState.WAIT, "stopped")
                return
            self._mouse.set_holding(False)
            with self._lock:
                if (
                    not self._session_enabled
                    or self._session != CastSessionState.FIRST_CLICK
                    or self._stop.is_set()
                ):
                    return
            self._emit_log(f"已松开 · 停顿 {after_s:.2f}s 后再交拉漂")
            if self._sleep_pump_audio(after_s):
                with self._lock:
                    if self._session_enabled:
                        self._set_session(CastSessionState.WAIT, "stopped")
                return
            with self._lock:
                if (
                    not self._session_enabled
                    or self._session != CastSessionState.FIRST_CLICK
                    or self._stop.is_set()
                ):
                    return
                self._last_trigger_at = time.time()
                self._trigger_count += 1
                self._emit_log(
                    f"第一下完成 · 水声已过 {acoustic_lag:.2f}s · 再等 {wait_s:.2f}s · "
                    f"按住 {hold_s:.2f}s · 松开后 {after_s:.2f}s"
                )
                self._set_session(CastSessionState.WAIT_BOBBER, "clicked")
            # 第一下期间的声只排空不匹配；结束时清缓冲，避免积压水声被 2 秒规则误伤
            self._drain_capture_queue()
            with self._lock:
                self._matcher.reset_buffer()
        except Exception as exc:  # noqa: BLE001
            self._emit_log(f"第一下失败 · {exc}")
            try:
                self._mouse.force_release()
            except Exception:  # noqa: BLE001
                pass
            with self._lock:
                if self._session_enabled:
                    self._set_session(CastSessionState.WAIT, "error")
            self._drain_capture_queue()

