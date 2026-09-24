"""段4：绿区 pos 范围抽样阈值策略。"""

from __future__ import annotations

import random


class ThresholdPosPolicy:
    """
    从范围抽 low/high：pos < low → 按住；pos > high → 松开；中间保持。
    每次意图切换成功后重抽；reset 时也重抽。
    意图切换立刻生效；按下间隔由 Act 段控制。
    """

    def __init__(
        self,
        *,
        press_lo: float = 70.6,
        press_hi: float = 74.4,
        release_lo: float = 76.6,
        release_hi: float = 79.2,
        seed: int | None = None,
    ) -> None:
        self._rng = random.Random(seed)
        self._holding = False
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
        self._resample()

    @property
    def holding(self) -> bool:
        return self._holding

    def decide(self, pos: float) -> tuple[bool, str]:
        """返回 (holding, reason)。"""
        want = self._holding
        reason = "hold"
        if pos < self.low:
            want = True
            reason = f"pos<{self.low:.1f}"
        elif pos > self.high:
            want = False
            reason = f"pos>{self.high:.1f}"
        else:
            reason = "band"

        if want != self._holding:
            self._holding = want
            self._resample()
            return self._holding, (
                f"{reason}→" f"next<{self.low:.0f}/>{self.high:.0f}"
            )
        return self._holding, reason
