"""AutoCastWorker：快捷键发起有限次数自动抛杆。

start_batch(N) →（约 1s settle）→ 鱼漂就绪 → AIM → CHARGING → DONE|ABORT。
蓄力：hold_s = full_charge_s × target ± hold_jitter_s，到时松开（不识红条）。
下一杆只在再次处于鱼漂就绪时抛出；鱼钩等其它外形一直等，不记失败。
未提供就绪探针时，两杆之间只走配置等待。
剩余用尽或 cancel_batch → DISABLED。
只在 CHARGING 控鼠，发布 Topic.CAST_PHASE 供 A / B 让位。
"""

from __future__ import annotations

import random
import threading
import time
import traceback
from collections.abc import Callable
from typing import TYPE_CHECKING

from autofish.act.mouse import MouseActuator, os_cursor_position, os_right_down
from autofish.cast_calibration.circle import CastCircle, load_cast_circle
from autofish.events.topics import CastPhase, CastPhaseEvent
from autofish.events.worker_base import WorkerBase
from autofish.locate.roi import primary_screen_size

if TYPE_CHECKING:
    from autofish.events.bus import AutofishBus

_MAX_WAIT_S = 30.0
_MIN_BATCH = 1
_MAX_BATCH = 10
_TICK_S = 0.01
_MIN_FULL_CHARGE_S = 0.05
_MAX_FULL_CHARGE_S = 5.0
_MIN_HOLD_S = 0.02  # target=0 时仍保证一次可感知按下
_DEFAULT_HOLD_JITTER_S = 0.1
_DEFAULT_START_SETTLE_S = 1.0  # 开抛后短等，避开右键与蓄力抢键
# 松杆后光标可能还没换成鱼钩；这段时间内仍是鱼漂不算「再次进入」
_REENTER_GRACE_S = 0.75
# 开抛用的那次右键按住期间勿当成结束
_RIGHT_CANCEL_GRACE_S = 0.35


class AutoCastWorker(WorkerBase):
    def __init__(
        self,
        bus: "AutofishBus",
        *,
        wait_lo_s: float = 3.0,
        wait_hi_s: float = 3.0,
        full_charge_s: float = 1.0,
        hold_jitter_s: float = _DEFAULT_HOLD_JITTER_S,
        start_settle_s: float = _DEFAULT_START_SETTLE_S,
        mouse: MouseActuator | None = None,
        load_circle: Callable[[], CastCircle | None] | None = None,
        cursor_pos: Callable[[], tuple[float, float] | None] = os_cursor_position,
        screen_size: Callable[[], tuple[int, int]] = primary_screen_size,
        right_down: Callable[[], bool | None] = os_right_down,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(bus, "autofish-auto-cast")
        self._mouse = mouse if mouse is not None else MouseActuator()
        self._load_circle = load_circle or _default_load_circle
        self._cursor_pos = cursor_pos
        self._screen_size = screen_size
        self._right_down = right_down
        self._clock = clock
        self._sleep = sleep

        lo, hi = _order_wait(wait_lo_s, wait_hi_s)
        self._wait_lo = lo
        self._wait_hi = hi
        self._full_charge_s = _clamp_full_charge(full_charge_s)
        self._hold_jitter_s = max(0.0, float(hold_jitter_s))
        self._start_settle_s = max(0.0, min(5.0, float(start_settle_s)))

        self._active = False
        self._remaining = 0
        self._batch_total = 0
        self._cast_index = 0
        self._settle_pending = False
        self._need_reenter = False
        self._ignore_right_until = 0.0
        self._cast_ready: Callable[[], bool] | None = None
        self._lock = threading.Lock()
        self._wake = threading.Condition()
        self._phase: CastPhase = CastPhase.DISABLED
        self._target: float | None = None
        self._last_power: float | None = None
        self._last_hold_s: float | None = None

    # ------------------------------------------------------------------ API
    @property
    def active(self) -> bool:
        return self._active

    @property
    def remaining(self) -> int:
        return self._remaining

    @property
    def phase(self) -> CastPhase:
        return self._phase

    @property
    def target(self) -> float | None:
        return self._target

    @property
    def last_power(self) -> float | None:
        return self._last_power

    @property
    def full_charge_s(self) -> float:
        return self._full_charge_s

    @property
    def batch_total(self) -> int:
        return self._batch_total

    @property
    def cast_index(self) -> int:
        return self._cast_index

    @property
    def last_hold_s(self) -> float | None:
        return self._last_hold_s

    def start_batch(self, count: int) -> bool:
        """开始一轮有限次数抛杆。已有任务时忽略并返回 False。"""
        n = max(_MIN_BATCH, min(_MAX_BATCH, int(count)))
        with self._lock:
            if self._active:
                return False
            self._active = True
            self._remaining = n
            self._batch_total = n
            self._cast_index = 0
            self._target = None
            self._last_hold_s = None
            self._settle_pending = self._start_settle_s > 0
            self._need_reenter = False
            # 避开「右键开抛」同一按住被当成结束
            self._ignore_right_until = self._clock() + (
                self._start_settle_s + _RIGHT_CANCEL_GRACE_S
            )
        self._notify()
        return True

    def cancel_batch(self, *, detail: str = "cancelled") -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            self._remaining = 0
            self._phase = CastPhase.DISABLED
            self._target = None
        self._release_mouse()
        self._publish(CastPhase.DISABLED, detail)
        self._notify()

    def set_wait_range(self, lo_s: float, hi_s: float) -> None:
        lo, hi = _order_wait(lo_s, hi_s)
        with self._lock:
            self._wait_lo = lo
            self._wait_hi = hi

    def set_full_charge_s(self, seconds: float) -> None:
        with self._lock:
            self._full_charge_s = _clamp_full_charge(seconds)

    def set_cast_ready(self, ready: Callable[[], bool] | None) -> None:
        """鱼漂就绪探针。None 表示不设门闩。True 才能 AIM。"""
        with self._lock:
            self._cast_ready = ready
        self._notify()

    def start(self) -> None:
        super().start()

    def stop(self, timeout: float = 2.0) -> None:
        self.cancel_batch()
        self._notify()
        super().stop(timeout=timeout)
        self._release_mouse()

    def _notify(self) -> None:
        with self._wake:
            self._wake.notify_all()

    # ------------------------------------------------------------------ 主循环
    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._active:
                with self._wake:
                    self._wake.wait(timeout=_TICK_S)
                continue
            try:
                if self._poll_right_cancel():
                    continue
                self._maybe_settle_after_start()
                if self._stop.is_set() or not self._active:
                    continue
                if not self._wait_bobber():
                    continue
                self._need_reenter = False
                if self._cast_index > 0:
                    self._wait_round()
                    if self._stop.is_set() or not self._active:
                        continue
                    if self._ready_now() is False:
                        self._need_reenter = self._has_ready_gate()
                        continue
                target = self._aim()
                if self._stop.is_set() or not self._active:
                    continue
                if target is None:
                    self._consume_one()
                    if self._should_continue():
                        self._retry_wait()
                    else:
                        self._finish_batch("batch_done")
                    continue

                ok = self._charge(target)
                if self._stop.is_set() or not self._active:
                    continue
                self._consume_one()
                if not self._should_continue():
                    self._finish_batch("batch_done")
                    continue
                if not ok:
                    self._retry_wait()
                    continue
                self._need_reenter = self._has_ready_gate()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                self._release_mouse()
                with self._lock:
                    self._phase = CastPhase.ABORT
                self._publish(CastPhase.ABORT, "exception")
                self._sleep(_TICK_S)

    def _should_continue(self) -> bool:
        with self._lock:
            return self._active and self._remaining > 0

    def _consume_one(self) -> None:
        with self._lock:
            if self._remaining > 0:
                self._remaining -= 1

    def _finish_batch(self, detail: str) -> None:
        with self._lock:
            self._active = False
            self._remaining = 0
            self._phase = CastPhase.DISABLED
            self._target = None
        self._release_mouse()
        self._publish(CastPhase.DISABLED, detail)

    def _cast_tag(self) -> str:
        with self._lock:
            return f"#{self._cast_index}/{self._batch_total}"

    def _sample_wait_s(self) -> float:
        with self._lock:
            lo, hi = self._wait_lo, self._wait_hi
        return float(random.uniform(lo, hi))

    def _maybe_settle_after_start(self) -> None:
        """开抛后短等，避免右键开抛与左键蓄力叠在一起。"""
        with self._lock:
            if not self._settle_pending:
                return
            self._settle_pending = False
            duration = self._start_settle_s
            self._phase = CastPhase.WAIT
        if duration <= 0:
            return
        with self._lock:
            total = self._batch_total
        self._publish(
            CastPhase.WAIT,
            f"settle wait={duration:.2f}s before #1/{total}",
        )
        self._interruptible_sleep(duration)

    def _wait_round(self) -> None:
        duration = self._sample_wait_s()
        with self._lock:
            self._phase = CastPhase.WAIT
        self._publish(
            CastPhase.WAIT,
            f"after_fish wait={duration:.2f}s {self._cast_tag()}",
        )
        self._interruptible_sleep(duration)

    def _retry_wait(self, reason: str = "retry") -> None:
        duration = self._sample_wait_s()
        with self._lock:
            self._phase = CastPhase.WAIT
        self._publish(
            CastPhase.WAIT,
            f"{reason} wait={duration:.2f}s {self._cast_tag()}",
        )
        self._interruptible_sleep(duration)

    def _aim(self) -> float | None:
        with self._lock:
            self._cast_index += 1
            self._phase = CastPhase.AIM
            self._target = None
            self._last_hold_s = None
            tag = f"#{self._cast_index}/{self._batch_total}"
        self._publish(CastPhase.AIM, f"aim {tag}")

        circle = self._load_circle()
        if circle is None:
            self._abort(f"no_calibration {tag}")
            return None
        pos = self._cursor_pos()
        if pos is None:
            self._abort(f"no_cursor {tag}")
            return None
        try:
            screen_w, screen_h = self._screen_size()
        except Exception:  # noqa: BLE001
            self._abort(f"no_screen {tag}")
            return None
        if screen_w <= 0 or screen_h <= 0:
            self._abort(f"no_screen {tag}")
            return None
        try:
            target = circle.target_power_ratio(pos[0], pos[1], screen_w, screen_h)
        except Exception:  # noqa: BLE001
            self._abort(f"target_error {tag}")
            return None
        target = max(0.0, min(1.0, float(target)))
        with self._lock:
            self._target = target
        return target

    def _charge(self, target: float) -> bool:
        with self._lock:
            self._phase = CastPhase.CHARGING
            self._last_power = None
            full_s = self._full_charge_s
            jitter = self._hold_jitter_s
            tag = f"#{self._cast_index}/{self._batch_total}"
        base = full_s * float(target)
        if jitter > 0:
            hold_s = base + random.uniform(-jitter, jitter)
        else:
            hold_s = base
        hold_s = max(_MIN_HOLD_S, float(hold_s))
        with self._lock:
            self._last_hold_s = hold_s
        self._publish(
            CastPhase.CHARGING,
            f"press {tag} hold={hold_s:.2f}s",
            target=target,
            power=None,
        )

        try:
            self._mouse.set_holding(True)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self._abort(f"press_failed {tag}")
            return False

        self._interruptible_sleep(hold_s)
        if self._stop.is_set() or not self._active:
            self._release_mouse()
            with self._lock:
                self._phase = CastPhase.ABORT
            if self._active:
                self._publish(CastPhase.ABORT, f"stopped {tag}")
            return False

        self._finish_done(target, target)
        return True

    def _poll_right_cancel(self) -> bool:
        """任务进行中系统右键按下 → 立刻结束。True 表示已取消。"""
        if not self._active:
            return False
        with self._lock:
            ignore_until = self._ignore_right_until
        if self._clock() < ignore_until:
            return False
        try:
            down = self._right_down()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return False
        if down is not True:
            return False
        self.cancel_batch(detail="right_click")
        return True

    def _has_ready_gate(self) -> bool:
        with self._lock:
            return self._cast_ready is not None

    def _ready_now(self) -> bool | None:
        """None：未设门闩。"""
        with self._lock:
            fn = self._cast_ready
        if fn is None:
            return None
        try:
            return bool(fn())
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return False

    def _wait_bobber(self) -> bool:
        """等到鱼漂就绪才返回 True。鱼钩等非就绪外形一直等。

        上一杆刚松手时，须先离开鱼漂再进入，才算下一次就绪；
        短时仍停在鱼漂则视为没换成鱼钩，仍允许再抛。
        """
        if not self._has_ready_gate():
            return True
        reenter = self._need_reenter
        grace_end = self._clock() + _REENTER_GRACE_S if reenter else 0.0
        left = False
        announced = False
        while not self._stop.is_set() and self._active:
            ready = self._ready_now()
            if ready is None:
                return True
            if reenter and not ready:
                left = True
            if reenter:
                opened = (left and ready) or (
                    not left and ready and self._clock() >= grace_end
                )
            else:
                opened = ready
            if opened:
                return True
            if self._poll_right_cancel():
                return False
            if not announced:
                announced = True
                with self._lock:
                    nxt = self._cast_index + 1
                    total = self._batch_total
                    self._phase = CastPhase.WAIT
                self._publish(
                    CastPhase.WAIT,
                    f"wait_bobber #{nxt}/{total}",
                )
            with self._wake:
                self._wake.wait(timeout=_TICK_S)
        return False

    def _interruptible_sleep(self, seconds: float) -> None:
        deadline = self._clock() + max(0.0, float(seconds))
        while not self._stop.is_set() and self._active:
            if self._poll_right_cancel():
                return
            remaining = deadline - self._clock()
            if remaining <= 0:
                return
            with self._wake:
                self._wake.wait(timeout=min(_TICK_S, remaining))

    def _finish_done(self, target: float, power: float) -> None:
        self._release_mouse()
        with self._lock:
            self._phase = CastPhase.DONE
            self._last_power = float(power)
        self._publish(CastPhase.DONE, "reached", target=target, power=power)

    def _finish_abort(self, detail: str) -> None:
        self._release_mouse()
        with self._lock:
            self._phase = CastPhase.ABORT
        self._publish(CastPhase.ABORT, detail)

    def _abort(self, detail: str) -> None:
        """AIM 阶段失败：未按下。"""
        with self._lock:
            self._phase = CastPhase.ABORT
            self._target = None
        self._publish(CastPhase.ABORT, detail)

    def _release_mouse(self) -> None:
        try:
            self._mouse.force_release()
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    def _publish(
        self,
        phase: CastPhase,
        detail: str,
        *,
        target: float | None = None,
        power: float | None = None,
    ) -> None:
        if target is None:
            with self._lock:
                target = self._target
        self.bus.publish_cast_phase(
            CastPhaseEvent(
                phase=phase,
                ts=time.time(),
                detail=detail,
                target=target,
                power=power,
            )
        )


def _default_load_circle() -> CastCircle | None:
    try:
        return load_cast_circle()
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return None


def _order_wait(lo_s: float, hi_s: float) -> tuple[float, float]:
    lo = max(0.0, min(_MAX_WAIT_S, float(lo_s)))
    hi = max(0.0, min(_MAX_WAIT_S, float(hi_s)))
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _clamp_full_charge(seconds: float) -> float:
    return max(_MIN_FULL_CHARGE_S, min(_MAX_FULL_CHARGE_S, float(seconds)))
