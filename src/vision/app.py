"""统一窗口四步：①截全屏 ②框选区 ③开监控 ④持续读数；右侧附模拟器。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pygame

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sim import config as sim_config
from sim.game import FishingGame, State
from ui.render import Renderer
from vision.bobber import BobberHit, find_bobber, pixel_to_pos
from vision.capture import (
    DEFAULT_SCREEN_PATH,
    ScreenGrab,
    grab_primary,
    grab_roi,
    load_screen,
    save_screen,
)
from vision.hsv_calib import load_zone_hsv, sample_zone_hsv, save_zone_hsv
from vision.roi import DEFAULT_ROI_PATH, Roi, load_roi, save_roi
from vision.smooth import PosSmoother

# ---- 三区布局 ----
WIN_W = 1280
PAD = 14
GAP = 12
READOUT_H = 96
FOOTER_H = 46
PANEL_H = 540
WIN_H = PAD + READOUT_H + GAP + PANEL_H + GAP + FOOTER_H + PAD
COL_W = (WIN_W - PAD * 2 - GAP) // 2

BG = (24, 26, 30)
PANEL = (38, 42, 48)
PANEL_EDGE = (60, 66, 74)
TEXT = (235, 235, 228)
MUTED = (140, 146, 140)
ACCENT = (255, 186, 72)
OK = (110, 200, 130)
BAD = (230, 100, 90)
MARK = (0, 230, 255)
SELECT_COLOR = (80, 180, 255)

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

# 阶段
IDLE = "idle"          # 未截图
SELECT = "select"      # 框选区域
READY = "ready"        # 区域已定，待开监控
MONITOR = "monitor"    # 持续监控中


def _font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in ("PingFang SC", "Hiragino Sans GB", "Songti SC", "Heiti SC"):
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.SysFont(None, size, bold=bold)


def _rgb_to_surface(rgb: np.ndarray) -> pygame.Surface:
    h, w = rgb.shape[:2]
    return pygame.image.frombuffer(np.ascontiguousarray(rgb).tobytes(), (w, h), "RGB").convert()


def _fit(surf: pygame.Surface, max_w: int, max_h: int) -> tuple[pygame.Surface, float]:
    sw, sh = surf.get_size()
    scale = min(max_w / max(1, sw), max_h / max(1, sh), 1.0)
    if scale >= 0.999:
        return surf, 1.0
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    return pygame.transform.smoothscale(surf, (nw, nh)), scale


def _panel(screen, rect, title, font) -> pygame.Rect:
    pygame.draw.rect(screen, PANEL, rect, border_radius=12)
    pygame.draw.rect(screen, PANEL_EDGE, rect, width=1, border_radius=12)
    label = font.render(title, True, MUTED)
    screen.blit(label, (rect.x + 14, rect.y + 10))
    return pygame.Rect(rect.x + 12, rect.y + 32, rect.w - 24, rect.h - 44)


def _overlay_vision(rgb: np.ndarray, hit: BobberHit | None) -> np.ndarray:
    """轻量叠层：不整片染绿，只标绿条边界与鱼漂。"""
    vis = rgb.copy()
    if hit is not None and hit.bar_width > 0:
        zx = int(hit.bar_left)
        zw = int(hit.bar_width)
        zh_est = max(8, min(vis.shape[0], int(hit.bar_width * 0.12)))
        zy = max(0, int(hit.y - zh_est / 2))
        y1 = min(vis.shape[0], zy + zh_est)
        # 左右界细线
        x_l0, x_l1 = max(0, zx), min(vis.shape[1], zx + 2)
        x_r0, x_r1 = max(0, zx + zw - 2), min(vis.shape[1], zx + zw)
        vis[zy:y1, x_l0:x_l1] = (80, 220, 100)
        vis[zy:y1, x_r0:x_r1] = (80, 220, 100)
        x, y = int(hit.x), int(hit.y)
        vis[max(0, y - 4) : y + 5, max(0, x - 4) : x + 5] = MARK
        # 竖线
        x0, x1 = max(0, x), min(vis.shape[1], x + 1)
        vis[:, x0:x1] = np.clip(
            vis[:, x0:x1].astype(np.int16) + np.array([0, 40, 50], dtype=np.int16),
            0,
            255,
        ).astype(np.uint8)
        vis[max(0, y - 4) : y + 5, max(0, x - 4) : x + 5] = MARK
    return vis


class VisionApp:
    def __init__(self, roi_path: Path = DEFAULT_ROI_PATH) -> None:
        self.roi_path = roi_path
        self.roi: Roi | None = None
        self.hit: BobberHit | None = None
        self.frame: np.ndarray | None = None
        self.grab_error = ""
        self.hint = "第 1 步：按 空格 截全屏"

        self.phase = IDLE
        self.screen_grab: ScreenGrab | None = None
        self._drag_start: tuple[int, int] | None = None
        self._drag_end: tuple[int, int] | None = None
        self._img_blit_rect: pygame.Rect | None = None
        self._img_scale = 1.0
        self._sim_area = pygame.Rect(0, 0, 1, 1)
        self._last_grab_ms = 0.0
        self._smoother = PosSmoother(window=7, hold_lost=12)
        self._zone_hsv = load_zone_hsv()
        self._pipette = False  # P：点绿条吸色

        self.game = FishingGame()
        self._sim_holding_mouse = False

        self._reload_roi()

        pygame.init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("Albion 拉鱼 · 截图 → 框选 → 监控 → 读数")
        self.clock = pygame.time.Clock()
        self.font_title = _font(20)
        self.font_pos = _font(64, bold=True)
        self.font_sub = _font(26, bold=True)
        self.font_body = _font(17)
        self.font_small = _font(14)

        self._sim_buf = pygame.Surface(
            (sim_config.WINDOW_WIDTH, sim_config.WINDOW_HEIGHT)
        ).convert()
        self._sim_renderer = Renderer(self._sim_buf)

        # 若有已存 ROI，直接进入 READY
        if self.roi is not None:
            self.phase = READY
            self.hint = "区域已载入：按 M 开始持续监控"

    # ---- 状态流转 ----
    def _reload_roi(self) -> None:
        try:
            if not self.roi_path.exists():
                self.roi = None
                return
            self.roi = load_roi(self.roi_path)
        except Exception as exc:  # noqa: BLE001
            self.roi = None
            self.hint = f"ROI 读取失败：{exc}"

    def _capture_fullscreen(self) -> None:
        pygame.display.iconify()
        time.sleep(0.35)
        try:
            grab = grab_primary()
            save_screen(grab)
            self.screen_grab = grab
            self.phase = SELECT
            self._drag_start = self._drag_end = None
            self.hint = "第 2 步：拖拽框选监控区域 → Enter 确认"
            self.grab_error = ""
        except Exception as exc:  # noqa: BLE001
            self.grab_error = str(exc)
            self.hint = f"截图失败：{exc}"
        finally:
            pygame.display.set_mode((WIN_W, WIN_H))

    def _load_screen_for_select(self) -> None:
        try:
            self.screen_grab = load_screen(DEFAULT_SCREEN_PATH)
            self.phase = SELECT
            self._drag_start = self._drag_end = None
            self.hint = "拖拽框选监控区域 → Enter 确认"
        except Exception as exc:  # noqa: BLE001
            self.hint = f"读取截图失败：{exc}"

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
            self.hint = "框太小，请重新拖拽"
            return
        save_roi(roi, self.roi_path)
        self.roi = roi
        self.phase = READY
        self.hint = "第 3 步：按 M 开始持续监控（再按 M 停止）"
        self._drag_start = self._drag_end = None

    def _toggle_monitor(self) -> None:
        if self.roi is None:
            self.hint = "请先截全屏并框选区域"
            return
        if self.phase == MONITOR:
            self.phase = READY
            self._smoother.reset()
            self.hint = "已停止 · 按 M 重新开始"
        else:
            self.phase = MONITOR
            self._smoother.reset()
            self.hint = "监控中 · P 吸色点绿条 · M 停止"

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

    def _view_to_frame(self, pos: tuple[int, int]) -> tuple[int, int] | None:
        """监控画面坐标 → 帧内像素。"""
        if self._img_blit_rect is None or self.frame is None:
            return None
        r = self._img_blit_rect
        if not r.collidepoint(pos):
            return None
        ix = int((pos[0] - r.x) / self._img_scale)
        iy = int((pos[1] - r.y) / self._img_scale)
        h, w = self.frame.shape[:2]
        return max(0, min(w - 1, ix)), max(0, min(h - 1, iy))

    def _apply_pipette(self, pos: tuple[int, int]) -> None:
        pt = self._view_to_frame(pos)
        if pt is None or self.frame is None:
            self.hint = "请在左侧监控画面上点击绿色区域"
            return
        x, y = pt
        zone = sample_zone_hsv(self.frame, x, y)
        save_zone_hsv(zone)
        self._zone_hsv = zone
        self._smoother.reset()
        self._pipette = False
        self.hint = (
            f"已吸色 HSV {zone.lower.tolist()}~{zone.upper.tolist()} → data/hsv_zone.json"
        )

    # ---- 每帧监控 ----
    def _tick_monitor(self) -> None:
        if self.phase != MONITOR or self.roi is None:
            if self.phase != MONITOR:
                self.frame = None
                self.hit = None
            return
        now = time.perf_counter()
        if now - self._last_grab_ms < 0.03:
            return
        self._last_grab_ms = now
        try:
            rgb = grab_roi(self.roi)
            self.frame = rgb
            raw = find_bobber(
                rgb, lower=self._zone_hsv.lower, upper=self._zone_hsv.upper
            )
            self.hit = self._smoother.push(raw)
            self.grab_error = ""
        except Exception as exc:  # noqa: BLE001
            self.grab_error = str(exc)
            self.hit = self._smoother.push(None)

    def _sim_pos(self) -> float:
        return pixel_to_pos(self.game.bobber_x, sim_config.TENSION_W)

    # ---- 绘制 ----
    def _draw_readout(self, rect: pygame.Rect) -> None:
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=12)
        pygame.draw.rect(self.screen, PANEL_EDGE, rect, width=1, border_radius=12)

        title = self.font_title.render("鱼漂读数（真机）", True, MUTED)
        self.screen.blit(title, (rect.x + 20, rect.y + 10))
        sub = self.font_small.render("0 = 最左 · 100 = 最右", True, MUTED)
        self.screen.blit(sub, (rect.x + 20, rect.y + 32))

        if self.phase == MONITOR:
            if self.hit is not None:
                live_s, live_c = f"{self.hit.pos:.1f}", ACCENT
            else:
                live_s, live_c = "—", BAD
        elif self.phase == SELECT:
            live_s, live_c = "框选中", SELECT_COLOR
        elif self.phase == READY:
            live_s, live_c = "待监控", MUTED
        else:
            live_s, live_c = "—", MUTED
        live = self.font_pos.render(live_s, True, live_c)
        self.screen.blit(live, (rect.x + 20, rect.y + 52))

        mid_x = rect.centerx + 40
        pygame.draw.line(self.screen, PANEL_EDGE, (mid_x - 24, rect.y + 14), (mid_x - 24, rect.bottom - 14), 1)
        st = self.font_title.render("模拟器读数", True, MUTED)
        self.screen.blit(st, (mid_x, rect.y + 10))
        sim_s = f"{self._sim_pos():.1f}" if self.game.state == State.PLAYING else "—"
        sim_c = OK if self.game.state == State.PLAYING else MUTED
        sim = self.font_sub.render(sim_s, True, sim_c)
        self.screen.blit(sim, (mid_x, rect.y + 50))
        tip = self.font_small.render(
            f"进度 {self.game.progress * 100:.0f}% · T{self.game.tier}", True, MUTED
        )
        self.screen.blit(tip, (mid_x, rect.y + 82))

    def _draw_vision_panel(self, rect: pygame.Rect) -> None:
        titles = {
            IDLE: "全屏截图预览",
            SELECT: "框选监控区域",
            READY: "监控区域（待开始）",
            MONITOR: "监控画面",
        }
        area = _panel(self.screen, rect, titles[self.phase], self.font_small)
        self._img_blit_rect = None

        if self.phase in (IDLE,):
            tip = self.font_body.render("按 空格 截取全屏", True, MUTED)
            self.screen.blit(tip, tip.get_rect(center=area.center))
            return

        if self.phase == SELECT:
            if self.screen_grab is None:
                return
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
                ov = pygame.Surface(sel.size, pygame.SRCALPHA)
                ov.fill((80, 180, 255, 55))
                self.screen.blit(ov, sel.topleft)
                pygame.draw.rect(self.screen, SELECT_COLOR, sel, 2)
            return

        # READY / MONITOR：显示 ROI 区域（若在监控则实时）
        if self.phase == MONITOR:
            if self.frame is None:
                tip = self.font_body.render("等待画面…", True, MUTED)
                self.screen.blit(tip, tip.get_rect(center=area.center))
                return
            vis = _overlay_vision(self.frame, self.hit)
            surf, scale = _fit(_rgb_to_surface(vis), area.w, area.h - 22)
            blit = surf.get_rect(midtop=(area.centerx, area.y))
            self.screen.blit(surf, blit)
            self._img_blit_rect = blit
            self._img_scale = scale
            if self._pipette:
                tag = self.font_small.render("吸色：点击画面中的绿色", True, SELECT_COLOR)
                self.screen.blit(tag, (area.x + 4, area.y))
        else:
            # READY：显示标定时的 ROI 缩略（从全屏图扣这一块）
            if self.screen_grab is not None and self.roi is not None:
                g = self.screen_grab.rgb
                x, y = self.roi.left - self.screen_grab.origin_left, self.roi.top - self.screen_grab.origin_top
                w, h = self.roi.width, self.roi.height
                if x >= 0 and y >= 0 and x + w <= g.shape[1] and y + h <= g.shape[0]:
                    crop = g[y:y + h, x:x + w]
                    surf, scale = _fit(_rgb_to_surface(crop), area.w, area.h - 22)
                    blit = surf.get_rect(midtop=(area.centerx, area.y))
                    self.screen.blit(surf, blit)
                    self._img_blit_rect = blit
                    self._img_scale = scale
                else:
                    tip = self.font_body.render("区域越界，请重新框选", True, MUTED)
                    self.screen.blit(tip, tip.get_rect(center=area.center))
            else:
                tip = self.font_body.render("无区域预览", True, MUTED)
                self.screen.blit(tip, tip.get_rect(center=area.center))

        # 底部 0–100 条
        bar = pygame.Rect(area.x + 8, area.bottom - 16, area.w - 16, 8)
        pygame.draw.rect(self.screen, PANEL_EDGE, bar, border_radius=4)
        for t, lab in ((0.0, "0"), (0.5, "50"), (1.0, "100")):
            x = int(bar.left + t * bar.w)
            pygame.draw.line(self.screen, MUTED, (x, bar.top - 2), (x, bar.bottom + 2), 1)
            tag = self.font_small.render(lab, True, MUTED)
            self.screen.blit(tag, tag.get_rect(midtop=(x, bar.bottom + 1)))
        if self.phase == MONITOR and self.hit is not None:
            px = int(bar.left + (self.hit.pos / 100.0) * bar.w)
            pygame.draw.circle(self.screen, ACCENT, (px, bar.centery), 6)

    def _draw_sim_panel(self, rect: pygame.Rect) -> None:
        area = _panel(self.screen, rect, "模拟器（鼠标点按练习）", self.font_small)
        self._sim_area = area
        self._sim_renderer.draw(self.game)
        fitted, _ = _fit(self._sim_buf, area.w, area.h)
        self.screen.blit(fitted, fitted.get_rect(center=area.center))

    def _draw_footer(self, rect: pygame.Rect) -> None:
        tips = {
            IDLE: "空格 截全屏",
            SELECT: "拖拽框选 · Enter 确认 · Esc 取消 · 空格 重截",
            READY: "M 开始监控 · 空格 重截 · C 重框",
            MONITOR: "M 停止 · P 吸色 · 读数已平滑",
        }
        phase_tag = f"{self.phase.upper()}"
        if self._pipette:
            phase_tag += "+PIPETTE"
        msg = f"[{phase_tag}]  {self.hint}"
        img = self.font_small.render(msg[:120], True, MUTED)
        self.screen.blit(img, img.get_rect(midleft=(rect.x + 8, rect.centery)))
        tip = self.font_small.render(tips[self.phase], True, MUTED)
        self.screen.blit(tip, tip.get_rect(midright=(rect.right - 8, rect.centery)))

    def draw(self) -> None:
        self.screen.fill(BG)
        y = PAD
        self._draw_readout(pygame.Rect(PAD, y, WIN_W - PAD * 2, READOUT_H))
        y += READOUT_H + GAP
        self._draw_vision_panel(pygame.Rect(PAD, y, COL_W, PANEL_H))
        self._draw_sim_panel(pygame.Rect(PAD + COL_W + GAP, y, COL_W, PANEL_H))
        y += PANEL_H + GAP
        self._draw_footer(pygame.Rect(PAD, y, WIN_W - PAD * 2, FOOTER_H))

    # ---- 输入 ----
    def _handle_sim_input(self, event: pygame.event.Event) -> None:
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
                self._drag_start = pt
                self._drag_end = pt
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
                        if self._pipette:
                            self._pipette = False
                            self.hint = "已取消吸色"
                        elif self.phase == SELECT:
                            self.phase = IDLE
                            self.hint = "已取消框选"
                            self._drag_start = self._drag_end = None
                        else:
                            running = False
                    elif event.key == pygame.K_SPACE:
                        self._capture_fullscreen()
                    elif event.key == pygame.K_m:
                        self._toggle_monitor()
                    elif event.key == pygame.K_p:
                        if self.phase == MONITOR and self.frame is not None:
                            self._pipette = not self._pipette
                            self.hint = (
                                "吸色模式：点击左侧画面中的绿色"
                                if self._pipette
                                else "已退出吸色"
                            )
                        else:
                            self.hint = "请先 M 开始监控再吸色"
                    elif event.key == pygame.K_c:
                        if DEFAULT_SCREEN_PATH.exists():
                            self._load_screen_for_select()
                        else:
                            self.hint = "尚无截图，先按空格"
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if self.phase == SELECT:
                            self._confirm_selection()
                    elif event.key == pygame.K_r:
                        self.game.reset()
                    elif event.key in _TIER_KEYS:
                        self.game.set_tier(_TIER_KEYS[event.key])
                elif self.phase == SELECT:
                    self._on_select_mouse(event)
                elif self.phase == MONITOR and self._pipette:
                    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        self._apply_pipette(event.pos)
                elif self.phase in (READY, MONITOR):
                    self._handle_sim_input(event)

            self._tick_monitor()
            self.game.update(dt)
            self.draw()
            pygame.display.flip()

        pygame.quit()
        return 0


def main() -> int:
    return VisionApp().run()


if __name__ == "__main__":
    raise SystemExit(main())