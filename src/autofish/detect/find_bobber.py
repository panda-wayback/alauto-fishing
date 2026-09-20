"""独立 CV 找漂：颜色结构候选 + 小 ROI 彩色模板复核；不定条、不算 pos。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc

from common.paths import assets_dir

_ASSET_DIR = assets_dir() / "bobber_anchor"
_DEFAULT_BOBBER = _ASSET_DIR / "bobber.png"

# 识别入图上限（等比缩小，不放大）
DETECT_MAX_W = 800
DETECT_MAX_H = 800

# 相对完整漂 ≈119×172；小漂～偏大漂（含高分屏压图后仍偏大）
_SCALES = (
    0.14,
    0.16,
    0.20,
    0.24,
    0.28,
    0.32,
    0.40,
    0.48,
    0.56,
    0.64,
    0.72,
    0.80,
    0.88,
    1.00,
)
_MIN_SCORE = 0.48
_EDGE_FRAC = 0.05
_COLOR_SF = 0.5  # 颜色结构半分辨率
_MAX_SEEDS = 6
_EARLY_RANK = 0.85
_REFINE_NEAR = 7  # 种子估尺度后多试邻近档（防估偏）
_REFINE_FALLBACK = 11  # 无峰时再扩一圈
# 红箍连通域宽约为整漂宽的比例；估尺度时须除回，否则档位偏低
_BAND_WIDTH_FRAC = 0.55
# 接受门槛：宁可 miss，不可错识（分值为 CCOEFF）
_ACCEPT_MIN_SCORE = 0.55
_ACCEPT_MIN_RANK = 0.55
_ACCEPT_MIN_CREAM = 0.05
_ACCEPT_MIN_BAND = 0.20
_ACCEPT_MIN_PLUME = 0.04
_ACCEPT_MIN_MARGIN = 0.04
# 单候选时须更高分，避免人物/白布弱峰过线
_ACCEPT_SOLO_SCORE = 0.68
BODY_Y0 = 0.42
BODY_Y1 = 0.98
# 条内搜：相对条高仅向上余量（羽冠高出条；底贴条底，不向下扩）
_BAR_Y_PAD_FRAC = 1.0
_BAR_Y_PAD_MIN = 20
_BAR_X_PAD = 4
_BAR_SCALE_NEAR = 5  # 条内跟漂邻近尺度档


def fit_detect_frame(
    rgb: np.ndarray,
    *,
    max_w: int = DETECT_MAX_W,
    max_h: int = DETECT_MAX_H,
) -> tuple[np.ndarray, float]:
    """等比压入 max_w×max_h；返回 (工作图, 工作/原图 比例)。已在限内则 sf=1。"""
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        return rgb, 1.0
    h, w = rgb.shape[:2]
    if w <= 0 or h <= 0:
        return rgb, 1.0
    sf = min(float(max_w) / float(w), float(max_h) / float(h), 1.0)
    if sf >= 1.0 - 1e-9:
        return np.ascontiguousarray(rgb), 1.0
    nw = max(1, int(round(w * sf)))
    nh = max(1, int(round(h * sf)))
    work = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(work), float(sf)


def scale_box(
    box: tuple[float, float, float, float], sf: float
) -> tuple[float, float, float, float]:
    l, t, w, h = box
    return (l * sf, t * sf, w * sf, h * sf)


def _neighbor_scales(scale_est: float, n: int = _REFINE_NEAR) -> tuple[float, ...]:
    est = float(np.clip(scale_est, _SCALES[0], _SCALES[-1]))
    return tuple(sorted(_SCALES, key=lambda s: abs(s - est))[:n])


def _clamp_box(
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    iw: int,
    ih: int,
) -> tuple[int, int, int, int] | None:
    x0 = int(max(0, min(iw - 1, round(left))))
    y0 = int(max(0, min(ih - 1, round(top))))
    x1 = int(max(0, min(iw, round(left + width))))
    y1 = int(max(0, min(ih, round(top + height))))
    if x1 - x0 < 16 or y1 - y0 < 12:
        return None
    return x0, y0, x1 - x0, y1 - y0


def bar_search_box(
    bar: tuple[float, float, float, float],
    *,
    iw: int,
    ih: int,
) -> tuple[int, int, int, int] | None:
    """条框 → 找漂搜区（左右夹条内；底贴条底，仅向上留羽冠余量）。"""
    left, top, bw, bh = bar
    y_pad = max(_BAR_Y_PAD_MIN, int(bh * _BAR_Y_PAD_FRAC))
    return _clamp_box(
        left - _BAR_X_PAD,
        top - y_pad,
        bw + 2 * _BAR_X_PAD,
        bh + y_pad,
        iw=iw,
        ih=ih,
    )


@dataclass(frozen=True)
class BobberLoc:
    """仅漂位置；无条框、无 pos。"""

    x: float
    y: float
    left: int
    top: int
    width: int
    height: int
    score: float  # 彩色模板分
    rank: float  # 彩色分 × 结构软权重
    cream: float
    band: float
    plume: float = 0.0
    detect_ms: float = 0.0

    @property
    def body_height(self) -> int:
        return max(8, int(self.height * (BODY_Y1 - BODY_Y0)))


def _map_loc(loc: BobberLoc, inv_sf: float) -> BobberLoc:
    """工作图坐标 → 原图。"""
    if abs(inv_sf - 1.0) < 1e-9:
        return loc
    return BobberLoc(
        x=loc.x * inv_sf,
        y=loc.y * inv_sf,
        left=int(round(loc.left * inv_sf)),
        top=int(round(loc.top * inv_sf)),
        width=max(1, int(round(loc.width * inv_sf))),
        height=max(1, int(round(loc.height * inv_sf))),
        score=loc.score,
        rank=loc.rank,
        cream=loc.cream,
        band=loc.band,
        plume=loc.plume,
        detect_ms=loc.detect_ms,
    )


def _load_rgb_alpha(path: Path) -> tuple[np.ndarray, np.ndarray]:
    bgr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if bgr is None:
        raise FileNotFoundError(f"无法读取模板: {path}")
    if bgr.ndim == 2:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_GRAY2RGB)
        return rgb, np.full(bgr.shape, 255, np.uint8)
    if bgr.shape[2] == 4:
        rgba = cv2.cvtColor(bgr, cv2.COLOR_BGRA2RGBA)
    else:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        rgba = np.dstack([rgb, np.full(rgb.shape[:2], 255, np.uint8)])
    return rgba[:, :, :3].copy(), rgba[:, :, 3].copy()


def _resize_pair(
    rgb: np.ndarray, alpha: np.ndarray, tw: int, th: int
) -> tuple[np.ndarray, np.ndarray]:
    r = cv2.resize(rgb, (tw, th), interpolation=cv2.INTER_AREA)
    a = cv2.resize(alpha, (tw, th), interpolation=cv2.INTER_NEAREST)
    return r, a


def _match_peaks(
    img: np.ndarray,
    tpl: np.ndarray,
    mask: np.ndarray,
    *,
    thr: float,
    n: int = 3,
) -> list[tuple[float, int, int, int, int]]:
    """彩色图 TM_CCOEFF_NORMED + 掩膜。"""
    if tpl.shape[0] >= img.shape[0] or tpl.shape[1] >= img.shape[1]:
        return []
    res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED, mask=mask)
    res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
    res = np.clip(res, -1.0, 1.0)
    out: list[tuple[float, int, int, int, int]] = []
    work = res.copy()
    th, tw = tpl.shape[:2]
    for _ in range(n):
        _mn, mv, _ml, ml = cv2.minMaxLoc(work)
        if float(mv) < thr:
            break
        x, y = int(ml[0]), int(ml[1])
        out.append((float(mv), x, y, tw, th))
        y0 = max(0, y - th // 2)
        x0 = max(0, x - tw // 2)
        work[y0 : y + th // 2 + 1, x0 : x + tw // 2 + 1] = -1.0
    return out


def _structure(
    rgb: np.ndarray, x: int, y: int, w: int, h: int
) -> tuple[float, float, float]:
    """(cream, band, plume)。"""
    if w < 3 or h < 8:
        return 0.0, 0.0, 0.0
    y_body = y + int(h * BODY_Y0)
    h_body = max(4, int(h * (BODY_Y1 - BODY_Y0)))
    x0, y0 = max(0, x), max(0, y_body)
    x1, y1 = min(rgb.shape[1], x + w), min(rgb.shape[0], y_body + h_body)
    body = rgb[y0:y1, x0:x1]
    if body.size == 0:
        return 0.0, 0.0, 0.0
    band_h = max(2, int(body.shape[0] * 0.55))
    band_patch = body[:band_h]
    hsv = cv2.cvtColor(body, cv2.COLOR_RGB2HSV)
    hsv_b = cv2.cvtColor(band_patch, cv2.COLOR_RGB2HSV)
    ss = hsv[:, :, 1]
    hb, sb, vb = hsv_b[:, :, 0], hsv_b[:, :, 1], hsv_b[:, :, 2]
    red = ((hb <= 10) | (hb >= 170)) & (sb > 70) & (vb > 70)
    cream = (
        (body[:, :, 0] > 145)
        & (body[:, :, 1] > 120)
        & (body[:, :, 2] > 85)
        & (ss < 160)
    )
    band = float(red.mean(axis=1).max()) if red.size else 0.0
    y_p1 = min(rgb.shape[0], y + max(4, int(h * BODY_Y0)))
    plume_r = rgb[max(0, y) : y_p1, max(0, x) : min(rgb.shape[1], x + w)]
    plume = 0.0
    if plume_r.size:
        hp = cv2.cvtColor(plume_r, cv2.COLOR_RGB2HSV)
        plume_m = ((hp[:, :, 0] <= 25) | (hp[:, :, 0] >= 160)) & (
            hp[:, :, 1] > 60
        ) & (hp[:, :, 2] > 80)
        plume = float(plume_m.mean())
    return float(cream.mean()), band, plume


def _salience(cream: float, band: float, plume: float) -> float:
    """结构软权重：缺羽冠/红箍明显降权（挡人物白布、技能栏）。"""
    if plume < _ACCEPT_MIN_PLUME:
        return 0.55
    if cream < 0.02 and band < 0.15:
        plume = min(plume, 0.08)
    body_ok = min(1.0, cream / 0.10) * 0.40 + min(1.0, max(0.0, band) / 0.25) * 0.45
    plume_ok = min(1.0, plume / 0.12)
    return 0.70 + 0.18 * body_ok + 0.12 * plume_ok


def _color_seeds(
    rgb: np.ndarray,
    *,
    max_n: int = _MAX_SEEDS,
    edge_frac: float = _EDGE_FRAC,
    color_sf: float = _COLOR_SF,
) -> list[tuple[float, int, int, int, int]]:
    """半分辨率：红箍薄条 + 上方橘羽 / 下方亮肚 → 少量候选 (score, cx, top, bw, est_h)。"""
    h_img, w_img = rgb.shape[:2]
    x0 = int(w_img * edge_frac)
    x1 = int(w_img * (1.0 - edge_frac))
    y0 = int(h_img * edge_frac)
    y1 = int(h_img * (1.0 - edge_frac))
    if x1 - x0 < 40 or y1 - y0 < 40:
        return []
    sub = rgb[y0:y1, x0:x1]
    sf = float(color_sf)
    sw = max(8, int(round(sub.shape[1] * sf)))
    sh = max(8, int(round(sub.shape[0] * sf)))
    small = cv2.resize(sub, (sw, sh), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    hh, ss, vv = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    r, g, b = small[:, :, 0], small[:, :, 1], small[:, :, 2]
    red = (((hh <= 15) | (hh >= 165)) & (ss > 70) & (vv > 55) & (r > 60)).astype(
        np.uint8
    )
    # 小半分辨率图用更细开运算，避免细红箍被抹掉
    open_w = 3 if min(sw, sh) < 220 else 5
    red = cv2.morphologyEx(
        red, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (open_w, 1))
    )
    red = cv2.morphologyEx(
        red, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    )
    n_cc, _lab, stats, _cent = cv2.connectedComponentsWithStats(red, 8)
    orange = (
        ((hh <= 26) | (hh >= 158)) & (ss > 70) & (vv > 75) & (r > g) & (r > b)
    ).astype(np.uint8)
    bright = ((vv > 105) & (r > 95) & (g > 85) & (ss < 175)).astype(np.uint8)
    cands: list[tuple[float, int, int, int, int]] = []
    for i in range(1, n_cc):
        area = int(stats[i, cv2.CC_STAT_AREA])
        bx = int(stats[i, cv2.CC_STAT_LEFT])
        by = int(stats[i, cv2.CC_STAT_TOP])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        if area < 5 or area > 450:
            continue
        if bw < 4 or bw > 45 or bh < 1 or bh > 16:
            continue
        if bw < bh * 1.05:
            continue
        cx = bx + bw // 2
        bw_full = int(round(bw / sf))
        est_h = int(np.clip(bw_full / 0.55, 28, 110))
        plume_h = max(4, int(est_h * BODY_Y0 * sf))
        body_h = max(6, int(est_h * (BODY_Y1 - BODY_Y0) * sf))
        py0 = max(0, by - plume_h)
        py1 = by
        by0 = by + bh
        by1 = min(small.shape[0], by0 + body_h)
        px0 = max(0, cx - max(bw, 6) // 2 - 1)
        px1 = min(small.shape[1], cx + max(bw, 6) // 2 + 1)
        if py1 <= py0 or by1 <= by0:
            continue
        plume_d = float(orange[py0:py1, px0:px1].mean())
        bright_d = float(bright[by0:by1, px0:px1].mean())
        if plume_d < 0.06:
            continue
        if bright_d < 0.03 or bright_d > 0.95:
            continue
        if plume_d > 0.85 and bright_d > 0.70:
            continue
        band_fill = area / float(max(1, bw * bh))
        if band_fill < 0.14:
            continue
        plume_pref = 1.0 - min(1.0, abs(plume_d - 0.50) / 0.50)
        score = (
            min(plume_d, 0.75) * 0.25
            + bright_d * 0.20
            + band_fill * 0.15
            + min(1.0, bw_full / 48.0) * 0.20
            + max(0.0, plume_pref) * 0.20
        )
        top_full = int(round((by - plume_h) / sf)) + y0
        cx_full = int(round(cx / sf)) + x0
        cands.append((score, cx_full, top_full, bw_full, est_h))
    cands.sort(reverse=True)
    nms = 18 if min(sw, sh) < 220 else 30
    kept: list[tuple[float, int, int, int, int]] = []
    for c in cands:
        if any(abs(c[1] - k[1]) + abs(c[2] - k[2]) < nms for k in kept):
            continue
        kept.append(c)
        if len(kept) >= max_n:
            break
    return kept


class FindBobber:
    """独立 CV 找漂（颜色结构候选 + 彩色模板复核）。"""

    name = "find_bobber"

    def __init__(
        self,
        bobber_path: str | Path | None = None,
        *,
        min_score: float = _MIN_SCORE,
        accept_min_score: float = _ACCEPT_MIN_SCORE,
        accept_min_rank: float = _ACCEPT_MIN_RANK,
        accept_min_cream: float = _ACCEPT_MIN_CREAM,
        accept_min_band: float = _ACCEPT_MIN_BAND,
        accept_min_plume: float = _ACCEPT_MIN_PLUME,
        accept_min_margin: float = _ACCEPT_MIN_MARGIN,
        accept_solo_score: float = _ACCEPT_SOLO_SCORE,
    ) -> None:
        path = Path(bobber_path) if bobber_path else _DEFAULT_BOBBER
        if not path.is_file():
            raise FileNotFoundError(f"find_bobber 资源不存在: {path}")
        self._rgb, self._a = _load_rgb_alpha(path)
        self.bobber_path = path
        self.min_score = float(min_score)
        self.accept_min_score = float(accept_min_score)
        self.accept_min_rank = float(accept_min_rank)
        self.accept_min_cream = float(accept_min_cream)
        self.accept_min_band = float(accept_min_band)
        self.accept_min_plume = float(accept_min_plume)
        self.accept_min_margin = float(accept_min_margin)
        self.accept_solo_score = float(accept_solo_score)
        self._cache: dict[float, tuple[np.ndarray, np.ndarray]] = {}
        self._locked_scale: float | None = None  # 命中后固定档（相对模板）
        # 预热常用尺度，避免首帧 resize 尖峰
        for s in _SCALES:
            self._tpl(float(s))

    def lock_scale(self, scale: float | None) -> None:
        """固定/清除后续复核优先档。"""
        if scale is None or scale <= 0:
            self._locked_scale = None
            return
        self._locked_scale = float(np.clip(scale, _SCALES[0], _SCALES[-1]))

    def clear_locked_scale(self) -> None:
        self._locked_scale = None

    def _tpl(self, scale: float) -> tuple[np.ndarray, np.ndarray]:
        if scale not in self._cache:
            tw = max(3, int(round(self._rgb.shape[1] * scale)))
            th = max(3, int(round(self._rgb.shape[0] * scale)))
            self._cache[scale] = _resize_pair(self._rgb, self._a, tw, th)
        return self._cache[scale]

    def _accept(self, best: BobberLoc, second: BobberLoc | None) -> bool:
        """不够确信 → 拒绝（宁可 None）。"""
        if best.score < self.accept_min_score:
            return False
        if best.rank < self.accept_min_rank:
            return False
        if best.plume < self.accept_min_plume:
            return False
        if best.band < self.accept_min_band and best.cream < self.accept_min_cream:
            return False
        if best.cream < self.accept_min_cream and best.band < 0.35:
            return False
        # 高 cream + 高 band 但羽冠弱 → 典型肤色/白布假阳
        if best.cream >= 0.35 and best.band >= 0.50 and best.plume < 0.08:
            return False
        if best.cream >= 0.12 and best.rank >= 0.75 and best.score >= 0.72:
            return True
        if second is None:
            return best.score >= self.accept_solo_score
        if best.rank - second.rank < self.accept_min_margin:
            if best.cream - second.cream < 0.04 and best.band - second.band < 0.1:
                return False
        return True

    def find(
        self,
        rgb: np.ndarray,
        *,
        search_box: tuple[float, float, float, float] | None = None,
        scale_hint: float | None = None,
    ) -> BobberLoc | None:
        """找一个最佳漂；search_box=(l,t,w,h) 时只在条邻域搜。不够确信返回 None。"""
        t0 = time.perf_counter()
        hint = scale_hint
        if hint is None and self._locked_scale is not None:
            hint = self._locked_scale
        cands = self.find_candidates(
            rgb, max_n=3, search_box=search_box, scale_hint=hint
        )
        dt = (time.perf_counter() - t0) * 1000.0
        if not cands:
            return None
        best = cands[0]
        second = cands[1] if len(cands) > 1 else None
        if not self._accept(best, second):
            return None
        # 命中后锁定档（相对模板宽）
        tw = float(self._rgb.shape[1])
        if tw > 0 and best.width > 0:
            self.lock_scale(float(best.width) / tw)
        return BobberLoc(
            x=best.x,
            y=best.y,
            left=best.left,
            top=best.top,
            width=best.width,
            height=best.height,
            score=best.score,
            rank=best.rank,
            cream=best.cream,
            band=best.band,
            plume=best.plume,
            detect_ms=float(dt),
        )

    def find_candidates(
        self,
        rgb: np.ndarray,
        *,
        max_n: int = 5,
        search_box: tuple[float, float, float, float] | None = None,
        scale_hint: float | None = None,
    ) -> list[BobberLoc]:
        """按 rank 降序返回至多 max_n 个漂候选。

        颜色结构挖种子 → 原图小 ROI 彩色模板复核。
        search_box 有则只在该邻域内搜（坐标映回调用方入图）。
        入图超出 DETECT_MAX_W×DETECT_MAX_H 时先等比缩小。
        """
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            return []
        work, sf = fit_detect_frame(rgb)
        inv = 1.0 / sf
        sb = scale_box(search_box, sf) if search_box is not None else None
        hint = (
            float(scale_hint) * sf
            if scale_hint is not None and scale_hint > 0 and sf < 1.0
            else scale_hint
        )
        kept = self._find_candidates_work(
            work, max_n=max_n, search_box=sb, scale_hint=hint
        )
        if abs(inv - 1.0) < 1e-9:
            return kept
        return [_map_loc(c, inv) for c in kept]

    def _find_candidates_work(
        self,
        rgb: np.ndarray,
        *,
        max_n: int = 5,
        search_box: tuple[float, float, float, float] | None = None,
        scale_hint: float | None = None,
    ) -> list[BobberLoc]:
        full = np.ascontiguousarray(rgb)
        ox = oy = 0
        img = full
        if search_box is not None:
            box = _clamp_box(
                float(search_box[0]),
                float(search_box[1]),
                float(search_box[2]),
                float(search_box[3]),
                iw=full.shape[1],
                ih=full.shape[0],
            )
            if box is None:
                return []
            ox, oy, rw, rh = box
            img = full[oy : oy + rh, ox : ox + rw]
            if img.shape[0] < 12 or img.shape[1] < 16:
                return []
        seeds = _color_seeds(img, max_n=_MAX_SEEDS)
        raw: list[BobberLoc] = []
        tpl_w = float(self._rgb.shape[1])
        tpl_h = float(self._rgb.shape[0])

        def _consider(
            sc: float, bx: int, by: int, w: int, h: int
        ) -> BobberLoc | None:
            cream, band, plume = _structure(full, bx, by, w, h)
            sal = _salience(cream, band, plume)
            rank = sc * sal
            return BobberLoc(
                x=float(bx + w * 0.5),
                y=float(by + h * ((BODY_Y0 + BODY_Y1) * 0.5)),
                left=bx,
                top=by,
                width=w,
                height=h,
                score=float(sc),
                rank=float(rank),
                cream=float(cream),
                band=float(band),
                plume=float(plume),
            )

        # 有条邻域：按尺度提示 / 锁定档 / 条高估档，多档模板扫
        if search_box is not None:
            if scale_hint is not None and scale_hint > 0:
                s_est = float(scale_hint)
            elif self._locked_scale is not None:
                s_est = float(self._locked_scale)
            else:
                body_frac = max(0.35, BODY_Y1 - BODY_Y0)
                s_est = (float(search_box[3]) / body_frac) / tpl_h
                # 邻域高常含羽冠 pad，按搜区短边封顶，避免尺度虚高
                s_cap = (min(img.shape[0], img.shape[1]) * 0.55) / tpl_h
                s_est = min(s_est, s_cap)
            scales = _neighbor_scales(s_est, n=_BAR_SCALE_NEAR)
            for scale in scales:
                tpl, mask = self._tpl(float(scale))
                for sc, x, y, w, h in _match_peaks(
                    img, tpl, mask, thr=self.min_score, n=1
                ):
                    hit = _consider(sc, x + ox, y + oy, w, h)
                    if hit is not None:
                        raw.append(hit)
            raw.sort(key=lambda c: (c.rank, c.score), reverse=True)
            kept: list[BobberLoc] = []
            for c in raw:
                if any(
                    abs(c.left - k.left) + abs(c.top - k.top)
                    < max(c.width, k.width) * 0.55
                    for k in kept
                ):
                    continue
                kept.append(c)
                if len(kept) >= max_n:
                    break
            return kept

        for _sc0, cx, top, bw, est_h in seeds:
            # 红箍宽 → 整漂尺度；有锁定档则优先锁定
            if self._locked_scale is not None:
                scale_est = float(self._locked_scale)
            elif scale_hint is not None and scale_hint > 0:
                scale_est = float(scale_hint)
            else:
                scale_est = (float(bw) / tpl_w) / _BAND_WIDTH_FRAC
            scale_est = float(np.clip(scale_est, _SCALES[0], _SCALES[-1]))
            est_tw = max(bw, int(round(tpl_w * scale_est)))
            est_th = max(est_h, int(round(tpl_h * scale_est)))
            half_w = max(40, est_tw // 2 + 28)
            x0 = max(0, cx - half_w)
            y0 = max(0, top - max(28, est_th // 4))
            x1 = min(img.shape[1], cx + half_w)
            y1 = min(img.shape[0], top + est_th + 40)
            roi = img[y0:y1, x0:x1]
            if roi.shape[0] < 12 or roi.shape[1] < 12:
                continue

            def _refine(n_near: int) -> BobberLoc | None:
                best_l: BobberLoc | None = None
                for scale in _neighbor_scales(scale_est, n=n_near):
                    tpl, mask = self._tpl(float(scale))
                    for sc, x, y, w, h in _match_peaks(
                        roi, tpl, mask, thr=self.min_score, n=1
                    ):
                        hit = _consider(sc, x + x0 + ox, y + y0 + oy, w, h)
                        if hit is not None and (
                            best_l is None or hit.rank > best_l.rank
                        ):
                            best_l = hit
                return best_l

            best = _refine(_REFINE_NEAR)
            if best is None:
                best = _refine(min(len(_SCALES), _REFINE_FALLBACK))
            if best is not None:
                raw.append(best)
                if best.rank >= _EARLY_RANK:
                    break
        raw.sort(key=lambda c: (c.rank, c.score), reverse=True)
        kept = []
        for c in raw:
            if any(
                abs(c.left - k.left) + abs(c.top - k.top)
                < max(c.width, k.width) * 0.55
                for k in kept
            ):
                continue
            kept.append(c)
            if len(kept) >= max_n:
                break
        return kept
