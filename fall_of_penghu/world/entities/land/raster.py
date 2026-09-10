from __future__ import annotations

from heapq import heappop, heappush
from math import hypot, sqrt

from fall_of_penghu.world.entities.land.geom import point_in_poly
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
        ox, oy = self.origin
        c = self.cell_m
        minx, miny, maxx, maxy = feat.bbox
        gx0 = max(0, int((minx - ox) / c) - 1)
        gy0 = max(0, int((miny - oy) / c) - 1)
        gx1 = min(self.w, int((maxx - ox) / c) + 2)
        gy1 = min(self.h, int((maxy - oy) / c) + 2)
        for gy in range(gy0, gy1):
            y0 = oy + gy * c
            y1 = y0 + c
            row = gy * self.w
            for gx in range(gx0, gx1):
                x0 = ox + gx * c
                x1 = x0 + c
                corners = (
                    point_in_poly(x0, y0, feat),
                    point_in_poly(x1, y0, feat),
                    point_in_poly(x0, y1, feat),
                    point_in_poly(x1, y1, feat),
                    point_in_poly((x0 + x1) * 0.5, (y0 + y1) * 0.5, feat),
                )
                n = sum(corners)
                if n == 5:
                    self.cell[row + gx] = 0
                elif n > 0 and self.cell[row + gx] == 2:
                    self.cell[row + gx] = 1

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
        came = self._astar(sa, sb)
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

    def _astar(self, start: int, goal: int) -> list[int] | None:
        w, h = self.w, self.h
        gx, gy = goal % w, goal // w
        heap: list[tuple[float, int]] = [(0.0, start)]
        cost = {start: 0.0}
        prev: dict[int, int] = {}
        cell = self.cell
        done: set[int] = set()
        steps = 0
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
                if v in done or cell[v] == 2:
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
