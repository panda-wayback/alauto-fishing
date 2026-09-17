"""橘|绿|橘 长条：最左/最右橘红定界，中间绿 = 0～100；带内孔/白 = 鱼漂。"""

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
# 条心霓虹绿（更高 V/S，排除同高暗草地）
_NEON_LO = np.array([38, 90, 90], dtype=np.uint8)
_NEON_HI = np.array([56, 255, 255], dtype=np.uint8)
# 两端/危险段橘黄（含条身黄绿过渡；与霓虹绿分离）
_ORANGE_LO = np.array([5, 70, 70], dtype=np.uint8)
_ORANGE_HI = np.array([36, 255, 255], dtype=np.uint8)
# 端帽橘红：色相更偏红、饱和更高；用于定条起止
_ENDCAP_LO = np.array([3, 130, 100], dtype=np.uint8)
_ENDCAP_HI = np.array([25, 255, 255], dtype=np.uint8)
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
    detect_ms: float = 0.0


def pixel_to_pos(x: float, width: int) -> float:
    if width <= 1:
        return 0.0
    return float(max(0.0, min(100.0, 100.0 * x / (width - 1))))


def _hsv_mask(rgb: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return cv2.inRange(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV), lo, hi)


def green_zone_mask(rgb: np.ndarray) -> np.ndarray:
    """HSV 绿 ∪ 偏亮草绿；排除暗草地（V/G 过低）。"""
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("expected HxWx3 RGB image")
    hsv = _hsv_mask(rgb, _GREEN_LO, _GREEN_HI)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    lime = (
        (g.astype(np.int16) > r.astype(np.int16) + 12)
        & (g.astype(np.int16) > b.astype(np.int16) + 12)
        & (g >= 70)
        & (g <= 200)
    )
    out = np.where(lime, np.uint8(255), hsv)
    # 暗绿草：压掉，避免与张力条同高抢带宽
    dark = (g < 60) | (rgb.min(axis=2) < 25)
    out = np.where(dark, np.uint8(0), out)
    return out


def neon_green_mask(rgb: np.ndarray) -> np.ndarray:
    """条心亮绿：定 y 带与绿核，不吃暗草地。"""
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("expected HxWx3 RGB image")
    hsv = _hsv_mask(rgb, _NEON_LO, _NEON_HI)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    bright = (
        (g.astype(np.int16) >= 100)
        & (g.astype(np.int16) > r.astype(np.int16) + 15)
        & (g.astype(np.int16) > b.astype(np.int16) + 15)
    )
    return np.where(bright, hsv, np.uint8(0))


def orange_zone_mask(rgb: np.ndarray) -> np.ndarray:
    """橘黄危险段/端帽；去掉已被霓虹绿占据的像素。"""
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("expected HxWx3 RGB image")
    om = _hsv_mask(rgb, _ORANGE_LO, _ORANGE_HI)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    # 真条身绿占优时不当橘
    greenish = (
        (g.astype(np.int16) > r.astype(np.int16) + 15)
        & (g.astype(np.int16) > b.astype(np.int16) + 15)
        & (g >= 100)
    )
    return np.where(greenish, np.uint8(0), om)


def endcap_mask(rgb: np.ndarray) -> np.ndarray:
    """两端橘红端帽：饱和偏红的橘；黄绿草地必须落选。"""
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("expected HxWx3 RGB image")
    hsv = _hsv_mask(rgb, _ENDCAP_LO, _ENDCAP_HI)
    r, g, b = (
        rgb[:, :, 0].astype(np.int16),
        rgb[:, :, 1].astype(np.int16),
        rgb[:, :, 2].astype(np.int16),
    )
    reddish = (r >= 120) & (r > g + 40) & (r > b + 60)
    return np.where(reddish, hsv, np.uint8(0))


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
    """
    取最像张力条的扁长绿带。
    禁止只认全局绿最多行（全屏草地/UI 会抢走真实细条）。
    """
    fh, fw = gmask.shape[:2]
    kw = max(51, min(101, fw // 8))
    if kw % 2 == 0:
        kw += 1
    closed = cv2.morphologyEx(
        gmask, cv2.MORPH_CLOSE, np.ones((5, kw), np.uint8)
    )
    contours, _ = cv2.findContours(
        closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    best: tuple[float, int, int] | None = None  # score, y0, y1
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < _MIN_W or h < 4:
            continue
        # 整图裁条时 h 可超过 MAX；先收成薄带再验宽高比
        rows = (gmask[y : y + h, x : x + w] > 0).sum(axis=1)
        if rows.size == 0 or int(rows.max()) < 4:
            continue
        peak = int(rows.max())
        thr = max(3, int(peak * 0.3))
        ys = np.where(rows >= thr)[0]
        if ys.size < 3:
            continue
        ry0 = y + int(ys[0])
        ry1 = y + int(ys[-1]) + 1
        if ry1 - ry0 > _MAX_BAR_H:
            best_s, best_i = -1, int(ys[0])
            last = int(ys[-1]) + 1 - _MAX_BAR_H
            for i in range(int(ys[0]), max(int(ys[0]), last) + 1):
                s = int(rows[i : i + _MAX_BAR_H].sum())
                if s > best_s:
                    best_s, best_i = s, i
            ry0, ry1 = y + best_i, y + best_i + _MAX_BAR_H
        rh = ry1 - ry0
        if rh < 4:
            continue
        aspect = float(w) / float(rh)
        if aspect < 3.2 or aspect > 28.0:
            continue
        patch = gmask[ry0:ry1, x : x + w]
        fill = float((patch > 0).mean())
        if fill < 0.10:
            continue
        score = aspect * fill * (w / float(fw))
        if best is None or score > best[0]:
            best = (score, ry0, ry1)
    if best is None:
        return None
    return best[1], best[2]


def _endcap_edge(
    ecols: np.ndarray,
    bcols: np.ndarray,
    start: int,
    direction: int,
    ethr: int,
    bthr: int,
    max_dist: int,
    body_gap_max: int = 12,
) -> int | None:
    """
    从绿核边沿向外找端帽外沿：沿条身（绿∪橘）走，记住最外的橘红列。
    条身断开超限即停 ⇒ 禁止跨草地把端帽认到远处。
    """
    n = int(ecols.size)
    outer: int | None = None
    gap = 0
    x = start
    for _ in range(max_dist):
        x += direction
        if x < 0 or x >= n:
            break
        if int(bcols[x]) >= bthr:
            gap = 0
        else:
            gap += 1
            if gap > body_gap_max:
                break
        if int(ecols[x]) >= ethr:
            outer = x
    return outer


def _span_from_orange_ends(
    gmask: np.ndarray,
    omask: np.ndarray,
    neon: np.ndarray | None = None,
    endcap: np.ndarray | None = None,
) -> tuple[int, int, int, int] | None:
    """
    霓虹绿核定 y 与绿核；两侧就近找橘红端帽，取其外沿为条起止。
    禁止穿过草地无限扩展（端帽只在绿核附近有限距离内）。
    """
    anchor = neon if neon is not None and int(cv2.countNonZero(neon)) > 30 else gmask
    band = _green_y_band(anchor)
    if band is None:
        band = _green_y_band(gmask)
    if band is None:
        return None
    y0, y1 = band
    gh = y1 - y0
    if gh < 4:
        return None

    nmask = neon if neon is not None else gmask
    ncols = (nmask[y0:y1, :] > 0).sum(axis=0)
    if int(ncols.max()) < 2:
        return None
    nthr = max(2, int(ncols.max() * 0.35))
    nxs = np.where(ncols >= nthr)[0]
    if nxs.size < 12:
        return None
    gx0 = int(nxs[0])
    gx1 = int(nxs[-1]) + 1
    core_w = gx1 - gx0

    emask = endcap if endcap is not None else omask
    ecols = (emask[y0:y1, :] > 0).sum(axis=0)
    bcols = (np.maximum(nmask, omask)[y0:y1, :] > 0).sum(axis=0)
    ethr = max(2, int(gh * 0.25))
    bthr = max(2, int(gh * 0.25))
    max_dist = max(40, int(core_w * 1.2))
    left = _endcap_edge(ecols, bcols, gx0, -1, ethr, bthr, max_dist)
    right = _endcap_edge(ecols, bcols, gx1 - 1, +1, ethr, bthr, max_dist)
    if left is None or right is None:
        return None
    x0 = left
    x1 = right + 1
    gw = x1 - x0
    if gw < _MIN_W or gw < gh * 3.5:
        return None
    if float((nmask[y0:y1, x0:x1] > 0).mean()) < 0.04:
        return None

    cap = max(6, min(40, gw // 10))
    oh_l = _slice_thickness(emask, x0, x0 + cap, y0, y1)
    oh_r = _slice_thickness(emask, max(x0, x1 - cap), x1, y0, y1)
    if oh_l < 3 or oh_r < 3:
        return None
    for oh in (oh_l, oh_r):
        if oh > gh * 2.8 or oh < max(3, int(gh * 0.25)):
            return None
    return x0, y0, gw, gh


def find_green_span(
    rgb: np.ndarray,
    mask: np.ndarray | None = None,
) -> tuple[int, int, int, int] | None:
    """只认「左橘 | 中绿 | 右橘」：霓虹绿核 + 两侧就近橘红端帽。"""
    if rgb.ndim != 3:
        return None
    gmask = mask if mask is not None else green_zone_mask(rgb)
    omask = orange_zone_mask(rgb)
    neon = neon_green_mask(rgb)
    endcap = endcap_mask(rgb)
    return _span_from_orange_ends(gmask, omask, neon, endcap)


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
    margin = max(3, int(zw * 0.015))
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
    # 漂白肚可略高于绿带上沿；窗口过大会把远处 UI/水花当漂
    y0 = max(0, zy - max(10, int(zh * 1.5)))
    y1 = min(fh, zy + zh + 2)
    x0, x1 = max(0, zx), min(fw, zx + zw)
    wm = white_mask(rgb[y0:y1, x0:x1])
    if int(cv2.countNonZero(wm)) < 4:
        return None
    contours, _ = cv2.findContours(wm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0.0
    bar_cy = zy + zh / 2.0
    # 漂可贴近端点（危险区），边距过大会漏检
    margin = max(3, int(zw * 0.015))
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
        # 允许漂在条上方约 3 倍条高
        if cy > zy + zh + zh * 0.5:
            continue
        if cy < zy - zh * 3.5:
            continue
        if abs(cy - bar_cy) > zh * 3.5 and cy > zy + zh:
            continue
        if cx < zx + margin or cx > zx + zw - margin:
            continue
        if area > best_area:
            best_area = area
            best = (cx, cy, int(area))
    return best


def _bobber_from_green_gap(
    gmask: np.ndarray, zx: int, zy: int, zw: int, zh: int
) -> tuple[float, float, int] | None:
    """
    绿条必有漂：带内绿密度谷（两侧仍有绿）= 漂挡住的位置。
    忽略端帽 pad 造成的边缘零绿。
    """
    if zw < 16 or zh < 4:
        return None
    y0 = max(0, zy)
    y1 = min(gmask.shape[0], zy + zh)
    x0 = max(0, zx)
    x1 = min(gmask.shape[1], zx + zw)
    strip = gmask[y0:y1, x0:x1]
    if strip.size == 0:
        return None
    col = (strip > 0).mean(axis=0)
    peak = float(col.max()) if col.size else 0.0
    if peak < 0.2:
        return None
    # 只在「绿核心」内找谷，避免 ±5% pad 进橘端后边缘零绿被当成漂
    strong = np.where(col >= peak * 0.45)[0]
    if strong.size < 12:
        return None
    core_lo = int(strong[0])
    core_hi = int(strong[-1])
    if core_hi - core_lo < 12:
        return None
    inner = col[core_lo : core_hi + 1]
    valley_thr = max(0.12, peak * 0.55)
    low = np.where(inner <= valley_thr)[0]
    if low.size == 0:
        # 无深谷则取核心内最低，且须明显低于峰值
        idx_local = int(np.argmin(inner))
        if float(inner[idx_local]) > peak * 0.75:
            return None
        idx = core_lo + idx_local
        w_gap = max(4, zh // 2)
    else:
        best_a = best_b = int(low[0])
        a = int(low[0])
        prev = a
        for v in low[1:]:
            v = int(v)
            if v == prev + 1:
                prev = v
            else:
                if prev - a >= best_b - best_a:
                    best_a, best_b = a, prev
                a = prev = v
        if prev - a >= best_b - best_a:
            best_a, best_b = a, prev
        idx = core_lo + (best_a + best_b) // 2
        w_gap = max(4, best_b - best_a + 1)
    # 谷两侧须仍有绿（真孔，不是端帽）
    if idx <= core_lo + 2 or idx >= core_hi - 2:
        return None
    cx = float(x0 + idx)
    cy = float(y0 + (y1 - y0) / 2.0)
    px = int(w_gap * max(1, y1 - y0) * (1.0 - float(col[idx])))
    return cx, cy, max(px, 8)


def bobber_in_bar(
    rgb: np.ndarray, zx: int, zy: int, zw: int, zh: int
) -> BobberHit | None:
    """绿条既定必有漂：白 → 绿孔 → 绿密度谷。只在条框附近 ROI 运算。"""
    if zw < 8 or zh < 4:
        return None
    fh, fw = rgb.shape[:2]
    margin = max(70, zh * 3)
    rx0 = max(0, zx)
    ry0 = max(0, zy - margin)
    rx1 = min(fw, zx + zw)
    ry1 = min(fh, zy + zh + margin)
    roi = rgb[ry0:ry1, rx0:rx1]
    gmask = green_zone_mask(roi)
    hit = _bobber_from_white(roi, 0, zy - ry0, rx1 - rx0, zh)
    if hit is None:
        hit = _bobber_from_green_hole(gmask, 0, zy - ry0, rx1 - rx0, zh)
    if hit is None:
        hit = _bobber_from_green_gap(gmask, 0, zy - ry0, rx1 - rx0, zh)
    if hit is None:
        return None
    cx, cy, px = hit
    return BobberHit(
        pos=pixel_to_pos(cx, rx1 - rx0),
        x=cx + rx0,
        y=cy + ry0,
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
