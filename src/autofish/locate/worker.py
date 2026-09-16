"""段1：圈定范围 — Locator。"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from autofish.bus import AutofishBus
from autofish.capture.screen import grab_primary
from autofish.locate.roi import DEFAULT_BAR_TEMPLATE, Roi, save_roi
from autofish.topics import RoiEvent
from autofish.worker_base import WorkerBase

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要安装 opencv-python-headless") from exc


class LocatorWorker(WorkerBase):
    """matchTemplate 找张力条 → 发布 ROI（低频）。"""

    def __init__(
        self,
        bus: AutofishBus,
        *,
        template_path: Path = DEFAULT_BAR_TEMPLATE,
        interval_s: float = 1.0,
        min_score: float = 0.55,
        persist_roi: bool = True,
    ) -> None:
        super().__init__(bus, "autofish-locator")
        self.template_path = template_path
        self.interval_s = interval_s
        self.min_score = min_score
        self.persist_roi = persist_roi
        self._version = 0
        self._tpl: np.ndarray | None = None

    def _load_tpl(self) -> np.ndarray | None:
        if self._tpl is not None:
            return self._tpl
        if not self.template_path.exists():
            return None
        bgr = cv2.imread(str(self.template_path), cv2.IMREAD_COLOR)
        if bgr is None:
            return None
        self._tpl = bgr
        return self._tpl

    def locate_once(self) -> RoiEvent | None:
        tpl = self._load_tpl()
        if tpl is None:
            return None
        grab = grab_primary()
        hay = cv2.cvtColor(grab.rgb, cv2.COLOR_RGB2BGR)
        th, tw = tpl.shape[:2]
        scale = min(1.0, hay.shape[1] / tw, hay.shape[0] / th)
        if scale < 0.999:
            tpl_use = cv2.resize(
                tpl,
                (max(1, int(tw * scale)), max(1, int(th * scale))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            tpl_use = tpl
        if hay.shape[0] < tpl_use.shape[0] or hay.shape[1] < tpl_use.shape[1]:
            return None
        res = cv2.matchTemplate(hay, tpl_use, cv2.TM_CCOEFF_NORMED)
        _min_v, max_v, _min_l, max_loc = cv2.minMaxLoc(res)
        if max_v < self.min_score:
            return None
        x, y = max_loc
        h, w = tpl_use.shape[:2]
        roi = Roi(
            left=grab.origin_left + int(x),
            top=grab.origin_top + int(y),
            width=int(w),
            height=int(h),
        )
        self._version += 1
        event = RoiEvent(
            roi=roi,
            version=self._version,
            ts=time.time(),
            source="template",
            score=float(max_v),
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
