"""调试壳：监控 / 策略 / 操作独立开关；模拟器仅手玩，零业务耦合。"""

from __future__ import annotations

import sys
import time
from collections import deque
from pathlib import Path

import numpy as np
import pygame

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sim import config as sim_config
from sim.game import FishingGame, State
from ui.render import Renderer
from autofish.detect.bobber import BobberHit
from autofish.capture.screen import (
    DEFAULT_SCREEN_PATH,
    ScreenGrab,
    grab_primary,
    load_screen,
    save_screen,
)
from autofish.locate.roi import DEFAULT_ROI_PATH, Roi, load_roi, save_roi
from autofish.pipeline import AutofishPipeline
from autofish.topics import ActionIntentEvent, PosEvent, Topic

WIN_W = 1320
PAD = 10
GAP = 8
HEADER_H = 78
PANEL_H = 400
LOG_H = 140
FOOTER_H = 28
WIN_H = PAD + HEADER_H + GAP + PANEL_H + GAP + LOG_H + GAP + FOOTER_H + PAD
COL_W = (WIN_W - PAD * 2 - GAP) // 2

BG = (18, 19, 22)
PANEL = (28, 30, 34)
PANEL_EDGE = (55, 58, 64)
HEADER_BG = (22, 24, 28)
TEXT = (220, 222, 218)
MUTED = (120, 124, 128)
ACCENT = (232, 168, 60)
OK = (72, 180, 110)
BAD = (210, 78, 70)
HOLD_ON = (255, 140, 40)
HOLD_OFF = (70, 74, 80)
MARK = (0, 210, 230)
SELECT_COLOR = (70, 160, 230)
LOG_BG = (16, 17, 20)
ON = (64, 160, 96)
OFF = (48, 50, 54)

_TIER_KEYS = {
    pygame.K_1: 1,
    pygame.K_2: 2,
    pygame.K_3: 3,
    pygame.K_4: 4,
    pygame.K_5: 5,
    pygame.K_6: 6,
    pygame.K_7: 7,
    pygame.K_8: 8,
}

IDLE = "idle"
SELECT = "select"
READY = "ready"


def _font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in ("SF Pro Text", "PingFang SC", "Hiragino Sans GB", "Heiti SC"):
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.SysFont(None, size, bold=bold)


def _rgb_to_surface(rgb: np.ndarray) -> pygame.Surface:
    h, w = rgb.shape[:2]
    return pygame.image.frombuffer(
        np.ascontiguousarray(rgb).tobytes(), (w, h), "RGB"
    ).convert()


def _fit(surf: pygame.Surface, max_w: int, max_h: int) -> tuple[pygame.Surface, float]:
    sw, sh = surf.get_size()
    scale = min(max_w / max(1, sw), max_h / max(1, sh), 1.0)
    if scale >= 0.999:
        return surf, 1.0
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    return pygame.transform.smoothscale(surf, (nw, nh)), scale


def _panel(screen, rect: pygame.Rect, title: str, font) -> pygame.Rect:
    pygame.draw.rect(screen, PANEL, rect)
    pygame.draw.rect(screen, PANEL_EDGE, rect, width=1)
    pygame.draw.line(
        screen, PANEL_EDGE, (rect.x, rect.y + 26), (rect.right - 1, rect.y + 26), 1
    )
    screen.blit(font.render(title, True, MUTED), (rect.x + 10, rect.y + 6))
    return pygame.Rect(rect.x + 8, rect.y + 30, rect.w - 16, rect.h - 38)


def _overlay_vision(rgb: np.ndarray, hit: BobberHit | None) -> np.ndarray:
    """原画面叠层：只标鱼漂命中（不画青框/青缘，避免干扰判断）。"""
    vis = rgb.copy()
    if hit is None:
        return vis
    x, y = int(hit.x), int(hit.y)
    x0 = max(0, min(vis.shape[1] - 1, x))
    y0 = max(0, int(hit.bar_top) - 6)
    y1 = min(
        vis.shape[0],
        int(hit.bar_top + max(hit.bar_height, 8)) + 6,
    )
    vis[y0:y1, x0 : x0 + 1] = np.clip(
        vis[y0:y1, x0 : x0 + 1].astype(np.int16) + np.array([0, 40, 50], dtype=np.int16),
        0,
        255,
    ).astype(np.uint8)
    vis[max(0, y - 4) : y + 5, max(0, x - 4) : x + 5] = MARK
    return vis


class PreviewApp:
    def __init__(self, roi_path: Path = DEFAULT_ROI_PATH) -> None:
        self.roi_path = roi_path
        self.roi: Roi | None = None
        self.hit: BobberHit | None = None
        self.frame: np.ndarray | None = None
        self.hint = "空格截屏 → 拖拽框选 · C重框 · M监控 S策略 A操作"

        self.phase = IDLE
        self.screen_grab: ScreenGrab | None = None
        self._drag_start: tuple[int, int] | None = None
        self._drag_end: tuple[int, int] | None = None
        self._img_blit_rect: pygame.Rect | None = None
        self._img_scale = 1.0
        self._sim_area = pygame.Rect(0, 0, 1, 1)

        self.game = FishingGame()
        self._sim_holding_mouse = False

        self._pipe: AutofishPipeline | None = None
        self._holding: bool | None = None
        self._intent_reason = ""
        self._logs: deque[str] = deque(maxlen=12)

        self._reload_roi()
        pygame.init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("Albion 拉鱼 · 调试壳（段独立）")
        self.clock = pygame.time.Clock()
        self.font_title = _font(12)
        self.font_pos = _font(40, bold=True)
        self.font_sub = _font(16, bold=True)
        self.font_body = _font(14)
        self.font_small = _font(12)
        self.font_log = _font(12)

        self._sim_buf = pygame.Surface(
            (sim_config.WINDOW_WIDTH, sim_config.WINDOW_HEIGHT)
        ).convert()
        self._sim_renderer = Renderer(self._sim_buf)

        if self.roi is not None:
            self.phase = READY
            self.hint = "ROI 已载入 · M监控 · S策略 · A操作"

    def _log(self, msg: str) -> None:
        self._logs.appendleft(f"{time.strftime('%H:%M:%S')}  {msg}")

    def _reload_roi(self) -> None:
        try:
            self.roi = load_roi(self.roi_path) if self.roi_path.exists() else None
        except Exception as exc:  # noqa: BLE001
            self.roi = None
            self.hint = f"ROI 失败：{exc}"

    def _ensure_pipe(self) -> AutofishPipeline:
        if self._pipe is None:
            pipe = AutofishPipeline(auto_locate=False, capture_fps=45.0)
            # 只订 POS：画面与读数同帧同频（不订 FRAME，避免 mss 快、读数慢的撕裂）
            pipe.subscribe(Topic.POS, self._on_pos)
            pipe.subscribe(Topic.ACTION_INTENT, self._on_intent)
            self._pipe = pipe
        return self._pipe

    def _shutdown_pipe(self) -> None:
        pipe = self._pipe
        if pipe is None:
            return
        pipe.unsubscribe(Topic.POS, self._on_pos)
        pipe.unsubscribe(Topic.ACTION_INTENT, self._on_intent)
        pipe.stop()
        self._pipe = None
        self.frame = None
        self.hit = None
        self._holding = None
        self._log("流水线已全部停止")

    def _on_pos(self, event: PosEvent) -> None:
        if event.frame is not None:
            self.frame = event.frame
        self.hit = event.hit

    def _on_intent(self, event: ActionIntentEvent) -> None:
        self._holding = event.holding
        self._intent_reason = event.reason
        pos_s = "—" if event.pos is None else f"{event.pos:.1f}"
        self._log(
            f"意图 {'HOLD' if event.holding else 'RELEASE'} pos={pos_s} {event.reason}"
        )

    def _toggle_monitor(self) -> None:
        if self.roi is None:
            self.hint = "先框选 ROI"
            return
        pipe = self._ensure_pipe()
        if pipe.monitor_on:
            pipe.stop_monitor()
            self.frame = None
            self.hit = None
            self._log("监控 OFF")
            self.hint = "监控已关"
        else:
            pipe.set_roi_manual(self.roi)
            pipe.start_monitor()
            self._log("监控 ON · Capture+Detect")
            self.hint = "监控中 · S开策略 · A开操作"

    def _toggle_decide(self) -> None:
        pipe = self._ensure_pipe()
        if pipe.decide_on:
            pipe.stop_decide()
            self._holding = None
            self._intent_reason = ""
            self._log("策略 OFF")
        else:
            if not pipe.monitor_on:
                self.hint = "建议先开监控(M)，否则无新 Pos"
            pipe.start_decide()
            self._log("策略 ON · Decide")

    def _toggle_act(self) -> None:
        pipe = self._ensure_pipe()
        if pipe.act_on:
            pipe.stop_act()
            self._log("操作 OFF · 已松开")
        else:
            if not pipe.decide_on:
                self.hint = "建议先开策略(S)，否则无意图"
            pipe.start_act()
            self._log("操作 ON · 真鼠标 · 光标放目标窗")

    def _capture_fullscreen(self) -> None:
        if self._pipe and self._pipe.monitor_on:
            self._pipe.stop_monitor()
        pygame.display.iconify()
        time.sleep(0.35)
        try:
            grab = grab_primary()
            save_screen(grab)
            self.screen_grab = grab
            self.phase = SELECT
            self._drag_start = self._drag_end = None
            self.hint = "拖拽框选张力条区域 → Enter 确认"
            self._log("已截全屏 · 请手框 ROI")
        except Exception as exc:  # noqa: BLE001
            self.hint = f"截图失败：{exc}"
        finally:
            pygame.display.set_mode((WIN_W, WIN_H))

    def _load_screen_for_select(self) -> None:
        try:
            self.screen_grab = load_screen(DEFAULT_SCREEN_PATH)
            self.phase = SELECT
            self._drag_start = self._drag_end = None
            self.hint = "拖拽框选 → Enter"
        except Exception as exc:  # noqa: BLE001
            self.hint = f"读截图失败：{exc}"

    def _selection_roi(self) -> Roi | None:
        if self.screen_grab is None or self._drag_start is None or self._drag_end is None:
            return None
        x0, y0 = self._drag_start
        x1, y1 = self._drag_end
        left, right = min(x0, x1), max(x0, x1)
        top, bottom = min(y0, y1), max(y0, y1)
        if right - left < 8 or bottom - top < 8:
            return None
        g = self.screen_grab
        return Roi(
            left=g.origin_left + left,
            top=g.origin_top + top,
            width=right - left,
            height=bottom - top,
        )

    def _confirm_selection(self) -> None:
        roi = self._selection_roi()
        if roi is None:
            self.hint = "框太小"
            return
        save_roi(roi, self.roi_path)
        self.roi = roi
        self.phase = READY
        self._drag_start = self._drag_end = None
        self._log(f"手框 {roi.width}x{roi.height}")
        self.hint = "M监控 S策略 A操作"

    def _view_to_image(self, pos: tuple[int, int]) -> tuple[int, int] | None:
        if self._img_blit_rect is None or self.screen_grab is None:
            return None
        r = self._img_blit_rect
        if not r.collidepoint(pos):
            return None
        ix = int((pos[0] - r.x) / self._img_scale)
        iy = int((pos[1] - r.y) / self._img_scale)
        h, w = self.screen_grab.rgb.shape[:2]
        return max(0, min(w - 1, ix)), max(0, min(h - 1, iy))

    def _sim_pos(self) -> float:
        span = float(sim_config.SAFE_RIGHT - sim_config.SAFE_LEFT)
        if span <= 1e-6:
            return 50.0
        return max(
            0.0,
            min(
                100.0,
                100.0
                * (self.game.bobber_x - float(sim_config.SAFE_LEFT))
                / span,
            ),
        )

    def _draw_toggle(
        self, x: int, y: int, label: str, on: bool, key: str
    ) -> None:
        bg = ON if on else OFF
        pygame.draw.rect(self.screen, bg, pygame.Rect(x, y, 72, 22))
        pygame.draw.rect(self.screen, PANEL_EDGE, pygame.Rect(x, y, 72, 22), 1)
        t = self.font_small.render(f"{key}:{label}", True, TEXT if on else MUTED)
        self.screen.blit(t, t.get_rect(center=(x + 36, y + 11)))

    def _draw_header(self, rect: pygame.Rect) -> None:
        pygame.draw.rect(self.screen, HEADER_BG, rect)
        pygame.draw.rect(self.screen, PANEL_EDGE, rect, width=1)
        pipe = self._pipe

        self.screen.blit(
            self.font_title.render("POS", True, MUTED), (rect.x + 12, rect.y + 6)
        )
        if self.hit is not None:
            live_s, live_c = f"{self.hit.pos:.1f}", ACCENT
        elif pipe and pipe.monitor_on:
            live_s, live_c = "无漂", BAD
        else:
            live_s, live_c = "—", MUTED
        self.screen.blit(
            self.font_pos.render(live_s, True, live_c), (rect.x + 12, rect.y + 22)
        )

        # 三开关
        tx = rect.x + 200
        self.screen.blit(
            self.font_title.render("SWITCHES", True, MUTED), (tx, rect.y + 6)
        )
        self._draw_toggle(tx, rect.y + 28, "监控", bool(pipe and pipe.monitor_on), "M")
        self._draw_toggle(tx + 80, rect.y + 28, "策略", bool(pipe and pipe.decide_on), "S")
        self._draw_toggle(tx + 160, rect.y + 28, "操作", bool(pipe and pipe.act_on), "A")
        self.screen.blit(
            self.font_small.render("操作默认关 · 勾选才真鼠标", True, MUTED),
            (tx, rect.y + 54),
        )

        # 意图
        ix = rect.x + 520
        self.screen.blit(
            self.font_title.render("INTENT", True, MUTED), (ix, rect.y + 6)
        )
        if self._holding is True:
            lamp, lab = HOLD_ON, "HOLD"
        elif self._holding is False:
            lamp, lab = HOLD_OFF, "RELEASE"
        else:
            lamp, lab = HOLD_OFF, "—"
        pygame.draw.rect(self.screen, lamp, pygame.Rect(ix, rect.y + 28, 90, 24))
        self.screen.blit(
            self.font_sub.render(lab, True, TEXT), (ix + 8, rect.y + 30)
        )
        self.screen.blit(
            self.font_small.render(self._intent_reason[:24] or "—", True, MUTED),
            (ix + 100, rect.y + 34),
        )

        # 模拟器只读状态
        sx = rect.right - 160
        self.screen.blit(
            self.font_title.render("SIM (手玩)", True, MUTED), (sx, rect.y + 6)
        )
        sim_s = f"{self._sim_pos():.1f}" if self.game.state == State.PLAYING else "—"
        self.screen.blit(
            self.font_sub.render(sim_s, True, OK if self.game.state == State.PLAYING else MUTED),
            (sx, rect.y + 28),
        )
        self.screen.blit(
            self.font_small.render(
                f"T{self.game.tier} {self.game.progress * 100:.0f}%", True, MUTED
            ),
            (sx, rect.y + 52),
        )

    def _draw_vision(self, rect: pygame.Rect) -> None:
        mon = bool(self._pipe and self._pipe.monitor_on)
        title = "MONITOR · 实时" if mon else (
            "MONITOR · 框选" if self.phase == SELECT else "MONITOR"
        )
        area = _panel(self.screen, rect, title, self.font_title)
        self._img_blit_rect = None

        if self.phase == IDLE and not mon:
            tip = self.font_body.render("空格截全屏", True, MUTED)
            self.screen.blit(tip, tip.get_rect(center=area.center))
            return

        if self.phase == SELECT and self.screen_grab is not None:
            surf, scale = _fit(_rgb_to_surface(self.screen_grab.rgb), area.w, area.h)
            blit = surf.get_rect(center=area.center)
            self.screen.blit(surf, blit)
            self._img_blit_rect = blit
            self._img_scale = scale
            if self._drag_start and self._drag_end and scale > 0:
                x0, y0 = self._drag_start
                x1, y1 = self._drag_end
                sel = pygame.Rect(
                    blit.x + int(min(x0, x1) * scale),
                    blit.y + int(min(y0, y1) * scale),
                    max(1, int(abs(x1 - x0) * scale)),
                    max(1, int(abs(y1 - y0) * scale)),
                )
                pygame.draw.rect(self.screen, SELECT_COLOR, sel, 1)
            return

        if mon:
            if self.frame is None:
                tip = self.font_body.render("等待帧…", True, MUTED)
                self.screen.blit(tip, tip.get_rect(center=area.center))
            else:
                vis = _overlay_vision(self.frame, self.hit)
                surf, _ = _fit(_rgb_to_surface(vis), area.w, area.h - 16)
                self.screen.blit(surf, surf.get_rect(midtop=(area.centerx, area.y)))
            bar = pygame.Rect(area.x + 4, area.bottom - 10, area.w - 8, 5)
            pygame.draw.rect(self.screen, PANEL_EDGE, bar)
            if self.hit is not None:
                px = int(bar.left + (self.hit.pos / 100.0) * bar.w)
                pygame.draw.rect(
                    self.screen, ACCENT, pygame.Rect(px - 2, bar.y - 2, 4, 9)
                )
            return

        if self.screen_grab is not None and self.roi is not None:
            g = self.screen_grab.rgb
            x = self.roi.left - self.screen_grab.origin_left
            y = self.roi.top - self.screen_grab.origin_top
            w, h = self.roi.width, self.roi.height
            if 0 <= x and 0 <= y and x + w <= g.shape[1] and y + h <= g.shape[0]:
                crop = g[y : y + h, x : x + w].copy()
                surf, _ = _fit(_rgb_to_surface(crop), area.w, area.h - 8)
                self.screen.blit(surf, surf.get_rect(center=area.center))

    def _draw_sim(self, rect: pygame.Rect) -> None:
        area = _panel(
            self.screen, rect, "SIMULATOR · 独立手玩（不跟策略）", self.font_title
        )
        self._sim_area = area
        self._sim_renderer.draw(self.game)
        fitted, _ = _fit(self._sim_buf, area.w, area.h)
        self.screen.blit(fitted, fitted.get_rect(center=area.center))

    def _draw_log(self, rect: pygame.Rect) -> None:
        pygame.draw.rect(self.screen, LOG_BG, rect)
        pygame.draw.rect(self.screen, PANEL_EDGE, rect, width=1)
        pygame.draw.line(
            self.screen, PANEL_EDGE, (rect.x, rect.y + 22), (rect.right - 1, rect.y + 22), 1
        )
        self.screen.blit(
            self.font_title.render("LOG", True, MUTED), (rect.x + 10, rect.y + 5)
        )
        y = rect.y + 28
        for line in self._logs:
            self.screen.blit(
                self.font_log.render(line[:110], True, TEXT), (rect.x + 10, y)
            )
            y += 15
            if y > rect.bottom - 6:
                break

    def _draw_footer(self, rect: pygame.Rect) -> None:
        tip = "空格截屏 · C重框 · M监控 S策略 A操作 · R重开模拟 · 1-8档 · Esc退出"
        self.screen.blit(
            self.font_small.render(f"{self.hint}  |  {tip}"[:130], True, MUTED),
            (rect.x + 4, rect.y + 6),
        )

    def draw(self) -> None:
        self.screen.fill(BG)
        y = PAD
        self._draw_header(pygame.Rect(PAD, y, WIN_W - PAD * 2, HEADER_H))
        y += HEADER_H + GAP
        self._draw_vision(pygame.Rect(PAD, y, COL_W, PANEL_H))
        self._draw_sim(pygame.Rect(PAD + COL_W + GAP, y, COL_W, PANEL_H))
        y += PANEL_H + GAP
        self._draw_log(pygame.Rect(PAD, y, WIN_W - PAD * 2, LOG_H))
        y += LOG_H + GAP
        self._draw_footer(pygame.Rect(PAD, y, WIN_W - PAD * 2, FOOTER_H))

    def _handle_sim_input(self, event: pygame.event.Event) -> None:
        """模拟器只吃本窗鼠标，与 Act 无关。"""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._sim_area.collidepoint(event.pos):
                if self.game.state == State.PLAYING:
                    self.game.set_holding(True)
                else:
                    self.game.start()
                    self.game.set_holding(True)
                self._sim_holding_mouse = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._sim_holding_mouse:
                self.game.set_holding(False)
                self._sim_holding_mouse = False

    def _on_select_mouse(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pt = self._view_to_image(event.pos)
            if pt:
                self._drag_start = self._drag_end = pt
        elif event.type == pygame.MOUSEMOTION and self._drag_start is not None:
            if event.buttons[0]:
                pt = self._view_to_image(event.pos)
                if pt:
                    self._drag_end = pt
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            pt = self._view_to_image(event.pos)
            if pt and self._drag_start is not None:
                self._drag_end = pt

    def run(self) -> int:
        running = True
        while running:
            dt = self.clock.tick(sim_config.FPS) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if self.phase == SELECT:
                            self.phase = IDLE
                            self.hint = "已取消框选"
                            self._drag_start = self._drag_end = None
                        else:
                            running = False
                    elif event.key == pygame.K_SPACE:
                        self._capture_fullscreen()
                    elif event.key == pygame.K_m:
                        self._toggle_monitor()
                    elif event.key == pygame.K_s:
                        self._toggle_decide()
                    elif event.key == pygame.K_a:
                        self._toggle_act()
                    elif event.key == pygame.K_c:
                        if DEFAULT_SCREEN_PATH.exists():
                            self._load_screen_for_select()
                        else:
                            self.hint = "尚无截图"
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if self.phase == SELECT:
                            self._confirm_selection()
                    elif event.key == pygame.K_r:
                        self.game.reset()
                    elif event.key in _TIER_KEYS:
                        self.game.set_tier(_TIER_KEYS[event.key])
                elif self.phase == SELECT:
                    self._on_select_mouse(event)
                else:
                    self._handle_sim_input(event)

            self.game.update(dt)
            self.draw()
            pygame.display.flip()

        self._shutdown_pipe()
        pygame.quit()
        return 0


def main() -> int:
    return PreviewApp().run()


AutofishApp = PreviewApp


if __name__ == "__main__":
    raise SystemExit(main())
