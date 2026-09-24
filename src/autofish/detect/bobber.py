"""漂命中载荷 + 调试用绿区掩膜（预览叠层）。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc

# 中间安全区绿（实机条心约 H≈41～46；须与橘红色相分离）
_GREEN_LO = np.array([36, 45, 40], dtype=np.uint8)
_GREEN_HI = np.array([80, 255, 235], dtype=np.uint8)


@dataclass(frozen=True)
class BobberHit:
    pos: float
    x: float
    y: float
    pixel_count: int
    bar_left: float = 0.0
    bar_top: float = 0.0
    bar_width: float = 0.0
    bar_height: float = 0.0
    score: float = 0.0
    detect_ms: float = 0.0


def pixel_to_pos(x: float, width: int) -> float:
    if width <= 1:
        return 0.0
    return float(max(0.0, min(100.0, 100.0 * x / (width - 1))))


def _prep(rgb: np.ndarray) -> tuple[np.ndarray, ...]:
    """一帧只算一次：HSV + 连续的 R/G/B 通道。"""
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("expected HxWx3 RGB image")
    hsv = cv2.cvtColor(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2HSV)
    r, g, b = cv2.split(rgb)
    return hsv, r, g, b


def _gt_by(a: np.ndarray, b: np.ndarray, delta: int) -> np.ndarray:
    """a > b + delta（uint8 饱和减）。"""
    return cv2.compare(cv2.subtract(a, b), float(delta), cv2.CMP_GT)


def green_zone_mask(rgb: np.ndarray) -> np.ndarray:
    """HSV 绿 ∪ 偏亮草绿；排除暗草地（V/G 过低）。"""
    hsv, r, g, b = _prep(rgb)
    out = cv2.inRange(hsv, _GREEN_LO, _GREEN_HI)
    lime = cv2.bitwise_and(_gt_by(g, r, 12), _gt_by(g, b, 12))
    lime = cv2.bitwise_and(lime, cv2.inRange(g, 70, 200))
    out = cv2.bitwise_or(out, lime)
    mn = cv2.min(cv2.min(r, g), b)
    bright = cv2.bitwise_and(
        cv2.compare(g, 60.0, cv2.CMP_GE),
        cv2.compare(mn, 25.0, cv2.CMP_GE),
    )
    return cv2.bitwise_and(out, bright)
