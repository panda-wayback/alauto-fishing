"""识别器：传入 RGB → 绿条 + 鱼漂 + pos（bobber_anchor）。"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from autofish.detect.bobber import BobberHit


class BarDetector(Protocol):
    """识别器：找漂、定条（若有）、算 pos。"""

    name: str

    def detect(self, rgb: np.ndarray) -> BobberHit | None:
        """条 + 漂 + pos；无漂返回 None（有漂无条时可仅带漂坐标）。"""
        ...


_current: BarDetector | None = None


def get_detector() -> BarDetector:
    global _current
    if _current is None:
        from autofish.detect.bobber_anchor import BobberAnchorDetector

        _current = BobberAnchorDetector()
    return _current


def apply_manual_bar(
    box: tuple[float, float, float, float] | None,
) -> None:
    """把手动条界注入当前识别器（无此能力则忽略）。"""
    setter = getattr(get_detector(), "set_manual_bar", None)
    if callable(setter):
        setter(box)


def detect(rgb: np.ndarray) -> BobberHit | None:
    """统一入口：传入 RGB 图 → BobberHit（含条框与 pos）或 None。"""
    return get_detector().detect(rgb)
