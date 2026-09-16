"""阈值策略：绿区相对 pos&lt;50 按住，&gt;90 松开；切换带最短间隔。"""

from __future__ import annotations

import random

from sim.api import Observation


def bobber_pos_in_safe_100(obs: Observation) -> float:
    """绿区内 0～100：左绿缘=0，右绿缘=100。"""
    span = obs.safe_right - obs.safe_left
    if span <= 1e-6:
        return 50.0
    raw = 100.0 * (obs.bobber_x - obs.safe_left) / span
    return max(0.0, min(100.0, raw))


class ThresholdHoldPolicy:
    """
    绿区相对 pos < low → 按住；pos > high → 松开；中间保持。
    按住↔松开切换：至少 min_interval，再加 U(0, jitter) 秒。
    """

    def __init__(
        self,
        *,
        low: float = 50.0,
        high: float = 90.0,
        min_interval: float = 0.2,
        jitter: float = 0.1,
        seed: int | None = None,
    ) -> None:
        if low >= high:
            raise ValueError("low must be < high")
        self.low = low
        self.high = high
        self.min_interval = min_interval
        self.jitter = jitter
        self._rng = random.Random(seed)
        self._holding = False
        self._next_change_at = 0.0

    def decide(self, obs: Observation) -> bool:
        pos = bobber_pos_in_safe_100(obs)
        want = self._holding
        if pos < self.low:
            want = True
        elif pos > self.high:
            want = False

        if want != self._holding and obs.time >= self._next_change_at:
            self._holding = want
            self._next_change_at = (
                obs.time + self.min_interval + self._rng.uniform(0.0, self.jitter)
            )
        return self._holding
