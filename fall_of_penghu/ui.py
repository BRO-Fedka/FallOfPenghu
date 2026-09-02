from __future__ import annotations

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.render.static.scene import palette_for
from fall_of_penghu.world.clock import Clock


class Hud:
    """Chrome overlay. Reads camera, clock, and draw stats. Does not move the world."""

    def __init__(self) -> None:
        self.font = pygame.font.SysFont("consolas", 16)

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
    ) -> None:
        pal = palette_for(camera.radar_mode)
        wx, wy = mouse_world
        hud = (
            f"{fps:5.1f} fps   "
            f"{backend}   "
            f"{clock.clock_label()}   "
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
            "WASD pan  MMB drag  wheel zoom  R radar  Space pause  "
            "1-7 speed  Home reset  Esc quit"
        )
        renderer.overlay(self.font.render(hud, True, pal["hud"]), (10, 8))
        renderer.overlay(self.font.render(hint, True, pal["hud"]), (10, 28))
