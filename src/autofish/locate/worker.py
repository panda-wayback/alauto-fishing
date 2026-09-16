"""段1：圈定范围 — Locator（固定绿 HSV 找绿条）。"""

from __future__ import annotations

import time

from autofish.bus import AutofishBus
from autofish.capture.screen import grab_primary
from autofish.detect.bobber import find_green_span, green_zone_mask
from autofish.locate.roi import Roi, save_roi
from autofish.topics import RoiEvent
from autofish.worker_base import WorkerBase


def roi_from_green_rgb(
    rgb,
    *,
    origin_left: int = 0,
    origin_top: int = 0,
    pad_x: int = 4,
    pad_y: int | None = None,
    clamp: Roi | None = None,
) -> tuple[Roi, float] | None:
    """
    在 RGB 图上找**原始绿条** → 屏幕绝对 ROI。
    仅小幅 pad 容纳鱼漂；若给 clamp（手框），结果必须落在 clamp 内，禁止撑破。
    """
    mask = green_zone_mask(rgb)
    bar = find_green_span(rgb, mask)
    if bar is None:
        return None
    x, y, w, h = bar
    ih, iw = rgb.shape[:2]
    py = pad_y if pad_y is not None else max(12, int(h * 0.35))
    x0 = max(0, x - pad_x)
    y0 = max(0, y - py)
    x1 = min(iw, x + w + pad_x)
    y1 = min(ih, y + h + py)
    if clamp is not None:
        # clamp 相对本图：图已是 clamp 裁切时 origin=0；否则用绝对坐标差
        cx0 = max(0, clamp.left - origin_left)
        cy0 = max(0, clamp.top - origin_top)
        cx1 = min(iw, cx0 + clamp.width)
        cy1 = min(ih, cy0 + clamp.height)
        x0 = max(x0, cx0)
        y0 = max(y0, cy0)
        x1 = min(x1, cx1)
        y1 = min(y1, cy1)
    rw, rh = x1 - x0, y1 - y0
    if rw < 8 or rh < 4:
        return None
    roi = Roi(
        left=origin_left + x0,
        top=origin_top + y0,
        width=rw,
        height=rh,
    )
    score = float(w * h) / float(max(1, iw * ih))
    return roi, score


class LocatorWorker(WorkerBase):
    """固定绿 HSV 找绿条 → 发布 ROI（低频）。不覆盖手动 ROI。"""

    def __init__(
        self,
        bus: AutofishBus,
        *,
        interval_s: float = 1.0,
        persist_roi: bool = True,
    ) -> None:
        super().__init__(bus, "autofish-locator")
        self.interval_s = interval_s
        self.persist_roi = persist_roi
        self._version = 0

    def locate_once(self) -> RoiEvent | None:
        snap = self.bus.snapshot()
        if snap.roi_ceiling is not None:
            return None
        grab = grab_primary()
        found = roi_from_green_rgb(
            grab.rgb,
            origin_left=grab.origin_left,
            origin_top=grab.origin_top,
        )
        if found is None:
            return None
        roi, score = found
        self._version += 1
        event = RoiEvent(
            roi=roi,
            version=self._version,
            ts=time.time(),
            source="green",
            score=score,
        )
        self.bus.publish_roi(event)
        if self.persist_roi:
            save_roi(roi)
        return event

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.locate_once()
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(self.interval_s)
