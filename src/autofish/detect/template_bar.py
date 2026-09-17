"""模板识别器：matchTemplate 定位张力条，带内找漂。"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc

from autofish.detect.bobber import BobberHit, bobber_in_bar
from common.paths import assets_dir

# 实机裁出的张力条（含两端端帽，已去漂）。模拟器条比例不同，禁止作默认。
_DEFAULT_TEMPLATE = assets_dir() / "tension_bar.live.png"

# 默认压缩 0.25 + 灰度 + 少量尺度：全图 ~10–15 ms，跟踪 ~0.5–1 ms
_DEFAULT_SCALE_FACTOR = 0.25
_DEFAULT_SCALES = tuple(round(x, 2) for x in (0.75, 0.82, 0.88, 0.94, 1.0, 1.08, 1.15))
_DEFAULT_TRACK_MARGIN = 10  # 压缩后像素


class TemplateBarDetector:
    """压缩灰度 + 多尺度 matchTemplate + 上一位置跟踪。"""

    name = "template"

    def __init__(
        self,
        template_path: str | Path | None = None,
        *,
        min_score: float = 0.38,
        scale_factor: float = _DEFAULT_SCALE_FACTOR,
        scales: tuple[float, ...] | None = None,
        track_margin: int = _DEFAULT_TRACK_MARGIN,
    ) -> None:
        path = Path(template_path) if template_path else _DEFAULT_TEMPLATE
        if not path.is_file():
            raise FileNotFoundError(f"张力条模板不存在: {path}")
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise FileNotFoundError(f"无法读取模板: {path}")
        self._tpl_gray = gray
        self.template_path = path
        self.min_score = float(min_score)
        self.scale_factor = float(scale_factor)
        self.scales = scales if scales is not None else _DEFAULT_SCALES
        self.track_margin = int(track_margin)
        self._prev_box: tuple[int, int, int, int] | None = None
        self._tpl_cache: dict[float, np.ndarray] | None = None
        self._last_sf: float | None = None

    def _ensure_templates(self, sf: float) -> dict[float, np.ndarray]:
        if self._tpl_cache is not None and self._last_sf == sf:
            return self._tpl_cache
        cache: dict[float, np.ndarray] = {}
        th, tw = self._tpl_gray.shape
        for scale in self.scales:
            ws = max(1, int(round(tw * scale * sf)))
            hs = max(1, int(round(th * scale * sf)))
            if ws < 20 or hs < 6:
                continue
            cache[scale] = cv2.resize(
                self._tpl_gray, (ws, hs), interpolation=cv2.INTER_AREA
            )
        self._tpl_cache = cache
        self._last_sf = sf
        return cache

    def find_bar(self, rgb: np.ndarray) -> tuple[int, int, int, int] | None:
        matched = self._match(rgb)
        if matched is None:
            return None
        _score, x, y, w, h = matched
        return x, y, w, h

    def detect(self, rgb: np.ndarray) -> BobberHit | None:
        t0 = time.perf_counter()
        matched = self._match(rgb)
        if matched is None:
            self._prev_box = None
            return None
        score, x, y, w, h = matched
        bob = bobber_in_bar(rgb, x, y, w, h)
        dt = (time.perf_counter() - t0) * 1000.0
        if bob is None:
            return None
        return BobberHit(
            pos=bob.pos,
            x=bob.x,
            y=bob.y,
            pixel_count=bob.pixel_count,
            bar_left=bob.bar_left,
            bar_top=bob.bar_top,
            bar_width=bob.bar_width,
            bar_height=bob.bar_height,
            score=max(bob.score, min(1.0, score)),
            detect_ms=dt,
        )

    def _match(
        self, rgb: np.ndarray
    ) -> tuple[float, int, int, int, int] | None:
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            return None
        img_gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        ih, iw = img_gray.shape
        sf = self.scale_factor
        sw, sh = max(1, int(round(iw * sf))), max(1, int(round(ih * sf)))
        img_s = cv2.resize(img_gray, (sw, sh), interpolation=cv2.INTER_AREA)
        roi, offset = self._roi(img_s)
        tpl_cache = self._ensure_templates(sf)
        best: tuple[float, int, int, int, int] | None = None
        for scale, tpl in tpl_cache.items():
            hs, ws = tpl.shape[:2]
            if ws >= roi.shape[1] or hs >= roi.shape[0]:
                continue
            res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
            _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(res)
            sx, sy = max_l[0] + offset[0], max_l[1] + offset[1]
            if best is None or max_v > best[0]:
                best = (float(max_v), int(sx), int(sy), ws, hs)
        if best is None or best[0] < self.min_score:
            self._prev_box = None
            return None
        # 映射回原始分辨率
        score, sx, sy, ws, hs = best
        x = int(round(sx / sf))
        y = int(round(sy / sf))
        w = int(round(ws / sf))
        h = int(round(hs / sf))
        # 下一帧只在此框附近搜（丢失时自动回全图）
        self._prev_box = (x, y, w, h)
        return score, x, y, w, h

    def _roi(
        self, img_s: np.ndarray
    ) -> tuple[np.ndarray, tuple[int, int]]:
        """返回压缩后搜索 ROI 与左上角偏移。"""
        if self._prev_box is None:
            return img_s, (0, 0)
        px, py, pw, ph = self._prev_box
        sf = self.scale_factor
        sx, sy = int(round(px * sf)), int(round(py * sf))
        sw, sh = int(round(pw * sf)), int(round(ph * sf))
        margin = self.track_margin
        x0 = max(0, sx - margin)
        y0 = max(0, sy - margin)
        x1 = min(img_s.shape[1], sx + sw + margin)
        y1 = min(img_s.shape[0], sy + sh + margin)
        # ROI 不能小于模板最小尺寸；否则退化全图
        if x1 - x0 < 40 or y1 - y0 < 16:
            return img_s, (0, 0)
        return img_s[y0:y1, x0:x1], (x0, y0)
