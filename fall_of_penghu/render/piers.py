from __future__ import annotations

from math import atan2, hypot, pi

import numpy as np
from shapely import contains_xy, prepare
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from fall_of_penghu.render.pier_params import PierParams


def _signed_area(pts: list[tuple[float, float]]) -> float:
    acc = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        acc += x1 * y2 - x2 * y1
    return 0.5 * acc


def _ensure_ccw(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if _signed_area(pts) < 0.0:
        return list(reversed(pts))
    return list(pts)


def _polys_from(geom) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom] if not geom.is_empty else []
    if isinstance(geom, MultiPolygon):
        return [p for p in geom.geoms if not p.is_empty]
    if isinstance(geom, GeometryCollection):
        out: list[Polygon] = []
        for item in geom.geoms:
            out.extend(_polys_from(item))
        return out
    return []


def _ring_xy(coords) -> list[tuple[float, float]]:
    pts = [(float(x), float(y)) for x, y in coords]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts.pop()
    return pts


def _corner(pts: list[tuple[float, float]], i: int) -> tuple[float, float, float] | None:
    n = len(pts)
    p0 = pts[(i - 1) % n]
    p1 = pts[i]
    p2 = pts[(i + 1) % n]
    d1x, d1y = p1[0] - p0[0], p1[1] - p0[1]
    d2x, d2y = p2[0] - p1[0], p2[1] - p1[1]
    l1, l2 = hypot(d1x, d1y), hypot(d2x, d2y)
    if l1 < 1e-4 or l2 < 1e-4:
        return None
    cross = d1x * d2y - d1y * d2x
    dot = d1x * d2x + d1y * d2y
    turn = atan2(cross, dot)
    if turn <= 0.0:
        return None
    interior = (pi - turn) * 180.0 / pi
    return interior, l1, l2


def _is_candidate(interior: float, l1: float, l2: float, params: PierParams) -> bool:
    if params.right_angle_min_deg <= interior <= params.right_angle_max_deg:
        return True
    if interior < params.right_angle_min_deg and min(l1, l2) < params.acute_edge_m:
        return True
    # Blunt seaward end: wide interior, shorter edge is still a pier-width nose.
    if interior > params.right_angle_max_deg and interior <= 160.0:
        short, long = (l1, l2) if l1 <= l2 else (l2, l1)
        if params.min_width_m <= short <= params.max_width_m and long >= params.min_length_m:
            return True
    return False


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])


def _line_angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % pi
    return min(d, pi - d)


def _perp_width(
    a0: tuple[float, float],
    a1: tuple[float, float],
    b0: tuple[float, float],
    b1: tuple[float, float],
) -> float:
    dx, dy = a1[0] - a0[0], a1[1] - a0[1]
    length = hypot(dx, dy)
    if length < 1e-9:
        return _dist(a0, b0)
    nx, ny = -dy / length, dx / length
    d0 = (b0[0] - a0[0]) * nx + (b0[1] - a0[1]) * ny
    d1 = (b1[0] - a0[0]) * nx + (b1[1] - a0[1]) * ny
    return abs(0.5 * (d0 + d1))


def _overlap_along(
    a0: tuple[float, float],
    a1: tuple[float, float],
    b0: tuple[float, float],
    b1: tuple[float, float],
) -> float:
    """How much of segment a overlaps b when projected onto a's direction."""
    dx, dy = a1[0] - a0[0], a1[1] - a0[1]
    length = hypot(dx, dy)
    if length < 1e-9:
        return 0.0
    ux, uy = dx / length, dy / length
    pb0 = (b0[0] - a0[0]) * ux + (b0[1] - a0[1]) * uy
    pb1 = (b1[0] - a0[0]) * ux + (b1[1] - a0[1]) * uy
    lo = max(0.0, min(pb0, pb1))
    hi = min(length, max(pb0, pb1))
    return max(0.0, hi - lo)


def _collect_side_edges(
    pts: list[tuple[float, float]],
    start: int,
    step: int,
    used: set[int],
    params: PierParams,
) -> list[tuple[tuple[float, float], tuple[float, float], float]]:
    """Edges walking from start, skipping crumbs. May stop before max hops."""
    n = len(pts)
    min_edge = max(3.0, params.min_width_m)
    max_arc = max(params.max_length_m, params.min_length_m)
    i = start
    arc = 0.0
    out: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    for _ in range(n - 1):
        j = (i + step) % n
        if j in used:
            break
        used.add(j)
        a, b = pts[i], pts[j]
        d = _dist(a, b)
        if d < 1e-4:
            i = j
            continue
        if d >= min_edge:
            out.append((a, b, atan2(b[1] - a[1], b[0] - a[0])))
        arc += d
        if arc >= max_arc or len(out) >= 20:
            break
        i = j
    return out


def _has_parallel_pair(
    pts: list[tuple[float, float]], i: int, land: Polygon, params: PierParams
) -> bool:
    """True if some edge left of i is parallel to some edge right of i."""
    n = len(pts)
    used = {i}
    left = _collect_side_edges(pts, i, -1, used, params)
    right = _collect_side_edges(pts, i, 1, used, params)
    if not left or not right:
        return False
    lim = params.parallel_deg * pi / 180.0
    for a0, a1, ang_l in left:
        for b0, b1, ang_r in right:
            if _line_angle_diff(ang_l, ang_r) > lim:
                continue
            width = _perp_width(a0, a1, b0, b1)
            if width < params.min_width_m or width > params.max_width_m:
                continue
            if _overlap_along(a0, a1, b0, b1) < params.min_length_m:
                continue
            mx = 0.25 * (a0[0] + a1[0] + b0[0] + b1[0])
            my = 0.25 * (a0[1] + a1[1] + b0[1] + b1[1])
            if land.covers(Point(mx, my)):
                return True
    return False


def _point_at_arc(
    pts: list[tuple[float, float]], chain: list[int], s: float
) -> tuple[float, float]:
    """Point along a nose→inland chain at arc length s."""
    if len(chain) == 1:
        return pts[chain[0]]
    acc = 0.0
    for i in range(len(chain) - 1):
        a = pts[chain[i]]
        b = pts[chain[i + 1]]
        d = _dist(a, b)
        last = i == len(chain) - 2
        if d < 1e-12:
            if last:
                return b
            continue
        if acc + d >= s or last:
            t = (s - acc) / d
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        acc += d
    return pts[chain[-1]]


def _land_covers(land: Polygon, a: tuple[float, float], b: tuple[float, float]) -> bool:
    mx = 0.5 * (a[0] + b[0])
    my = 0.5 * (a[1] + b[1])
    return bool(land.covers(Point(mx, my)))


def _corridor_ok(
    pts: list[tuple[float, float]],
    left: list[int],
    right: list[int],
    left_arc: float,
    right_arc: float,
    land: Polygon,
    params: PierParams,
) -> bool:
    """Local width along a (possibly bent) corridor, not global collinearity."""
    span = min(left_arc, right_arc)
    if span < 1e-4:
        return True
    step = 8.0
    s = step
    while True:
        sample = s if s < span - 1e-6 else span
        pl = _point_at_arc(pts, left, min(sample, left_arc))
        pr = _point_at_arc(pts, right, min(sample, right_arc))
        w = _dist(pl, pr)
        if w > params.max_width_m:
            return False
        if sample > 8.0 and w < params.min_width_m * 0.4:
            return False
        if not _land_covers(land, pl, pr):
            return False
        if sample >= span - 1e-6:
            return True
        s += step


def _walk_strip(
    pts: list[tuple[float, float]], nose_a: int, land: Polygon, params: PierParams
) -> Polygon | None:
    n = len(pts)
    nose_b = (nose_a + 1) % n
    w0 = _dist(pts[nose_a], pts[nose_b])
    if w0 < params.min_width_m or w0 > params.max_width_m:
        return None

    left = [nose_a]
    right = [nose_b]
    used = {nose_a, nose_b}

    def first_vertex(path: list[int], step: int) -> float | None:
        nxt = (path[0] + step) % n
        if nxt in used:
            return None
        d = _dist(pts[path[0]], pts[nxt])
        if d < 1e-4:
            return None
        path.append(nxt)
        used.add(nxt)
        return d

    left_arc = first_vertex(left, -1)
    right_arc = first_vertex(right, 1)
    if left_arc is None or right_arc is None:
        return None
    if not _corridor_ok(pts, left, right, left_arc, right_arc, land, params):
        return None

    def try_extend(side: str) -> bool:
        nonlocal left_arc, right_arc
        if side == "L":
            path, other, step, arc, other_arc = left, right, -1, left_arc, right_arc
        else:
            path, other, step, arc, other_arc = right, left, 1, right_arc, left_arc
        nxt = (path[-1] + step) % n
        if nxt in used:
            return False
        step_len = _dist(pts[path[-1]], pts[nxt])
        if step_len < 1e-4:
            path.append(nxt)
            used.add(nxt)
            return True
        new_arc = arc + step_len
        path.append(nxt)
        if side == "L":
            ok = _corridor_ok(pts, path, other, new_arc, other_arc, land, params)
        else:
            ok = _corridor_ok(pts, other, path, other_arc, new_arc, land, params)
        if not ok:
            path.pop()
            return False
        # Overshooting the other side: width at the new vertex vs the
        # opposite tip. Catches a coast that turns into the island body.
        opp = _point_at_arc(pts, other, min(new_arc, other_arc))
        if _dist(pts[nxt], opp) > params.max_width_m:
            path.pop()
            return False
        used.add(nxt)
        if side == "L":
            left_arc = new_arc
        else:
            right_arc = new_arc
        return True

    max_arc = max(params.max_length_m, params.min_length_m)
    while min(left_arc, right_arc) < max_arc:
        if abs(left_arc - right_arc) < 1e-6:
            if not try_extend("L") and not try_extend("R"):
                break
        elif left_arc < right_arc:
            if not try_extend("L"):
                break
        else:
            if not try_extend("R"):
                break
        if len(used) >= n - 1:
            break

    def trim(path: list[int], arc: float, other_arc: float) -> float:
        while len(path) > 2 and arc > other_arc + 1.0:
            d = _dist(pts[path[-2]], pts[path[-1]])
            used.discard(path.pop())
            arc -= d
        return arc

    left_arc = trim(left, left_arc, right_arc)
    right_arc = trim(right, right_arc, left_arc)

    if min(left_arc, right_arc) < params.min_length_m:
        return None
    coords = [pts[i] for i in reversed(left)] + [pts[i] for i in right]
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    try:
        poly = Polygon(coords)
    except Exception:
        return None
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly is None or poly.is_empty:
        return None
    clipped = poly.intersection(land)
    best: Polygon | None = None
    best_area = 0.0
    min_area = params.min_width_m * params.min_length_m * 0.25
    for part in _polys_from(clipped):
        if part.area >= min_area and part.area > best_area:
            best = part
            best_area = part.area
    return best


def _clean_geom(geom):
    if geom is None or geom.is_empty:
        return geom
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def _seed_width_m(poly: Polygon) -> float:
    mrr = poly.minimum_rotated_rectangle
    if mrr is None or mrr.is_empty:
        return hypot(poly.bounds[2] - poly.bounds[0], poly.bounds[3] - poly.bounds[1])
    coords = list(mrr.exterior.coords)
    s1 = _dist(coords[0], coords[1])
    s2 = _dist(coords[1], coords[2])
    return max(min(s1, s2), 1.0)


def _grid_ccs(cells: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    leftover = set(cells)
    comps: list[list[tuple[int, int]]] = []
    while leftover:
        start = leftover.pop()
        stack = [start]
        comp = [start]
        while stack:
            y, x = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    n = (y + dy, x + dx)
                    if n in leftover:
                        leftover.remove(n)
                        stack.append(n)
                        comp.append(n)
        comps.append(comp)
    return comps


def _mask_rects(mask, origin_x: float, origin_y: float, cell: float) -> list:
    rects = []
    ny, nx = mask.shape
    for y in range(ny):
        x = 0
        row = mask[y]
        while x < nx:
            if not row[x]:
                x += 1
                continue
            x0 = x
            while x < nx and row[x]:
                x += 1
            rects.append(
                box(
                    origin_x + x0 * cell,
                    origin_y + y * cell,
                    origin_x + x * cell,
                    origin_y + (y + 1) * cell,
                )
            )
    return rects


def _grow_seed(seed: Polygon, land: Polygon, params: PierParams) -> list[Polygon]:
    """Grow a seed into land by successive buffer rings.

    Each ring is land ∩ dilated seed. A connected piece of the ring is a
    path; it stops when that piece (the land contact of the outer outline)
    is grow_widths × the seed width. Forks become separate paths.
    """
    seed = _clean_geom(seed)
    if seed is None or seed.is_empty:
        return []
    width = _seed_width_m(seed)
    stop_len = min(
        max(params.grow_widths, 1.0) * width,
        max(params.max_width_m, width),
    )
    cell = max(1.5, min(width * 0.5, 3.0))
    max_travel = max(params.max_length_m, params.min_length_m)
    pad = max_travel + stop_len + cell * 2.0
    minx, miny, maxx, maxy = seed.bounds
    minx -= pad
    miny -= pad
    maxx += pad
    maxy += pad
    nx = int(np.ceil((maxx - minx) / cell)) + 1
    ny = int(np.ceil((maxy - miny) / cell)) + 1
    if nx * ny > 220_000:
        cell *= (nx * ny / 220_000.0) ** 0.5
        nx = int(np.ceil((maxx - minx) / cell)) + 1
        ny = int(np.ceil((maxy - miny) / cell)) + 1
    xs = minx + (np.arange(nx, dtype=np.float64) + 0.5) * cell
    ys = miny + (np.arange(ny, dtype=np.float64) + 0.5) * cell
    xx, yy = np.meshgrid(xs, ys)
    local = _clean_geom(land.intersection(box(minx, miny, maxx, maxy)))
    if local is None or local.is_empty:
        return [seed]
    prepare(local)
    land_m = contains_xy(local, xx, yy)
    seed_m = contains_xy(seed, xx, yy) & land_m
    if not np.any(seed_m):
        return [seed]

    claimed = seed_m.copy()

    def collect_ring(front: set[tuple[int, int]]) -> list[tuple[int, int]]:
        nxt: dict[tuple[int, int], bool] = {}
        for y, x in front:
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    iy, ix = y + dy, x + dx
                    if iy < 0 or ix < 0 or iy >= ny or ix >= nx:
                        continue
                    if land_m[iy, ix] and not claimed[iy, ix]:
                        nxt[iy, ix] = True
        return list(nxt.keys())

    def take_ring(front: set[tuple[int, int]], limit: bool) -> set[tuple[int, int]]:
        ring = collect_ring(front)
        if not ring:
            return set()
        grouped = set(ring)
        if limit:
            for y, x in ring:
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        iy, ix = y + dy, x + dx
                        if 0 <= iy < ny and 0 <= ix < nx:
                            grouped.add((iy, ix))
        ring_set = set(ring)
        kept: set[tuple[int, int]] = set()
        for comp in _grid_ccs(list(grouped)):
            members = [c for c in comp if c in ring_set]
            if not members:
                continue
            if limit:
                ys = [c[0] for c in members]
                xs = [c[1] for c in members]
                bbox_len = max(max(ys) - min(ys) + 1, max(xs) - min(xs) + 1) * cell
                arc_len = len(members) * cell
                if max(bbox_len, arc_len) >= stop_len:
                    continue
            kept.update(members)
            for iy, ix in members:
                claimed[iy, ix] = True
        return kept

    fy, fx = np.nonzero(seed_m)
    frontier = set(zip(fy.tolist(), fx.tolist()))
    # 2-cell halo around the vector seed closes raster cracks only.
    for _ in range(2):
        frontier = take_ring(frontier, limit=False)
        if not frontier:
            break
    if not frontier:
        fy, fx = np.nonzero(claimed)
        frontier = set(zip(fy.tolist(), fx.tolist()))

    max_steps = int(max_travel / cell) + 2
    for _ in range(max_steps):
        frontier = take_ring(frontier, limit=True)
        if not frontier:
            break

    rects = _mask_rects(claimed, minx, miny, cell)
    if not rects:
        return [seed]
    grown = _clean_geom(unary_union(rects))
    if grown is None or grown.is_empty:
        return [seed]
    grown = _clean_geom(unary_union([seed, grown]).intersection(land))
    parts = _polys_from(grown)
    return parts if parts else [seed]


def _detect_on_island(land: Polygon, params: PierParams) -> list[Polygon]:
    pts = _ensure_ccw(_ring_xy(land.exterior.coords))
    n = len(pts)
    if n < 6:
        return []
    found: list[Polygon] = []
    seen: set[tuple[int, int]] = set()
    for i in range(n):
        corner = _corner(pts, i)
        if corner is None:
            continue
        interior, l1, l2 = corner
        if not _is_candidate(interior, l1, l2, params):
            continue
        if not _has_parallel_pair(pts, i, land, params):
            continue
        noses: list[int] = []
        prev_i = (i - 1) % n
        if params.right_angle_min_deg <= interior <= params.right_angle_max_deg:
            if l1 <= params.max_width_m:
                noses.append(prev_i)
            if l2 <= params.max_width_m:
                noses.append(i)
        elif interior < params.right_angle_min_deg:
            if l1 < params.acute_edge_m:
                noses.append(prev_i)
            if l2 < params.acute_edge_m:
                noses.append(i)
        else:
            if l1 <= l2 and l1 <= params.max_width_m:
                noses.append(prev_i)
            if l2 <= l1 and l2 <= params.max_width_m:
                noses.append(i)
        if not noses:
            continue
        for nose_a in noses:
            key = (nose_a, (nose_a + 1) % n)
            if key in seen:
                continue
            poly = _walk_strip(pts, nose_a, land, params)
            if poly is None:
                continue
            seen.add(key)
            found.append(poly)
    if not found:
        return []
    packed = unary_union(found)
    gap = max(params.merge_gap_m, 0.0)
    if gap > 0.0 and not packed.is_empty:
        packed = packed.buffer(gap).buffer(-gap)
    packed = packed.intersection(land)
    seeds = _polys_from(packed)
    # Small harbor islets: the corridor walk is enough. Growing on every
    # rock-scale island is slow and floods the islet with concrete.
    if land.area < 1_000_000.0:
        return seeds
    grown: list[Polygon] = []
    for seed in seeds:
        grown.extend(_grow_seed(seed, land, params))
    return grown


def find_pier_rings(coast, params: PierParams | None = None) -> list[list[tuple[float, float]]]:
    """Return pier exteriors (open rings) on islands larger than min_island_m2."""
    params = params or PierParams()
    chunks: list[Polygon] = []
    islands: list[Polygon] = []
    n_islands = 0
    for feat in coast:
        area = float(feat.area_m2 or 0.0)
        try:
            land = Polygon(feat.exterior, feat.holes or None)
        except Exception:
            continue
        if land.is_empty:
            continue
        if not land.is_valid:
            land = land.buffer(0)
        if land is None or land.is_empty:
            continue
        if area <= 0.0:
            area = float(land.area)
        if area < params.min_island_m2:
            continue
        n_islands += 1
        for part in _polys_from(land):
            islands.append(part)
            chunks.extend(_detect_on_island(part, params))
    if not chunks:
        print(f"GL piers: 0 strips  islands {n_islands}", flush=True)
        return []
    merged = unary_union(chunks)
    gap = max(params.merge_gap_m, 0.0)
    if gap > 0.0 and not merged.is_empty:
        merged = merged.buffer(gap).buffer(-gap)
    if islands:
        merged = merged.intersection(unary_union(islands))
    pad = max(params.stamp_pad_m, 0.0)
    if pad > 0.0 and not merged.is_empty:
        merged = merged.buffer(pad)
    rings: list[list[tuple[float, float]]] = []
    for part in _polys_from(merged):
        ring = _ring_xy(part.exterior.coords)
        if len(ring) >= 3:
            rings.append(ring)
    print(
        f"GL piers: {len(rings)} regions from {len(chunks)} grown  "
        f"islands {n_islands}",
        flush=True,
    )
    return rings
