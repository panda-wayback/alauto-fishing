"""识别器协议与默认切换。传入 RGB → 绿条 + 鱼漂 + pos。"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from autofish.detect.bobber import BobberHit

BarBox = tuple[int, int, int, int]  # x, y, w, h


class BarDetector(Protocol):
    """可替换识别器：只负责找条、找漂、算 pos。"""

    name: str

    def find_bar(self, rgb: np.ndarray) -> BarBox | None:
        """绿条（或整条张力条）包围盒；找不到返回 None。"""
        ...

    def detect(self, rgb: np.ndarray) -> BobberHit | None:
        """条 + 漂 + pos；无漂或无条返回 None。"""
        ...


_current: BarDetector | None = None


def get_detector() -> BarDetector:
    global _current
    if _current is None:
        from autofish.detect.color_blocks import ColorBlocksDetector

        _current = ColorBlocksDetector()
    return _current


def set_detector(detector: BarDetector) -> BarDetector:
    """切换识别方法（测试/对比用）。返回新当前器。"""
    global _current
    _current = detector
    return detector


def use_template() -> BarDetector:
    from autofish.detect.template_bar import TemplateBarDetector

    return set_detector(TemplateBarDetector())


def use_color_blocks() -> BarDetector:
    from autofish.detect.color_blocks import ColorBlocksDetector

    return set_detector(ColorBlocksDetector())


def detect(rgb: np.ndarray) -> BobberHit | None:
    """统一入口：传入 RGB 图 → BobberHit（含条框与 pos）或 None。"""
    return get_detector().detect(rgb)


def find_bar(rgb: np.ndarray) -> BarBox | None:
    """统一入口：只取条框。"""
    return get_detector().find_bar(rgb)
