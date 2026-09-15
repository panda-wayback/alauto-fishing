"""Albion 拉鱼模拟器入口。"""

from __future__ import annotations

import pygame

import config
from fishing import FishingGame, State
from render import Renderer

_TIER_KEYS = {
    pygame.K_1: 1,
    pygame.K_2: 2,
    pygame.K_3: 3,
    pygame.K_4: 4,
    pygame.K_5: 5,
    pygame.K_6: 6,
    pygame.K_7: 7,
    pygame.K_8: 8,
    pygame.K_KP1: 1,
    pygame.K_KP2: 2,
    pygame.K_KP3: 3,
    pygame.K_KP4: 4,
    pygame.K_KP5: 5,
    pygame.K_KP6: 6,
    pygame.K_KP7: 7,
    pygame.K_KP8: 8,
}


def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((config.WINDOW_WIDTH, config.WINDOW_HEIGHT))
    pygame.display.set_caption(config.TITLE)
    clock = pygame.time.Clock()
    game = FishingGame()
    renderer = Renderer(screen)

    running = True
    while running:
        dt = clock.tick(config.FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_r:
                    game.reset()
                elif event.key in _TIER_KEYS:
                    game.set_tier(_TIER_KEYS[event.key])
                elif event.key == pygame.K_SPACE:
                    if game.state == State.PLAYING:
                        game.set_holding(True)
                    else:
                        game.start()
            elif event.type == pygame.KEYUP:
                if event.key == pygame.K_SPACE:
                    game.set_holding(False)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if game.state == State.PLAYING:
                    game.set_holding(True)
                else:
                    game.start()
                    game.set_holding(True)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                game.set_holding(False)

        game.update(dt)
        renderer.draw(game)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
