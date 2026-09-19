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

# 相对完整漂 ≈119×172；须覆盖手框小漂(~0.16)～常见中大档
_SCALES = (0.16, 0.20, 0.24, 0.28, 0.32, 0.40, 0.48, 0.56, 0.64)
_MIN_SCORE = 0.40
_EDGE_FRAC = 0.05
_COLOR_SF = 0.5  # 颜色结构半分辨率
_MAX_SEEDS = 6
_EARLY_RANK = 0.80
_REFINE_NEAR = 3  # 每个种子只跑最邻近的尺度档数
# 红箍连通域宽约为整漂宽的比例；估尺度时须除回，否则档位偏低
_BAND_WIDTH_FRAC = 0.55
# 接受门槛：宁可 miss，不可错识（分值为 CCOEFF）
_ACCEPT_MIN_SCORE = 0.42
_ACCEPT_MIN_RANK = 0.42
_ACCEPT_MIN_CREAM = 0.06
_ACCEPT_MIN_MARGIN = 0.03
BODY_Y0 = 0.42
BODY_Y1 = 0.98


def _neighbor_scales(scale_est: float, n: int = _REFINE_NEAR) -> tuple[float, ...]:
    est = float(np.clip(scale_est, _SCALES[0], _SCALES[-1]))
    return tuple(sorted(_SCALES, key=lambda s: abs(s - est))[:n])


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
    detect_ms: float = 0.0

    @property
    def body_height(self) -> int:
        return max(8, int(self.height * (BODY_Y1 - BODY_Y0)))


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
    """结构软权重：无红箍/羽冠的峰降权（挡顶栏噪声、端帽假峰）。"""
    if cream < 0.02 and band < 0.15:
        plume = min(plume, 0.08)
    body_ok = min(1.0, cream / 0.10) * 0.45 + min(1.0, max(0.0, band) / 0.25) * 0.55
    plume_ok = min(1.0, plume / 0.12)
    return 0.78 + 0.14 * body_ok + 0.08 * plume_ok


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
        accept_min_margin: float = _ACCEPT_MIN_MARGIN,
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
        self.accept_min_margin = float(accept_min_margin)
        self._cache: dict[float, tuple[np.ndarray, np.ndarray]] = {}

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
        if best.cream < self.accept_min_cream and best.band < 0.35:
            return False
        if best.cream >= 0.12 and best.rank >= 0.70 and best.score >= 0.70:
            return True
        if second is not None:
            if best.rank - second.rank < self.accept_min_margin:
                if best.cream - second.cream < 0.04 and best.band - second.band < 0.1:
                    return False
        return True

    def find(self, rgb: np.ndarray) -> BobberLoc | None:
        """全图找一个最佳漂；不够确信返回 None。"""
        t0 = time.perf_counter()
        cands = self.find_candidates(rgb, max_n=3)
        dt = (time.perf_counter() - t0) * 1000.0
        if not cands:
            return None
        best = cands[0]
        second = cands[1] if len(cands) > 1 else None
        if not self._accept(best, second):
            return None
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
            detect_ms=float(dt),
        )

    def find_candidates(
        self, rgb: np.ndarray, *, max_n: int = 5
    ) -> list[BobberLoc]:
        """按 rank 降序返回至多 max_n 个漂候选。

        颜色结构挖种子 → 原图小 ROI 彩色模板复核。
        """
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            return []
        img = np.ascontiguousarray(rgb)
        seeds = _color_seeds(img, max_n=_MAX_SEEDS)
        raw: list[BobberLoc] = []
        tpl_w = float(self._rgb.shape[1])
        tpl_h = float(self._rgb.shape[0])
        for _sc0, cx, top, bw, est_h in seeds:
            # 红箍宽 → 整漂尺度；ROI 按估模板尺寸留余量（羽冠 top 可能偏下）
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
            scales = _neighbor_scales(scale_est)
            best: BobberLoc | None = None
            for scale in scales:
                tpl, mask = self._tpl(float(scale))
                for sc, x, y, w, h in _match_peaks(
                    roi, tpl, mask, thr=self.min_score, n=1
                ):
                    bx, by = x + x0, y + y0
                    cream, band, plume = _structure(rgb, bx, by, w, h)
                    sal = _salience(cream, band, plume)
                    rank = sc * sal
                    hit = BobberLoc(
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
                    )
                    if best is None or rank > best.rank:
                        best = hit
            if best is not None:
                raw.append(best)
                if best.rank >= _EARLY_RANK:
                    break
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
