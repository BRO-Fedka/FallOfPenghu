from __future__ import annotations

from array import array
from heapq import heappop, heappush
from math import hypot

from fall_of_penghu.world.entities.land.limits import (
    SEA_ASTAR_MAX_ITERS,
    tick,
    unwind,
)

# Open water merges up to this many fine cells on a side (16 × 150 m = 2.4 km).
# Coasts stay at one cell so channels and berths keep the old resolution.
SEA_LEAF_MAX = 16


class SeaGraph:
    """Water graph with large cells offshore, fine cells along land.

    Same idea as the island road graph: A* walks a sparse adjacency list,
    not every 150 m cell between the map edges.
    """

    def __init__(self) -> None:
        self.nodes: list[tuple[float, float]] = []
        self.adj: list[list[tuple[int, float]]] = []
        self.leaf_of = array("i")
        self._w = 0
        self._h = 0

    @classmethod
    def from_grid(
        cls,
        origin: tuple[float, float],
        cell_m: float,
        w: int,
        h: int,
        block: list[bool],
    ) -> SeaGraph:
        graph = cls()
        graph._build(origin, cell_m, w, h, block)
        return graph

    def dump(self) -> dict:
        return {
            "w": int(self._w),
            "h": int(self._h),
            "nodes": [(float(x), float(y)) for x, y in self.nodes],
            "adj": [[(int(j), float(cost)) for j, cost in row] for row in self.adj],
            "leaf_of": self.leaf_of,
        }

    @classmethod
    def from_dump(cls, data: dict) -> SeaGraph | None:
        try:
            w = int(data["w"])
            h = int(data["h"])
            nodes = [(float(x), float(y)) for x, y in data["nodes"]]
            adj = [
                [(int(j), float(cost)) for j, cost in row] for row in data["adj"]
            ]
            raw = data["leaf_of"]
            if isinstance(raw, array) and raw.typecode == "i":
                leaf_of = array("i", raw)
            elif isinstance(raw, (bytes, bytearray)):
                leaf_of = array("i")
                leaf_of.frombytes(bytes(raw))
            else:
                leaf_of = array("i", (int(v) for v in raw))
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if w < 1 or h < 1 or len(leaf_of) != w * h or len(nodes) != len(adj):
            return None
        graph = cls()
        graph._w = w
        graph._h = h
        graph.nodes = nodes
        graph.adj = adj
        graph.leaf_of = leaf_of
        return graph

    def leaf_of_cell(self, cell: int) -> int | None:
        if cell < 0 or cell >= len(self.leaf_of):
            return None
        leaf = self.leaf_of[cell]
        return None if leaf < 0 else leaf

    def astar(self, start: int, goal: int) -> list[int] | None:
        if start == goal:
            return [start]
        gx, gy = self.nodes[goal]
        heap: list[tuple[float, int]] = [(0.0, start)]
        cost = {start: 0.0}
        prev: dict[int, int] = {}
        done: set[int] = set()
        steps = 0
        while heap:
            steps = tick("sea.astar", steps, SEA_ASTAR_MAX_ITERS)
            _, u = heappop(heap)
            if u in done:
                continue
            done.add(u)
            if u == goal:
                return unwind(prev, u, "sea.astar")
            for v, w in self.adj[u]:
                if v in done:
                    continue
                nxt = cost[u] + w
                if nxt < cost.get(v, 1e30):
                    cost[v] = nxt
                    prev[v] = u
                    hx, hy = self.nodes[v]
                    heappush(heap, (nxt + hypot(hx - gx, hy - gy), v))
        return None

    def _build(
        self,
        origin: tuple[float, float],
        cell_m: float,
        w: int,
        h: int,
        block: list[bool],
    ) -> None:
        self._w = w
        self._h = h
        if w < 1 or h < 1:
            return
        integ = _integral(block, w, h)
        iw = w + 1
        leaves: list[tuple[int, int, int]] = []

        def subdiv(gx: int, gy: int, size: int) -> None:
            land, area = _land_in(integ, iw, w, h, gx, gy, size)
            if area == 0 or land == area:
                return
            inside = gx >= 0 and gy >= 0 and gx + size <= w and gy + size <= h
            if land == 0 and size <= SEA_LEAF_MAX and inside:
                leaves.append((gx, gy, size))
                return
            if size == 1:
                leaves.append((gx, gy, 1))
                return
            half = size >> 1
            subdiv(gx, gy, half)
            subdiv(gx + half, gy, half)
            subdiv(gx, gy + half, half)
            subdiv(gx + half, gy + half, half)

        subdiv(0, 0, _pow2_ge(max(w, h)))

        ox, oy = origin
        nodes = [
            (ox + (gx + size * 0.5) * cell_m, oy + (gy + size * 0.5) * cell_m)
            for gx, gy, size in leaves
        ]
        leaf_of = array("i", [-1]) * (w * h)
        for i, (gx, gy, size) in enumerate(leaves):
            for yy in range(gy, gy + size):
                row = yy * w
                for xx in range(gx, gx + size):
                    leaf_of[row + xx] = i

        adj: list[list[tuple[int, float]]] = [[] for _ in leaves]
        seen: set[tuple[int, int]] = set()

        def water(x: int, y: int) -> bool:
            return 0 <= x < w and 0 <= y < h and leaf_of[y * w + x] >= 0

        def link(i: int, x: int, y: int) -> None:
            if not water(x, y):
                return
            j = leaf_of[y * w + x]
            if j == i:
                return
            key = (i, j) if i < j else (j, i)
            if key in seen:
                return
            seen.add(key)
            d = hypot(nodes[i][0] - nodes[j][0], nodes[i][1] - nodes[j][1])
            adj[i].append((j, d))
            adj[j].append((i, d))

        def diag(i: int, ux: int, uy: int, dx: int, dy: int) -> None:
            if not water(ux + dx, uy + dy):
                return
            if not water(ux + dx, uy) or not water(ux, uy + dy):
                return
            link(i, ux + dx, uy + dy)

        for i, (gx, gy, size) in enumerate(leaves):
            x1 = gx + size
            y1 = gy + size
            for x in range(gx, x1):
                link(i, x, gy - 1)
                link(i, x, y1)
            for y in range(gy, y1):
                link(i, gx - 1, y)
                link(i, x1, y)
            diag(i, gx, gy, -1, -1)
            diag(i, x1 - 1, gy, 1, -1)
            diag(i, gx, y1 - 1, -1, 1)
            diag(i, x1 - 1, y1 - 1, 1, 1)

        self.nodes = nodes
        self.adj = adj
        self.leaf_of = leaf_of


def _pow2_ge(n: int) -> int:
    size = 1
    while size < n:
        size <<= 1
    return size


def _integral(block: list[bool], w: int, h: int) -> list[int]:
    iw = w + 1
    out = [0] * ((h + 1) * iw)
    for y in range(h):
        run = 0
        above = y * iw
        row = (y + 1) * iw
        base = y * w
        for x in range(w):
            run += 1 if block[base + x] else 0
            out[row + x + 1] = out[above + x + 1] + run
    return out


def _land_in(
    integ: list[int],
    iw: int,
    w: int,
    h: int,
    gx: int,
    gy: int,
    size: int,
) -> tuple[int, int]:
    x0 = 0 if gx < 0 else gx
    y0 = 0 if gy < 0 else gy
    x1 = w if gx + size > w else gx + size
    y1 = h if gy + size > h else gy + size
    if x1 <= x0 or y1 <= y0:
        return 0, 0
    area = (x1 - x0) * (y1 - y0)
    count = (
        integ[y1 * iw + x1]
        - integ[y0 * iw + x1]
        - integ[y1 * iw + x0]
        + integ[y0 * iw + x0]
    )
    return count, area
