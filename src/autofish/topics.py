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
    CAST_SESSION = "cast_session"
    ACTION_INTENT = "action_intent"
    PRESS_INTERVAL = "press_interval"


class FishingState(str, Enum):
    IDLE = "idle"
    FISHING = "fishing"
    LOST = "lost"


class CastSessionState(str, Enum):
    """开钓会话态（A）；DISABLED = A 关。"""

    DISABLED = "disabled"
    WAIT = "wait"
    FIRST_CLICK = "first_click"
    WAIT_BOBBER = "wait_bobber"
    FISHING = "fishing"


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
class SplashHit:
    """水声命中进入 FIRST_CLICK 时的结构化载荷。"""

    score: float
    delay_s: float
    hold_s: float
    after_s: float
    threshold: float


@dataclass(frozen=True)
class CastSessionEvent:
    state: CastSessionState
    ts: float
    detail: str = ""
    splash: SplashHit | None = None


@dataclass(frozen=True)
class ActionIntentEvent:
    """Decide → Act：要按住 / 要松开。"""

    holding: bool
    ts: float
    reason: str = ""
    pos: float | None = None


@dataclass(frozen=True)
class PressIntervalEvent:
    """调试壳 → Act：两次程序按下的最短间隔（秒）。"""

    interval_s: float
    ts: float
