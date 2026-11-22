"""当前光标位图：漂形（可开抛）与鱼钩（可起钩）。输入可为 RGB 或 RGBA。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc

from common.paths import assets_dir

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

_HOOK_TEMPLATE_REL = Path("cursor_arm") / "fishing_hook.png"
_HOOK_MATCH_MIN = 0.55
_HOOK_SCALES = (0.55, 0.70, 0.85, 1.0, 1.15, 1.35, 1.60)


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


def see_fishing_hook(rgb: np.ndarray) -> bool:
    """光标小图是否呈鱼钩外形（对内置鱼钩模板够像）；漂形直接否。"""
    return classify_cursor_shape(rgb) == "hook"


def classify_cursor_shape(rgb: np.ndarray) -> str:
    """光标外形：bobber / hook / other。先漂后钩。"""
    if rgb is None or not isinstance(rgb, np.ndarray) or rgb.ndim != 3:
        return "other"
    h, w, c = rgb.shape
    if c < 3 or h * w < 16:
        return "other"
    if see_surface_bobber(rgb):
        return "bobber"
    tpl = _hook_template_bgr()
    if tpl is None:
        return "other"
    probe = _cursor_bgr_masked(rgb)
    if probe is None:
        return "other"
    if _match_hook_template(probe, tpl) >= _HOOK_MATCH_MIN:
        return "hook"
    return "other"


def _row_centroid(mask: np.ndarray) -> float | None:
    """掩膜的加权行质心（0=最上）；无命中像素时 None。"""
    weights = mask.sum(axis=1).astype(np.float64)
    total = float(weights.sum())
    if total <= 0:
        return None
    rows = np.arange(mask.shape[0], dtype=np.float64)
    return float((rows * weights).sum() / total)


@lru_cache(maxsize=1)
def _hook_template_bgr() -> np.ndarray | None:
    path = assets_dir() / _HOOK_TEMPLATE_REL
    if not path.is_file():
        return None
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    raw = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if raw is None or raw.ndim != 3 or raw.shape[2] < 3:
        return None
    if raw.shape[2] >= 4:
        rgba = cv2.cvtColor(raw, cv2.COLOR_BGRA2RGBA)
    else:
        rgb = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
        alpha = np.full(rgb.shape[:2], 255, dtype=np.uint8)
        rgba = np.dstack([rgb, alpha])
    return _cursor_bgr_masked(rgba)


def _cursor_bgr_masked(img: np.ndarray) -> np.ndarray | None:
    """转 BGR，并把非前景涂黑，便于模板匹配。"""
    arr = np.asarray(img)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return None
    rgb = np.asarray(arr[..., :3], dtype=np.uint8)
    if arr.shape[2] >= 4:
        opaque = np.asarray(arr[..., 3], dtype=np.uint8) > 24
    else:
        r = rgb[..., 0].astype(np.int16)
        g = rgb[..., 1].astype(np.int16)
        b = rgb[..., 2].astype(np.int16)
        opaque = (r + g + b) > 40
    if int(opaque.sum()) < _MIN_OPAQUE:
        return None
    out = np.zeros_like(rgb)
    out[opaque] = rgb[opaque]
    return cv2.cvtColor(out, cv2.COLOR_RGB2BGR)


def _match_hook_template(probe_bgr: np.ndarray, tpl_bgr: np.ndarray) -> float:
    ph, pw = probe_bgr.shape[:2]
    th, tw = tpl_bgr.shape[:2]
    best = 0.0
    for scale in _HOOK_SCALES:
        nh = max(8, int(round(th * scale)))
        nw = max(8, int(round(tw * scale)))
        if nh > ph or nw > pw:
            # 模板比光标大：反过来把光标放大到模板再比一次
            if scale >= 0.99:
                sh = max(8, int(round(ph * (th / max(ph, 1)))))
                sw = max(8, int(round(pw * (tw / max(pw, 1)))))
                if sh <= th and sw <= tw:
                    resized = cv2.resize(probe_bgr, (sw, sh), interpolation=cv2.INTER_AREA)
                    canvas = np.zeros_like(tpl_bgr)
                    canvas[:sh, :sw] = resized
                    score = _ncc(tpl_bgr, canvas)
                    if score > best:
                        best = score
            continue
        resized = cv2.resize(tpl_bgr, (nw, nh), interpolation=cv2.INTER_AREA)
        score = _ncc(probe_bgr, resized)
        if score > best:
            best = score
    return float(best)


def _ncc(hay_bgr: np.ndarray, needle_bgr: np.ndarray) -> float:
    hh, hw = hay_bgr.shape[:2]
    nh, nw = needle_bgr.shape[:2]
    if nh > hh or nw > hw or nh < 8 or nw < 8:
        return 0.0
    result = cv2.matchTemplate(hay_bgr, needle_bgr, cv2.TM_CCOEFF_NORMED)
    return float(result.max()) if result.size else 0.0
