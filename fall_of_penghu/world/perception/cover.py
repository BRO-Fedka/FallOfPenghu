from __future__ import annotations

from fall_of_penghu.world.map import MapData, PolyFeature


def _point_in_ring(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            xint = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xint:
                inside = not inside
        j = i
    return inside


def point_in_poly(x: float, y: float, feat: PolyFeature) -> bool:
    minx, miny, maxx, maxy = feat.bbox
    if x < minx or x > maxx or y < miny or y > maxy:
        return False
    if not _point_in_ring(x, y, feat.exterior):
        return False
    for hole in feat.holes:
        if _point_in_ring(x, y, hole):
            return False
    return True


class CoverIndex:
    """Forest / grass / open at a point. Air and sea skip vegetation."""

    def __init__(self, world: MapData) -> None:
        self._map = world

    def at(self, x: float, y: float, role: str) -> str:
        if role != "ground":
            return "open"
        world = self._map
        if world.veg_grid is None:
            return "open"
        hit = "open"
        for i in world.veg_grid.query(x, y, x, y):
            feat = world.vegetation[i]
            if not point_in_poly(x, y, feat):
                continue
            if feat.class_name == "forest":
                return "forest"
            hit = "grass"
        return hit
