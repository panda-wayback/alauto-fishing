"""当前光标位图是否为漂形（自上而下：黄羽 → 红带 → 白肚）；输入可为 RGB 或 RGBA。"""

from __future__ import annotations

import numpy as np

# 相对「不透明像素」占比下限（系统光标大量透明）
_MIN_YELLOW = 0.02
_MIN_RED = 0.01
_MIN_BODY = 0.02
_MIN_OPAQUE = 32
# 三色质心须自上而下呈 黄羽 → 红带 → 白肚；允许的顺序容差（占图高比例）
# 纯按色块占比易把同样偏金黄、明暗混杂但并非漂形的图标（如系统光标主题图标）
# 误判为漂；多数这类图标高光/阴影并非按「羽-带-肚」纵向分层，加质心顺序校验可排除
_ORDER_TOL_FRAC = 0.04
# 不透明像素中「黄/红/肚」三色合计占比下限。真漂（无论整图还是缩成小光标）
# 几乎整个不透明区域都是这三色；很多游戏图标（如可互动提示、营火类图标）即使
# 凑够三色各自占比、顺序也对，但图标里还混了大片背景/描边/装饰（如水纹涟漪）
# 等三色之外的颜色，合计占比明显偏低，用这条再排除一批
_MIN_COLOR_COVERAGE = 0.45


def see_surface_bobber(rgb: np.ndarray) -> bool:
    """光标小图是否呈漂形特征（黄羽 + 红带 + 乳白肚）。"""
    if rgb is None or not isinstance(rgb, np.ndarray) or rgb.ndim != 3:
        return False
    h, w, c = rgb.shape
    if c < 3 or h * w < 16:
        return False
    arr = np.asarray(rgb[..., :3], dtype=np.uint8)
    r = arr[..., 0].astype(np.int16)
    g = arr[..., 1].astype(np.int16)
    b = arr[..., 2].astype(np.int16)

    if c >= 4:
        a = np.asarray(rgb[..., 3], dtype=np.uint8)
        opaque = a > 24
    else:
        # 无 alpha：排除近黑近纯透明底
        opaque = (r.astype(np.int16) + g + b) > 40

    n = int(opaque.sum())
    if n < _MIN_OPAQUE:
        return False

    yellow = opaque & (r > 170) & (g > 120) & (b < 130) & (r > b + 40) & (g > b + 20)
    red = opaque & (r > 140) & (g < 110) & (b < 110) & (r > g + 40) & (r > b + 40)
    white = (
        opaque
        & (r > 200)
        & (g > 190)
        & (b > 170)
        & (np.abs(r - g) < 45)
        & (np.abs(g - b) < 50)
    )
    cream = (
        opaque
        & (r > 175)
        & (g > 150)
        & (b > 110)
        & (r > b + 20)
        & (g > b)
        & (np.abs(r - g) < 60)
    )
    body = white | cream
    nf = float(n)
    if not (
        float(yellow.sum()) / nf >= _MIN_YELLOW
        and float(red.sum()) / nf >= _MIN_RED
        and float(body.sum()) / nf >= _MIN_BODY
    ):
        return False

    # 三色占比各自达标还不够：图标里三色之外还混了大片其它颜色（背景、描边、
    # 涟漪等装饰）时，说明这只是碰巧带点黄红白的别的图标，不是真漂（漂本身
    # 不透明区域几乎全是这三色）。
    colored = yellow | red | body
    if float(colored.sum()) / nf < _MIN_COLOR_COVERAGE:
        return False

    # 色块占比达标还不够：很多金黄色调、明暗混杂的图标（如系统光标主题里的
    # 箭头/沙漏/链接选择图标）三色都能凑够占比，但并非漂的纵向分层结构。
    # 漂形固定自上而下为 黄羽 → 红带 → 白肚，用各色质心行号校验这一顺序。
    yc = _row_centroid(yellow)
    rc = _row_centroid(red)
    bc = _row_centroid(body)
    if yc is None or rc is None or bc is None:
        return False
    tol = h * _ORDER_TOL_FRAC
    return yc <= rc + tol and rc <= bc + tol


def _row_centroid(mask: np.ndarray) -> float | None:
    """掩膜的加权行质心（0=最上）；无命中像素时 None。"""
    weights = mask.sum(axis=1).astype(np.float64)
    total = float(weights.sum())
    if total <= 0:
        return None
    rows = np.arange(mask.shape[0], dtype=np.float64)
    return float((rows * weights).sum() / total)
