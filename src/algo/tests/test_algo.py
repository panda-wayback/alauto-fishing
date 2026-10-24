import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from algo import (
    BatchResult,
    EpisodeResult,
    ThresholdHoldPolicy,
    bobber_pos_in_safe_100,
    run_batch,
    run_episode,
)
from algo.__main__ import main
from sim import Observation, State, config

SRC = Path(__file__).resolve().parents[2]
STATS_LINE = re.compile(
    r"^tier=T(\d) episodes=(\d+) win_rate=[\d.]+% avg_time=[\d.]+s avg_progress=[\d.]+$"
)
SAMPLE_LINE = re.compile(r"^sample episode: (SUCCESS|FAILED|PLAYING) time=[\d.]+s progress=[\d.]+$")


def _obs(x, t=0.0, left=100.0, right=200.0):
    return Observation(
        state=State.PLAYING,
        tier=4,
        bobber_x=x,
        bobber_v=0.0,
        progress=0.0,
        holding=False,
        hold_time=0.0,
        time=t,
        safe_left=left,
        safe_right=right,
        tension_w=300.0,
    )


class CountingPolicy:
    def __init__(self, holding):
        self.holding = holding
        self.calls = 0

    def decide(self, obs):
        self.calls += 1
        return self.holding


class AlternatingPolicy:
    def __init__(self):
        self.calls = 0

    def decide(self, obs):
        self.calls += 1
        return self.calls % 2 == 0


def test_pos_in_safe_100_maps_and_clamps():
    assert bobber_pos_in_safe_100(_obs(100.0)) == 0.0
    assert bobber_pos_in_safe_100(_obs(200.0)) == 100.0
    assert bobber_pos_in_safe_100(_obs(125.0)) == pytest.approx(25.0)
    assert bobber_pos_in_safe_100(_obs(50.0)) == 0.0
    assert bobber_pos_in_safe_100(_obs(260.0)) == 100.0
    assert bobber_pos_in_safe_100(_obs(170.0, left=150.0, right=150.0)) == 50.0


@pytest.mark.parametrize("low,high", [(50.0, 50.0), (90.0, 50.0)])
def test_threshold_rejects_low_not_below_high(low, high):
    with pytest.raises(ValueError):
        ThresholdHoldPolicy(low=low, high=high)


def test_threshold_hold_release_and_keep():
    p = ThresholdHoldPolicy(low=50, high=90, min_interval=0.0, jitter=0.0)
    assert p.decide(_obs(170.0, t=0.0)) is False  # 70: keep initial release
    assert p.decide(_obs(140.0, t=0.1)) is True  # 40 < low
    assert p.decide(_obs(170.0, t=0.2)) is True  # 70: keep holding
    assert p.decide(_obs(195.0, t=0.3)) is False  # 95 > high
    assert p.decide(_obs(170.0, t=0.4)) is False


def test_threshold_switch_interval():
    p = ThresholdHoldPolicy(min_interval=0.2, jitter=0.1, seed=1)
    assert p.decide(_obs(110.0, t=0.0)) is True
    assert p.decide(_obs(199.0, t=0.19)) is True
    assert p.decide(_obs(110.0, t=0.25)) is True
    assert p.decide(_obs(199.0, t=0.31)) is False
    assert p.decide(_obs(110.0, t=0.5)) is False
    assert p.decide(_obs(110.0, t=0.62)) is True


def test_threshold_same_seed_same_output():
    xs = [110, 199, 110, 199, 150, 110, 199, 199, 110, 150] * 10
    seq = [_obs(float(x), t=i * 0.05) for i, x in enumerate(xs)]
    a = ThresholdHoldPolicy(seed=7)
    b = ThresholdHoldPolicy(seed=7)
    assert [a.decide(o) for o in seq] == [b.decide(o) for o in seq]


def test_run_episode_threshold_policy_wins_tier1():
    r = run_episode(ThresholdHoldPolicy(seed=0), tier=1)
    assert isinstance(r, EpisodeResult)
    assert r.state == State.SUCCESS
    assert r.tier == 1
    assert r.progress == pytest.approx(1.0)
    assert r.time == pytest.approx(r.frames / config.FPS)


def test_run_episode_always_hold_fails_and_counts_frames():
    p = CountingPolicy(True)
    r = run_episode(p, tier=4)
    assert r.state == State.FAILED
    assert r.frames == p.calls > 0


def test_run_episode_frame_limit_and_tier_clamp():
    r = run_episode(AlternatingPolicy(), tier=42, dt=0.01, max_frames=5)
    assert r.state == State.PLAYING
    assert r.frames == 5
    assert r.time == pytest.approx(0.05)
    assert r.tier == 8


def test_run_batch_aggregates_and_shares_policy():
    p = CountingPolicy(True)
    b = run_batch(p, episodes=3, tier=2)
    assert isinstance(b, BatchResult)
    assert b.episodes == 3
    assert b.wins == 0 and b.win_rate == 0.0
    single = run_episode(CountingPolicy(True), tier=2)
    assert p.calls == 3 * single.frames
    assert b.avg_time == pytest.approx(single.time)
    assert b.avg_progress == pytest.approx(single.progress)


def test_run_episode_resets_policy_before_each_episode():
    class ResettablePolicy(CountingPolicy):
        def __init__(self):
            super().__init__(True)
            self.resets_before_first_decide = []

        def reset(self):
            self.resets_before_first_decide.append(self.calls)

    p = ResettablePolicy()
    first = run_episode(p, tier=2)
    run_episode(p, tier=2)
    assert p.resets_before_first_decide == [0, first.frames]


def test_threshold_reset_restores_initial_state():
    p = ThresholdHoldPolicy(min_interval=5.0, jitter=0.0)
    assert p.decide(_obs(110.0, t=10.0)) is True
    p.reset()
    assert p.decide(_obs(170.0, t=0.0)) is False
    assert p.decide(_obs(110.0, t=0.0)) is True


def test_run_batch_shared_threshold_policy_matches_fresh_policies():
    tier = 1
    batch = run_batch(ThresholdHoldPolicy(seed=0), episodes=5, tier=tier)
    assert run_episode(ThresholdHoldPolicy(seed=0), tier=tier).state == State.SUCCESS
    assert batch.wins == 5


def test_run_batch_zero_episodes():
    b = run_batch(CountingPolicy(True), episodes=0)
    assert b == BatchResult(episodes=0, wins=0, win_rate=0.0, avg_time=0.0, avg_progress=0.0)


def test_main_prints_stats_and_returns_zero(capsys):
    assert main(["--tier", "1", "--episodes", "1", "--seed", "3"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    m = STATS_LINE.match(lines[0])
    assert m and m.group(1) == "1" and m.group(2) == "1"
    assert SAMPLE_LINE.match(lines[1])


def test_main_returns_one_when_all_fail(capsys):
    assert main(["--tier", "1", "--episodes", "1", "--low", "1", "--high", "2"]) == 1
    assert "win_rate=0.0%" in capsys.readouterr().out


def test_main_rejects_bad_tier():
    with pytest.raises(SystemExit) as exc:
        main(["--tier", "9"])
    assert exc.value.code == 2


def test_cli_subprocess():
    env = dict(os.environ, PYTHONPATH=str(SRC))
    proc = subprocess.run(
        [sys.executable, "-m", "algo", "--tier", "1", "--episodes", "1"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.strip().splitlines()
    assert STATS_LINE.match(lines[0])
    assert SAMPLE_LINE.match(lines[1])
