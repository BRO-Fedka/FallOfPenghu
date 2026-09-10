from __future__ import annotations

from math import cos, hypot, pi, sin

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.render.dynamic.icons import CHIP, IconStore
from fall_of_penghu.render.static.scene import palette_for
from fall_of_penghu.render.static.tod import contrast_rgb
from fall_of_penghu.selection import Selection
from fall_of_penghu.vision import SCATTER_COLOR, SCATTER_LINE, VISION_RINGS
from fall_of_penghu.world.entities import (
    DynamicObject,
    Entities,
    FACTION_CHINA,
    FACTION_COLORS,
    FACTION_PLAYER,
    GameObject,
)
from fall_of_penghu.world.perception import ContactImprint, Perception

ICON_PX = 14
INACTIVE_X = (220, 40, 40)
ROUTE_COLOR = (120, 200, 255, 180)
SELECT_COLOR = (255, 230, 80, 220)
RING_SEGS = 72
RING_COLOR = (70, 190, 120, 90)
PRIMITIVE_RING = (70, 170, 220, 110)
ADVANCED_RING = (170, 90, 220, 110)
ENGAGE_COLOR = (235, 200, 40, 150)
FOCUS_COLOR = (255, 150, 50, 200)
HEADING_PX = 18.0
HEADING_GAP = ICON_PX * 0.5
ARROW_PX = 5.5
XFER_ARC_W = 2
XFER_ARC_SEGS = 48
MISSILE_ON = (255, 190, 40, 230)
MISSILE_OFF = (220, 45, 40, 230)
TRACER_COLOR = (235, 210, 50, 220)
SHELL_COLOR = (230, 110, 40, 230)
CHINA_VISION = (220, 40, 40, 220)
CHINA_MEMORY = (235, 200, 40, 220)
MISSILE_BLINK_S = 0.16
STREAK_M = 70.0
FLAME_CELL = 12
FLAME_STEP_M = 16.0
FLAME_LEN = 6


class DynamicRenderer:
    """Icons for world.entities. Small chips + lines, not a fullscreen overlay."""

    def __init__(self) -> None:
        self._icons = IconStore()
        self._strip: pygame.Surface | None = None
        self._strip_cap = 0
        self._flame_strip: pygame.Surface | None = None
        self._flame_cap = 0

    def _ensure_strip(self, n: int) -> pygame.Surface:
        cap = max(32, (n + 31) // 32 * 32)
        if self._strip is None or self._strip_cap < cap:
            self._strip_cap = cap
            self._strip = pygame.Surface((cap * CHIP, CHIP), pygame.SRCALPHA)
        return self._strip

    def _ensure_flame_strip(self, n: int) -> pygame.Surface:
        cap = max(16, (n + 15) // 16 * 16)
        if self._flame_strip is None or self._flame_cap < cap:
            self._flame_cap = cap
            self._flame_strip = pygame.Surface(
                (cap * FLAME_CELL, FLAME_CELL), pygame.SRCALPHA
            )
        return self._flame_strip

    def draw(
        self,
        renderer,
        camera: Camera,
        entities: Entities,
        selection: Selection,
        screen_w: int,
        screen_h: int,
        tod: float = 0.5,
        perception: Perception | None = None,
        now_sim: float = 0.0,
        vision_on: set[str] | None = None,
        mouse_world: tuple[float, float] | None = None,
    ) -> None:
        visible = entities.snapshot(FACTION_PLAYER)
        ink = contrast_rgb(tod)
        radar = camera.radar_mode
        pal = palette_for(radar, tod)
        if perception is not None:
            if radar:
                self._draw_rings(
                    renderer,
                    camera,
                    perception.radar_rings(FACTION_PLAYER),
                    screen_w,
                    screen_h,
                    RING_COLOR,
                )
            else:
                enabled = set() if vision_on is None else vision_on
                for ring_id, channel, cover, color, _label in VISION_RINGS:
                    if ring_id not in enabled:
                        continue
                    self._draw_rings(
                        renderer,
                        camera,
                        perception.sensor_rings(
                            FACTION_PLAYER, channel, cover=cover
                        ),
                        screen_w,
                        screen_h,
                        color,
                    )
            self._draw_rings(
                renderer,
                camera,
                perception.engagement_rings(
                    FACTION_PLAYER,
                    selection.selected,
                    show_all=camera.show_engagement,
                ),
                screen_w,
                screen_h,
                ENGAGE_COLOR,
            )
        marks: list[tuple[object, float]] = [(obj, 1.0) for obj in visible]
        if perception is not None:
            for mark in perception.imprints(FACTION_PLAYER):
                if radar:
                    if mark.radar_on(now_sim):
                        marks.append((mark, 1.0))
                else:
                    alpha = mark.map_alpha(now_sim)
                    if alpha > 0.02:
                        marks.append((mark, alpha))
        margin = CHIP
        dests: list[tuple[int, int]] = []
        drawn: list[tuple[object, float]] = []
        rotated: list[tuple[object, float, float, float]] = []
        intercepts: list[tuple[object, float]] = []
        headings: dict[int, list[list[tuple[float, float]]]] = {}
        tracers: list[list[tuple[float, float]]] = []
        shells: list[list[tuple[float, float]]] = []
        for item, alpha in marks:
            if getattr(item, "stowed", False):
                continue
            kind = getattr(item, "kind", "")
            sx, sy = camera.world_to_screen(item.x, item.y, screen_w, screen_h)
            if kind in ("tracer", "shell"):
                streak = _heading_world_streak(camera, item, screen_w, screen_h)
                if streak is not None:
                    if kind == "shell":
                        shells.append(streak)
                    else:
                        tracers.append(streak)
                continue
            if kind == "intercept" and not radar:
                if _flame_hits_view(camera, item, screen_w, screen_h, margin):
                    intercepts.append((item, alpha))
                continue
            if (
                sx < -margin
                or sy < -margin
                or sx > screen_w + margin
                or sy > screen_h + margin
            ):
                continue
            if radar and getattr(item, "orient_radar", False):
                rotated.append((item, alpha, sx, sy))
                continue
            drawn.append((item, alpha))
            dests.append((int(sx) - CHIP // 2, int(sy) - CHIP // 2))
            if not radar and _show_heading(item):
                a = max(0, min(255, int(230 * alpha)))
                headings.setdefault(a, []).extend(
                    _heading_arrow(sx, sy, item.heading)
                )

        if drawn:
            strip = self._ensure_strip(len(drawn))
            strip.fill((0, 0, 0, 0))
            cx = CHIP * 0.5
            cy = CHIP * 0.5
            for i, (item, alpha) in enumerate(drawn):
                selected = (
                    isinstance(item, GameObject) and item.id in selection.selected
                )
                self._draw_item(
                    strip,
                    item,
                    i * CHIP + cx,
                    cy,
                    radar,
                    selected,
                    alpha,
                )
            renderer.overlay_sprites(strip, dests, CHIP)
            if not radar:
                self._draw_cargo_badges(
                    renderer, camera, entities, drawn, screen_w, screen_h
                )
            self._draw_xfer_badges(
                renderer, camera, drawn, radar, screen_w, screen_h, ink
            )

        for item, alpha, sx, sy in rotated:
            selected = isinstance(item, GameObject) and item.id in selection.selected
            self._blit_oriented(
                renderer, item, sx, sy, radar, selected, alpha
            )

        if intercepts:
            self._draw_flames(renderer, camera, intercepts, screen_w, screen_h, now_sim)

        for alpha, segs in headings.items():
            renderer.overlay_aalines(segs, (*ink, alpha))

        routes: list[list[tuple[float, float]]] = []
        for obj in visible:
            if obj.faction != FACTION_PLAYER:
                continue
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
        if tracers:
            renderer.overlay_aalines(tracers, TRACER_COLOR)
        if shells:
            renderer.overlay_aalines(shells, SHELL_COLOR)
        if not radar:
            self._draw_artillery_marks(
                renderer,
                camera,
                entities,
                selection,
                perception,
                screen_w,
                screen_h,
                mouse_world,
            )
            self._draw_focus_marks(
                renderer, camera, entities, selection, screen_w, screen_h
            )

        if camera.debug_mode and perception is not None:
            self._draw_china_debug(
                renderer, camera, perception, screen_w, screen_h
            )

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

    def _draw_china_debug(
        self,
        renderer,
        camera: Camera,
        perception: Perception,
        screen_w: int,
        screen_h: int,
    ) -> None:
        half = CHIP * 0.5 + 2.0
        memory = _debug_boxes(
            camera,
            [
                (mark.x, mark.y)
                for mark in perception.imprints(FACTION_CHINA)
            ],
            screen_w,
            screen_h,
            half,
        )
        wrecked = _debug_boxes(
            camera,
            [
                (mark.x, mark.y)
                for mark in perception.imprints(FACTION_CHINA)
                if not mark.active
            ],
            screen_w,
            screen_h,
            half,
            cross=True,
        )
        live = _debug_boxes(
            camera,
            [
                (obj.x, obj.y)
                for obj in perception.visible_objects(FACTION_CHINA)
            ],
            screen_w,
            screen_h,
            half,
        )
        if memory:
            renderer.overlay_aalines(memory, CHINA_MEMORY)
        if wrecked:
            renderer.overlay_aalines(wrecked, CHINA_MEMORY)
        if live:
            renderer.overlay_aalines(live, CHINA_VISION)

    def _draw_artillery_marks(
        self,
        renderer,
        camera: Camera,
        entities: Entities,
        selection: Selection,
        perception: Perception | None,
        screen_w: int,
        screen_h: int,
        mouse_world: tuple[float, float] | None,
    ) -> None:
        catalog = None if perception is None else perception.catalog
        rings: list[tuple[float, float, float]] = []
        lines: list[list[tuple[float, float]]] = []
        for item in entities.items:
            if getattr(item, "kind", "") != "shell" or not item.active:
                continue
            scatter = float(getattr(item, "scatter_m", 0.0) or 0.0)
            mx = float(getattr(item, "mark_x", item.aim_x))
            my = float(getattr(item, "mark_y", item.aim_y))
            fx = float(getattr(item, "from_x", item.x))
            fy = float(getattr(item, "from_y", item.y))
            if scatter > 1.0:
                rings.append((mx, my, scatter))
            p0 = camera.world_to_screen(fx, fy, screen_w, screen_h)
            p1 = camera.world_to_screen(mx, my, screen_w, screen_h)
            if _polyline_hits_view([p0, p1], screen_w, screen_h):
                lines.append([p0, p1])
        aiming = bool(getattr(selection, "artillery_aim", False))
        for oid in selection.selected:
            obj = entities.get(oid)
            if obj is None or obj.kind != "artillery" or obj.faction != FACTION_PLAYER:
                continue
            mark = None
            if aiming and mouse_world is not None:
                mark = mouse_world
            elif getattr(obj, "aim_xy", None) is not None:
                mark = obj.aim_xy
            if mark is None or catalog is None:
                continue
            dist = hypot(mark[0] - obj.x, mark[1] - obj.y)
            scatter = catalog.scatter_m(obj.kind, dist)
            if scatter > 1.0:
                rings.append((mark[0], mark[1], scatter))
        if lines:
            renderer.overlay_aalines(lines, SCATTER_LINE)
        if rings:
            self._draw_rings(renderer, camera, rings, screen_w, screen_h, SCATTER_COLOR)

    def _draw_focus_marks(
        self,
        renderer,
        camera: Camera,
        entities: Entities,
        selection: Selection,
        screen_w: int,
        screen_h: int,
    ) -> None:
        ids: set[str] = set()
        for oid in selection.selected:
            obj = entities.get(oid)
            ids |= set(getattr(obj, "focus_ids", ()) or ())
        if not ids:
            return
        half = CHIP * 0.5 + 3.0
        boxes: list[list[tuple[float, float]]] = []
        for fid in ids:
            target = entities.get(fid)
            if target is None or not target.active:
                continue
            sx, sy = camera.world_to_screen(target.x, target.y, screen_w, screen_h)
            boxes.append(
                [
                    (sx - half, sy - half),
                    (sx + half, sy - half),
                    (sx + half, sy + half),
                    (sx - half, sy + half),
                    (sx - half, sy - half),
                ]
            )
        if boxes:
            renderer.overlay_aalines(boxes, FOCUS_COLOR)

    def _draw_rings(
        self,
        renderer,
        camera: Camera,
        rings: list[tuple[float, float, float]],
        screen_w: int,
        screen_h: int,
        color: tuple[int, int, int, int] = RING_COLOR,
    ) -> None:
        lines: list[list[tuple[float, float]]] = []
        for x, y, radius in rings:
            if radius <= 1.0:
                continue
            pts: list[tuple[float, float]] = []
            for i in range(RING_SEGS + 1):
                ang = (2.0 * pi) * i / RING_SEGS
                sx, sy = camera.world_to_screen(
                    x + cos(ang) * radius, y + sin(ang) * radius, screen_w, screen_h
                )
                pts.append((sx, sy))
            if _polyline_hits_view(pts, screen_w, screen_h):
                lines.append(pts)
        if lines:
            renderer.overlay_aalines(lines, color)

    def _draw_flames(
        self,
        renderer,
        camera: Camera,
        intercepts: list[tuple[object, float]],
        screen_w: int,
        screen_h: int,
        now_sim: float,
    ) -> None:
        blink = _missile_on(now_sim)
        dests: list[tuple[int, int]] = []
        chips: list[tuple[tuple[int, int, int, int], int]] = []
        half = FLAME_CELL // 2
        for item, alpha in intercepts:
            last_sx: float | None = None
            last_sy: float | None = None
            last_r = 0
            pts = _flame_world(item)
            n = len(pts)
            for i, (wx, wy) in enumerate(pts):
                sx, sy = camera.world_to_screen(wx, wy, screen_w, screen_h)
                t = i / max(n - 1, 1)
                radius = 2 + int(3 * t)
                if (
                    last_sx is not None
                    and hypot(sx - last_sx, sy - last_sy) < (radius + last_r) * 0.85
                ):
                    continue
                color = MISSILE_ON if ((i + int(blink)) % 2 == 0) else MISSILE_OFF
                if alpha < 0.999:
                    color = (*color[:3], max(0, min(255, int(color[3] * alpha))))
                dests.append((int(sx) - half, int(sy) - half))
                chips.append((color, radius))
                last_sx, last_sy, last_r = sx, sy, radius
        if not dests:
            return
        strip = self._ensure_flame_strip(len(dests))
        strip.fill((0, 0, 0, 0))
        cx = FLAME_CELL * 0.5
        cy = FLAME_CELL * 0.5
        for i, (color, radius) in enumerate(chips):
            pygame.draw.circle(
                strip,
                color,
                (int(i * FLAME_CELL + cx), int(cy)),
                radius,
            )
        renderer.overlay_sprites(strip, dests, FLAME_CELL)

    def _draw_cargo_badges(
        self,
        renderer,
        camera: Camera,
        entities: Entities,
        drawn: list[tuple[object, float]],
        screen_w: int,
        screen_h: int,
    ) -> None:
        dests: list[tuple[int, int]] = []
        chips: list[tuple[pygame.Surface, float]] = []
        for item, alpha in drawn:
            if getattr(item, "kind", "") != "ferry":
                continue
            cargo_id = getattr(item, "cargo_id", None)
            if not cargo_id:
                continue
            cargo = entities.get(cargo_id)
            if cargo is None:
                continue
            icon = self._icons.get(cargo.kind, cargo.faction, False)
            if icon is None:
                continue
            sx, sy = camera.world_to_screen(item.x, item.y, screen_w, screen_h)
            dests.append((int(sx) - CHIP // 2, int(sy) - CHIP - CHIP // 2))
            chips.append((icon, alpha))
        if not dests:
            return
        strip = self._ensure_strip(len(dests))
        strip.fill((0, 0, 0, 0))
        for i, (icon, alpha) in enumerate(chips):
            if alpha < 0.999:
                faded = icon.copy()
                faded.set_alpha(max(0, min(255, int(alpha * 255))))
                strip.blit(faded, (i * CHIP, 0))
            else:
                strip.blit(icon, (i * CHIP, 0))
        renderer.overlay_sprites(strip, dests, CHIP)

    def _draw_xfer_badges(
        self,
        renderer,
        camera: Camera,
        drawn: list[tuple[object, float]],
        radar: bool,
        screen_w: int,
        screen_h: int,
        ink: tuple[int, int, int],
    ) -> None:
        icon = self._icons.overlay("embark", radar)
        arcs: list[list[tuple[float, float]]] = []
        for item, alpha in drawn:
            mark = getattr(item, "xfer", None)
            if mark not in ("load", "unload"):
                continue
            sx, sy = camera.world_to_screen(item.x, item.y, screen_w, screen_h)
            dest = (int(sx) + CHIP // 2, int(sy) - CHIP // 2)
            if icon is not None:
                if alpha < 0.999:
                    faded = icon.copy()
                    faded.set_alpha(max(0, min(255, int(alpha * 255))))
                    renderer.overlay(faded, dest)
                else:
                    renderer.overlay(icon, dest)
            frac = max(0.0, min(1.0, float(getattr(item, "xfer_frac", 0.0))))
            cx = dest[0] + CHIP * 0.5
            cy = dest[1] + CHIP * 0.5
            ring = _xfer_arc(cx, cy, CHIP * 0.5 + 3.0, frac)
            if ring:
                arcs.append(ring)
        for ring in arcs:
            renderer.overlay_lines(ring, (*ink, 230), XFER_ARC_W)

    def _draw_item(
        self,
        layer: pygame.Surface,
        item: GameObject | ContactImprint,
        sx: float,
        sy: float,
        radar: bool,
        selected: bool,
        alpha: float,
    ) -> None:
        if alpha < 0.999:
            chip = pygame.Surface((CHIP, CHIP), pygame.SRCALPHA)
            self._draw_object(chip, item, CHIP * 0.5, CHIP * 0.5, radar, selected)
            chip.set_alpha(max(0, min(255, int(alpha * 255))))
            layer.blit(chip, (int(sx) - CHIP // 2, int(sy) - CHIP // 2))
            return
        self._draw_object(layer, item, sx, sy, radar, selected)

    def _draw_object(
        self,
        layer: pygame.Surface,
        obj: GameObject | ContactImprint,
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

        if isinstance(obj, GameObject):
            wrecked = not obj.active
        elif isinstance(obj, ContactImprint):
            wrecked = not obj.active
        else:
            wrecked = False
        if wrecked:
            half = ICON_PX // 2 + 2
            ix, iy = int(sx), int(sy)
            pygame.draw.line(
                layer, (*INACTIVE_X, 230), (ix - half, iy - half), (ix + half, iy + half), 3
            )
            pygame.draw.line(
                layer, (*INACTIVE_X, 230), (ix - half, iy + half), (ix + half, iy - half), 3
            )

    def _draw_radar_icon(
        self, layer: pygame.Surface, obj: GameObject, sx: float, sy: float
    ) -> None:
        color = FACTION_COLORS.get(obj.faction, FACTION_COLORS[FACTION_PLAYER])
        ix, iy = int(sx), int(sy)
        pygame.draw.circle(layer, color, (ix, iy), 6)
        if getattr(obj, "orient_radar", False):
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

    def _blit_oriented(
        self,
        renderer,
        obj: GameObject | ContactImprint,
        sx: float,
        sy: float,
        radar: bool,
        selected: bool,
        alpha: float,
    ) -> None:
        chip = pygame.Surface((CHIP * 2, CHIP * 2), pygame.SRCALPHA)
        cx = CHIP
        cy = CHIP
        icon = self._icons.get(obj.kind, obj.faction, radar)
        if icon is not None:
            rot = pygame.transform.rotate(icon, obj.heading * 180.0 / pi)
            chip.blit(rot, rot.get_rect(center=(cx, cy)))
        else:
            self._draw_radar_icon(chip, obj, cx, cy)
        if selected:
            half = CHIP // 2
            pygame.draw.rect(
                chip, SELECT_COLOR, (cx - half, cy - half, CHIP - 1, CHIP - 1), 1
            )
        if alpha < 0.999:
            chip.set_alpha(max(0, min(255, int(alpha * 255))))
        renderer.overlay(chip, (int(sx) - CHIP, int(sy) - CHIP))


def _xfer_arc(
    cx: float, cy: float, radius: float, frac: float
) -> list[tuple[float, float]]:
    frac = max(0.0, min(1.0, frac))
    if frac <= 0.004:
        return []
    n = max(2, int(round(XFER_ARC_SEGS * frac)))
    pts: list[tuple[float, float]] = []
    for i in range(n + 1):
        u = (i / n) * frac
        ang = 0.5 * pi + 2.0 * pi * u
        pts.append((cx + radius * cos(ang), cy - radius * sin(ang)))
    return pts


def _debug_boxes(
    camera: Camera,
    points: list[tuple[float, float]],
    screen_w: int,
    screen_h: int,
    half: float,
    *,
    cross: bool = False,
) -> list[list[tuple[float, float]]]:
    boxes: list[list[tuple[float, float]]] = []
    for x, y in points:
        sx, sy = camera.world_to_screen(x, y, screen_w, screen_h)
        if (
            sx < -half
            or sy < -half
            or sx > screen_w + half
            or sy > screen_h + half
        ):
            continue
        boxes.append(
            [
                (sx - half, sy - half),
                (sx + half, sy - half),
                (sx + half, sy + half),
                (sx - half, sy + half),
                (sx - half, sy - half),
            ]
        )
        if cross:
            boxes.append([(sx - half, sy - half), (sx + half, sy + half)])
            boxes.append([(sx - half, sy + half), (sx + half, sy - half)])
    return boxes


def _missile_on(now_sim: float) -> bool:
    return (now_sim % (MISSILE_BLINK_S * 2.0)) < MISSILE_BLINK_S


def _show_heading(item: object) -> bool:
    kind = getattr(item, "kind", "")
    if kind in ("intercept", "tracer", "shell"):
        return False
    return bool(getattr(item, "moving", False))


def _heading_arrow(
    sx: float, sy: float, heading: float
) -> list[list[tuple[float, float]]]:
    ux = cos(heading)
    uy = -sin(heading)
    x0 = sx + ux * HEADING_GAP
    y0 = sy + uy * HEADING_GAP
    x1 = x0 + ux * HEADING_PX
    y1 = y0 + uy * HEADING_PX
    bx = x1 - ux * ARROW_PX
    by = y1 - uy * ARROW_PX
    px = -uy
    py = ux
    wing = ARROW_PX * 0.7
    return [
        [(x0, y0), (x1, y1)],
        [(x1, y1), (bx + px * wing, by + py * wing)],
        [(x1, y1), (bx - px * wing, by - py * wing)],
    ]


def _flame_world(item: object) -> list[tuple[float, float]]:
    x = float(getattr(item, "x", 0.0))
    y = float(getattr(item, "y", 0.0))
    heading = float(getattr(item, "heading", 0.0))
    hx = cos(heading)
    hy = sin(heading)
    raw = getattr(item, "trail", None)
    pts = list(raw) if raw else []
    if not pts or hypot(pts[-1][0] - x, pts[-1][1] - y) > 0.5:
        pts.append((x, y))
    missing = FLAME_LEN - len(pts)
    if missing > 0:
        ox, oy = pts[0]
        extra = [
            (ox - hx * FLAME_STEP_M * i, oy - hy * FLAME_STEP_M * i)
            for i in range(missing, 0, -1)
        ]
        pts = extra + pts
    return pts


def _flame_hits_view(
    camera: Camera,
    item: object,
    screen_w: int,
    screen_h: int,
    margin: float,
) -> bool:
    for wx, wy in _flame_world(item):
        sx, sy = camera.world_to_screen(wx, wy, screen_w, screen_h)
        if -margin <= sx <= screen_w + margin and -margin <= sy <= screen_h + margin:
            return True
    return False


def _heading_world_streak(
    camera: Camera, item: object, screen_w: int, screen_h: int
) -> list[tuple[float, float]] | None:
    heading = float(getattr(item, "heading", 0.0))
    hx = cos(heading) * STREAK_M
    hy = sin(heading) * STREAK_M
    x = float(getattr(item, "x", 0.0))
    y = float(getattr(item, "y", 0.0))
    pts = [
        camera.world_to_screen(x - hx, y - hy, screen_w, screen_h),
        camera.world_to_screen(x + hx, y + hy, screen_w, screen_h),
    ]
    if not _polyline_hits_view(pts, screen_w, screen_h):
        return None
    return pts


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
