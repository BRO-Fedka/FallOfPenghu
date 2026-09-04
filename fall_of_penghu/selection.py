from __future__ import annotations

from math import hypot

from fall_of_penghu.camera import Camera
from fall_of_penghu.world.entities import Entities, FACTION_PLAYER, GameObject

PICK_PX = 14.0
DRAG_PX = 5.0


def _dist2(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


class Selection:
    """Session selection state. Not part of World."""

    def __init__(self) -> None:
        self.selected: set[str] = set()
        self.hover_id: str | None = None
        self.box: tuple[int, int, int, int] | None = None

    def clear(self) -> None:
        self.selected.clear()

    def toggle(self, object_id: str) -> None:
        if object_id in self.selected:
            self.selected.remove(object_id)
        else:
            self.selected.add(object_id)

    def replace(self, object_id: str) -> None:
        self.selected = {object_id}

    def apply_box(
        self,
        entities: Entities,
        camera: Camera,
        screen_w: int,
        screen_h: int,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        *,
        additive: bool,
    ) -> None:
        left = min(x0, x1)
        right = max(x0, x1)
        top = min(y0, y1)
        bottom = max(y0, y1)
        if right - left < 2 and bottom - top < 2:
            return
        hits: set[str] = set()
        for obj in entities.snapshot(FACTION_PLAYER):
            sx, sy = camera.world_to_screen(obj.x, obj.y, screen_w, screen_h)
            if left <= sx <= right and top <= sy <= bottom:
                hits.add(obj.id)
        if additive:
            self.selected |= hits
        else:
            self.selected = hits

    def update_hover(
        self,
        entities: Entities,
        camera: Camera,
        screen_w: int,
        screen_h: int,
        sx: float,
        sy: float,
    ) -> None:
        hit = pick_at(entities, camera, screen_w, screen_h, sx, sy)
        self.hover_id = hit.id if hit else None


def pick_at(
    entities: Entities,
    camera: Camera,
    screen_w: int,
    screen_h: int,
    sx: float,
    sy: float,
) -> GameObject | None:
    mpp = camera.meters_per_pixel(screen_w)
    radius_m = max(PICK_PX * mpp, 8.0)
    radius2 = radius_m * radius_m
    wx, wy = camera.screen_to_world(sx, sy, screen_w, screen_h)
    best: GameObject | None = None
    best_d = radius2
    for obj in entities.snapshot(FACTION_PLAYER):
        d = _dist2((obj.x, obj.y), (wx, wy))
        if d <= best_d:
            best_d = d
            best = obj
    return best
