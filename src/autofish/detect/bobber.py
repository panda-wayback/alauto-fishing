"""橘|绿|橘 长条：最左/最右橘红定界，中间绿 = 0～100；带内孔/白 = 鱼漂。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc

# 中间安全区绿
_GREEN_LO = np.array([40, 60, 50], dtype=np.uint8)
_GREEN_HI = np.array([78, 255, 230], dtype=np.uint8)
# 两端橘红/橘黄（略放宽 H，避免端帽偏黄漏检）
_ORANGE_LO = np.array([3, 60, 70], dtype=np.uint8)
_ORANGE_HI = np.array([42, 255, 255], dtype=np.uint8)
_MIN_W = 80
_PAD = 0.05
_MIN_ASPECT = 4.0
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
    ok = (mn >= 130) & ((mx.astype(np.int16) - mn) <= 115)
    return ok.astype(np.uint8) * 255


def _slice_thickness(
    mask: np.ndarray, x0: int, x1: int, y0: int | None = None, y1: int | None = None
) -> int:
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
    if green_h < 6 or orange_l < 3 or orange_r < 3:
        return False
    for oh in (orange_l, orange_r):
        lo, hi = (oh, green_h) if oh < green_h else (green_h, oh)
        if hi > lo * 2.5:
            return False
        if hi - lo > max(12, int(green_h * 1.0)):
            return False
    return True


def _green_y_band(gmask: np.ndarray) -> tuple[int, int] | None:
    """绿最多的薄水平带。"""
    fw = gmask.shape[1]
    row = (gmask > 0).sum(axis=1)
    if row.size == 0:
        return None
    peak = int(row.max())
    if peak < max(16, fw // 20):
        return None
    py = int(np.argmax(row))
    thr = max(6, int(peak * 0.4))
    y0 = y1 = py
    while y0 > 0 and int(row[y0 - 1]) >= thr:
        y0 -= 1
    while y1 < row.size - 1 and int(row[y1 + 1]) >= thr:
        y1 += 1
    y1 += 1
    if y1 - y0 > _MAX_BAR_H:
        best_s, best_i = -1, y0
        last = y1 - _MAX_BAR_H
        for i in range(y0, max(y0, last) + 1):
            s = int(row[i : i + _MAX_BAR_H].sum())
            if s > best_s:
                best_s, best_i = s, i
        y0, y1 = best_i, best_i + _MAX_BAR_H
    if y1 - y0 < 6:
        return None
    return y0, y1


def _orange_runs(ocols: np.ndarray, thr: int) -> list[tuple[int, int]]:
    """列上橘像素达标的连续区间 [start, end)。"""
    runs: list[tuple[int, int]] = []
    n = int(ocols.size)
    i = 0
    while i < n:
        if int(ocols[i]) >= thr:
            j = i + 1
            while j < n and int(ocols[j]) >= thr:
                j += 1
            if j - i >= 3:
                runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def _span_from_orange_ends(
    gmask: np.ndarray, omask: np.ndarray
) -> tuple[int, int, int, int] | None:
    """
    主路径：绿带内取贴绿的最左橘红与最右橘红为起止，其间为绿条。
    中部漂橙叶 / 远处杂色不参与定界。
    """
    band = _green_y_band(gmask)
    if band is None:
        return None
    y0, y1 = band
    gh = y1 - y0
    pad = max(2, gh // 3)
    yw0 = max(0, y0 - pad)
    yw1 = min(omask.shape[0], y1 + pad)
    ocols = (omask[yw0:yw1, :] > 0).sum(axis=0)
    thr = max(2, int((yw1 - yw0) * 0.22))
    runs = _orange_runs(ocols, thr)
    if len(runs) < 2:
        return None

    gcols = (gmask[y0:y1, :] > 0).sum(axis=0)
    if int(gcols.max()) < 2:
        return None
    gthr = max(2, int(gcols.max() * 0.3))
    gxs = np.where(gcols >= gthr)[0]
    if gxs.size < _MIN_W:
        return None
    gx0 = int(gxs[0])
    gx1 = int(gxs[-1]) + 1
    mid = (gx0 + gx1) // 2

    # 贴绿左侧：右缘靠近绿起点的橘段；贴绿右侧：左缘靠近绿终点的橘段
    left_cands = [r for r in runs if r[1] <= mid and r[1] <= gx0 + max(12, gh)]
    right_cands = [r for r in runs if r[0] >= mid and r[0] >= gx1 - max(12, gh)]
    if not left_cands:
        left_cands = [r for r in runs if r[1] <= mid]
    if not right_cands:
        right_cands = [r for r in runs if r[0] >= mid]
    if not left_cands or not right_cands:
        return None
    left = max(left_cands, key=lambda r: r[1])
    right = min(right_cands, key=lambda r: r[0])
    if left[1] + 8 >= right[0]:
        return None

    # 定界：左橘内侧 → 右橘内侧（无橘则退到绿列）
    x0 = max(left[1], gx0)
    x1 = min(right[0], gx1)
    # 若橘贴在绿外，用橘内侧
    if left[1] <= gx0:
        x0 = left[1]
    if right[0] >= gx1:
        x1 = right[0]
    gw = x1 - x0
    if gw < _MIN_W or gw < gh * _MIN_ASPECT:
        return None
    patch = gmask[y0:y1, x0:x1]
    if float((patch > 0).mean()) < 0.12:
        return None
    # 厚度只量贴绿的端帽窄条（避免远处杂色拉高 spill）
    cap = max(8, min(36, gw // 10))
    xl0, xl1 = max(0, x0 - cap), x0
    xr0, xr1 = x1, min(omask.shape[1], x1 + cap)
    oh_l = _slice_thickness(omask, xl0, xl1, yw0, yw1)
    oh_r = _slice_thickness(omask, xr0, xr1, yw0, yw1)
    if not _same_strip_thickness(gh, oh_l, oh_r):
        return None
    for xa, xb in ((xl0, xl1), (xr0, xr1)):
        total = int((omask[:, xa:xb] > 0).sum())
        in_band = int((omask[y0:y1, xa:xb] > 0).sum())
        if total > 0 and in_band < total * 0.30:
            return None
    return x0, y0, gw, gh


def find_green_span(
    rgb: np.ndarray,
    mask: np.ndarray | None = None,
) -> tuple[int, int, int, int] | None:
    """只认「左橘 | 中绿 | 右橘」：以最左/最右橘红为起止。"""
    if rgb.ndim != 3:
        return None
    gmask = mask if mask is not None else green_zone_mask(rgb)
    omask = orange_zone_mask(rgb)
    return _span_from_orange_ends(gmask, omask)


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
    x_start = max(0, zx)
    x_end = min(gmask.shape[1], zx + zw)
    if x_end - x_start < _MIN_W:
        return None
    inv = cv2.bitwise_not(gmask[:, x_start:x_end])
    contours, _ = cv2.findContours(inv, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0.0
    bar_cy = zy + zh / 2.0
    margin = max(6, int(zw * 0.04))
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < 10 or area > 800:
            continue
        _fx, fy, fw_, fh_ = cv2.boundingRect(cnt)
        if fw_ > zw * 0.4 or fh_ > zh * 2.8:
            continue
        if fy + fh_ < zy - 10 or fy > zy + zh + 10:
            continue
        m = cv2.moments(cnt)
        if m["m00"] <= 1e-3:
            continue
        cx = float(x_start + m["m10"] / m["m00"])
        cy = float(m["m01"] / m["m00"])
        if abs(cy - bar_cy) > zh * 1.8:
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
    if int(cv2.countNonZero(wm)) < 4:
        return None
    contours, _ = cv2.findContours(wm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0.0
    bar_cy = zy + zh / 2.0
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < 8:
            continue
        bw = cv2.boundingRect(cnt)[2]
        if bw > zw * 0.45:
            continue
        m = cv2.moments(cnt)
        if m["m00"] <= 1e-3:
            continue
        cx = float(x0 + m["m10"] / m["m00"])
        cy = float(y0 + m["m01"] / m["m00"])
        if abs(cy - bar_cy) > zh * 1.8:
            continue
        if area > best_area:
            best_area = area
            best = (cx, cy, int(area))
    return best


def bobber_in_bar(
    rgb: np.ndarray, zx: int, zy: int, zw: int, zh: int
) -> BobberHit | None:
    if zw < 8 or zh < 4:
        return None
    gmask = green_zone_mask(rgb)
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


def find_bobber(rgb: np.ndarray) -> BobberHit | None:
    """色块法找条+漂。统一入口请用 detect.api.detect。"""
    gmask = green_zone_mask(rgb)
    bar = find_green_bar(rgb, gmask)
    if bar is None:
        return None
    return bobber_in_bar(rgb, *bar)
