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


_MIN_HOLD_S = 0.7
_MAX_HOLD_S = 1.5
_MIN_DELAY_BEFORE_CLICK_S = 0.3
_MAX_DELAY_BEFORE_CLICK_S = 1.5
_MIN_AFTER_RELEASE_S = 0.2
_MAX_AFTER_RELEASE_S = 0.8
_WAIT_BOBBER_TIMEOUT_S = 3.0
_LOST_BOBBER_END_S = 1.0
_WAIT_LISTEN_COOLDOWN_S = 3.0
_DEFAULT_THRESHOLD = 0.70
_RING_SECONDS = 20.0
_LIVE_WAVE_SECONDS = 20.0
_MARK_SECONDS = 1.0
_SILENT_DB = -55.0
# 试听时峰值归一化目标（只影响播放，不改模板文件）
_AUDITION_PEAK = 0.85


def _db(rms: float) -> float:
    if rms <= 0:
        return -120.0
    return 20.0 * float(np.log10(max(rms, 1e-12)))


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
        use_energy_fallback: bool = False,
        energy_threshold_db: float = -30.0,
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
        self._pending_logs: deque[tuple[str, str]] = deque(maxlen=80)
        self._last_trigger_at = 0.0
        self._trigger_count = 0
        self._last_score = 0.0
        self._level_db = -120.0
        self._running_mode = "等待标记"
        self._wait_bobber_since: float | None = None
        self._miss_since: float | None = None
        self._listen_after: float = 0.0
        self._pos_subscribed = False
        self._last_reject_log_at = 0.0
        self._session_recording = False
        self._session_ranges: list[tuple[float, float]] = []
        self._session_range_start: float | None = None
        self._session_started_at: float = 0.0
        # 实时波形命中：墙钟时刻 + 分数（展示时映射到最近 20s）
        self._live_hits: deque[dict[str, float]] = deque(maxlen=40)
        self._was_listening = False
        self._delay_lo_s = _MIN_DELAY_BEFORE_CLICK_S
        self._delay_hi_s = _MAX_DELAY_BEFORE_CLICK_S
        self._hold_lo_s = _MIN_HOLD_S
        self._hold_hi_s = _MAX_HOLD_S
        self._after_lo_s = _MIN_AFTER_RELEASE_S
        self._after_hi_s = _MAX_AFTER_RELEASE_S
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
    def running_mode(self) -> str:
        return self._running_mode

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
    def session_mark_count(self) -> int:
        with self._lock:
            return len(self._session_ranges)

    @property
    def session_pending_range_start(self) -> float | None:
        with self._lock:
            return self._session_range_start

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

    def set_energy_threshold(self, db: float) -> None:
        self._detector.threshold_db = db
        self._detector.threshold_linear = 10 ** (db / 20.0)

    def load_template(self, path: str | Path) -> None:
        self._matcher.load_template(path)
        self._running_mode = "频谱模板匹配"

    def save_template(self, path: str | Path) -> None:
        self._matcher.save_template(path)

    def set_template(self, wave, *, trim_energy: bool = True) -> None:
        self._matcher.set_template(wave, trim_energy=trim_energy)
        self._running_mode = "频谱模板匹配"

    def play_template(self) -> None:
        """用扬声器试听当前模板（避免仍走 BlackHole / Loopback 听不见）。"""
        wave = self.template_wave
        if wave is None or wave.size == 0:
            raise RuntimeError("没有模板可播放")
        import sounddevice as sd

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

    def session_recording_preview(self) -> tuple["npt.NDArray[np.float32] | None", int, list[tuple[float, float]]]:
        """长录音进行中：返回当前已录波形副本与已闭合区间（供波形条刷新）。"""
        sr = int(self._audio.samplerate)
        with self._lock:
            ranges = list(self._session_ranges)
            recording = self._session_recording
        chunks = self._audio.record_snapshot() if recording else []
        if not chunks:
            return None, sr, ranges
        raw = np.concatenate(chunks, axis=0)
        wave = raw.mean(axis=1) if raw.ndim > 1 else raw
        return wave.astype(np.float32), sr, ranges

    def start_session_recording(self) -> None:
        """开始长录音（需已在监听）；与开钓会话无关。"""
        with self._lock:
            if self._session_recording:
                raise RuntimeError("已在长录音中")
            self._session_recording = True
            self._session_ranges = []
            self._session_range_start = None
            self._session_started_at = time.time()
            self._audio.begin_record()
        self._emit_log("长录音开始 · 录完后在波形条上拖选水花区间", channel="backtest")

    def mark_session_range_start(self) -> float:
        """长录音中：记下区间起点。"""
        with self._lock:
            if not self._session_recording:
                raise RuntimeError("请先开始长录音")
            t = self.session_record_duration_s
            self._session_range_start = t
        self._emit_log(f"区间起点 · {t:.2f}s · 再点「区间终点」", channel="backtest")
        return t

    def mark_session_range_end(self) -> tuple[float, float]:
        """长录音中：用当前时刻作终点，闭合一个水花区间。"""
        with self._lock:
            if not self._session_recording:
                raise RuntimeError("请先开始长录音")
            if self._session_range_start is None:
                raise RuntimeError("请先点「区间起点」")
            end = self.session_record_duration_s
            start = float(self._session_range_start)
            self._session_range_start = None
            if end < start:
                start, end = end, start
            if end - start < 0.05:
                raise RuntimeError("区间太短，请稍后再点终点")
            self._session_ranges.append((start, end))
            n = len(self._session_ranges)
        self._emit_log(f"水花区间 #{n} · [{start:.2f},{end:.2f}]s", channel="backtest")
        return start, end

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
            ranges = list(self._session_ranges)
            pending = self._session_range_start
            self._session_ranges = []
            self._session_range_start = None
        raw = self._audio.end_record()
        if pending is not None:
            self._emit_log(
                f"未闭合的起点 @{pending:.2f}s 已丢弃", channel="backtest"
            )
        if raw is None or raw.size == 0:
            raise RuntimeError("长录音为空")
        wave = (raw.mean(axis=1) if raw.ndim > 1 else raw).astype(np.float32)
        sr = int(self._audio.samplerate)
        paths = save_session(raw, sr, ranges)
        self._emit_log(
            f"长录音已保存 {paths.root.name} · {len(wave)/sr:.1f}s · 区间 {len(ranges)} 段",
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

    def mark_heard_splash(self) -> dict:
        """
        你听到水花时点：保存近 2 秒录音，并用当前模板立刻复盘判定。
        不改模板；用于对照「人耳听到 vs 程序判定」。
        """
        from autofish.first_click_trigger.paths import user_heard_marks_dir

        with self._lock:
            if not self._matcher.has_template:
                raise RuntimeError("还没有模板，请先标记/加载模板")
            n = int(self._audio.samplerate * 2.0)
            if self._ring.size < self._audio.samplerate // 4:
                raise RuntimeError("录音还太短，请先听几秒再标记「听到」")
            wave = self._ring.last(n)
            # 用当前匹配缓冲复盘（与实时判定同一状态）
            buf = self._matcher._buffer.copy()
            report = self._matcher.analyze_buffer(buf)
            # 同时用近 2 秒片段再分析一份（给人听的那截）
            clip_report = self._matcher.analyze_clip(wave)

        out_dir = user_heard_marks_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"heard_{stamp}.npy"
        np.save(path, wave)

        ok = bool(report["would_trigger"])
        self._emit_log(
            f"听到标记 · 实时窗 相似 {report['score']:.2f} "
            f"峰差 {report['prominence']:.3f} 突兀={report['abrupt']} "
            f"→ {'会触发' if ok else '不触发'} "
            f"{('· ' + report['reason']) if report['reason'] else ''}"
        )
        self._emit_log(
            f"听到标记 · 近2秒片段 相似 {clip_report['score']:.2f} "
            f"→ {'会触发' if clip_report['would_trigger'] else '不触发'} "
            f"{('· ' + clip_report['reason']) if clip_report['reason'] else ''} "
            f"· 已存 {path.name}"
        )
        return {
            "path": str(path),
            "live": report,
            "clip": clip_report,
        }

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
                CastSessionEvent(state=state, ts=time.time(), detail=detail)
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
                self._check_timeouts()
                block = self._audio.read()
                if block is None:
                    self._sleep_interruptible(0.005)
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
                        and time.time() >= self._listen_after
                    )
                    if can_listen and not self._was_listening:
                        # 进入听声：基线归零，与回测独立匹配器一致
                        self._matcher.reset_score_baseline()
                    self._was_listening = can_listen
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
                    elif can_listen and self._use_fallback:
                        triggered = self._detector.feed(mono)
                        score = float(rms)
                        self._last_score = rms
                    elif self._matcher.has_template:
                        # 非听声态：只填缓冲，不更新抬升基线（与回测独立匹配器一致）
                        _, score = self._matcher.feed(
                            mono, update_baseline=False
                        )
                        self._matcher.clear_streak()
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
                    self._do_first_click(score)
        finally:
            try:
                self._audio.stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._mouse.force_release()
            except Exception:  # noqa: BLE001
                pass

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

    def _do_first_click(self, score: float = 0.0) -> None:
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
            detail = (
                f"splash|{float(score):.2f}|{delay_s:.2f}|{hold_s:.2f}|"
                f"{after_s:.2f}|{thr:.2f}"
            )
            self._live_hits.append(
                {"t_wall": time.time(), "score": float(score)}
            )
            self._set_session(CastSessionState.FIRST_CLICK, detail)
            self._emit_log(
                f"命中水花 · 相似 {score:.2f} / 阈值 {thr:.2f} · "
                f"等待 {delay_s:.2f}s · 按住 {hold_s:.2f}s · "
                f"松开后 {after_s:.2f}s"
            )

        try:
            if self._sleep_interruptible(delay_s):
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
            self._emit_log(f"开始按住 · {hold_s:.2f}s")
            self._mouse.set_holding(True)
            if self._sleep_interruptible(hold_s):
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
            if self._sleep_interruptible(after_s):
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
                    f"第一下完成 · 等待 {delay_s:.2f}s · 按住 {hold_s:.2f}s · "
                    f"松开后 {after_s:.2f}s"
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
