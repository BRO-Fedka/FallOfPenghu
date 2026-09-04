from __future__ import annotations

import math

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.mapdata import MapData
from fall_of_penghu.render.static.geom import clip_ring, overlaps
from fall_of_penghu.render.static.radar import COAST_PX, GRID_M, GRID_PX, RADAR
from fall_of_penghu.render.static.scene import (
    BUILDINGS_FADE_GONE_M,
    build_frame,
    palette_for,
)


class SoftwareMapRenderer:
    """CPU vector path: pygame.draw on a Surface. Shaders are ignored."""

    backend = "software"

    def __init__(self, world: MapData, surface: pygame.Surface) -> None:
        self.world = world
        self.surface = surface
        self.radar = False
        self.tod = 0.5
        self.last_stats: dict[str, int] = {}

    def palette(self) -> dict[str, tuple[int, int, int]]:
        return palette_for(self.radar, self.tod)

    def resize(self, width: int, height: int, surface: pygame.Surface | None = None) -> None:
        if surface is not None:
            self.surface = surface
        del width, height

    def draw(
        self, camera: Camera, screen_w: int, screen_h: int, tod: float = 0.5
    ) -> dict[str, int]:
        self.radar = camera.radar_mode
        self.tod = tod
        if camera.radar_mode:
            stats = self._draw_radar(camera, screen_w, screen_h)
        else:
            stats = self._draw_normal(camera, screen_w, screen_h, tod)
        self.last_stats = stats
        return stats

    def _draw_normal(
        self, camera: Camera, screen_w: int, screen_h: int, tod: float
    ) -> dict[str, int]:
        frame = build_frame(self.world, camera, screen_w, screen_h, False, tod)
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
            pygame.draw.polygon(self.surface, cmd.color, pts)
        for cmd in frame.lines:
            pts = _to_screen(cmd.feat.points, camera, screen_w, screen_h)
            if len(pts) < 2:
                continue
            pygame.draw.lines(self.surface, cmd.color, False, pts, max(1, cmd.width_px))
        return frame.stats

    def _draw_radar(self, camera: Camera, screen_w: int, screen_h: int) -> dict[str, int]:
        pal = RADAR
        view = camera.world_bounds(screen_w, screen_h)
        stats = {
            "taiwan": 0,
            "coast": 0,
            "vegetation": 0,
            "buildings": 0,
            "roads": 0,
            "airports": 0,
        }
        self.surface.fill(pal["sea"])
        _draw_radar_grid(self.surface, camera, screen_w, screen_h, pal["grid"])
        for feat in self.world.taiwan:
            if not overlaps(feat.bbox, view):
                continue
            pts = _to_screen(feat.exterior, camera, screen_w, screen_h)
            if len(pts) >= 3:
                pygame.draw.polygon(self.surface, pal["land"], pts)
                stats["taiwan"] += 1
        coast_ids = self.world.coast_grid.query(*view) if self.world.coast_grid else range(
            len(self.world.coast)
        )
        for idx in coast_ids:
            feat = self.world.coast[idx]
            if not overlaps(feat.bbox, view):
                continue
            pts = _to_screen(feat.exterior, camera, screen_w, screen_h)
            if len(pts) >= 3:
                pygame.draw.polygon(self.surface, pal["land"], pts)
                pygame.draw.lines(self.surface, pal["coast"], True, pts, max(1, int(round(COAST_PX))))
                stats["coast"] += 1
        for feat in self.world.taiwan:
            if not overlaps(feat.bbox, view):
                continue
            pts = _to_screen(feat.exterior, camera, screen_w, screen_h)
            if len(pts) >= 2:
                pygame.draw.lines(self.surface, pal["coast"], True, pts, max(1, int(round(COAST_PX))))
        view_w = camera.view_width_m
        for feat in self.world.airports:
            if not overlaps(feat.bbox, view):
                continue
            pts = _to_screen(feat.exterior, camera, screen_w, screen_h)
            if len(pts) >= 2:
                pygame.draw.lines(self.surface, pal["airport"], True, pts, max(1, int(round(COAST_PX))))
                stats["airports"] += 1
        for feat in self.world.airport_lines:
            if not overlaps(feat.bbox, view):
                continue
            pts = _to_screen(feat.points, camera, screen_w, screen_h)
            if len(pts) >= 2:
                pygame.draw.lines(self.surface, pal["airport"], False, pts, max(1, int(round(COAST_PX))))
                stats["airports"] += 1
        for feat in self.world.roads:
            if not feat.bridge or not overlaps(feat.bbox, view):
                continue
            pts = _to_screen(feat.points, camera, screen_w, screen_h)
            if len(pts) >= 2:
                pygame.draw.lines(self.surface, pal["bridge"], False, pts, 2)
                stats["roads"] += 1
        if view_w <= BUILDINGS_FADE_GONE_M:
            b_ids = self.world.building_grid.query(*view) if self.world.building_grid else []
            for idx in b_ids:
                feat = self.world.buildings[idx]
                if not overlaps(feat.bbox, view):
                    continue
                pts = _to_screen(feat.exterior, camera, screen_w, screen_h)
                if len(pts) >= 3:
                    pygame.draw.polygon(self.surface, pal["building"], pts)
                    stats["buildings"] += 1
        return stats

    def overlay(self, surface: pygame.Surface, dest: tuple[int, int] = (0, 0)) -> None:
        self.surface.blit(surface, dest)

    def overlay_sprites(
        self, strip: pygame.Surface, dests: list[tuple[int, int]], cell: int
    ) -> None:
        if cell <= 0:
            return
        for i, dest in enumerate(dests):
            self.surface.blit(strip, dest, area=pygame.Rect(i * cell, 0, cell, cell))

    def overlay_lines(
        self,
        points: list[tuple[float, float]],
        color: tuple[int, int, int] | tuple[int, int, int, int],
        width: int = 2,
    ) -> None:
        if len(points) < 2:
            return
        pts = [(int(x), int(y)) for x, y in points]
        pygame.draw.lines(self.surface, color[:3], False, pts, max(width, 1))

    def overlay_aalines(
        self,
        polylines: list[list[tuple[float, float]]],
        color: tuple[int, int, int] | tuple[int, int, int, int],
    ) -> None:
        rgb = color[:3]
        for points in polylines:
            if len(points) < 2:
                continue
            for a, b in zip(points, points[1:]):
                pygame.draw.aaline(self.surface, rgb, a, b, 1)

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


def _draw_radar_grid(
    surface: pygame.Surface,
    camera: Camera,
    screen_w: int,
    screen_h: int,
    color: tuple[int, int, int],
) -> None:
    view = camera.world_bounds(screen_w, screen_h)
    mpp = camera.meters_per_pixel(screen_w)
    x0 = math.floor(view[0] / GRID_M) * GRID_M
    y0 = math.floor(view[1] / GRID_M) * GRID_M
    x = x0
    while x <= view[2] + 0.5:
        sx = int((x - camera.x) / mpp + screen_w * 0.5)
        pygame.draw.line(surface, color, (sx, 0), (sx, screen_h), int(round(GRID_PX)))
        x += GRID_M
    y = y0
    while y <= view[3] + 0.5:
        sy = int((camera.y - y) / mpp + screen_h * 0.5)
        pygame.draw.line(surface, color, (0, sy), (screen_w, sy), int(round(GRID_PX)))
        y += GRID_M
