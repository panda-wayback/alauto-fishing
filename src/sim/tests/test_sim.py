import dataclasses

import pytest

from sim import FishingGame, Observation, State, config, observe, step

DT = 1.0 / 60
TIERS = range(1, 9)
MAX_FRAMES = 20_000


def _playing(tier=4):
    game = FishingGame()
    game.set_tier(tier)
    game.start()
    return game


def _run_constant(game, holding):
    frames = 0
    while game.state == State.PLAYING and frames < MAX_FRAMES:
        step(game, holding, DT)
        frames += 1
    return frames


def test_new_game_initial_state():
    game = FishingGame()
    obs = observe(game)
    assert obs.state == State.READY
    assert obs.tier == 4
    assert obs.bobber_x == pytest.approx(config.TENSION_W * 0.5)
    assert obs.bobber_v == 0.0
    assert obs.progress == 0.0
    assert obs.time == 0.0
    assert obs.holding is False


def test_set_tier_clamps_and_ignored_while_playing():
    game = FishingGame()
    game.set_tier(0)
    assert game.tier == 1
    game.set_tier(99)
    assert game.tier == 8
    game.set_tier(3)
    game.start()
    game.set_tier(6)
    assert game.tier == 3


def test_start_enters_playing_and_restart_while_playing_is_noop():
    game = _playing()
    assert game.state == State.PLAYING
    for _ in range(5):
        step(game, True, DT)
    before = observe(game)
    game.start()
    assert observe(game) == before


def test_inactive_state_and_nonpositive_dt_are_noops():
    game = FishingGame()
    game.set_holding(True)
    game.update(0.5)
    assert game.holding is False and game.time == 0.0

    game.start()
    game.set_holding(True)
    before = observe(game)
    game.update(0.0)
    game.update(-1.0)
    assert observe(game) == before


def test_short_hold_moves_right_and_raises_progress():
    game = _playing(4)
    x0 = game.bobber_x
    observations = [step(game, True, DT) for _ in range(6)]
    assert all(o.state == State.PLAYING for o in observations)
    assert observations[-1].bobber_x > x0
    progress = [o.progress for o in observations]
    assert progress == sorted(progress) and progress[-1] > 0
    assert observations[-1].hold_time == pytest.approx(6 * DT)
    assert observations[-1].time == pytest.approx(6 * DT)


@pytest.mark.parametrize("tier", TIERS)
def test_continuous_hold_fails_on_right_red(tier):
    game = _playing(tier)
    _run_constant(game, True)
    assert game.state == State.FAILED
    assert game.bobber_x > config.SAFE_RIGHT


@pytest.mark.parametrize("tier", TIERS)
def test_continuous_release_fails_on_left_red_without_progress(tier):
    game = _playing(tier)
    progress = []
    while game.state == State.PLAYING and len(progress) < MAX_FRAMES:
        progress.append(step(game, False, DT).progress)
    assert game.state == State.FAILED
    assert game.bobber_x < config.SAFE_LEFT
    assert max(progress) == 0.0


def test_release_after_hold_turns_left_and_progress_never_rises():
    game = _playing(4)
    for _ in range(9):
        step(game, True, DT)
    assert game.bobber_v > 0 and game.progress > 0

    obs = observe(game)
    turned = False
    for _ in range(30):
        prev = obs
        obs = step(game, False, DT)
        assert obs.state == State.PLAYING
        assert obs.hold_time == 0.0
        assert obs.progress <= prev.progress
        if obs.bobber_v < 0:
            turned = True
            assert obs.bobber_x < prev.bobber_x
    assert turned


@pytest.mark.parametrize("tier", [1, 4])
def test_tapping_controller_reaches_success(tier):
    game = _playing(tier)
    obs = observe(game)
    frames = 0
    while obs.state == State.PLAYING and frames < MAX_FRAMES:
        assert 0.0 <= obs.progress <= 1.0
        pos = (obs.bobber_x - obs.safe_left) / (obs.safe_right - obs.safe_left)
        obs = step(game, pos < 0.5, DT)
        frames += 1
    assert obs.state == State.SUCCESS
    assert obs.progress == pytest.approx(1.0)
    assert config.SAFE_LEFT <= obs.bobber_x <= config.SAFE_RIGHT


def test_terminal_state_clears_holding_and_reset_keeps_tier():
    game = _playing(2)
    _run_constant(game, True)
    assert game.state == State.FAILED
    assert game.holding is False and game.hold_time == 0.0

    game.reset()
    obs = observe(game)
    assert obs.state == State.READY
    assert obs.tier == 2
    assert obs.progress == 0.0
    assert obs.bobber_x == pytest.approx(config.TENSION_W * 0.5)

    game.start()
    assert game.state == State.PLAYING and game.progress == 0.0


def test_higher_tier_falls_into_left_red_faster():
    frames = [_run_constant(_playing(t), False) for t in TIERS]
    assert all(a > b for a, b in zip(frames, frames[1:]))


def test_step_matches_set_holding_update_and_observation_is_frozen_snapshot():
    a, b = _playing(5), _playing(5)
    seq = [True] * 7 + [False] * 5 + [True] * 3
    for holding in seq:
        obs_a = step(a, holding, DT)
        b.set_holding(holding)
        b.update(DT)
        assert obs_a == observe(b)

    assert isinstance(obs_a, Observation)
    assert obs_a.safe_left == float(config.SAFE_LEFT)
    assert obs_a.safe_right == float(config.SAFE_RIGHT)
    assert obs_a.tension_w == float(config.TENSION_W)
    with pytest.raises(dataclasses.FrozenInstanceError):
        obs_a.progress = 0.5

    snapshot = obs_a
    step(a, True, DT)
    assert snapshot.time == obs_a.time
    assert observe(a).time > snapshot.time
