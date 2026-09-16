"""读数时间平滑：中值窗 + 短暂丢帧保持。"""

from __future__ import annotations

from collections import deque

from vision.bobber import BobberHit, pixel_to_pos


class PosSmoother:
    def __init__(self, window: int = 7, hold_lost: int = 10) -> None:
        self._xs: deque[float] = deque(maxlen=max(3, window))
        self._hold_lost = hold_lost
        self._lost = 0
        self._last: BobberHit | None = None

    def reset(self) -> None:
        self._xs.clear()
        self._lost = 0
        self._last = None

    def push(self, hit: BobberHit | None) -> BobberHit | None:
        if hit is None:
            self._lost += 1
            if self._lost > self._hold_lost:
                self.reset()
                return None
            return self._last

        self._lost = 0
        self._xs.append(hit.x)
        xs = sorted(self._xs)
        sx = xs[len(xs) // 2]
        if hit.bar_width > 1:
            pos = pixel_to_pos(sx - hit.bar_left, int(hit.bar_width))
        else:
            pos = hit.pos
        smoothed = BobberHit(
            pos=pos,
            x=sx,
            y=hit.y,
            pixel_count=hit.pixel_count,
            bar_left=hit.bar_left,
            bar_width=hit.bar_width,
        )
        self._last = smoothed
        return smoothed
