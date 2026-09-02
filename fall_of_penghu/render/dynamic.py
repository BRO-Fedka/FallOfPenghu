from __future__ import annotations

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.render.scene import palette_for
from fall_of_penghu.world.entities import Entities


class DynamicRenderer:
    """Icons for world.entities. pygame.draw on a Surface, then map overlay."""

    def draw(
        self,
        renderer,
        camera: Camera,
        entities: Entities,
        screen_w: int,
        screen_h: int,
    ) -> None:
        if not entities.items:
            return
        pal = palette_for(camera.radar_mode)
        color = pal["hud"]
        layer = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
        for item in entities.items:
            sx, sy = camera.world_to_screen(item.x, item.y, screen_w, screen_h)
            pygame.draw.circle(layer, color, (int(sx), int(sy)), 5)
        renderer.overlay(layer, (0, 0))
