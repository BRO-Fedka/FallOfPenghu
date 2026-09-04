from __future__ import annotations

from math import cos, sin

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.render.dynamic.icons import CHIP, IconStore
from fall_of_penghu.render.static.scene import palette_for
from fall_of_penghu.selection import Selection
from fall_of_penghu.world.entities import (
    DynamicObject,
    Entities,
    FACTION_COLORS,
    FACTION_PLAYER,
    GameObject,
)

ICON_PX = 14
INACTIVE_X = (220, 40, 40)
ROUTE_COLOR = (120, 200, 255, 180)
SELECT_COLOR = (255, 230, 80, 220)


class DynamicRenderer:
    """Icons for world.entities. Small chips + lines, not a fullscreen overlay."""

    def __init__(self) -> None:
        self._icons = IconStore()
        self._strip: pygame.Surface | None = None
        self._strip_cap = 0

    def _ensure_strip(self, n: int) -> pygame.Surface:
        cap = max(32, (n + 31) // 32 * 32)
        if self._strip is None or self._strip_cap < cap:
            self._strip_cap = cap
            self._strip = pygame.Surface((cap * CHIP, CHIP), pygame.SRCALPHA)
        return self._strip

    def draw(
        self,
        renderer,
        camera: Camera,
        entities: Entities,
        selection: Selection,
        screen_w: int,
        screen_h: int,
        tod: float = 0.5,
    ) -> None:
        visible = entities.snapshot(FACTION_PLAYER)
        radar = camera.radar_mode
        pal = palette_for(radar, tod)
        margin = CHIP
        dests: list[tuple[int, int]] = []
        drawn: list[GameObject] = []
        for obj in visible:
            sx, sy = camera.world_to_screen(obj.x, obj.y, screen_w, screen_h)
            if (
                sx < -margin
                or sy < -margin
                or sx > screen_w + margin
                or sy > screen_h + margin
            ):
                continue
            drawn.append(obj)
            dests.append((int(sx) - CHIP // 2, int(sy) - CHIP // 2))

        if drawn:
            strip = self._ensure_strip(len(drawn))
            strip.fill((0, 0, 0, 0))
            cx = CHIP * 0.5
            cy = CHIP * 0.5
            for i, obj in enumerate(drawn):
                self._draw_object(
                    strip,
                    obj,
                    i * CHIP + cx,
                    cy,
                    radar,
                    obj.id in selection.selected,
                )
            renderer.overlay_sprites(strip, dests, CHIP)

        routes: list[list[tuple[float, float]]] = []
        for obj in visible:
            if not isinstance(obj, DynamicObject) or obj.route is None:
                continue
            if obj.route.remaining_length() <= 1.0:
                continue
            world_pts = obj.route.remaining_points(obj.x, obj.y)
            if len(world_pts) < 2:
                continue
            screen_pts = [
                camera.world_to_screen(x, y, screen_w, screen_h)
                for x, y in world_pts
            ]
            if not _polyline_hits_view(screen_pts, screen_w, screen_h):
                continue
            routes.append(screen_pts)
        if routes:
            renderer.overlay_aalines(routes, ROUTE_COLOR)

        if selection.box is not None:
            x0, y0, x1, y1 = selection.box
            left, right = min(x0, x1), max(x0, x1)
            top, bottom = min(y0, y1), max(y0, y1)
            renderer.overlay_lines(
                [
                    (left, top),
                    (right, top),
                    (right, bottom),
                    (left, bottom),
                    (left, top),
                ],
                (*pal["hud"][:3], 90),
                1,
            )

    def _draw_object(
        self,
        layer: pygame.Surface,
        obj: GameObject,
        sx: float,
        sy: float,
        radar: bool,
        selected: bool,
    ) -> None:
        icon = self._icons.get(obj.kind, obj.faction, radar)
        if icon is not None:
            rect = icon.get_rect(center=(int(sx), int(sy)))
            layer.blit(icon, rect)
        elif radar:
            self._draw_radar_icon(layer, obj, sx, sy)
        else:
            self._draw_map_icon(layer, obj, sx, sy)

        if selected:
            half = CHIP // 2
            ix, iy = int(sx), int(sy)
            pygame.draw.rect(
                layer, SELECT_COLOR, (ix - half, iy - half, CHIP - 1, CHIP - 1), 1
            )

        if not obj.active:
            half = ICON_PX // 2 + 2
            ix, iy = int(sx), int(sy)
            pygame.draw.line(
                layer, (*INACTIVE_X, 230), (ix - half, iy - half), (ix + half, iy + half), 2
            )
            pygame.draw.line(
                layer, (*INACTIVE_X, 230), (ix - half, iy + half), (ix + half, iy - half), 2
            )

    def _draw_radar_icon(
        self, layer: pygame.Surface, obj: GameObject, sx: float, sy: float
    ) -> None:
        color = FACTION_COLORS.get(obj.faction, FACTION_COLORS[FACTION_PLAYER])
        ix, iy = int(sx), int(sy)
        pygame.draw.circle(layer, color, (ix, iy), 6)
        if obj.orient_icon:
            tip = 10
            hx = cos(obj.heading) * tip
            hy = -sin(obj.heading) * tip
            pygame.draw.line(layer, color, (ix, iy), (ix + int(hx), iy + int(hy)), 2)

    def _draw_map_icon(
        self, layer: pygame.Surface, obj: GameObject, sx: float, sy: float
    ) -> None:
        half = ICON_PX // 2
        ix, iy = int(sx), int(sy)
        rect = pygame.Rect(ix - half, iy - half, ICON_PX, ICON_PX)
        pygame.draw.rect(layer, (255, 255, 255, 240), rect)
        pygame.draw.rect(layer, (0, 0, 0, 255), rect, 1)
        fcolor = FACTION_COLORS.get(obj.faction, FACTION_COLORS[FACTION_PLAYER])
        pygame.draw.circle(layer, fcolor, (ix, iy), half - 4)


def _polyline_hits_view(
    pts: list[tuple[float, float]], screen_w: int, screen_h: int
) -> bool:
    if not pts:
        return False
    minx = min(p[0] for p in pts)
    miny = min(p[1] for p in pts)
    maxx = max(p[0] for p in pts)
    maxy = max(p[1] for p in pts)
    return not (maxx < 0 or maxy < 0 or minx > screen_w or miny > screen_h)
