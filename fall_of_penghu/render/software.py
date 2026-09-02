from __future__ import annotations

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.mapdata import MapData
from fall_of_penghu.render.geom import clip_ring
from fall_of_penghu.render.scene import build_frame, palette_for


class SoftwareMapRenderer:
    """CPU vector path: pygame.draw on a Surface. Shaders are ignored."""

    backend = "software"

    def __init__(self, world: MapData, surface: pygame.Surface) -> None:
        self.world = world
        self.surface = surface
        self.radar = False
        self.last_stats: dict[str, int] = {}

    def palette(self) -> dict[str, tuple[int, int, int]]:
        return palette_for(self.radar)

    def resize(self, width: int, height: int, surface: pygame.Surface | None = None) -> None:
        if surface is not None:
            self.surface = surface
        del width, height

    def draw(self, camera: Camera, screen_w: int, screen_h: int) -> dict[str, int]:
        self.radar = camera.radar_mode
        frame = build_frame(self.world, camera, screen_w, screen_h, self.radar)
        self.surface.fill(frame.sea)
        for cmd in frame.polys:
            src = cmd.feat.exterior
            if cmd.clip:
                src = clip_ring(src, frame.clip_rect)
                if len(src) < 3:
                    continue
            pts = _to_screen(src, camera, screen_w, screen_h)
            if len(pts) < 3:
                continue
            if cmd.outline:
                pygame.draw.lines(self.surface, cmd.color, True, pts, 1)
            else:
                pygame.draw.polygon(self.surface, cmd.color, pts)
        for cmd in frame.lines:
            pts = _to_screen(cmd.feat.points, camera, screen_w, screen_h)
            if len(pts) < 2:
                continue
            pygame.draw.lines(self.surface, cmd.color, False, pts, max(1, cmd.width_px))
        self.last_stats = frame.stats
        return frame.stats

    def overlay(self, surface: pygame.Surface, dest: tuple[int, int] = (0, 0)) -> None:
        self.surface.blit(surface, dest)

    def present(self) -> None:
        pygame.display.flip()


def _to_screen(
    points: list[tuple[float, float]],
    camera: Camera,
    screen_w: int,
    screen_h: int,
) -> list[tuple[int, int]]:
    mpp = camera.meters_per_pixel(screen_w)
    hx = screen_w * 0.5
    hy = screen_h * 0.5
    cx, cy = camera.x, camera.y
    out: list[tuple[int, int]] = []
    for wx, wy in points:
        out.append((int((wx - cx) / mpp + hx), int((cy - wy) / mpp + hy)))
    return out
