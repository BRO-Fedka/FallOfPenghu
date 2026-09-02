from __future__ import annotations

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.world.clock import SPEEDS, Clock

PAN_PIXELS_PER_SEC = 680.0
ZOOM_IN = 1 / 1.12
ZOOM_OUT = 1.12

SPEED_KEYS = {
    pygame.K_1: SPEEDS[0],
    pygame.K_2: SPEEDS[1],
    pygame.K_3: SPEEDS[2],
    pygame.K_4: SPEEDS[3],
    pygame.K_5: SPEEDS[4],
    pygame.K_6: SPEEDS[5],
    pygame.K_7: SPEEDS[6],
}


class Input:
    """Map and clock controls. Does not draw. Does not import shaders."""

    def __init__(self, home_x: float, home_y: float, home_view_m: float) -> None:
        self.quit = False
        self.dragging = False
        self.home_x = home_x
        self.home_y = home_y
        self.home_view_m = home_view_m
        self.resize_to: tuple[int, int] | None = None

    def handle_event(
        self,
        event: pygame.event.Event,
        camera: Camera,
        clock: Clock,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
    ) -> None:
        if event.type == pygame.QUIT:
            self.quit = True
        elif event.type == pygame.VIDEORESIZE:
            self.resize_to = (event.w, event.h)
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.quit = True
            elif event.key == pygame.K_r:
                camera.radar_mode = not camera.radar_mode
            elif event.key == pygame.K_SPACE:
                clock.toggle_pause()
            elif event.key in SPEED_KEYS:
                clock.set_speed(SPEED_KEYS[event.key])
            elif event.key == pygame.K_HOME:
                camera.move_to(self.home_x, self.home_y, self.home_view_m)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 2:
                self.dragging = True
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 2:
                self.dragging = False
        elif event.type == pygame.MOUSEMOTION:
            if self.dragging:
                camera.pan_pixels(event.rel[0], event.rel[1], screen_w)
        elif event.type == pygame.MOUSEWHEEL:
            factor = ZOOM_IN if event.y > 0 else ZOOM_OUT
            camera.zoom_at_screen(factor, *mouse, screen_w, screen_h)

    def handle_held(
        self, camera: Camera, dt_wall: float, screen_w: int
    ) -> None:
        keys = pygame.key.get_pressed()
        move = PAN_PIXELS_PER_SEC * dt_wall * camera.meters_per_pixel(screen_w)
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            camera.pan_world(0.0, move)
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            camera.pan_world(0.0, -move)
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            camera.pan_world(-move, 0.0)
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            camera.pan_world(move, 0.0)
