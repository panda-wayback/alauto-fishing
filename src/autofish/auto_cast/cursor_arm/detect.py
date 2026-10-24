"""当前光标位图是否为漂形（白肚 + 红带 + 黄羽）；输入可为 RGB 或 RGBA。"""

from __future__ import annotations

import numpy as np

# 相对「不透明像素」占比下限（系统光标大量透明）
_MIN_YELLOW = 0.02
_MIN_RED = 0.01
_MIN_BODY = 0.02
_MIN_OPAQUE = 32


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
    return (
        float(yellow.sum()) / nf >= _MIN_YELLOW
        and float(red.sum()) / nf >= _MIN_RED
        and float(body.sum()) / nf >= _MIN_BODY
    )
