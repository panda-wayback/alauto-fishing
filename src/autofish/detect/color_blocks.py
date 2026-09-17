"""色块识别器：橘|绿|橘 + 同高。"""

from __future__ import annotations

import numpy as np

from autofish.detect.bobber import BobberHit, find_bobber, find_green_bar


class ColorBlocksDetector:
    name = "color_blocks"

    def find_bar(self, rgb: np.ndarray) -> tuple[int, int, int, int] | None:
        return find_green_bar(rgb)

    def detect(self, rgb: np.ndarray) -> BobberHit | None:
        return find_bobber(rgb)
