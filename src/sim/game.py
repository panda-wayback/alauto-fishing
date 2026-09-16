"""Albion 拉鱼：按住向右、松开向左；须高频点按，长按/松太久都会撞红。"""

from __future__ import annotations

import math
from enum import Enum

from sim import config
from sim.difficulty import DEFAULT_TIER, TierProfile, clamp_tier, profile_for


class State(Enum):
    READY = "ready"
    PLAYING = "playing"
    SUCCESS = "success"
    FAILED = "failed"


class FishingGame:
    def __init__(self) -> None:
        self.tier = DEFAULT_TIER
        self.profile: TierProfile = profile_for(self.tier)
        self.reset()

    def reset(self) -> None:
        self.state = State.READY
        self.holding = False
        self.hold_time = 0.0
        self.time = 0.0
        self.bobber_x = config.TENSION_W * config.START_X_RATIO
        self.bobber_v = 0.0
        self.progress = config.PROGRESS_START
        self.profile = profile_for(self.tier)

    def set_tier(self, tier: int) -> None:
        if self.state == State.PLAYING:
            return
        self.tier = clamp_tier(tier)
        self.profile = profile_for(self.tier)

    def start(self) -> None:
        if self.state in (State.READY, State.SUCCESS, State.FAILED):
            self.profile = profile_for(self.tier)
            self.state = State.PLAYING
            self.holding = False
            self.hold_time = 0.0
            self.time = 0.0
            self.bobber_x = config.TENSION_W * config.START_X_RATIO
            self.bobber_v = 0.0
            self.progress = config.PROGRESS_START

    def set_holding(self, holding: bool) -> None:
        if self.state != State.PLAYING:
            return
        if holding and not self.holding:
            self.hold_time = 0.0
        if not holding:
            self.hold_time = 0.0
        self.holding = holding

    def update(self, dt: float) -> None:
        if self.state != State.PLAYING:
            return
        if dt <= 0:
            return

        p = self.profile
        self.time += dt
        fish_pull = p.fish_accel_base + p.fish_accel_variation * math.sin(
            self.time * p.fish_variation_hz * math.tau
        )

        if self.holding:
            self.hold_time += dt
            # 短按：中等向右；越按越久向右力线性暴涨 → 长按必撞右红
            player_pull = min(
                p.pull_force_cap,
                p.pull_force_start + p.pull_force_ramp * self.hold_time,
            )
            accel = player_pull - fish_pull
        else:
            accel = -fish_pull
            # 松开立刻刹向右动量，避免右向滑行过长
            if self.bobber_v > 0:
                accel -= config.RELEASE_RIGHT_BRAKE * self.bobber_v

        accel -= config.VELOCITY_DRAG * self.bobber_v

        self.bobber_v += accel * dt
        max_right = p.max_speed * config.RIGHT_SPEED_SCALE
        max_left = p.max_speed * config.LEFT_SPEED_SCALE
        self.bobber_v = max(-max_left, min(max_right, self.bobber_v))
        self.bobber_x += self.bobber_v * dt

        if self.holding:
            self.progress += self._progress_rate() * dt
        if self.bobber_v < 0:
            self.progress -= self._progress_loss_rate() * dt
        self.progress = max(0.0, min(1.0, self.progress))

        if self.bobber_x < config.SAFE_LEFT or self.bobber_x > config.SAFE_RIGHT:
            self.state = State.FAILED
            self.holding = False
            self.hold_time = 0.0
            return

        if self.progress >= 1.0:
            self.state = State.SUCCESS
            self.holding = False
            self.hold_time = 0.0

    def _progress_rate(self) -> float:
        p = self.profile
        span = config.SAFE_RIGHT - config.SAFE_LEFT
        if span <= 0:
            return p.progress_per_sec
        t = (self.bobber_x - config.SAFE_LEFT) / span
        t = max(0.0, min(1.0, t))
        mult = p.progress_rate_at_left + (
            p.progress_rate_at_right - p.progress_rate_at_left
        ) * t
        return p.progress_per_sec * mult

    def _progress_loss_rate(self) -> float:
        p = self.profile
        speed = min(1.0, abs(self.bobber_v) / max(1.0, p.max_speed))
        return p.progress_loss_per_sec * (0.55 + 0.45 * speed)
