"""用截图抠出的元素拼两横条界面。"""

from __future__ import annotations

import pygame

from sim import config
from sim.game import FishingGame, State


def _load(path) -> pygame.Surface:
    return pygame.image.load(str(path)).convert_alpha()


def _load_font(size: int) -> pygame.font.Font:
    for name in (
        "PingFang SC",
        "Hiragino Sans GB",
        "Songti SC",
        "Arial Unicode MS",
        "Heiti SC",
    ):
        path = pygame.font.match_font(name)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.SysFont(None, size)


class Renderer:
    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.tension = _load(config.TENSION_BAR)
        self.progress_bar = _load(config.PROGRESS_BAR)
        self.bobber = _load(config.BOBBER)
        self.fish = _load(config.FISH_MARKER)
        self.font = _load_font(18)

        self.tension_x = (config.WINDOW_WIDTH - config.TENSION_W) // 2
        self.tension_y = config.PAD_Y
        self.progress_x = (config.WINDOW_WIDTH - config.PROGRESS_W) // 2
        self.progress_y = self.tension_y + config.TENSION_H + config.GAP

    def draw(self, game: FishingGame) -> None:
        self.screen.fill(config.BG_COLOR)
        self.screen.blit(self.tension, (self.tension_x, self.tension_y))
        self.screen.blit(self.progress_bar, (self.progress_x, self.progress_y))

        bobber_rect = self.bobber.get_rect(
            centerx=int(self.tension_x + game.bobber_x),
            centery=self.tension_y + config.TENSION_H // 2,
        )
        self.screen.blit(self.bobber, bobber_rect)

        # 进度：鱼标从左到右；身后细白线（对齐截图）
        fish_travel = config.PROGRESS_W - self.fish.get_width() - 36
        fish_x = self.progress_x + 8 + int(fish_travel * game.progress)
        fish_y = self.progress_y + (config.PROGRESS_H - self.fish.get_height()) // 2
        line_y = self.progress_y + config.PROGRESS_H // 2
        line_start = self.progress_x + 8
        line_end = fish_x + self.fish.get_width() // 2
        if line_end > line_start:
            pygame.draw.line(
                self.screen,
                (210, 225, 240),
                (line_start, line_y),
                (line_end, line_y),
                2,
            )
        self.screen.blit(self.fish, (fish_x, fish_y))

        tip = {
            State.READY: f"鱼 T{game.tier}｜1-8 选档｜点击或空格开始",
            State.PLAYING: f"鱼 T{game.tier}｜高频点按 · 别碰左右红",
            State.SUCCESS: f"成功！T{game.tier}｜R 重开｜1-8 换档",
            State.FAILED: f"失败！T{game.tier}｜R 重开｜1-8 换档",
        }[game.state]
        text = self.font.render(tip, True, (220, 220, 210))
        self.screen.blit(
            text,
            text.get_rect(
                centerx=self.screen.get_width() // 2,
                bottom=self.screen.get_height() - 16,
            ),
        )
