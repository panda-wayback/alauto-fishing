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
# 入图宽超过此值则等比压缩后再识别（坐标映回）
_INPUT_MAX_W = 720


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
    """一帧只算一次：HSV + 连续的 R/G/B 通道。掩膜共用，避免重复转换。"""
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("expected HxWx3 RGB image")
    hsv = cv2.cvtColor(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2HSV)
    r, g, b = cv2.split(rgb)
    return hsv, r, g, b


def _gt_by(a: np.ndarray, b: np.ndarray, delta: int) -> np.ndarray:
    """a > b + delta（uint8 饱和减，走 cv2 比 numpy 逐元素快）。"""
    return cv2.compare(cv2.subtract(a, b), float(delta), cv2.CMP_GT)


def green_zone_mask(
    rgb: np.ndarray, prep: tuple[np.ndarray, ...] | None = None
) -> np.ndarray:
    """HSV 绿 ∪ 偏亮草绿；排除暗草地（V/G 过低）。"""
    hsv, r, g, b = prep if prep is not None else _prep(rgb)
    out = cv2.inRange(hsv, _GREEN_LO, _GREEN_HI)
    lime = cv2.bitwise_and(_gt_by(g, r, 12), _gt_by(g, b, 12))
    lime = cv2.bitwise_and(lime, cv2.inRange(g, 70, 200))
    out = cv2.bitwise_or(out, lime)
    # 暗绿草：压掉，避免与张力条同高抢带宽
    mn = cv2.min(cv2.min(r, g), b)
    bright = cv2.bitwise_and(
        cv2.compare(g, 60.0, cv2.CMP_GE),
        cv2.compare(mn, 25.0, cv2.CMP_GE),
    )
    return cv2.bitwise_and(out, bright)


def neon_green_mask(
    rgb: np.ndarray, prep: tuple[np.ndarray, ...] | None = None
) -> np.ndarray:
    """条心亮绿：定 y 带与绿核，不吃暗草地。"""
    hsv, r, g, b = prep if prep is not None else _prep(rgb)
    out = cv2.inRange(hsv, _NEON_LO, _NEON_HI)
    bright = cv2.bitwise_and(_gt_by(g, r, 15), _gt_by(g, b, 15))
    bright = cv2.bitwise_and(bright, cv2.compare(g, 100.0, cv2.CMP_GE))
    return cv2.bitwise_and(out, bright)


def orange_zone_mask(
    rgb: np.ndarray, prep: tuple[np.ndarray, ...] | None = None
) -> np.ndarray:
    """橘黄危险段/端帽；去掉已被霓虹绿占据的像素。"""
    hsv, r, g, b = prep if prep is not None else _prep(rgb)
    om = cv2.inRange(hsv, _ORANGE_LO, _ORANGE_HI)
    # 真条身绿占优时不当橘
    greenish = cv2.bitwise_and(_gt_by(g, r, 15), _gt_by(g, b, 15))
    greenish = cv2.bitwise_and(greenish, cv2.compare(g, 100.0, cv2.CMP_GE))
    return cv2.bitwise_and(om, cv2.bitwise_not(greenish))


def endcap_mask(
    rgb: np.ndarray, prep: tuple[np.ndarray, ...] | None = None
) -> np.ndarray:
    """两端橘红端帽：饱和偏红的橘；黄绿草地必须落选。"""
    hsv, r, g, b = prep if prep is not None else _prep(rgb)
    out = cv2.inRange(hsv, _ENDCAP_LO, _ENDCAP_HI)
    reddish = cv2.bitwise_and(_gt_by(r, g, 40), _gt_by(r, b, 60))
    reddish = cv2.bitwise_and(reddish, cv2.compare(r, 120.0, cv2.CMP_GE))
    return cv2.bitwise_and(out, reddish)


def white_mask(rgb: np.ndarray) -> np.ndarray:
    """亮且低彩 = 乳白。"""
    r, g, b = cv2.split(rgb)
    mn = cv2.min(cv2.min(r, g), b)
    mx = cv2.max(cv2.max(r, g), b)
    return cv2.bitwise_and(
        cv2.compare(mn, 130.0, cv2.CMP_GE),
        cv2.compare(cv2.subtract(mx, mn), 115.0, cv2.CMP_LE),
    )


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


def _green_y_band(
    gmask: np.ndarray, min_w: int = _MIN_W
) -> tuple[int, int] | None:
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
        if w < min_w or h < 4:
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
    min_w: int = _MIN_W,
) -> tuple[int, int, int, int] | None:
    """
    霓虹绿核定 y 与绿核；两侧就近找橘红端帽，取其外沿为条起止。
    禁止穿过草地无限扩展（端帽只在绿核附近有限距离内）。
    """
    anchor = neon if neon is not None and int(cv2.countNonZero(neon)) > 30 else gmask
    band = _green_y_band(anchor, min_w)
    if band is None:
        band = _green_y_band(gmask, min_w)
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
    if gw < min_w or gw < gh * 3.5:
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


def _maybe_downscale(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    """过宽则压到 _INPUT_MAX_W；返回 (工作图, 缩放比 work/原)。"""
    fh, fw = rgb.shape[:2]
    if fw <= _INPUT_MAX_W:
        return rgb, 1.0
    scale = _INPUT_MAX_W / float(fw)
    sw = max(1, int(round(fw * scale)))
    sh = max(1, int(round(fh * scale)))
    return cv2.resize(rgb, (sw, sh), interpolation=cv2.INTER_AREA), scale


def _scale_box(
    box: tuple[int, int, int, int], inv: float
) -> tuple[int, int, int, int]:
    x, y, w, h = box
    return (
        int(round(x * inv)),
        int(round(y * inv)),
        max(1, int(round(w * inv))),
        max(1, int(round(h * inv))),
    )


def _span_at(
    rgb: np.ndarray, min_w: int = _MIN_W
) -> tuple[int, int, int, int] | None:
    """在给定图上找条：HSV/通道只算一次，四种掩膜共用。"""
    prep = _prep(rgb)
    return _span_from_orange_ends(
        green_zone_mask(rgb, prep),
        orange_zone_mask(rgb, prep),
        neon_green_mask(rgb, prep),
        endcap_mask(rgb, prep),
        min_w=min_w,
    )


def find_green_span(rgb: np.ndarray) -> tuple[int, int, int, int] | None:
    """
    只认「左橘 | 中绿 | 右橘」：霓虹绿核 + 两侧就近橘红端帽。
    入图过宽先等比压缩再识别，坐标映回原图。
    """
    if rgb.ndim != 3:
        return None
    work, scale = _maybe_downscale(rgb)
    min_w = max(24, int(round(_MIN_W * scale)))
    span = _span_at(work, min_w=min_w)
    if span is None:
        return None
    if scale == 1.0:
        return span
    return _scale_box(span, 1.0 / scale)


def find_green_bar(rgb: np.ndarray) -> tuple[int, int, int, int] | None:
    span = find_green_span(rgb)
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
    margin = max(3, int(zw * 0.015))
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < 10 or area > 800:
            continue
        _fx, _fy, fw_, fh_ = cv2.boundingRect(cnt)
        if fw_ > zw * 0.4 or fh_ > zh * 2.8:
            continue
        m = cv2.moments(cnt)
        if m["m00"] <= 1e-3:
            continue
        cx = float(x_start + m["m10"] / m["m00"])
        cy = float(m["m01"] / m["m00"])
        if cy < zy or cy > zy + zh:
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
    # 漂白肚可略出条沿，故窗口留小余量；但质心必须落在条内
    pad = max(2, int(zh * 0.25))
    y0 = max(0, zy - pad)
    y1 = min(fh, zy + zh + pad)
    x0, x1 = max(0, zx), min(fw, zx + zw)
    wm = white_mask(rgb[y0:y1, x0:x1])
    if int(cv2.countNonZero(wm)) < 4:
        return None
    contours, _ = cv2.findContours(wm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0.0
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
        if cy < zy or cy > zy + zh:
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
    # 漂必在条内，ROI 只留白肚溢出条沿的余量
    margin = max(2, zh // 2)
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
    """色块法找条+漂。统一入口请用 detect.api.detect。

    过宽入图：压缩图上定条（坐标映回），漂仍在原图像素条框附近找，避免压缩糊掉漂点。
    """
    if rgb.ndim != 3:
        return None
    work, scale = _maybe_downscale(rgb)
    min_w = max(24, int(round(_MIN_W * scale)))
    span = _span_at(work, min_w=min_w)
    if span is None:
        return None
    gx0, y0, gw, gh = span
    pad = max(1, int(round(gw * _PAD)))
    x0 = max(0, gx0 - pad)
    x1 = min(work.shape[1], gx0 + gw + pad)
    if x1 - x0 < min_w:
        return None
    bar = (x0, y0, x1 - x0, gh)
    if scale != 1.0:
        bar = _scale_box(bar, 1.0 / scale)
        # 映回后夹紧到原图
        bx, by, bw, bh = bar
        bx = max(0, min(bx, rgb.shape[1] - 1))
        by = max(0, min(by, rgb.shape[0] - 1))
        bw = max(1, min(bw, rgb.shape[1] - bx))
        bh = max(1, min(bh, rgb.shape[0] - by))
        bar = (bx, by, bw, bh)
    return bobber_in_bar(rgb, *bar)
