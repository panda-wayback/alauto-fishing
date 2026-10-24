import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame
import pytest

from sim import FishingGame, State, config, observe, step
from ui.render import Renderer

DT = 1.0 / 60
W, H = config.WINDOW_WIDTH, config.WINDOW_HEIGHT
TENSION_ROWS = pygame.Rect(0, config.PAD_Y, W, config.TENSION_H)
_progress_top = config.PAD_Y + config.TENSION_H + config.GAP
PROGRESS_ROWS = pygame.Rect(0, _progress_top + 15, W, config.PROGRESS_H - 30)
TIP_ROWS = pygame.Rect(0, H - 48, W, 48)


def _ensure_display():
    pygame.display.init()
    pygame.font.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((1, 1))


@pytest.fixture
def screen():
    _ensure_display()
    return pygame.Surface((W, H))


@pytest.fixture
def renderer(screen):
    return Renderer(screen)


def _pixels(surface, rect):
    return pygame.image.tobytes(surface.subsurface(rect).copy(), "RGB")


def _game(state):
    game = FishingGame()
    game.set_tier(3)
    if state == State.READY:
        return game
    game.start()
    if state == State.PLAYING:
        for _ in range(10):
            step(game, True, DT)
        return game
    holding = state == State.FAILED
    while game.state == State.PLAYING:
        if state == State.SUCCESS:
            obs = observe(game)
            holding = (obs.bobber_x - obs.safe_left) / (obs.safe_right - obs.safe_left) < 0.5
        step(game, holding, DT)
    assert game.state == state
    return game


def test_renderer_requires_video_mode():
    pygame.display.quit()
    pygame.display.init()
    pygame.font.init()
    with pytest.raises(pygame.error):
        Renderer(pygame.Surface((W, H)))


@pytest.mark.parametrize("state", list(State))
def test_draw_every_state_without_mutating_game(renderer, state):
    game = _game(state)
    before = observe(game)
    renderer.draw(game)
    assert observe(game) == before


def test_draw_overwrites_with_background(screen, renderer):
    screen.fill((255, 0, 0))
    renderer.draw(FishingGame())
    bg = pygame.Color(*config.BG_COLOR)
    for xy in [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]:
        assert screen.get_at(xy) == bg


def test_bobber_position_changes_tension_area(screen, renderer):
    left, right = FishingGame(), FishingGame()
    left.start()
    for _ in range(20):
        step(left, False, DT)
    assert left.bobber_x < right.bobber_x - 5

    renderer.draw(left)
    a = _pixels(screen, TENSION_ROWS)
    renderer.draw(right)
    b = _pixels(screen, TENSION_ROWS)
    assert a != b


def test_progress_changes_progress_area(screen, renderer):
    fresh = FishingGame()
    advanced = _game(State.SUCCESS)
    assert advanced.progress > fresh.progress

    renderer.draw(fresh)
    a = _pixels(screen, PROGRESS_ROWS)
    renderer.draw(advanced)
    b = _pixels(screen, PROGRESS_ROWS)
    assert a != b


def test_tip_text_changes_with_state(screen, renderer):
    ready = FishingGame()
    playing = FishingGame()
    playing.start()
    assert observe(ready).bobber_x == observe(playing).bobber_x

    renderer.draw(ready)
    a = _pixels(screen, TIP_ROWS)
    renderer.draw(playing)
    b = _pixels(screen, TIP_ROWS)
    assert a != b
