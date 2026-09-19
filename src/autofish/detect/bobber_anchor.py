"""锚漂识别器：独立 find_bobber 定漂 → 同高由内向外彩色端帽定条。"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc

from autofish.detect.bobber import BobberHit, pixel_to_pos
from autofish.detect.find_bobber import FindBobber
from common.paths import assets_dir

_ASSET_DIR = assets_dir() / "bobber_anchor"
_DEFAULT_ENDCAP_L = _ASSET_DIR / "endcap_left_full.png"
_DEFAULT_ENDCAP_R = _ASSET_DIR / "endcap_right_full.png"
_FALLBACK_ENDCAP_L = _ASSET_DIR / "endcap_left.png"
_FALLBACK_ENDCAP_R = _ASSET_DIR / "endcap_right.png"
# CCOEFF 彩色分；配合橘黄软权重
_ENDCAP_MIN_SCORE = 0.42
_ENDCAP_MIN_ORANGE = 0.12


def _resolve_endcap(preferred: Path, fallback: Path) -> Path:
    if preferred.is_file():
        return preferred
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(f"bobber_anchor 端帽不存在: {preferred} / {fallback}")


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
    n: int = 4,
) -> list[tuple[float, int, int, int, int]]:
    """彩色 TM_CCOEFF_NORMED + 掩膜。"""
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


def _orange_soft(
    rgb: np.ndarray, x: int, y: int, w: int, h: int
) -> tuple[float, float]:
    """橘黄占比软权重（不否决，只乘到 rank）。返回 (weight, frac)。"""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(rgb.shape[1], x + w), min(rgb.shape[0], y + h)
    patch = rgb[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.82, 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
    hh, ss, vv = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    r, g, b = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
    m = ((hh <= 25) | (hh >= 160)) & (ss > 70) & (vv > 70) & (r > g) & (r > b)
    frac = float(m.mean())
    return 0.82 + 0.18 * min(1.0, frac / 0.12), frac


class BobberAnchorDetector:
    """先漂后条：FindBobber 定锚，彩色端帽由内向外定边界。"""

    name = "bobber_anchor"

    def __init__(
        self,
        bobber_path: str | Path | None = None,
        endcap_left_path: str | Path | None = None,
        endcap_right_path: str | Path | None = None,
        *,
        endcap_min_score: float = _ENDCAP_MIN_SCORE,
        endcap_min_orange: float = _ENDCAP_MIN_ORANGE,
        find_bobber: FindBobber | None = None,
    ) -> None:
        if endcap_left_path is None:
            left_p = _resolve_endcap(_DEFAULT_ENDCAP_L, _FALLBACK_ENDCAP_L)
        else:
            left_p = Path(endcap_left_path)
        if endcap_right_path is None:
            right_p = _resolve_endcap(_DEFAULT_ENDCAP_R, _FALLBACK_ENDCAP_R)
        else:
            right_p = Path(endcap_right_path)
        for p in (left_p, right_p):
            if not p.is_file():
                raise FileNotFoundError(f"bobber_anchor 资源不存在: {p}")
        self._finder = find_bobber or FindBobber(bobber_path)
        self._el_rgb, self._el_a = _load_rgb_alpha(left_p)
        self._er_rgb, self._er_a = _load_rgb_alpha(right_p)
        self.endcap_left_path = left_p
        self.endcap_right_path = right_p
        self.endcap_min_score = float(endcap_min_score)
        self.endcap_min_orange = float(endcap_min_orange)
        self._el_cache: dict[float, tuple[np.ndarray, np.ndarray]] = {}
        self._er_cache: dict[float, tuple[np.ndarray, np.ndarray]] = {}

    def _end_tpl(self, side: str, scale: float) -> tuple[np.ndarray, np.ndarray]:
        cache = self._el_cache if side == "L" else self._er_cache
        src = self._el_rgb if side == "L" else self._er_rgb
        src_a = self._el_a if side == "L" else self._er_a
        if scale not in cache:
            tw = max(8, int(round(src.shape[1] * scale)))
            th = max(6, int(round(src.shape[0] * scale)))
            cache[scale] = _resize_pair(src, src_a, tw, th)
        return cache[scale]

    def _find_endcap(
        self,
        rgb: np.ndarray,
        *,
        side: str,
        cx: float,
        cy: float,
        bh: int,
    ) -> tuple[float, int, int, int, int] | None:
        """返回 (rank, ax, ay, w, h)；轴对齐框；bar 外沿由调用方取 L 的 ax / R 的 ax+w。"""
        src = self._el_rgb if side == "L" else self._er_rgb
        s_nom = (bh * 1.15) / float(src.shape[0])
        scales = sorted(
            (
                float(s)
                for s in np.linspace(max(0.10, s_nom * 0.78), s_nom * 1.22, 3)
            ),
            key=lambda s: abs(s - s_nom),
        )
        max_half = min(max(180.0, bh * 11.0), 400.0)
        thr = self.endcap_min_score - 0.08
        # (dist, -rank, sc, rank, ax, ay, w, h, orange_frac)
        cands: list[tuple[float, float, float, float, int, int, int, int, float]] = []
        for scale in scales:
            tpl, mask = self._end_tpl(side, float(scale))
            th, tw = tpl.shape[:2]
            y0 = max(0, int(cy - th * 0.65))
            y1 = min(rgb.shape[0], int(cy + th * 0.65))
            if side == "L":
                x0 = max(0, int(cx - max_half))
                x1 = max(tw + 2, int(cx - 2))
            else:
                x0 = min(rgb.shape[1] - 1, int(cx + 2))
                x1 = min(rgb.shape[1], int(cx + max_half))
            if y1 - y0 <= th or x1 - x0 <= tw:
                continue
            roi = np.ascontiguousarray(rgb[y0:y1, x0:x1])
            for sc, x, y, w, h in _match_peaks(roi, tpl, mask, thr=thr, n=3):
                ax, ay = x + x0, y + y0
                if abs((ay + h * 0.5) - cy) > max(14.0, bh * 0.6):
                    continue
                soft, frac = _orange_soft(rgb, ax, ay, w, h)
                rank = sc * soft
                if side == "L":
                    dist = cx - (ax + w)
                else:
                    dist = ax - cx
                if dist <= 0:
                    continue
                cands.append((dist, -rank, sc, rank, ax, ay, w, h, frac))
                # 近侧已过门槛则可提前结束该尺度扫峰
                if dist < bh * 4 and rank >= self.endcap_min_score and frac >= self.endcap_min_orange:
                    break
            # 若已有很近且合格的候选，不必再更大尺度空扫太远
            if any(
                c[0] < bh * 3.5 and c[3] >= self.endcap_min_score and c[8] >= self.endcap_min_orange
                for c in cands
            ):
                break

        cands.sort(key=lambda c: (c[0], c[1]))
        for dist, _nr, sc, rank, ax, ay, w, h, frac in cands:
            if rank >= self.endcap_min_score and frac >= self.endcap_min_orange:
                return (rank, ax, ay, w, h)
        # 兜底：近侧候选里 rank 最高（仍要求有一点橘）
        ok = [c for c in cands if c[8] >= self.endcap_min_orange * 0.5]
        if not ok:
            return None
        best = max(ok, key=lambda c: c[3])
        if best[3] < self.endcap_min_score - 0.05:
            return None
        return (best[3], best[4], best[5], best[6], best[7])

    def find_bar(self, rgb: np.ndarray) -> tuple[int, int, int, int] | None:
        hit = self.detect(rgb)
        if hit is None:
            return None
        return (
            int(hit.bar_left),
            int(hit.bar_top),
            int(hit.bar_width),
            int(hit.bar_height),
        )

    def detect(self, rgb: np.ndarray) -> BobberHit | None:
        t0 = time.perf_counter()
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            return None
        loc = self._finder.find(rgb)
        if loc is None:
            return None
        cx, cy = loc.x, loc.y
        body_h = loc.body_height
        left = self._find_endcap(rgb, side="L", cx=cx, cy=cy, bh=body_h)
        right = self._find_endcap(rgb, side="R", cx=cx, cy=cy, bh=body_h)
        if left is None or right is None:
            return None
        x0 = left[1]
        x1 = right[1] + right[3]
        if not (x0 < cx < x1):
            return None
        bar_w = x1 - x0
        if bar_w < max(80, loc.width * 2.5):
            return None
        aspect = bar_w / max(1.0, (left[4] + right[4]) * 0.5)
        if aspect < 3.5 or aspect > 22.0:
            return None
        yb = min(left[2], right[2])
        hh = max(left[2] + left[4], right[2] + right[4]) - yb
        pos = pixel_to_pos(cx - x0, int(bar_w))
        dt = (time.perf_counter() - t0) * 1000.0
        return BobberHit(
            pos=float(pos),
            x=float(cx),
            y=float(cy),
            pixel_count=int(loc.width * loc.height),
            bar_left=float(x0),
            bar_top=float(yb),
            bar_width=float(bar_w),
            bar_height=float(hh),
            score=float(loc.score),
            detect_ms=float(dt),
        )
