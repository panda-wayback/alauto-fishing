"""段4：绿区 pos 范围抽样阈值策略。"""

from __future__ import annotations

import random


class ThresholdPosPolicy:
    """
    从范围抽 low/high：pos < low → 按住；pos > high → 松开；中间保持。
    每次意图切换成功后重抽；reset 时也重抽。
    切换：距上次成功切换满 min_interval 即可立刻再切（默认 0.1s；无额外再等一轮）。
    """

    def __init__(
        self,
        *,
        press_lo: float = 40.0,
        press_hi: float = 70.0,
        release_lo: float = 75.0,
        release_hi: float = 90.0,
        min_interval: float = 0.1,
        jitter: float = 0.0,
        seed: int | None = None,
    ) -> None:
        self.min_interval = min_interval
        self.jitter = jitter
        self._rng = random.Random(seed)
        self._holding = False
        self._next_change_at = 0.0
        self.low = 50.0
        self.high = 80.0
        self.set_ranges(press_lo, press_hi, release_lo, release_hi)

    def set_ranges(
        self,
        press_lo: float,
        press_hi: float,
        release_lo: float,
        release_hi: float,
    ) -> None:
        if press_lo > press_hi:
            raise ValueError("press_lo must be <= press_hi")
        if release_lo > release_hi:
            raise ValueError("release_lo must be <= release_hi")
        if press_hi >= release_lo:
            raise ValueError("press_hi must be < release_lo")
        self.press_lo = float(press_lo)
        self.press_hi = float(press_hi)
        self.release_lo = float(release_lo)
        self.release_hi = float(release_hi)
        self._resample()

    def _resample(self) -> None:
        self.low = self._rng.uniform(self.press_lo, self.press_hi)
        self.high = self._rng.uniform(self.release_lo, self.release_hi)

    def reset(self) -> None:
        self._holding = False
        self._next_change_at = 0.0
        self._resample()

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
                self._resample()
                return self._holding, (
                    f"{reason}→"
                    f"next<{self.low:.0f}/>{self.high:.0f}"
                )
            return self._holding, "gated"
        return self._holding, reason
