"""段4：绿区 pos 阈值策略（与 algo-test 规则对齐，不依赖 sim）。"""

from __future__ import annotations

import random


class ThresholdPosPolicy:
    """
    pos < low → 按住；pos > high → 松开；中间保持。
    切换：至少 min_interval + U(0, jitter)。
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

    def reset(self) -> None:
        self._holding = False
        self._next_change_at = 0.0

    @property
    def holding(self) -> bool:
        return self._holding

    def decide(self, pos: float, t: float) -> tuple[bool, str]:
        """返回 (holding, reason)。"""
        want = self._holding
        reason = "hold"
        if pos < self.low:
            want = True
            reason = f"pos<{self.low:.0f}"
        elif pos > self.high:
            want = False
            reason = f"pos>{self.high:.0f}"
        else:
            reason = "band"

        if want != self._holding:
            if t >= self._next_change_at:
                self._holding = want
                self._next_change_at = (
                    t + self.min_interval + self._rng.uniform(0.0, self.jitter)
                )
                return self._holding, reason
            return self._holding, "gated"
        return self._holding, reason
