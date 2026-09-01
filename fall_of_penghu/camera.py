from __future__ import annotations

import math


class Camera:
    """World camera in planar meters. Screen Y grows down; world Y grows north."""

    def __init__(
        self,
        *,
        center_x: float,
        center_y: float,
        view_width_m: float,
        min_view_width_m: float = 300.0,
        max_view_width_m: float = 200_000.0,
        smooth_tau_s: float = 0.14,
    ) -> None:
        self.min_view_width_m = min_view_width_m
        self.max_view_width_m = max_view_width_m
        self.smooth_tau_s = smooth_tau_s
        self.frame = (-100_000.0, -100_000.0, 100_000.0, 100_000.0)
        self.x = center_x
        self.y = center_y
        self.view_width_m = view_width_m
        self.target_x = center_x
        self.target_y = center_y
        self.target_view_width_m = view_width_m

    def set_frame(self, minx: float, miny: float, maxx: float, maxy: float) -> None:
        self.frame = (minx, miny, maxx, maxy)

    def _max_width(self, screen_w: int, screen_h: int) -> float:
        minx, miny, maxx, maxy = self.frame
        frame_w = max(1.0, maxx - minx)
        frame_h = max(1.0, maxy - miny)
        aspect_cap = frame_h * max(screen_w, 1) / max(screen_h, 1)
        return min(self.max_view_width_m, frame_w, aspect_cap)

    def _clamp_width(self, width_m: float, screen_w: int = 1280, screen_h: int = 720) -> float:
        return max(self.min_view_width_m, min(self._max_width(screen_w, screen_h), width_m))

    def _clamp_center(
        self, x: float, y: float, width_m: float, screen_w: int, screen_h: int
    ) -> tuple[float, float]:
        minx, miny, maxx, maxy = self.frame
        mpp = width_m / max(screen_w, 1)
        half_w = width_m * 0.5
        half_h = mpp * screen_h * 0.5
        lo_x = minx + half_w
        hi_x = maxx - half_w
        lo_y = miny + half_h
        hi_y = maxy - half_h
        if lo_x > hi_x:
            x = (minx + maxx) * 0.5
        else:
            x = min(max(x, lo_x), hi_x)
        if lo_y > hi_y:
            y = (miny + maxy) * 0.5
        else:
            y = min(max(y, lo_y), hi_y)
        return x, y

    def _world_from(
        self,
        x: float,
        y: float,
        width_m: float,
        sx: float,
        sy: float,
        screen_w: int,
        screen_h: int,
    ) -> tuple[float, float]:
        mpp = width_m / max(screen_w, 1)
        wx = x + (sx - screen_w * 0.5) * mpp
        wy = y - (sy - screen_h * 0.5) * mpp
        return wx, wy

    def move_to(self, x: float, y: float, view_width_m: float | None = None) -> None:
        self.target_x = x
        self.target_y = y
        if view_width_m is not None:
            self.target_view_width_m = view_width_m

    def meters_per_pixel(self, screen_w: int) -> float:
        return self.view_width_m / max(screen_w, 1)

    def world_bounds(self, screen_w: int, screen_h: int) -> tuple[float, float, float, float]:
        mpp = self.meters_per_pixel(screen_w)
        half_w = self.view_width_m * 0.5
        half_h = mpp * screen_h * 0.5
        return (
            self.x - half_w,
            self.y - half_h,
            self.x + half_w,
            self.y + half_h,
        )

    def screen_to_world(
        self, sx: float, sy: float, screen_w: int, screen_h: int
    ) -> tuple[float, float]:
        return self._world_from(
            self.x, self.y, self.view_width_m, sx, sy, screen_w, screen_h
        )

    def pan_pixels(self, dx_px: float, dy_px: float, screen_w: int) -> None:
        mpp = self.meters_per_pixel(screen_w)
        dx = -dx_px * mpp
        dy = dy_px * mpp
        self.x += dx
        self.y += dy
        self.target_x += dx
        self.target_y += dy

    def pan_world(self, dx_m: float, dy_m: float) -> None:
        self.target_x += dx_m
        self.target_y += dy_m

    def zoom_at_screen(
        self,
        factor: float,
        sx: float,
        sy: float,
        screen_w: int,
        screen_h: int,
    ) -> None:
        world = self.screen_to_world(sx, sy, screen_w, screen_h)
        self.target_view_width_m = self._clamp_width(
            self.target_view_width_m * factor, screen_w, screen_h
        )
        mpp = self.target_view_width_m / max(screen_w, 1)
        self.target_x = world[0] - (sx - screen_w * 0.5) * mpp
        self.target_y = world[1] + (sy - screen_h * 0.5) * mpp

    def follow(self, dt: float, screen_w: int, screen_h: int) -> None:
        dt = min(max(dt, 0.0), 0.05)
        k = 1.0 - math.exp(-dt / max(self.smooth_tau_s, 1e-4))
        self.view_width_m += (self.target_view_width_m - self.view_width_m) * k
        self.x += (self.target_x - self.x) * k
        self.y += (self.target_y - self.y) * k
        self.view_width_m = self._clamp_width(self.view_width_m, screen_w, screen_h)
        self.target_view_width_m = self._clamp_width(
            self.target_view_width_m, screen_w, screen_h
        )
        self.x, self.y = self._clamp_center(
            self.x, self.y, self.view_width_m, screen_w, screen_h
        )
        self.target_x, self.target_y = self._clamp_center(
            self.target_x, self.target_y, self.target_view_width_m, screen_w, screen_h
        )
