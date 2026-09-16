"""算法用观测与步进：不暴露内部字段写权限。"""

from __future__ import annotations

from dataclasses import dataclass

from sim import config
from sim.game import FishingGame, State


@dataclass(frozen=True)
class Observation:
    state: State
    tier: int
    bobber_x: float
    bobber_v: float
    progress: float
    holding: bool
    hold_time: float
    time: float
    safe_left: float
    safe_right: float
    tension_w: float


def observe(game: FishingGame) -> Observation:
    return Observation(
        state=game.state,
        tier=game.tier,
        bobber_x=game.bobber_x,
        bobber_v=game.bobber_v,
        progress=game.progress,
        holding=game.holding,
        hold_time=game.hold_time,
        time=game.time,
        safe_left=float(config.SAFE_LEFT),
        safe_right=float(config.SAFE_RIGHT),
        tension_w=float(config.TENSION_W),
    )


def step(game: FishingGame, holding: bool, dt: float) -> Observation:
    """设置是否按住并推进一帧，返回新观测。"""
    game.set_holding(holding)
    game.update(dt)
    return observe(game)
