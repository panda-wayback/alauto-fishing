"""模板识别器：matchTemplate 定位张力条，带内找漂。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc

from autofish.detect.bobber import BobberHit, bobber_in_bar

_DEFAULT_TEMPLATE = (
    Path(__file__).resolve().parents[3]
    / "assets"
    / "tension_bar.before_endcap_fix.png"
)


class TemplateBarDetector:
    """多尺度 matchTemplate（绿通道 + CCOEFF_NORMED）。"""

    name = "template"

    def __init__(
        self,
        template_path: str | Path | None = None,
        *,
        min_score: float = 0.55,
        scales: tuple[float, ...] | None = None,
    ) -> None:
        path = Path(template_path) if template_path else _DEFAULT_TEMPLATE
        if not path.is_file():
            raise FileNotFoundError(f"张力条模板不存在: {path}")
        # RGB
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise FileNotFoundError(f"无法读取模板: {path}")
        self._tpl_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        self._tpl_g = self._tpl_rgb[:, :, 1]
        self.min_score = float(min_score)
        self.scales = scales or tuple(
            float(x) for x in np.linspace(0.35, 1.15, 25)
        )
        self.template_path = path

    def find_bar(self, rgb: np.ndarray) -> tuple[int, int, int, int] | None:
        hit = self._match(rgb)
        if hit is None:
            return None
        _score, x, y, w, h = hit
        return x, y, w, h

    def detect(self, rgb: np.ndarray) -> BobberHit | None:
        matched = self._match(rgb)
        if matched is None:
            return None
        score, x, y, w, h = matched
        bob = bobber_in_bar(rgb, x, y, w, h)
        if bob is None:
            return None
        # 保留模板匹配分作为 score 上限参考
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
        )

    def _match(
        self, rgb: np.ndarray
    ) -> tuple[float, int, int, int, int] | None:
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            return None
        ih, iw = rgb.shape[:2]
        th, tw = self._tpl_g.shape[:2]
        img_g = rgb[:, :, 1]
        best: tuple[float, int, int, int, int] | None = None
        for scale in self.scales:
            w = int(round(tw * scale))
            h = int(round(th * scale))
            if w < 60 or h < 10 or w >= iw or h >= ih:
                continue
            tpl = cv2.resize(self._tpl_g, (w, h), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(img_g, tpl, cv2.TM_CCOEFF_NORMED)
            _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(res)
            if best is None or max_v > best[0]:
                best = (float(max_v), int(max_l[0]), int(max_l[1]), w, h)
        if best is None or best[0] < self.min_score:
            return None
        return best
