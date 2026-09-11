from __future__ import annotations

from heapq import heappop, heappush
from math import hypot

from fall_of_penghu.world.entities.land.islands import IslandIndex
from fall_of_penghu.world.entities.land.limits import (
    ASTAR_MAX_ITERS,
    NEAREST_MAX_RINGS,
    tick,
    unwind,
)
from fall_of_penghu.world.map import MapData

SNAP_M = 12.0
HASH_M = 400.0


class IslandRoads:
    """Road graph of one island. Inter-island spans are not included."""

    def __init__(self) -> None:
        self.nodes: list[tuple[float, float]] = []
        self.adj: list[list[tuple[int, float]]] = []
        self.edges: list[tuple[int, int]] = []
        self._grid: dict[tuple[int, int], list[int]] = {}
        self._segs: dict[tuple[int, int], list[int]] = {}
        self._cache: dict[tuple[int, int], list[int] | None] = {}

    def near_edge(self, x: float, y: float, max_m: float) -> float | None:
        """Distance to the closest road segment, not to the closest node.

        A unit halfway between two nodes is still on the road, so node
        distance alone would strip it of road speed.
        """
        if not self.edges:
            return None
        rad = int(max_m // HASH_M) + 1
        gx, gy = int(x // HASH_M), int(y // HASH_M)
        best = max_m * max_m
        hit = False
        seen: set[int] = set()
        for ox in range(gx - rad, gx + rad + 1):
            for oy in range(gy - rad, gy + rad + 1):
                for e in self._segs.get((ox, oy), ()):
                    if e in seen:
                        continue
                    seen.add(e)
                    ia, ib = self.edges[e]
                    d = _seg_dist2(x, y, self.nodes[ia], self.nodes[ib])
                    if d < best:
                        best = d
                        hit = True
        return best**0.5 if hit else None

    def nearest(self, x: float, y: float, max_m: float | None = None) -> int | None:
        if not self.nodes:
            return None
        gx, gy = int(x // HASH_M), int(y // HASH_M)
        best_i = None
        best_d = 1e30 if max_m is None else max_m * max_m
        limit = NEAREST_MAX_RINGS
        if max_m is not None:
            limit = min(limit, int(max_m / HASH_M) + 2)
        for rad in range(0, limit):
            for ox in range(gx - rad, gx + rad + 1):
                for oy in range(gy - rad, gy + rad + 1):
                    if rad and abs(ox - gx) != rad and abs(oy - gy) != rad:
                        continue
                    for i in self._grid.get((ox, oy), ()):
                        nx, ny = self.nodes[i]
                        d = (nx - x) * (nx - x) + (ny - y) * (ny - y)
                        if d < best_d:
                            best_d = d
                            best_i = i
            if best_i is not None and rad >= 1:
                return best_i
        return best_i

    def astar(self, start: int, goal: int) -> list[int] | None:
        key = (start, goal)
        if key in self._cache:
            return self._cache[key]
        gx, gy = self.nodes[goal]
        heap: list[tuple[float, int]] = [(0.0, start)]
        cost = {start: 0.0}
        prev: dict[int, int] = {}
        found: list[int] | None = None
        steps = 0
        while heap:
            steps = tick("island_roads.astar", steps, ASTAR_MAX_ITERS)
            _, u = heappop(heap)
            if u == goal:
                found = unwind(prev, u, "island_roads.astar")
                break
            for v, w in self.adj[u]:
                nxt = cost[u] + w
                if nxt < cost.get(v, 1e30):
                    cost[v] = nxt
                    prev[v] = u
                    hx, hy = self.nodes[v]
                    heappush(heap, (nxt + hypot(hx - gx, hy - gy), v))
        self._cache[key] = found
        if found is not None:
            self._cache[(goal, start)] = list(reversed(found))
        return found

    def points_of(self, nodes: list[int]) -> list[tuple[float, float]]:
        return [self.nodes[i] for i in nodes]


def build_island_roads(
    world: MapData,
    islands: IslandIndex,
    skip_roads: set[int],
) -> dict[int, IslandRoads]:
    buckets: dict[int, list[tuple[float, float]]] = {}
    edges: dict[int, list[tuple[tuple[float, float], tuple[float, float]]]] = {}
    for i, road in enumerate(world.roads):
        if i in skip_roads or len(road.points) < 2:
            continue
        mid = road.points[len(road.points) // 2]
        owner = islands.at(*mid)
        if owner is None:
            owner = islands.nearest(*mid, 80.0)
        if owner is None:
            continue
        buckets.setdefault(owner, []).extend(road.points)
        pair = edges.setdefault(owner, [])
        for a, b in zip(road.points, road.points[1:]):
            pair.append((a, b))
    out: dict[int, IslandRoads] = {}
    for island, raw in buckets.items():
        out[island] = _snap_graph(raw, edges.get(island, ()))
    return out


def _snap_graph(
    raw: list[tuple[float, float]],
    segs: list[tuple[tuple[float, float], tuple[float, float]]],
) -> IslandRoads:
    graph = IslandRoads()
    if not raw:
        return graph
    parent = list(range(len(raw)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cell = SNAP_M
    buckets: dict[tuple[int, int], list[int]] = {}
    for i, (x, y) in enumerate(raw):
        buckets.setdefault((int(x // cell), int(y // cell)), []).append(i)
    thresh2 = SNAP_M * SNAP_M
    for (gx, gy), idxs in buckets.items():
        nearby: list[int] = []
        for ox in range(gx - 1, gx + 2):
            for oy in range(gy - 1, gy + 2):
                nearby.extend(buckets.get((ox, oy), ()))
        for i in idxs:
            xi, yi = raw[i]
            for j in nearby:
                if j <= i:
                    continue
                dx = xi - raw[j][0]
                dy = yi - raw[j][1]
                if dx * dx + dy * dy <= thresh2:
                    parent[find(j)] = find(i)

    remap = [-1] * len(raw)
    acc: dict[int, list[tuple[float, float]]] = {}
    for i, pt in enumerate(raw):
        acc.setdefault(find(i), []).append(pt)
    nodes: list[tuple[float, float]] = []
    for n, root in enumerate(sorted(acc)):
        pts = acc[root]
        nodes.append(
            (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        )
        remap[root] = n
    for i in range(len(raw)):
        remap[i] = remap[find(i)]

    index: dict[tuple[float, float], int] = {}
    for i, pt in enumerate(raw):
        index[pt] = remap[i]

    adj: list[list[tuple[int, float]]] = [[] for _ in nodes]
    seen: set[tuple[int, int]] = set()
    for a, b in segs:
        ia = index.get(a)
        ib = index.get(b)
        if ia is None or ib is None or ia == ib:
            continue
        key = (ia, ib) if ia < ib else (ib, ia)
        if key in seen:
            continue
        seen.add(key)
        d = hypot(nodes[ia][0] - nodes[ib][0], nodes[ia][1] - nodes[ib][1])
        adj[ia].append((ib, d))
        adj[ib].append((ia, d))

    grid: dict[tuple[int, int], list[int]] = {}
    for i, (x, y) in enumerate(nodes):
        grid.setdefault((int(x // HASH_M), int(y // HASH_M)), []).append(i)
    graph.nodes = nodes
    graph.adj = adj
    graph.edges = sorted(seen)
    graph._grid = grid
    graph._segs = _seg_grid(nodes, graph.edges)
    return graph


def _seg_grid(
    nodes: list[tuple[float, float]],
    edges: list[tuple[int, int]],
) -> dict[tuple[int, int], list[int]]:
    out: dict[tuple[int, int], list[int]] = {}
    for e, (ia, ib) in enumerate(edges):
        ax, ay = nodes[ia]
        bx, by = nodes[ib]
        for gx in range(int(min(ax, bx) // HASH_M), int(max(ax, bx) // HASH_M) + 1):
            for gy in range(int(min(ay, by) // HASH_M), int(max(ay, by) // HASH_M) + 1):
                out.setdefault((gx, gy), []).append(e)
    return out


def _seg_dist2(
    x: float,
    y: float,
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    span = dx * dx + dy * dy
    if span <= 0.0:
        return (x - ax) ** 2 + (y - ay) ** 2
    t = ((x - ax) * dx + (y - ay) * dy) / span
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2
