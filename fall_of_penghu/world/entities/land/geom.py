from __future__ import annotations

from math import hypot

from fall_of_penghu.world.map import PolyFeature


def point_in_ring(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
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
    if not point_in_ring(x, y, feat.exterior):
        return False
    for hole in feat.holes:
        if point_in_ring(x, y, hole):
            return False
    return True


def dist_seg(
    x: float, y: float, ax: float, ay: float, bx: float, by: float
) -> float:
    dx = bx - ax
    dy = by - ay
    den = dx * dx + dy * dy
    if den <= 1e-12:
        return hypot(x - ax, y - ay)
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / den))
    return hypot(x - (ax + t * dx), y - (ay + t * dy))


def dist_poly(x: float, y: float, pts: list[tuple[float, float]]) -> float:
    if len(pts) < 2:
        return 1e30
    best = 1e30
    for a, b in zip(pts, pts[1:]):
        d = dist_seg(x, y, a[0], a[1], b[0], b[1])
        if d < best:
            best = d
    return best


def extend(pts: list[tuple[float, float]], extra: list[tuple[float, float]]) -> None:
    for pt in extra:
        if not pts or pt != pts[-1]:
            pts.append(pt)
