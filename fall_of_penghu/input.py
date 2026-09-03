from __future__ import annotations

import pygame

from fall_of_penghu.camera import KEYBOARD_TICK_S, Camera
from fall_of_penghu.world.clock import DEBUG_SPEED, SPEEDS, Clock

PAN_SPEED_PX = 5.0
ZOOM_DELTA_DIVISOR = 600.0
WHEEL_SCALE = 100.0
WHEEL_DEADZONE = 2.0
ZOOM_KEY_DELTA = 10.0
MAX_KEY_TICKS = 32.0

SPEED_KEYS = {
    pygame.K_F1: SPEEDS[0],
    pygame.K_F2: SPEEDS[1],
    pygame.K_F3: SPEEDS[2],
    pygame.K_F4: SPEEDS[3],
    pygame.K_F5: SPEEDS[4],
    pygame.K_F6: SPEEDS[5],
}

ZOOM_IN_KEYS = (pygame.K_e, pygame.K_EQUALS, pygame.K_KP_PLUS)
ZOOM_OUT_KEYS = (pygame.K_q, pygame.K_MINUS, pygame.K_KP_MINUS)


def _key_ticks(dt_wall: float) -> float:
    return min(max(dt_wall, 0.0) / KEYBOARD_TICK_S, MAX_KEY_TICKS)


def _zoom_factor(delta: float) -> float:
    return 1.0 + delta / ZOOM_DELTA_DIVISOR


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
            elif event.key == pygame.K_F7:
                if camera.debug_mode:
                    clock.set_speed(DEBUG_SPEED)
            elif event.key == pygame.K_F12:
                camera.debug_mode = not camera.debug_mode
                if not camera.debug_mode:
                    clock.cap_to_player_speeds()
            elif event.key in (pygame.K_HOME, pygame.K_c):
                camera.fly_to(self.home_x, self.home_y, self.home_view_m)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                self.dragging = True
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.dragging = False
        elif event.type == pygame.MOUSEMOTION:
            if self.dragging:
                camera.pan_pixels(event.rel[0], event.rel[1], screen_w, screen_h)
        elif event.type == pygame.MOUSEWHEEL:
            delta = -event.y * WHEEL_SCALE
            if abs(delta) < WHEEL_DEADZONE:
                return
            camera.zoom_at_screen(
                _zoom_factor(delta), *mouse, screen_w, screen_h
            )

    def handle_held(
        self, camera: Camera, dt_wall: float, screen_w: int, screen_h: int
    ) -> None:
        keys = pygame.key.get_pressed()
        ticks = _key_ticks(dt_wall)
        step = PAN_SPEED_PX * ticks
        dx = 0.0
        dy = 0.0
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dy += step
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dy -= step
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            dx += step
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            dx -= step
        if dx or dy:
            camera.pan_pixels(dx, dy, screen_w, screen_h)

        zoom_in = any(keys[k] for k in ZOOM_IN_KEYS)
        zoom_out = any(keys[k] for k in ZOOM_OUT_KEYS)
        if zoom_in == zoom_out:
            return
        signed = -ZOOM_KEY_DELTA if zoom_in else ZOOM_KEY_DELTA
        factor = _zoom_factor(signed) ** ticks
        camera.zoom_at_screen(
            factor, screen_w * 0.5, screen_h * 0.5, screen_w, screen_h
        )
