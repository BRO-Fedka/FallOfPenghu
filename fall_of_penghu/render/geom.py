from __future__ import annotations

from array import array
from math import hypot


def pad_view(
    view: tuple[float, float, float, float], pad_m: float
) -> tuple[float, float, float, float]:
    return (view[0] - pad_m, view[1] - pad_m, view[2] + pad_m, view[3] + pad_m)


def overlaps(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def _inside(p, edge: str, r: tuple[float, float, float, float]) -> bool:
    x, y = p
    minx, miny, maxx, maxy = r
    if edge == "left":
        return x >= minx
    if edge == "right":
        return x <= maxx
    if edge == "bottom":
        return y >= miny
    return y <= maxy


def _intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    edge: str,
    r: tuple[float, float, float, float],
) -> tuple[float, float]:
    minx, miny, maxx, maxy = r
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay
    if edge == "left":
        t = (minx - ax) / dx if dx else 0.0
        return minx, ay + t * dy
    if edge == "right":
        t = (maxx - ax) / dx if dx else 0.0
        return maxx, ay + t * dy
    if edge == "bottom":
        t = (miny - ay) / dy if dy else 0.0
        return ax + t * dx, miny
    t = (maxy - ay) / dy if dy else 0.0
    return ax + t * dx, maxy


def clip_ring(
    points: list[tuple[float, float]],
    rect: tuple[float, float, float, float],
) -> list[tuple[float, float]]:
    """Sutherland–Hodgman clip against an axis-aligned rect in world meters."""
    out = points
    for edge in ("left", "right", "bottom", "top"):
        if len(out) < 3:
            return []
        prev = out
        out = []
        s = prev[-1]
        for e in prev:
            ein = _inside(e, edge, rect)
            sin = _inside(s, edge, rect)
            if ein:
                if not sin:
                    out.append(_intersect(s, e, edge, rect))
                out.append(e)
            elif sin:
                out.append(_intersect(s, e, edge, rect))
            s = e
    return out if len(out) >= 3 else []


def _dedupe_ring(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for x, y in points:
        if out and abs(out[-1][0] - x) < 1e-9 and abs(out[-1][1] - y) < 1e-9:
            continue
        out.append((x, y))
    if len(out) >= 2 and abs(out[0][0] - out[-1][0]) < 1e-9 and abs(out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    return out


def _signed_area(pts: list[tuple[float, float]]) -> float:
    acc = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        acc += x1 * y2 - x2 * y1
    return acc * 0.5


def _cross(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_in_tri(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> bool:
    c1 = _cross(a, b, p)
    c2 = _cross(b, c, p)
    c3 = _cross(c, a, p)
    has_neg = c1 < -1e-12 or c2 < -1e-12 or c3 < -1e-12
    has_pos = c1 > 1e-12 or c2 > 1e-12 or c3 > 1e-12
    return not (has_neg and has_pos)


def _is_convex(pts: list[tuple[float, float]]) -> bool:
    n = len(pts)
    sign = 0
    for i in range(n):
        cr = _cross(pts[i], pts[(i + 1) % n], pts[(i + 2) % n])
        if abs(cr) < 1e-12:
            continue
        s = 1 if cr > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def _clip_ears(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    n = len(pts)
    prev = [(i - 1) % n for i in range(n)]
    nxt = [(i + 1) % n for i in range(n)]
    remaining = n
    tris: list[tuple[float, float]] = []

    def convex(i: int) -> bool:
        return _cross(pts[prev[i]], pts[i], pts[nxt[i]]) > 1e-12

    def ear(i: int) -> bool:
        if not convex(i):
            return False
        a, b, c = pts[prev[i]], pts[i], pts[nxt[i]]
        minx = min(a[0], b[0], c[0])
        maxx = max(a[0], b[0], c[0])
        miny = min(a[1], b[1], c[1])
        maxy = max(a[1], b[1], c[1])
        j = nxt[nxt[i]]
        stop = prev[i]
        while j != stop:
            x, y = pts[j]
            if minx <= x <= maxx and miny <= y <= maxy and _point_in_tri((x, y), a, b, c):
                return False
            j = nxt[j]
        return True

    i = 0
    misses = 0
    max_iter = n * n
    it = 0
    while remaining > 3 and it < max_iter:
        it += 1
        if ear(i):
            tris.extend((pts[prev[i]], pts[i], pts[nxt[i]]))
            nxt[prev[i]] = nxt[i]
            prev[nxt[i]] = prev[i]
            remaining -= 1
            i = nxt[i]
            misses = 0
        else:
            i = nxt[i]
            misses += 1
            if misses >= remaining:
                break

    if remaining >= 3:
        start = i
        ring = [start]
        j = nxt[start]
        while j != start and len(ring) < remaining:
            ring.append(j)
            j = nxt[j]
        origin = pts[ring[0]]
        for k in range(1, len(ring) - 1):
            tris.extend((origin, pts[ring[k]], pts[ring[k + 1]]))
    return tris


def triangulate(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Fill triangles for a simple ring. Empty if the ring is degenerate."""
    pts = _dedupe_ring(points)
    n = len(pts)
    if n < 3:
        return []
    area = _signed_area(pts)
    if abs(area) < 1e-12:
        return []
    if area < 0:
        pts = list(reversed(pts))
        n = len(pts)
    if n == 3:
        return [pts[0], pts[1], pts[2]]
    if n == 4 and _cross(pts[0], pts[1], pts[2]) > 0 and _cross(pts[0], pts[2], pts[3]) > 0:
        return [pts[0], pts[1], pts[2], pts[0], pts[2], pts[3]]
    if _is_convex(pts):
        out: list[tuple[float, float]] = []
        for i in range(1, n - 1):
            out.extend((pts[0], pts[i], pts[i + 1]))
        return out
    return _clip_ears(pts)


def pack_xy(points: list[tuple[float, float]]) -> array:
    data = array("f")
    for x, y in points:
        data.append(x)
        data.append(y)
    return data


_SEG_EPS = 1e-6
_MITER_LIMIT = 4.0


def _clean_poly(
    points: list[tuple[float, float]], *, closed: bool
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for x, y in points:
        if out and hypot(x - out[-1][0], y - out[-1][1]) < _SEG_EPS:
            continue
        out.append((float(x), float(y)))
    if (
        closed
        and len(out) >= 2
        and hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < _SEG_EPS
    ):
        out.pop()
    return out


def _seg_list(
    pts: list[tuple[float, float]], *, closed: bool
) -> list[tuple[tuple[float, float], tuple[float, float], float, float, float, float]]:
    """Non-degenerate segments: (A, B, ux, uy, left_nx, left_ny)."""
    n = len(pts)
    count = n if closed else n - 1
    segs: list[
        tuple[tuple[float, float], tuple[float, float], float, float, float, float]
    ] = []
    for i in range(max(count, 0)):
        a = pts[i]
        b = pts[(i + 1) % n]
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        length = hypot(dx, dy)
        if length < _SEG_EPS:
            continue
        ux, uy = dx / length, dy / length
        segs.append((a, b, ux, uy, -uy, ux))
    return segs


def _offset(
    p: tuple[float, float], nx: float, ny: float, scale: float
) -> tuple[float, float]:
    return p[0] + nx * scale, p[1] + ny * scale


def _miter_vec(
    n0x: float, n0y: float, n1x: float, n1y: float, scale: float, limit: float
) -> tuple[float, float] | None:
    """Offset from the vertex to the miter point, or None to bevel."""
    denom = 1.0 + n0x * n1x + n0y * n1y
    if denom <= 1e-4:
        return None
    ox = (n0x + n1x) * scale / denom
    oy = (n0y + n1y) * scale / denom
    max_len = limit * scale
    if ox * ox + oy * oy > max_len * max_len:
        return None
    return ox, oy


def _append_xy_tri(
    data: array,
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> None:
    data.extend((a[0], a[1], b[0], b[1], c[0], c[1]))


def _append_xy_quad(
    data: array,
    left0: tuple[float, float],
    right0: tuple[float, float],
    left1: tuple[float, float],
    right1: tuple[float, float],
) -> None:
    data.extend(
        (
            left0[0],
            left0[1],
            right0[0],
            right0[1],
            left1[0],
            left1[1],
            left1[0],
            left1[1],
            right0[0],
            right0[1],
            right1[0],
            right1[1],
        )
    )


def _join_both_sides(
    p: tuple[float, float],
    n0x: float,
    n0y: float,
    n1x: float,
    n1y: float,
    half: float,
) -> tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
    tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None,
]:
    """Incoming L/R, outgoing L/R, optional bevel triangle on the convex side."""
    miter = _miter_vec(n0x, n0y, n1x, n1y, half, _MITER_LIMIT)
    if miter is not None:
        left = (p[0] + miter[0], p[1] + miter[1])
        right = (p[0] - miter[0], p[1] - miter[1])
        return left, right, left, right, None
    left_in = _offset(p, n0x, n0y, half)
    right_in = _offset(p, -n0x, -n0y, half)
    left_out = _offset(p, n1x, n1y, half)
    right_out = _offset(p, -n1x, -n1y, half)
    # d = (n.y, -n.x) recovers the unit tangent from a left normal.
    cross = n0y * (-n1x) - (-n0x) * n1y
    if cross < 0.0:
        bevel = (left_in, p, left_out)
    elif cross > 0.0:
        bevel = (right_in, p, right_out)
    else:
        bevel = None
    return left_in, right_in, left_out, right_out, bevel


def stroke_polyline(
    points: list[tuple[float, float]],
    width_m: float,
    *,
    closed: bool = False,
) -> array:
    """Two-sided stroke with miter joins (bevel past miter limit)."""
    pts = _clean_poly(points, closed=closed)
    data = array("f")
    segs = _seg_list(pts, closed=closed)
    if not segs:
        return data
    half = max(width_m * 0.5, 1e-4)
    n = len(segs)
    start_l: list[tuple[float, float]] = [(0.0, 0.0)] * n
    start_r: list[tuple[float, float]] = [(0.0, 0.0)] * n
    end_l: list[tuple[float, float]] = [(0.0, 0.0)] * n
    end_r: list[tuple[float, float]] = [(0.0, 0.0)] * n
    bevels: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]] = []

    def apply_end_cap(i: int, *, at_start: bool) -> None:
        nx, ny = segs[i][4], segs[i][5]
        p = segs[i][0] if at_start else segs[i][1]
        left = _offset(p, nx, ny, half)
        right = _offset(p, -nx, -ny, half)
        if at_start:
            start_l[i] = left
            start_r[i] = right
        else:
            end_l[i] = left
            end_r[i] = right

    def apply_join(i_in: int, i_out: int) -> None:
        p = segs[i_in][1]
        n0x, n0y = segs[i_in][4], segs[i_in][5]
        n1x, n1y = segs[i_out][4], segs[i_out][5]
        lin, rin, lout, rout, bevel = _join_both_sides(p, n0x, n0y, n1x, n1y, half)
        end_l[i_in] = lin
        end_r[i_in] = rin
        start_l[i_out] = lout
        start_r[i_out] = rout
        if bevel is not None:
            bevels.append(bevel)

    if n == 1:
        apply_end_cap(0, at_start=True)
        apply_end_cap(0, at_start=False)
    else:
        for i in range(n - 1):
            apply_join(i, i + 1)
        if closed:
            apply_join(n - 1, 0)
        else:
            apply_end_cap(0, at_start=True)
            apply_end_cap(n - 1, at_start=False)
    for i in range(n):
        _append_xy_quad(data, start_l[i], start_r[i], end_l[i], end_r[i])
    for a, b, c in bevels:
        _append_xy_tri(data, a, b, c)
    return data


def _append_band_vert(
    data: array,
    p: tuple[float, float],
    t: float,
    n: tuple[float, float],
) -> None:
    nx, ny = n
    length = hypot(nx, ny)
    if length < 1e-8:
        nx, ny = 0.0, 1.0
    else:
        nx /= length
        ny /= length
    data.extend((p[0], p[1], t, nx, ny))


def _append_band_quad(
    data: array,
    land0: tuple[float, float],
    sea0: tuple[float, float],
    sea1: tuple[float, float],
    land1: tuple[float, float],
    n0: tuple[float, float],
    n1: tuple[float, float],
) -> None:
    n_sea0 = (sea0[0] - land0[0], sea0[1] - land0[1])
    n_sea1 = (sea1[0] - land1[0], sea1[1] - land1[1])
    _append_band_vert(data, land0, 0.0, n0)
    _append_band_vert(data, sea0, 1.0, n_sea0)
    _append_band_vert(data, sea1, 1.0, n_sea1)
    _append_band_vert(data, land0, 0.0, n0)
    _append_band_vert(data, sea1, 1.0, n_sea1)
    _append_band_vert(data, land1, 0.0, n1)


def _join_one_side(
    p: tuple[float, float],
    n0x: float,
    n0y: float,
    n1x: float,
    n1y: float,
    width_m: float,
) -> tuple[tuple[float, float], tuple[float, float], bool]:
    """Incoming outer, outgoing outer, and whether a bevel fill is needed."""
    miter = _miter_vec(n0x, n0y, n1x, n1y, width_m, _MITER_LIMIT)
    if miter is not None:
        outer = (p[0] + miter[0], p[1] + miter[1])
        return outer, outer, False
    return _offset(p, n0x, n0y, width_m), _offset(p, n1x, n1y, width_m), True


def stroke_seaward_band(
    points: list[tuple[float, float]],
    width_m: float,
    *,
    closed: bool = True,
    landward_m: float = 0.0,
) -> array:
    """Shore band. Vertex: x y t nx ny. t=0 landward edge, t=1 seaward edge."""
    pts = _clean_poly(points, closed=closed)
    data = array("f")
    if len(pts) < 3:
        return data
    area = 0.0
    npts = len(pts)
    for i in range(npts):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % npts]
        area += x1 * y2 - x2 * y1
    seaward = 1.0 if area > 0.0 else -1.0
    segs = _seg_list(pts, closed=closed)
    if not segs:
        return data
    width_m = max(width_m, 1e-4)
    landward_m = max(landward_m, 0.0)
    n = len(segs)
    start_sea: list[tuple[float, float]] = [(0.0, 0.0)] * n
    end_sea: list[tuple[float, float]] = [(0.0, 0.0)] * n
    start_land: list[tuple[float, float]] = [(0.0, 0.0)] * n
    end_land: list[tuple[float, float]] = [(0.0, 0.0)] * n
    sea_bevels: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]] = []
    land_bevels: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]] = []
    t_shore = landward_m / (landward_m + width_m)

    def sea_n(i: int) -> tuple[float, float]:
        ux, uy = segs[i][2], segs[i][3]
        return seaward * uy, seaward * (-ux)

    def apply_end_cap(i: int, *, at_start: bool) -> None:
        nx, ny = sea_n(i)
        p = segs[i][0] if at_start else segs[i][1]
        sea = _offset(p, nx, ny, width_m)
        land = _offset(p, -nx, -ny, landward_m) if landward_m > 1e-6 else p
        if at_start:
            start_sea[i] = sea
            start_land[i] = land
        else:
            end_sea[i] = sea
            end_land[i] = land

    def apply_join(i_in: int, i_out: int) -> None:
        p = segs[i_in][1]
        n0x, n0y = sea_n(i_in)
        n1x, n1y = sea_n(i_out)
        sea_in, sea_out, bev_sea = _join_one_side(p, n0x, n0y, n1x, n1y, width_m)
        end_sea[i_in] = sea_in
        start_sea[i_out] = sea_out
        if bev_sea is not None:
            sea_bevels.append((p, sea_in, sea_out))
        if landward_m > 1e-6:
            land_in, land_out, bev_land = _join_one_side(
                p, -n0x, -n0y, -n1x, -n1y, landward_m
            )
            end_land[i_in] = land_in
            start_land[i_out] = land_out
            if bev_land is not None:
                land_bevels.append((p, land_in, land_out))
        else:
            end_land[i_in] = p
            start_land[i_out] = p

    if n == 1:
        apply_end_cap(0, at_start=True)
        apply_end_cap(0, at_start=False)
    else:
        for i in range(n - 1):
            apply_join(i, i + 1)
        if closed:
            apply_join(n - 1, 0)
        else:
            apply_end_cap(0, at_start=True)
            apply_end_cap(n - 1, at_start=False)
    for i, (a, b, _ux, _uy, _lnx, _lny) in enumerate(segs):
        sn = sea_n(i)
        _append_band_quad(
            data, start_land[i], start_sea[i], end_sea[i], end_land[i], sn, sn
        )
    for shore, o0, o1 in sea_bevels:
        n0 = (o0[0] - shore[0], o0[1] - shore[1])
        n1 = (o1[0] - shore[0], o1[1] - shore[1])
        _append_band_vert(data, shore, t_shore, n0)
        _append_band_vert(data, o0, 1.0, n0)
        _append_band_vert(data, o1, 1.0, n1)
    for shore, o0, o1 in land_bevels:
        n0 = (shore[0] - o0[0], shore[1] - o0[1])
        n1 = (shore[0] - o1[0], shore[1] - o1[1])
        _append_band_vert(data, shore, t_shore, n0)
        _append_band_vert(data, o0, 0.0, n0)
        _append_band_vert(data, o1, 0.0, n1)
    return data
