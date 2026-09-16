"""完整绿条两端各+5% → 找白 → 0～100（不越出 ROI/帧）。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc

DEFAULT_LOWER_ZONE = np.array([46, 84, 106], dtype=np.uint8)
DEFAULT_UPPER_ZONE = np.array([67, 247, 193], dtype=np.uint8)
_ORANGE_LOWER = np.array([5, 90, 110], dtype=np.uint8)
_ORANGE_UPPER = np.array([35, 255, 255], dtype=np.uint8)
_WHITE_LOWER = np.array([0, 0, 175], dtype=np.uint8)
_WHITE_UPPER = np.array([179, 70, 255], dtype=np.uint8)
_MIN_BAR_W = 60
_MIN_WHITE_PX = 24
_EDGE_PAD_RATIO = 0.05


@dataclass(frozen=True)
class BobberHit:
    pos: float
    """绿条两端+5%：左=0，右=100。"""
    x: float
    y: float
    pixel_count: int
    bar_left: float = 0.0
    bar_top: float = 0.0
    bar_width: float = 0.0
    bar_height: float = 0.0
    score: float = 0.0


def pixel_to_pos(x: float, width: int) -> float:
    if width <= 1:
        return 0.0
    return float(max(0.0, min(100.0, 100.0 * x / (width - 1))))


def green_zone_mask(
    rgb: np.ndarray,
    lower: np.ndarray | None = None,
    upper: np.ndarray | None = None,
) -> np.ndarray:
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("expected HxWx3 RGB image")
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    lo = DEFAULT_LOWER_ZONE if lower is None else lower
    hi = DEFAULT_UPPER_ZONE if upper is None else upper
    return cv2.inRange(hsv, lo, hi)


def orange_end_mask(rgb: np.ndarray) -> np.ndarray:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, _ORANGE_LOWER, _ORANGE_UPPER)


def white_mask(rgb: np.ndarray) -> np.ndarray:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, _WHITE_LOWER, _WHITE_UPPER)


def _green_row_band(gmask: np.ndarray) -> tuple[int, int] | None:
    row = (gmask > 0).sum(axis=1)
    peak = int(row.max()) if row.size else 0
    if peak < 40:
        return None
    ys = np.where(row >= max(20, peak // 4))[0]
    if ys.size < 4:
        return None
    return int(ys[0]), int(ys[-1]) + 1


def _green_ends_via_orange(
    rgb: np.ndarray, gmask: np.ndarray, y0: int, y1: int
) -> tuple[int, int] | None:
    """绿条左右端 ≈ 左橙右缘、右橙左缘（忽略中部鱼漂橙）。"""
    zh = y1 - y0
    fh, fw = rgb.shape[:2]
    pad = max(2, zh // 5)
    by0, by1 = max(0, y0 - pad), min(fh, y1 + pad)
    strip = orange_end_mask(rgb)[by0:by1, :]
    strip = cv2.morphologyEx(strip, cv2.MORPH_CLOSE, np.ones((3, 5), np.uint8))
    contours, _ = cv2.findContours(strip, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    left_inner, right_inner = -1, fw + 1
    left_lim, right_lim = int(fw * 0.34), int(fw * 0.66)
    min_o = max(40, zh * 2)
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < min_o:
            continue
        x, _y, w, h = cv2.boundingRect(cnt)
        if h < 3 or w < 4:
            continue
        cx = x + w / 2.0
        if int(cv2.countNonZero(gmask[y0:y1, x : min(fw, x + w)])) > area * 0.45:
            continue
        if cx <= left_lim:
            left_inner = max(left_inner, x + w)
        elif cx >= right_lim:
            right_inner = min(right_inner, x)
    if left_inner < 0 or right_inner > fw:
        return None
    if right_inner - left_inner < _MIN_BAR_W:
        return None
    return left_inner, right_inner


def _green_ends_via_close(gmask: np.ndarray, y0: int, y1: int) -> tuple[int, int] | None:
    """完整绿水平跨度：强横闭运算桥接鱼漂空洞。"""
    zh = max(1, y1 - y0)
    fw = gmask.shape[1]
    # 核宽按帧宽，足以盖住鱼漂挖断，且不随鱼漂位置乱跳
    kx = max(61, min(fw // 4, max(zh * 3, 81)))
    if kx % 2 == 0:
        kx += 1
    closed = cv2.morphologyEx(
        gmask, cv2.MORPH_CLOSE, np.ones((max(3, zh // 4), kx), np.uint8)
    )
    cols = (closed[y0:y1, :] > 0).sum(axis=0)
    thr = max(2, zh // 10)
    xs = np.where(cols >= thr)[0]
    if xs.size < _MIN_BAR_W:
        return None
    return int(xs[0]), int(xs[-1]) + 1


def find_green_bar(
    rgb: np.ndarray,
    mask: np.ndarray | None = None,
) -> tuple[int, int, int, int] | None:
    """
    读数区间 (x,y,w,h)：完整绿端 + 左右各 5% 绿宽，裁在帧内（=手框内）。
    """
    if rgb.ndim != 3:
        return None
    gmask = mask if mask is not None else green_zone_mask(rgb)
    band = _green_row_band(gmask)
    if band is None:
        return None
    y0, y1 = band
    zh = y1 - y0
    # 绿端优先闭运算（稳）；橙交界作校验兜底
    ends = _green_ends_via_close(gmask, y0, y1)
    if ends is None:
        ends = _green_ends_via_orange(rgb, gmask, y0, y1)
    if ends is None:
        return None
    gx0, gx1 = ends
    gw = gx1 - gx0
    if gw < _MIN_BAR_W:
        return None
    pad = max(1, int(round(gw * _EDGE_PAD_RATIO)))
    fw = rgb.shape[1]
    x0 = max(0, gx0 - pad)
    x1 = min(fw, gx1 + pad)
    if x1 - x0 < _MIN_BAR_W:
        return None
    return x0, y0, x1 - x0, zh


def find_bobber(
    rgb: np.ndarray,
    *,
    lower: np.ndarray | None = None,
    upper: np.ndarray | None = None,
) -> BobberHit | None:
    """绿条两端+5% 内找白 → 0～100。"""
    gmask = green_zone_mask(rgb, lower=lower, upper=upper)
    bar = find_green_bar(rgb, gmask)
    if bar is None:
        return None
    zx, zy, zw, zh = bar
    fh, fw = rgb.shape[:2]
    y0 = max(0, zy - max(4, int(zh * 0.55)))
    y1 = min(fh, zy + zh + max(2, int(zh * 0.12)))
    x0, x1 = max(0, zx), min(fw, zx + zw)
    crop = rgb[y0:y1, x0:x1]
    wm = cv2.morphologyEx(white_mask(crop), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    min_px = max(_MIN_WHITE_PX, int(zh * 0.8))
    if int(cv2.countNonZero(wm)) < min_px:
        return None
    contours, _ = cv2.findContours(wm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = -1.0
    bar_cy = zy + zh / 2.0
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < min_px:
            continue
        m = cv2.moments(cnt)
        if m["m00"] <= 1e-3:
            continue
        cx = float(x0 + m["m10"] / m["m00"])
        cy = float(y0 + m["m01"] / m["m00"])
        if cx < zx or cx > zx + zw:
            continue
        dist = abs(cy - bar_cy) / max(1.0, float(zh))
        score = area / (1.0 + dist * 3.0)
        if score > best_score:
            best_score = score
            best = (cx, cy, int(area))
    if best is None:
        return None
    cx, cy, px = best
    return BobberHit(
        pos=pixel_to_pos(cx - zx, zw),
        x=cx,
        y=cy,
        pixel_count=px,
        bar_left=float(zx),
        bar_top=float(zy),
        bar_width=float(zw),
        bar_height=float(zh),
        score=min(1.0, px / max(1.0, float(zh * zh))),
    )
