"""感知主题与事件载荷。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from autofish.detect.bobber import BobberHit
from autofish.locate.roi import Roi


class Topic(str, Enum):
    ROI = "roi"
    FRAME = "frame"
    POS = "pos"
    FISHING_STATE = "fishing_state"


class FishingState(str, Enum):
    IDLE = "idle"          # 无有效条 / 未在拉鱼
    FISHING = "fishing"    # 条在且读数可用
    LOST = "lost"          # 曾在钓，暂时丢漂或丢条


@dataclass(frozen=True)
class RoiEvent:
    roi: Roi | None
    version: int
    ts: float
    source: str  # "manual" | "template" | "clear"
    score: float = 0.0


@dataclass(frozen=True)
class FrameEvent:
    frame: np.ndarray
    roi_version: int
    ts: float


@dataclass(frozen=True)
class PosEvent:
    pos: float | None
    hit: BobberHit | None
    roi_version: int
    frame_ts: float
    ts: float


@dataclass(frozen=True)
class FishingStateEvent:
    state: FishingState
    ts: float
    detail: str = ""


# 订阅回调
Subscriber = Any  # Callable[[Any], None]
