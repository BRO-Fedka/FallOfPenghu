from __future__ import annotations

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.render.static.scene import palette_for
from fall_of_penghu.render.static.tod import phase_label
from fall_of_penghu.world.clock import DEBUG_SPEED, SPEEDS, Clock

PANEL_H = 40
DEBUG_H = 44
BTN_W = 52
BTN_H = 26
BTN_GAP = 6
CLOCK_W = 148


class Hud:
    """Chrome overlay. Top bar is always on; debug text only in debug_mode."""

    def __init__(self) -> None:
        self.font = pygame.font.SysFont("consolas", 16)
        self.small = pygame.font.SysFont("consolas", 14)
        self._buttons: list[tuple[pygame.Rect, float]] = []
        self._panel_h = PANEL_H

    def hits_chrome(self, x: int, y: int, screen_h: int, debug: bool) -> bool:
        if y < self._panel_h:
            return True
        return bool(debug and y >= screen_h - DEBUG_H)

    def _layout(self, debug: bool) -> None:
        speeds: tuple[float, ...] = SPEEDS + ((DEBUG_SPEED,) if debug else ())
        x = 12 + CLOCK_W
        y = (PANEL_H - BTN_H) // 2
        self._buttons = []
        for speed in speeds:
            self._buttons.append((pygame.Rect(x, y, BTN_W, BTN_H), speed))
            x += BTN_W + BTN_GAP

    def handle_event(self, event: pygame.event.Event, clock: Clock, debug: bool) -> bool:
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False
        self._layout(debug)
        for rect, speed in self._buttons:
            if rect.collidepoint(event.pos):
                clock.set_speed(speed)
                return True
        return False

    def blit(
        self,
        renderer,
        *,
        camera: Camera,
        clock: Clock,
        fps: float,
        backend: str,
        stats: dict[str, int],
        mouse_world: tuple[float, float],
        screen_w: int,
        screen_h: int,
    ) -> None:
        debug = camera.debug_mode
        self._layout(debug)
        pal = palette_for(camera.radar_mode, clock.time_of_day)
        ink = pal["hud"]
        bar = pygame.Surface((screen_w, PANEL_H), pygame.SRCALPHA)
        bar.fill((8, 10, 12, 170))

        clock_surf = self.font.render(clock.clock_label(), True, ink)
        bar.blit(clock_surf, (12, (PANEL_H - clock_surf.get_height()) // 2))

        for rect, speed in self._buttons:
            selected = abs(clock.speed - speed) < 1e-6
            fill = (ink[0], ink[1], ink[2], 55 if selected else 18)
            pygame.draw.rect(bar, fill, rect, border_radius=3)
            pygame.draw.rect(bar, (*ink, 200 if selected else 90), rect, 1, border_radius=3)
            label = clock.speed_label(speed)
            text = self.small.render(label, True, ink)
            bar.blit(
                text,
                (
                    rect.x + (rect.w - text.get_width()) // 2,
                    rect.y + (rect.h - text.get_height()) // 2,
                ),
            )

        if debug:
            badge = self.small.render("DEBUG", True, ink)
            bar.blit(badge, (screen_w - badge.get_width() - 12, (PANEL_H - badge.get_height()) // 2))

        renderer.overlay(bar, (0, 0))

        if debug:
            wx, wy = mouse_world
            hud = (
                f"{fps:5.1f} fps   "
                f"{backend}   "
                f"{phase_label(clock.time_of_day)}   "
                f"tod {clock.time_of_day:.3f}   "
                f"{clock.speed_label()}   "
                f"view {camera.view_width_m / 1000:6.2f} km   "
                f"{camera.meters_per_pixel(screen_w):7.2f} m/px   "
                f"cam {camera.x:.0f},{camera.y:.0f}   "
                f"cursor {wx:.0f},{wy:.0f} m   "
                f"{'RADAR' if camera.radar_mode else 'MAP'}   "
                f"draw c{stats['coast']} v{stats['vegetation']} "
                f"b{stats['buildings']} r{stats['roads']}"
            )
            hint = (
                "WASD pan  LMB drag  Q/E zoom  C/Home fly  R radar  Space 0x  "
                "F1-F6 speed  F7 32x  F12 debug  Home reset  Esc quit"
            )
            footer = pygame.Surface((screen_w, DEBUG_H), pygame.SRCALPHA)
            footer.fill((8, 10, 12, 170))
            footer.blit(self.small.render(hud, True, ink), (10, 4))
            footer.blit(self.small.render(hint, True, ink), (10, 22))
            renderer.overlay(footer, (0, screen_h - DEBUG_H))
