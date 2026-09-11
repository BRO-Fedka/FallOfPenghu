from __future__ import annotations

from heapq import heappop, heappush
from math import hypot, sqrt

from fall_of_penghu.world.entities.land.limits import (
    RASTER_ASTAR_MAX_ITERS,
    RASTER_MAX_CELL_M,
    RASTER_MAX_CELLS,
    RASTER_MIN_CELL_M,
    RASTER_TARGET_CELLS,
    SearchLimitError,
    tick,
    unwind,
)
from fall_of_penghu.world.map import PolyFeature

# 0 full land, 1 mixed/coast, 2 water.


class IslandRaster:
    """Per-island occupancy. Cell size grows so Magong still fits."""

    def __init__(self, feats: PolyFeature | list[PolyFeature]) -> None:
        if isinstance(feats, PolyFeature):
            feats = [feats]
        if not feats:
            raise ValueError("island raster needs a coast")
        minx = min(feat.bbox[0] for feat in feats)
        miny = min(feat.bbox[1] for feat in feats)
        maxx = max(feat.bbox[2] for feat in feats)
        maxy = max(feat.bbox[3] for feat in feats)
        self.cell_m = _cell_m(minx, miny, maxx, maxy)
        pad = self.cell_m * 2.0
        self.origin = (minx - pad, miny - pad)
        self.w = max(2, int((maxx - minx + 2 * pad) / self.cell_m) + 1)
        self.h = max(2, int((maxy - miny + 2 * pad) / self.cell_m) + 1)
        cells = self.w * self.h
        if cells > RASTER_MAX_CELLS:
            raise SearchLimitError("island_raster.bake", cells, RASTER_MAX_CELLS)
        self.cell = [2] * cells
        for feat in feats:
            self._fill(feat)

    def _fill(self, feat: PolyFeature) -> None:
        """Scanline fill, then trace the rings.

        Sampling five points per cell meant a quarter million polygon tests on
        Magong and froze the game for twenty seconds the first time a unit asked
        for an off-road route.
        """
        rings = [list(feat.exterior), *[list(hole) for hole in feat.holes]]
        self._scan(rings, feat.bbox)
        self._trace(rings)

    def _scan(
        self,
        rings: list[list[tuple[float, float]]],
        bbox: tuple[float, float, float, float],
    ) -> None:
        ox, oy = self.origin
        c = self.cell_m
        gy0 = max(0, int((bbox[1] - oy) / c))
        gy1 = min(self.h - 1, int((bbox[3] - oy) / c) + 1)
        by_row: dict[int, list[tuple[float, float, float, float]]] = {}
        for ring in rings:
            for a, b in zip(ring, ring[1:] + ring[:1]):
                if a[1] == b[1]:
                    continue
                lo, hi = (a, b) if a[1] < b[1] else (b, a)
                slope = (hi[0] - lo[0]) / (hi[1] - lo[1])
                r0 = max(gy0, int((lo[1] - oy) / c) - 1)
                r1 = min(gy1, int((hi[1] - oy) / c) + 1)
                for gy in range(r0, r1 + 1):
                    by_row.setdefault(gy, []).append((lo[1], hi[1], lo[0], slope))
        for gy in range(gy0, gy1 + 1):
            y = oy + (gy + 0.5) * c
            xs = [
                x0 + (y - y0) * slope
                for y0, y1, x0, slope in by_row.get(gy, ())
                if y0 <= y < y1
            ]
            if len(xs) < 2:
                continue
            xs.sort()
            row = gy * self.w
            for k in range(0, len(xs) - 1, 2):
                lo_x, hi_x = xs[k], xs[k + 1]
                ga = max(0, int((lo_x - ox) / c))
                gb = min(self.w - 1, int((hi_x - ox) / c) + 1)
                for gx in range(ga, gb + 1):
                    cx = ox + (gx + 0.5) * c
                    if lo_x <= cx <= hi_x:
                        self.cell[row + gx] = 0

    def _trace(self, rings: list[list[tuple[float, float]]]) -> None:
        """Coast cells stay walkable so thin spits and capes are not cut off."""
        ox, oy = self.origin
        c = self.cell_m
        step = c * 0.5
        for ring in rings:
            for a, b in zip(ring, ring[1:] + ring[:1]):
                dx = b[0] - a[0]
                dy = b[1] - a[1]
                n = max(1, int(hypot(dx, dy) / step))
                for k in range(n + 1):
                    t = k / n
                    gx = int((a[0] + dx * t - ox) / c)
                    gy = int((a[1] + dy * t - oy) / c)
                    if 0 <= gx < self.w and 0 <= gy < self.h:
                        self.cell[gy * self.w + gx] = 1

    def index(self, x: float, y: float) -> int | None:
        gx = int((x - self.origin[0]) / self.cell_m)
        gy = int((y - self.origin[1]) / self.cell_m)
        if gx < 0 or gy < 0 or gx >= self.w or gy >= self.h:
            return None
        i = gy * self.w + gx
        if self.cell[i] == 2:
            return None
        return i

    def xy(self, i: int) -> tuple[float, float]:
        gx = i % self.w
        gy = i // self.w
        return (
            self.origin[0] + (gx + 0.5) * self.cell_m,
            self.origin[1] + (gy + 0.5) * self.cell_m,
        )

    def code(self, i: int) -> int:
        return self.cell[i]

    def path(
        self, start: tuple[float, float], goal: tuple[float, float]
    ) -> list[tuple[float, float]] | None:
        sa = self.index(*start)
        sb = self.index(*goal)
        if sa is None or sb is None:
            return None
        if sa == sb:
            return [start, goal] if start != goal else [start]
        came = self._astar(sa, sb, strict=True)
        if came is None:
            came = self._astar(sa, sb, strict=False)
        if came is None:
            return None
        pts = [start]
        for i in came:
            pt = self.xy(i)
            if pt != pts[-1]:
                pts.append(pt)
        if goal != pts[-1]:
            pts.append(goal)
        return pts if len(pts) >= 2 else None

    def _astar(self, start: int, goal: int, *, strict: bool) -> list[int] | None:
        """Strict keeps to full-land cells, so the line never clips a bay.

        Coast cells are half water: a route through their centres used to run
        over the sea. They are allowed only as a fallback and at the ends.
        """
        w, h = self.w, self.h
        gx, gy = goal % w, goal // w
        heap: list[tuple[float, int]] = [(0.0, start)]
        cost = {start: 0.0}
        prev: dict[int, int] = {}
        cell = self.cell
        done: set[int] = set()
        ends = (start, goal)
        steps = 0

        def open_cell(i: int) -> bool:
            code = cell[i]
            if code == 2:
                return False
            return code == 0 or not strict or i in ends

        while heap:
            steps = tick("island_raster.astar", steps, RASTER_ASTAR_MAX_ITERS)
            _, u = heappop(heap)
            if u in done:
                continue
            done.add(u)
            if u == goal:
                return unwind(prev, u, "island_raster.astar")
            ux, uy = u % w, u // w
            for dx, dy, step in (
                (-1, 0, 1.0),
                (1, 0, 1.0),
                (0, -1, 1.0),
                (0, 1, 1.0),
                (-1, -1, 1.414),
                (-1, 1, 1.414),
                (1, -1, 1.414),
                (1, 1, 1.414),
            ):
                vx, vy = ux + dx, uy + dy
                if vx < 0 or vy < 0 or vx >= w or vy >= h:
                    continue
                v = vy * w + vx
                if v in done or not open_cell(v):
                    continue
                if dx and dy:
                    if not open_cell(uy * w + vx) or not open_cell(vy * w + ux):
                        continue
                nxt = cost[u] + step
                if nxt < cost.get(v, 1e30):
                    cost[v] = nxt
                    prev[v] = u
                    heappush(heap, (nxt + hypot(vx - gx, vy - gy), v))
        return None


def _cell_m(minx: float, miny: float, maxx: float, maxy: float) -> float:
    pad = RASTER_MIN_CELL_M * 4.0
    span_x = max(maxx - minx + pad, RASTER_MIN_CELL_M)
    span_y = max(maxy - miny + pad, RASTER_MIN_CELL_M)
    area = span_x * span_y
    cell = RASTER_MIN_CELL_M
    if area / (cell * cell) > RASTER_TARGET_CELLS:
        cell = sqrt(area / RASTER_TARGET_CELLS)
    return min(RASTER_MAX_CELL_M, max(RASTER_MIN_CELL_M, cell))
