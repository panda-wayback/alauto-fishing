"""橘|绿|橘 长条：中间绿 = 0～100；带内孔/亮白 = 鱼漂。纯色块，不用模板。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc

# 中间安全区绿（略放宽 H，实机条心约 H≈44）
_GREEN_LO = np.array([40, 70, 60], dtype=np.uint8)
_GREEN_HI = np.array([75, 255, 220], dtype=np.uint8)
# 两端橘红/橘黄
_ORANGE_LO = np.array([5, 70, 80], dtype=np.uint8)
_ORANGE_HI = np.array([38, 255, 255], dtype=np.uint8)
_MIN_W = 80
_PAD = 0.05
_MIN_ASPECT = 4.0
_MAX_ASPECT = 20.0
_MAX_BAR_H = 56


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


def orange_zone_mask(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("expected HxWx3 RGB image")
    return _hsv_mask(rgb, _ORANGE_LO, _ORANGE_HI)


def white_mask(rgb: np.ndarray) -> np.ndarray:
    """亮且低彩 = 乳白。"""
    mn = rgb.min(axis=2)
    mx = rgb.max(axis=2)
    ok = (mn >= 150) & ((mx.astype(np.int16) - mn) <= 100)
    return ok.astype(np.uint8) * 255


def _slice_thickness(
    mask: np.ndarray, x0: int, x1: int, y0: int | None = None, y1: int | None = None
) -> int:
    """某水平区间内色块的垂直厚度。"""
    if x1 <= x0 or mask.size == 0:
        return 0
    fh = mask.shape[0]
    yw0 = 0 if y0 is None else max(0, y0)
    yw1 = fh if y1 is None else min(fh, y1)
    if yw1 <= yw0:
        return 0
    x0 = max(0, x0)
    x1 = min(mask.shape[1], x1)
    if x1 <= x0:
        return 0
    rows = (mask[yw0:yw1, x0:x1] > 0).sum(axis=1)
    if int(rows.max()) < 2:
        return 0
    thr = max(1, int(rows.max() * 0.35))
    ys = np.where(rows >= thr)[0]
    if ys.size == 0:
        return 0
    return int(ys[-1] - ys[0] + 1)


def _same_strip_thickness(green_h: int, orange_l: int, orange_r: int) -> bool:
    """橘端与绿段基本同高（同一扁条厚度）。"""
    if green_h < 6 or orange_l < 4 or orange_r < 4:
        return False
    for oh in (orange_l, orange_r):
        lo, hi = (oh, green_h) if oh < green_h else (green_h, oh)
        if hi > lo * 2.2:
            return False
        if hi - lo > max(10, int(green_h * 0.85)):
            return False
    return True


def _orange_caps_ok(
    omask: np.ndarray, x0: int, y0: int, x1: int, y1: int
) -> bool:
    """绿段左右邻接各有橘端，且与绿段同高；禁止竖向橘塔。"""
    gh = y1 - y0
    gw = x1 - x0
    if gh < 6 or gw < _MIN_W:
        return False
    cap_w = max(10, min(48, gw // 8))
    pad = max(2, gh // 3)
    yw0, yw1 = max(0, y0 - pad), min(omask.shape[0], y1 + pad)
    xl0, xl1 = max(0, x0 - cap_w), x0
    xr0, xr1 = x1, min(omask.shape[1], x1 + cap_w)
    if xl1 - xl0 < 4 or xr1 - xr0 < 4:
        return False
    left = omask[yw0:yw1, xl0:xl1]
    right = omask[yw0:yw1, xr0:xr1]
    if float((left > 0).mean()) < 0.12 or float((right > 0).mean()) < 0.12:
        return False
    oh_l = _slice_thickness(omask, xl0, xl1, yw0, yw1)
    oh_r = _slice_thickness(omask, xr0, xr1, yw0, yw1)
    if not _same_strip_thickness(gh, oh_l, oh_r):
        return False
    # 橘端主要落在条带高度内，拒绝整列竖塔
    for xa, xb in ((xl0, xl1), (xr0, xr1)):
        total = int((omask[:, xa:xb] > 0).sum())
        in_band = int((omask[y0:y1, xa:xb] > 0).sum())
        if total > 0 and in_band < total * 0.35:
            return False
    return True


def _refine_bar_box(
    gmask: np.ndarray, x: int, y: int, w: int, h: int
) -> tuple[int, int, int, int] | None:
    """轮廓框内压成绿密度最高的薄带（兼容整图裁成条的情况）。"""
    rows = (gmask[y : y + h, x : x + w] > 0).sum(axis=1)
    if rows.size == 0:
        return None
    peak = int(rows.max())
    if peak < max(8, w // 16):
        return None
    thr = max(4, int(peak * 0.45))
    ys = np.where(rows >= thr)[0]
    if ys.size < 4:
        return None
    y0 = int(ys[0])
    y1 = int(ys[-1]) + 1
    if y1 - y0 > _MAX_BAR_H:
        best_s, best_i = -1, y0
        last = y1 - _MAX_BAR_H
        for i in range(y0, max(y0, last) + 1):
            s = int(rows[i : i + _MAX_BAR_H].sum())
            if s > best_s:
                best_s, best_i = s, i
        y0, y1 = best_i, best_i + _MAX_BAR_H
    ry0, rh = y + y0, y1 - y0
    if rh < 8:
        return None
    patch = gmask[ry0 : ry0 + rh, x : x + w]
    if float((patch > 0).mean()) < 0.22:
        return None
    aspect = float(w) / float(rh)
    if aspect < _MIN_ASPECT or aspect > _MAX_ASPECT:
        return None
    return x, ry0, w, rh


def _green_bar_candidates(gmask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """水平闭运算后按扁长轮廓取候选绿段（借鉴 AutoFishing）。"""
    kernel = np.ones((5, 21), np.uint8)
    closed = cv2.morphologyEx(gmask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out: list[tuple[int, int, int, int]] = []
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True):
        x, y, w, h = cv2.boundingRect(cnt)
        if w < _MIN_W or h < 8:
            continue
        refined = _refine_bar_box(gmask, x, y, w, h)
        if refined is not None:
            out.append(refined)
    return out

def find_green_span(
    rgb: np.ndarray,
    mask: np.ndarray | None = None,
) -> tuple[int, int, int, int] | None:
    """
    只认「左橘 | 中绿 | 右橘」扁长条，且橘端与绿段同高。
    绿：闭运算扁长轮廓；橘：贴在绿左右外侧验。
    """
    if rgb.ndim != 3:
        return None
    gmask = mask if mask is not None else green_zone_mask(rgb)
    omask = orange_zone_mask(rgb)
    for x, y, w, h in _green_bar_candidates(gmask):
        if _orange_caps_ok(omask, x, y, x + w, y + h):
            return x, y, w, h
    return None


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


def _bobber_from_green_hole(
    gmask: np.ndarray, zx: int, zy: int, zw: int, zh: int
) -> tuple[float, float, int] | None:
    """绿掩膜内孔 = 漂（AutoFishing 同款）；忽略贴边碎孔。"""
    fh, fw = gmask.shape[:2]
    x_start = max(0, zx)
    x_end = min(fw, zx + zw)
    if x_end - x_start < _MIN_W:
        return None
    inv = cv2.bitwise_not(gmask[:, x_start:x_end])
    contours, _ = cv2.findContours(inv, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0.0
    bar_cy = zy + zh / 2.0
    margin = max(8, int(zw * 0.06))
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < 25 or area > 500:
            continue
        fx, fy, fw_, fh_ = cv2.boundingRect(cnt)
        if fw_ > zw * 0.35 or fh_ > zh * 2.5:
            continue
        if fy + fh_ < zy - 8 or fy > zy + zh + 8:
            continue
        m = cv2.moments(cnt)
        if m["m00"] <= 1e-3:
            continue
        cx = float(x_start + m["m10"] / m["m00"])
        cy = float(m["m01"] / m["m00"])
        if abs(cy - bar_cy) > zh * 1.5:
            continue
        if cx < zx + margin or cx > zx + zw - margin:
            continue
        if area > best_area:
            best_area = area
            best = (cx, cy, int(area))
    return best

def _bobber_from_white(
    rgb: np.ndarray, zx: int, zy: int, zw: int, zh: int
) -> tuple[float, float, int] | None:
    fh, fw = rgb.shape[:2]
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
        if bw > zw * 0.4:
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
    return best


def find_bobber(rgb: np.ndarray) -> BobberHit | None:
    gmask = green_zone_mask(rgb)
    bar = find_green_bar(rgb, gmask)
    if bar is None:
        return None
    zx, zy, zw, zh = bar
    # 乳白优先（实机漂体）；无白再退绿内孔
    hit = _bobber_from_white(rgb, zx, zy, zw, zh)
    if hit is None:
        hit = _bobber_from_green_hole(gmask, zx, zy, zw, zh)
    if hit is None:
        return None
    cx, cy, px = hit
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
