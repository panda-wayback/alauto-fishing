"""橘|绿|橘，绿±5% = 0～100；带内亮白块 = 鱼漂。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc

_GREEN_LO = np.array([46, 80, 70], dtype=np.uint8)
_GREEN_HI = np.array([70, 255, 200], dtype=np.uint8)
_ORANGE_LO = np.array([5, 80, 100], dtype=np.uint8)
_ORANGE_HI = np.array([35, 255, 255], dtype=np.uint8)
_MIN_W = 40
_PAD = 0.05


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


def pixel_to_pos(x: float, width: int) -> float:
    if width <= 1:
        return 0.0
    return float(max(0.0, min(100.0, 100.0 * x / (width - 1))))


def _hsv_mask(rgb: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return cv2.inRange(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV), lo, hi)


def green_zone_mask(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("expected HxWx3 RGB image")
    return _hsv_mask(rgb, _GREEN_LO, _GREEN_HI)


def white_mask(rgb: np.ndarray) -> np.ndarray:
    """亮且低彩 = 乳白（不靠 HSV，避免绿底染色漏检）。"""
    mn = rgb.min(axis=2)
    mx = rgb.max(axis=2)
    ok = (mn >= 150) & ((mx.astype(np.int16) - mn) <= 100)
    return ok.astype(np.uint8) * 255


def _green_band(gmask: np.ndarray) -> tuple[int, int] | None:
    """绿最多的几行。"""
    row = (gmask > 0).sum(axis=1)
    if row.size == 0:
        return None
    peak = int(row.max())
    fw = gmask.shape[1]
    if peak < max(20, fw // 12):
        return None
    py = int(np.argmax(row))
    thr = max(12, int(peak * 0.6))
    y0 = y1 = py
    while y0 > 0 and int(row[y0 - 1]) >= thr:
        y0 -= 1
    while y1 < row.size - 1 and int(row[y1 + 1]) >= thr:
        y1 += 1
    y1 += 1
    if y1 - y0 < 4:
        return None
    return y0, y1


def _orange_ends(rgb: np.ndarray, y0: int, y1: int) -> tuple[int, int] | None:
    """左右两端橙块内侧 → 中间绿（只看画面两侧，忽略中部鱼漂橙叶）。"""
    fh, fw = rgb.shape[:2]
    pad = max(2, (y1 - y0) // 4)
    strip = _hsv_mask(rgb, _ORANGE_LO, _ORANGE_HI)[
        max(0, y0 - pad) : min(fh, y1 + pad), :
    ]
    cols = (strip > 0).sum(axis=0)
    if int(cols.max()) < 3:
        return None
    thr = max(2, int(cols.max() * 0.3))
    # 只认左右各 18% 内的端帽橙，中部鱼漂橙叶不参与
    edge = max(16, fw * 18 // 100)
    left_xs = np.where((cols[:edge] >= thr))[0]
    right_xs = np.where((cols[fw - edge :] >= thr))[0]
    if left_xs.size == 0 or right_xs.size == 0:
        return None
    left = int(left_xs[-1]) + 1
    right = int(fw - edge + right_xs[0])
    if right - left < _MIN_W:
        return None
    return left, right


def _green_ends(gmask: np.ndarray, y0: int, y1: int) -> tuple[int, int] | None:
    """橙失败时：闭运算补洞后取绿列范围。"""
    zh = max(1, y1 - y0)
    kx = max(31, min(91, zh * 4 + 11)) | 1
    closed = cv2.morphologyEx(
        gmask, cv2.MORPH_CLOSE, np.ones((max(3, zh // 5), kx), np.uint8)
    )
    cols = (closed[y0:y1] > 0).sum(axis=0)
    xs = np.where(cols >= max(2, zh // 12))[0]
    if xs.size < _MIN_W:
        return None
    return int(xs[0]), int(xs[-1]) + 1


def find_green_span(
    rgb: np.ndarray,
    mask: np.ndarray | None = None,
) -> tuple[int, int, int, int] | None:
    if rgb.ndim != 3:
        return None
    gmask = mask if mask is not None else green_zone_mask(rgb)
    band = _green_band(gmask)
    if band is None:
        return None
    y0, y1 = band
    ends = _orange_ends(rgb, y0, y1) or _green_ends(gmask, y0, y1)
    if ends is None:
        return None
    x0, x1 = ends
    if x1 - x0 < _MIN_W:
        return None
    return x0, y0, x1 - x0, y1 - y0


def find_green_bar(
    rgb: np.ndarray,
    mask: np.ndarray | None = None,
) -> tuple[int, int, int, int] | None:
    span = find_green_span(rgb, mask)
    if span is None:
        return None
    gx0, y0, gw, gh = span
    pad = max(1, int(round(gw * _PAD)))
    x0 = max(0, gx0 - pad)
    x1 = min(rgb.shape[1], gx0 + gw + pad)
    if x1 - x0 < _MIN_W:
        return None
    return x0, y0, x1 - x0, gh


def find_bobber(rgb: np.ndarray) -> BobberHit | None:
    gmask = green_zone_mask(rgb)
    bar = find_green_bar(rgb, gmask)
    if bar is None:
        return None
    zx, zy, zw, zh = bar
    fh, fw = rgb.shape[:2]
    # 鱼漂坐在绿带上：略向上探，不往下伸到进度条
    y0 = max(0, zy - max(6, zh // 2))
    y1 = min(fh, zy + zh + 2)
    x0, x1 = max(0, zx), min(fw, zx + zw)
    wm = white_mask(rgb[y0:y1, x0:x1])
    if int(cv2.countNonZero(wm)) < 6:
        return None
    contours, _ = cv2.findContours(wm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0.0
    bar_cy = zy + zh / 2.0
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < 10:
            continue
        bw = cv2.boundingRect(cnt)[2]
        if bw > zw * 0.4:  # 整条高亮不是鱼漂
            continue
        m = cv2.moments(cnt)
        if m["m00"] <= 1e-3:
            continue
        cx = float(x0 + m["m10"] / m["m00"])
        cy = float(y0 + m["m01"] / m["m00"])
        if abs(cy - bar_cy) > zh * 1.5:
            continue
        if area > best_area:
            best_area = area
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
        score=min(1.0, px / 200.0),
    )
