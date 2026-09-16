"""T1–T8 鱼等级难度曲线（相对 T4 基准）。"""

from __future__ import annotations

from dataclasses import dataclass

from sim import config

DEFAULT_TIER = 4
MIN_TIER = 1
MAX_TIER = 8


@dataclass(frozen=True)
class TierProfile:
    tier: int
    pull_force_start: float
    pull_force_ramp: float
    pull_force_cap: float
    fish_accel_base: float
    fish_accel_variation: float
    fish_variation_hz: float
    max_speed: float
    progress_per_sec: float
    progress_loss_per_sec: float
    progress_rate_at_left: float
    progress_rate_at_right: float


# 高等级：鱼更猛、窗口更短；人的起步力不抬高
_FISH_BASE = (0, 0.70, 0.82, 0.92, 1.00, 1.15, 1.32, 1.52, 1.75)
_FISH_VAR = (0, 0.65, 0.78, 0.90, 1.00, 1.22, 1.48, 1.80, 2.20)
_FISH_HZ = (0, 0.80, 0.88, 0.94, 1.00, 1.15, 1.32, 1.55, 1.85)
_PROGRESS = (0, 1.30, 1.18, 1.08, 1.00, 0.85, 0.72, 0.58, 0.45)
_PROGRESS_LOSS = (0, 0.75, 0.85, 0.92, 1.00, 1.20, 1.45, 1.75, 2.10)
_MAX_SPEED = (0, 0.88, 0.92, 0.96, 1.00, 1.08, 1.16, 1.28, 1.40)
_PULL = (0, 1.06, 1.03, 1.01, 1.00, 0.97, 0.94, 0.90, 0.86)
_LEFT = (0, 0.40, 0.32, 0.26, 0.20, 0.14, 0.10, 0.07, 0.04)
_RIGHT = (0, 1.50, 1.65, 1.78, 1.90, 2.10, 2.35, 2.60, 2.90)


def clamp_tier(tier: int) -> int:
    return max(MIN_TIER, min(MAX_TIER, int(tier)))


def profile_for(tier: int) -> TierProfile:
    t = clamp_tier(tier)
    return TierProfile(
        tier=t,
        pull_force_start=config.PULL_FORCE_START * _PULL[t],
        pull_force_ramp=config.PULL_FORCE_RAMP * _PULL[t],
        pull_force_cap=config.PULL_FORCE_CAP * _PULL[t],
        fish_accel_base=config.FISH_ACCEL_BASE * _FISH_BASE[t],
        fish_accel_variation=config.FISH_ACCEL_VARIATION * _FISH_VAR[t],
        fish_variation_hz=config.FISH_VARIATION_HZ * _FISH_HZ[t],
        max_speed=config.MAX_SPEED * _MAX_SPEED[t],
        progress_per_sec=config.PROGRESS_PER_SEC * _PROGRESS[t],
        progress_loss_per_sec=config.PROGRESS_LOSS_PER_SEC * _PROGRESS_LOSS[t],
        progress_rate_at_left=_LEFT[t],
        progress_rate_at_right=_RIGHT[t],
    )
