"""对齐 AutoFishing：HSV 绿条 + 反掩膜空洞 = 鱼漂；输出 0～100。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc

# AutoFishing settings.py 默认绿区 HSV（OpenCV H:0-179）
DEFAULT_LOWER_ZONE = np.array([46, 84, 106], dtype=np.uint8)
DEFAULT_UPPER_ZONE = np.array([67, 247, 193], dtype=np.uint8)

# AF 默认 bar 宽约 250、空洞面积 8~350；按绿条宽度比例缩放
_AF_REF_BAR_W = 250.0
_HOLE_AREA_MIN = 8.0
_HOLE_AREA_MAX = 350.0


@dataclass(frozen=True)
class BobberHit:
    """鱼漂检测结果。"""

    pos: float
    """相对绿条：最左=0，最右=100。"""
    x: float
    """像素 x（相对 ROI 左缘）。"""
    y: float
    pixel_count: int
    bar_left: float = 0.0
    bar_width: float = 0.0


def pixel_to_pos(x: float, width: int) -> float:
    if width <= 1:
        return 0.0
    return float(max(0.0, min(100.0, 100.0 * x / (width - 1))))


def green_zone_mask(
    rgb: np.ndarray,
    lower: np.ndarray | None = None,
    upper: np.ndarray | None = None,
) -> np.ndarray:
    """RGB 帧 → 绿安全区二值掩膜（uint8 0/255）。"""
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("expected HxWx3 RGB image")
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    lo = DEFAULT_LOWER_ZONE if lower is None else lower
    hi = DEFAULT_UPPER_ZONE if upper is None else upper
    return cv2.inRange(hsv, lo, hi)


def find_green_bar(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """在绿掩膜上找张力条绿区矩形 (x, y, w, h)。对齐 AF 扁长条条件。"""
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 21), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0.0
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        x, y, w, h = cv2.boundingRect(cnt)
        if h <= 0 or w < 80 or h < 8:
            continue
        aspect = float(w) / h
        if aspect < 3.5 or aspect > 16.0:
            continue
        if area > best_area:
            best_area = area
            best = (x, y, w, h)
    return best


def _hole_area_limits(bar_w: int) -> tuple[float, float]:
    scale = max(0.5, bar_w / _AF_REF_BAR_W)
    # 面积随分辨率平方缩放；抬高下限减少红区噪点
    return max(40.0, _HOLE_AREA_MIN * scale * scale), _HOLE_AREA_MAX * scale * scale


def find_hole_on_bar(
    mask: np.ndarray, bar: tuple[int, int, int, int]
) -> tuple[float, float, int] | None:
    """
    对齐 AF：在绿条水平带内反掩膜找小空洞。
    只在条带 crop 内找，排除两端红区假洞；面积按条宽缩放。
    """
    zx, zy, zw, zh = bar
    h, w = mask.shape
    y0, y1 = max(0, zy), min(h, zy + zh)
    x0, x1 = max(0, zx), min(w, zx + zw)
    if y1 <= y0 or x1 <= x0:
        return None

    crop = mask[y0:y1, x0:x1]
    inv = cv2.bitwise_not(crop)
    # 去掉贴边的「整条外」连通域：先清零上下若几乎全非绿…用面积上限即可
    contours, _ = cv2.findContours(inv, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    amin, amax = _hole_area_limits(zw)
    # 不超过绿条面积的 25%
    amax = min(amax, 0.25 * zw * max(1, zh))

    best = None
    best_score = -1.0
    margin = max(8, int(0.10 * zw))
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < amin or area > amax:
            continue
        fx, fy, fw, fh = cv2.boundingRect(cnt)
        cx_local = fx + fw / 2.0
        # 排除左右端红过渡假洞
        if cx_local < margin or cx_local > (x1 - x0) - margin:
            continue
        # 偏好更「高」的洞（鱼漂竖条）且面积适中
        score = area * (1.0 + 0.5 * (fh / max(1, fw)))
        if score > best_score:
            best_score = score
            best = (
                float(x0 + cx_local),
                float(y0 + fy + fh / 2.0),
                int(area),
            )
    if best is not None:
        return best

    # 回退：绿条内按列「缺绿」峰值（鱼漂挡住绿）
    return _column_gap(crop, x0, y0, zw, zh)


def _column_gap(
    crop: np.ndarray, x0: int, y0: int, zw: int, zh: int
) -> tuple[float, float, int] | None:
    """列投影：绿越少越可能是鱼漂。"""
    if crop.size == 0:
        return None
    green_ratio = (crop > 0).mean(axis=0)  # per column
    gap = 1.0 - green_ratio.astype(np.float64)
    if gap.size < 5:
        return None
    # 平滑
    k = max(3, zw // 40 | 1)
    kernel = np.ones(k) / k
    smooth = np.convolve(gap, kernel, mode="same")
    margin = max(8, int(0.10 * zw))
    smooth[:margin] = 0
    smooth[-margin:] = 0
    if smooth.max() < 0.12:
        return None
    cx_local = int(np.argmax(smooth))
    return (
        float(x0 + cx_local),
        float(y0 + zh / 2.0),
        int(smooth[cx_local] * zh),
    )


def find_bobber(
    rgb: np.ndarray,
    *,
    lower: np.ndarray | None = None,
    upper: np.ndarray | None = None,
) -> BobberHit | None:
    """
    对齐 AF 小游戏：绿条 HSV → 空洞/缺绿中心。
    pos 相对绿条宽度 0～100。
    """
    mask = green_zone_mask(rgb, lower=lower, upper=upper)
    bar = find_green_bar(mask)
    if bar is None:
        return None
    zx, zy, zw, zh = bar
    hole = find_hole_on_bar(mask, bar)
    if hole is None:
        return None
    cx, cy, area = hole
    pos = pixel_to_pos(cx - zx, zw)
    return BobberHit(
        pos=pos,
        x=cx,
        y=cy,
        pixel_count=area,
        bar_left=float(zx),
        bar_width=float(zw),
    )


def orange_mask(rgb: np.ndarray) -> np.ndarray:
    """兼容名：绿区布尔掩膜。"""
    return green_zone_mask(rgb) > 0
