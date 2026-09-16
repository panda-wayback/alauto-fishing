"""无头跑局与批量统计。"""

from __future__ import annotations

from dataclasses import dataclass

from algo.base import PullPolicy
from sim import config
from sim.api import Observation, observe, step
from sim.game import FishingGame, State


@dataclass(frozen=True)
class EpisodeResult:
    state: State
    frames: int
    progress: float
    time: float
    tier: int


@dataclass(frozen=True)
class BatchResult:
    episodes: int
    wins: int
    win_rate: float
    avg_time: float
    avg_progress: float


def run_episode(
    policy: PullPolicy,
    *,
    tier: int = 4,
    dt: float | None = None,
    max_frames: int = 60_000,
) -> EpisodeResult:
    """无头跑一局；policy.decide 每帧决定是否按住。"""
    frame_dt = 1.0 / config.FPS if dt is None else dt
    game = FishingGame()
    game.set_tier(tier)
    game.start()

    obs: Observation = observe(game)
    frames = 0
    while game.state == State.PLAYING and frames < max_frames:
        holding = policy.decide(obs)
        obs = step(game, holding, frame_dt)
        frames += 1

    return EpisodeResult(
        state=game.state,
        frames=frames,
        progress=game.progress,
        time=game.time,
        tier=game.tier,
    )


def run_batch(
    policy: PullPolicy,
    *,
    episodes: int = 100,
    tier: int = 4,
    dt: float | None = None,
    max_frames: int = 60_000,
) -> BatchResult:
    results = [
        run_episode(policy, tier=tier, dt=dt, max_frames=max_frames)
        for _ in range(episodes)
    ]
    wins = sum(1 for r in results if r.state == State.SUCCESS)
    n = len(results)
    return BatchResult(
        episodes=n,
        wins=wins,
        win_rate=wins / n if n else 0.0,
        avg_time=sum(r.time for r in results) / n if n else 0.0,
        avg_progress=sum(r.progress for r in results) / n if n else 0.0,
    )
