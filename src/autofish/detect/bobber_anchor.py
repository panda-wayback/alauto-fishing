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
from autofish.detect.find_bobber import (
    BODY_Y0,
    BODY_Y1,
    FindBobber,
    fit_detect_frame,
    scale_box,
)
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
        # 程序锁 / 手动条界：(left, top, width, height)；手动优先
        self._locked_bar: tuple[float, float, float, float] | None = None
        self._manual_bar: tuple[float, float, float, float] | None = None
        self._program_bar: tuple[float, float, float, float] | None = None
        self._follow_scale: float | None = None
        self._follow_xy: tuple[float, float] | None = None
        self._recover_tick: int = 0
        # 预热端帽常见尺度，减轻首次定界尖峰
        for s in (0.20, 0.28, 0.36, 0.48):
            self._end_tpl("L", float(s))
            self._end_tpl("R", float(s))

    def clear_bar_lock(self) -> None:
        """ROI 变更 / 重框时丢弃程序锁定（监控开关不调用；手动界由壳另行处理）。"""
        self._locked_bar = None
        self._program_bar = None
        self._follow_scale = None
        self._follow_xy = None
        self._recover_tick = 0
        self._finder.clear_locked_scale()

    def set_manual_bar(
        self, box: tuple[float, float, float, float] | None
    ) -> None:
        """设置/清除手动条界（left, top, width, height）；有则永不跑端帽。"""
        self._manual_bar = box
        if box is None:
            self._follow_scale = None
            self._follow_xy = None
            self._recover_tick = 0
            self._finder.clear_locked_scale()

    @property
    def bar_locked(self) -> bool:
        return self._locked_bar is not None or self._manual_bar is not None

    @property
    def manual_bar(self) -> tuple[float, float, float, float] | None:
        return self._manual_bar

    @property
    def program_bar(self) -> tuple[float, float, float, float] | None:
        return self._program_bar

    def _remember_scale(self, loc) -> None:
        tw = float(self._finder._rgb.shape[1])
        if tw > 0 and loc.width > 0:
            self._follow_scale = float(loc.width) / tw
            self._finder.lock_scale(self._follow_scale)
        self._follow_xy = (float(loc.x), float(loc.y))
        self._recover_tick = 0

    def _scale_hint_from_bar(
        self, bar: tuple[float, float, float, float]
    ) -> float:
        """用条高估漂尺度。禁止用邻域高（含羽冠 pad 会虚高到 0.5+）。"""
        body_frac = max(0.35, BODY_Y1 - BODY_Y0)
        tpl_h = float(self._finder._rgb.shape[0])
        raw = (float(bar[3]) / body_frac) / max(1.0, tpl_h)
        return float(np.clip(raw, 0.12, 1.0))

    def _bar_neighborhood(
        self, bar: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        """整条邻域：左右略扩；底贴条底，仅向上留羽冠容差。"""
        left, top, bw, bh = bar
        y_pad = max(20.0, bh * 1.0)
        return (left - 4.0, top - y_pad, bw + 8.0, bh + y_pad)

    def _follow_y_span(
        self,
        bar: tuple[float, float, float, float],
        *,
        up: float,
    ) -> tuple[float, float]:
        """跟漂竖直范围：底=条底，顶不超过漂心−up，且至少高出条顶一截。"""
        _left, top, _bw, bh = bar
        bar_bottom = top + bh
        assert self._follow_xy is not None
        _cx, cy = self._follow_xy
        y0 = min(cy - up, top - max(16.0, bh * 0.4))
        min_h = max(20.0, bh + max(20.0, bh * 0.5))
        if bar_bottom - y0 < min_h:
            y0 = bar_bottom - min_h
        return y0, bar_bottom

    def _intersect_box(
        self,
        box: tuple[float, float, float, float],
        limit: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float] | None:
        """box 与 limit 求交；过小则 None。保证 mid 不超出 full-nbr。"""
        ax, ay, aw, ah = box
        bx, by, bw, bh = limit
        x0 = max(ax, bx)
        y0 = max(ay, by)
        x1 = min(ax + aw, bx + bw)
        y1 = min(ay + ah, by + bh)
        if x1 - x0 < 28 or y1 - y0 < 20:
            return None
        return (x0, y0, x1 - x0, y1 - y0)

    def _follow_x_span(
        self,
        bar: tuple[float, float, float, float],
        *,
        target_w: float,
        x_limit: tuple[float, float],
    ) -> tuple[float, float] | None:
        """水平跟窗：目标宽度；限制在 [x_lo,x_hi] 内，靠边向内平移保宽。"""
        if self._follow_xy is None:
            return None
        cx, _cy = self._follow_xy
        x_lo, x_hi = x_limit
        span = max(28.0, x_hi - x_lo)
        tw = float(np.clip(target_w, 28.0, span))
        x0 = cx - tw * 0.5
        x1 = cx + tw * 0.5
        if x0 < x_lo:
            x0 = x_lo
            x1 = x_lo + tw
        if x1 > x_hi:
            x1 = x_hi
            x0 = x1 - tw
        x0 = max(x_lo, x0)
        x1 = min(x_hi, x1)
        if x1 - x0 < 28:
            return None
        return x0, x1

    def _mid_follow_box(
        self, bar: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        """中等跟窗：水平≈条长 1/2；底贴条底、只向上扩；长宽夹在 full-nbr 内。"""
        full = self._bar_neighborhood(bar)
        if self._follow_xy is None:
            return full
        _left, _top, bw, bh = bar
        fx, fy, fw, fh = full
        xs = self._follow_x_span(
            bar, target_w=bw / 2.0, x_limit=(fx, fx + fw)
        )
        if xs is None:
            return full
        x0, x1 = xs
        up = max(48.0, bh * 1.8)
        y0, y1 = self._follow_y_span(bar, up=up)
        mid = (x0, y0, x1 - x0, y1 - y0)
        clipped = self._intersect_box(mid, full)
        return clipped if clipped is not None else full

    def _hit_from_bar(
        self,
        loc,
        *,
        x0: float,
        yb: float,
        bar_w: float,
        hh: float,
        t0: float,
    ) -> BobberHit | None:
        cx, cy = loc.x, loc.y
        if not (x0 < cx < x0 + bar_w):
            return None
        # 纵向也须落在条带容差内（避免技能栏上方人物同 X 假命中）
        y_pad = max(16.0, hh * 1.2, loc.height * 0.35)
        if not (yb - y_pad <= cy <= yb + hh + y_pad):
            return None
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

    def _active_bar(self) -> tuple[float, float, float, float] | None:
        if self._manual_bar is not None:
            return self._manual_bar
        return self._locked_bar

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

    def _bobber_only_hit(self, loc, *, t0: float) -> BobberHit:
        """有漂无条：供壳画漂 / 出参考图；pos 由工人置空，不进策略。"""
        dt = (time.perf_counter() - t0) * 1000.0
        return BobberHit(
            pos=0.0,
            x=float(loc.x),
            y=float(loc.y),
            pixel_count=int(loc.width * loc.height),
            bar_left=0.0,
            bar_top=0.0,
            bar_width=0.0,
            bar_height=0.0,
            score=float(loc.score),
            detect_ms=float(dt),
        )

    def find_bar(self, rgb: np.ndarray) -> tuple[int, int, int, int] | None:
        hit = self.detect(rgb)
        if hit is None or hit.bar_width <= 0:
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
        work, sf = fit_detect_frame(rgb)
        inv = 1.0 / sf
        active_o = self._active_bar()
        active = scale_box(active_o, sf) if active_o is not None else None
        follow_o = self._follow_xy
        if follow_o is not None:
            self._follow_xy = (follow_o[0] * sf, follow_o[1] * sf)
        locked_before = self._locked_bar
        try:
            hit = self._detect_work(work, active, t0=t0)
        finally:
            if self._follow_xy is not None:
                self._follow_xy = (
                    self._follow_xy[0] * inv,
                    self._follow_xy[1] * inv,
                )
        # 本帧新锁的条界在工作图坐标 → 映回原图存盘
        if (
            self._locked_bar is not None
            and self._locked_bar is not locked_before
            and abs(inv - 1.0) >= 1e-9
        ):
            self._locked_bar = scale_box(self._locked_bar, inv)
            self._program_bar = (
                scale_box(self._program_bar, inv)
                if self._program_bar is not None
                else None
            )
        if hit is None or abs(inv - 1.0) < 1e-9:
            return hit
        return BobberHit(
            pos=hit.pos,
            x=hit.x * inv,
            y=hit.y * inv,
            pixel_count=hit.pixel_count,
            bar_left=hit.bar_left * inv,
            bar_top=hit.bar_top * inv,
            bar_width=hit.bar_width * inv,
            bar_height=hit.bar_height * inv,
            score=hit.score,
            detect_ms=hit.detect_ms,
        )

    def _detect_work(
        self,
        rgb: np.ndarray,
        active: tuple[float, float, float, float] | None,
        *,
        t0: float,
    ) -> BobberHit | None:
        """在已压入 1000×1000 的工作图上识别；条界/跟点均为工作图坐标。"""
        if active is not None:
            hint = self._follow_scale
            if hint is None:
                hint = self._scale_hint_from_bar(active)
            if self._follow_xy is None:
                # 无跟点：隔帧扫整条邻域，空窗期不打满 CPU
                self._recover_tick += 1
                if self._recover_tick % 2 == 0:
                    return None
                loc = self._finder.find(
                    rgb,
                    search_box=self._bar_neighborhood(active),
                    scale_hint=hint,
                )
            else:
                # 只扫 mid；禁止同帧再扫 full-nbr（重钓尖峰）
                loc = self._finder.find(
                    rgb,
                    search_box=self._mid_follow_box(active),
                    scale_hint=hint,
                )
                if loc is None:
                    self._follow_xy = None
                    self._recover_tick = 0
                    return None
            if loc is None:
                return None
            hit = self._hit_from_bar(
                loc,
                x0=active[0],
                yb=active[1],
                bar_w=active[2],
                hh=active[3],
                t0=t0,
            )
            if hit is not None:
                self._remember_scale(loc)
                return hit
            # 有条锁但漂出条：仍回报漂位，不算 pos
            self._remember_scale(loc)
            return self._bobber_only_hit(loc, t0=t0)
        loc = self._finder.find(rgb)
        if loc is None:
            return None
        cx, cy = loc.x, loc.y
        body_h = loc.body_height
        left = self._find_endcap(rgb, side="L", cx=cx, cy=cy, bh=body_h)
        right = self._find_endcap(rgb, side="R", cx=cx, cy=cy, bh=body_h)
        if left is None or right is None:
            return self._bobber_only_hit(loc, t0=t0)
        x0 = float(left[1])
        x1 = float(right[1] + right[3])
        if not (x0 < cx < x1):
            return self._bobber_only_hit(loc, t0=t0)
        bar_w = x1 - x0
        if bar_w < max(80, loc.width * 2.5):
            return self._bobber_only_hit(loc, t0=t0)
        aspect = bar_w / max(1.0, (left[4] + right[4]) * 0.5)
        if aspect < 3.5 or aspect > 22.0:
            return self._bobber_only_hit(loc, t0=t0)
        yb = float(min(left[2], right[2]))
        hh = float(max(left[2] + left[4], right[2] + right[4]) - yb)
        hit = self._hit_from_bar(loc, x0=x0, yb=yb, bar_w=bar_w, hh=hh, t0=t0)
        if hit is not None:
            # 工作图条界 → 存原图坐标（detect 出口按 inv 映回 hit；锁存须原图）
            # 此处仍在工作图；外层 detect 用 sf 映回前先写入工作坐标，再换算
            box = (x0, yb, bar_w, hh)
            self._locked_bar = box
            self._program_bar = box
            self._remember_scale(loc)
            return hit
        return self._bobber_only_hit(loc, t0=t0)
