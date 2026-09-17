"""感知 / 决策主题与事件载荷。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from autofish.detect.bobber import BobberHit
from autofish.locate.roi import Roi


class Topic(str, Enum):
    ROI = "roi"
    FRAME = "frame"
    POS = "pos"
    FISHING_STATE = "fishing_state"
    ACTION_INTENT = "action_intent"


class FishingState(str, Enum):
    IDLE = "idle"
    FISHING = "fishing"
    LOST = "lost"


@dataclass(frozen=True)
class RoiEvent:
    roi: Roi | None
    version: int
    ts: float
    source: str  # "manual" | "green" | "clear"
    score: float = 0.0


@dataclass(frozen=True)
class FrameEvent:
    frame: np.ndarray
    roi_version: int
    ts: float
    seq: int = 0


@dataclass(frozen=True)
class PosEvent:
    pos: float | None
    hit: BobberHit | None
    roi_version: int
    frame_ts: float
    ts: float
    frame_seq: int = 0
    """与 FrameEvent.seq 对齐；同帧画面与读数。"""
    frame: np.ndarray | None = None
    """刚完成识别的那一帧（供 UI 与读数同频显示）。"""
    detect_ms: float = 0.0
    """本次识别耗时（毫秒）。"""


@dataclass(frozen=True)
class FishingStateEvent:
    state: FishingState
    ts: float
    detail: str = ""


@dataclass(frozen=True)
class ActionIntentEvent:
    """Decide → Act：要按住 / 要松开。"""

    holding: bool
    ts: float
    reason: str = ""
    pos: float | None = None
