from __future__ import annotations

GOTO_SMOOTHING = 0.03
GOTO_MAX_SPEED_M = 15.0
GOTO_STOP_M = 2.0
KEYBOARD_TICK_S = 0.001


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
    ) -> None:
        self.min_view_width_m = min_view_width_m
        self.max_view_width_m = max_view_width_m
        self.frame = (-100_000.0, -100_000.0, 100_000.0, 100_000.0)
        self.radar_mode = False
        self.debug_mode = False
        self.flying = False
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
        """Allow a map corner at screen center; do not pan a full viewport off-map."""
        minx, miny, maxx, maxy = self.frame
        frame_w = max(1.0, maxx - minx)
        frame_h = max(1.0, maxy - miny)
        if frame_w <= width_m:
            x = (minx + maxx) * 0.5
        else:
            x = min(max(x, minx), maxx)
        mpp = width_m / max(screen_w, 1)
        view_h = mpp * screen_h
        if frame_h <= view_h:
            y = (miny + maxy) * 0.5
        else:
            y = min(max(y, miny), maxy)
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

    def settle(self, screen_w: int, screen_h: int) -> None:
        """Clamp the live pose and copy it to targets. Cancels fly-to."""
        self.flying = False
        self.view_width_m = self._clamp_width(self.view_width_m, screen_w, screen_h)
        self.x, self.y = self._clamp_center(
            self.x, self.y, self.view_width_m, screen_w, screen_h
        )
        self.target_x, self.target_y = self.x, self.y
        self.target_view_width_m = self.view_width_m

    def meters_per_pixel(self, screen_w: int) -> float:
        return self.view_width_m / max(screen_w, 1)

    def world_to_screen(
        self, wx: float, wy: float, screen_w: int, screen_h: int
    ) -> tuple[float, float]:
        mpp = self.meters_per_pixel(screen_w)
        sx = (wx - self.x) / mpp + screen_w * 0.5
        sy = (self.y - wy) / mpp + screen_h * 0.5
        return sx, sy

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

    def pan_pixels(self, dx_px: float, dy_px: float, screen_w: int, screen_h: int) -> None:
        mpp = self.meters_per_pixel(screen_w)
        self.x += -dx_px * mpp
        self.y += dy_px * mpp
        self.settle(screen_w, screen_h)

    def fly_to(self, x: float, y: float, view_width_m: float | None = None) -> None:
        self.target_x = x
        self.target_y = y
        if view_width_m is not None:
            self.target_view_width_m = view_width_m
        self.flying = True

    def zoom_at_screen(
        self,
        factor: float,
        sx: float,
        sy: float,
        screen_w: int,
        screen_h: int,
    ) -> None:
        world = self.screen_to_world(sx, sy, screen_w, screen_h)
        width = self._clamp_width(self.view_width_m * factor, screen_w, screen_h)
        mpp = width / max(screen_w, 1)
        self.view_width_m = width
        self.target_view_width_m = width
        self.x = world[0] - (sx - screen_w * 0.5) * mpp
        self.y = world[1] + (sy - screen_h * 0.5) * mpp
        self.settle(screen_w, screen_h)

    def step_fly_to(self, dt: float, screen_w: int, screen_h: int) -> None:
        if not self.flying:
            return
        dt = min(max(dt, 0.0), 0.05)
        self.target_view_width_m = self._clamp_width(
            self.target_view_width_m, screen_w, screen_h
        )
        self.target_x, self.target_y = self._clamp_center(
            self.target_x, self.target_y, self.target_view_width_m, screen_w, screen_h
        )
        r = 1.0 - pow(GOTO_SMOOTHING, dt)
        max_step = GOTO_MAX_SPEED_M * (dt / KEYBOARD_TICK_S)
        self.x += _clamp((self.target_x - self.x) * r, -max_step, max_step)
        self.y += _clamp((self.target_y - self.y) * r, -max_step, max_step)
        self.view_width_m += (self.target_view_width_m - self.view_width_m) * r
        self.view_width_m = self._clamp_width(self.view_width_m, screen_w, screen_h)
        self.x, self.y = self._clamp_center(
            self.x, self.y, self.view_width_m, screen_w, screen_h
        )
        dist = abs(self.target_x - self.x) + abs(self.target_y - self.y)
        zoom_err = abs(self.target_view_width_m - self.view_width_m)
        if dist < GOTO_STOP_M and zoom_err < 1.0:
            self.x, self.y = self.target_x, self.target_y
            self.view_width_m = self.target_view_width_m
            self.flying = False


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(max(value, lo), hi)
