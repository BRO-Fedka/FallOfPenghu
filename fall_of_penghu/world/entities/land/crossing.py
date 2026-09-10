from __future__ import annotations

from dataclasses import dataclass

from math import hypot

from fall_of_penghu.world.entities.game_object import GameObject
from fall_of_penghu.world.entities.land.geom import dist_poly
from fall_of_penghu.world.entities.land.islands import IslandIndex
from fall_of_penghu.world.entities.land.limits import CHAIN_MAX_ITERS, tick
from fall_of_penghu.world.map import MapData

CLUSTER_M = 100.0
END_SNAP_M = 150.0
SITE_MATCH_M = 280.0
ON_BRIDGE_M = 22.0


@dataclass
class Crossing:
    """Inter-island span. Integrity is the GameObject, not a copy on the edge."""

    id: str
    island_a: int
    island_b: int
    points: list[tuple[float, float]]
    portal_a: tuple[float, float]
    portal_b: tuple[float, float]


def _cluster_roads(world: MapData) -> list[list[int]]:
    segs = [i for i, r in enumerate(world.roads) if r.bridge and len(r.points) >= 2]
    if not segs:
        return []
    parent = list(range(len(segs)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cell = CLUSTER_M
    buckets: dict[tuple[int, int], list[tuple[int, float, float]]] = {}
    for si, road_i in enumerate(segs):
        for x, y in world.roads[road_i].points:
            buckets.setdefault((int(x // cell), int(y // cell)), []).append((si, x, y))
    thresh2 = CLUSTER_M * CLUSTER_M
    for (gx, gy), pts in buckets.items():
        nearby: list[tuple[int, float, float]] = []
        for ox in range(gx - 1, gx + 2):
            for oy in range(gy - 1, gy + 2):
                nearby.extend(buckets.get((ox, oy), ()))
        for si, x, y in pts:
            for sj, ux, uy in nearby:
                if sj <= si:
                    continue
                if (x - ux) * (x - ux) + (y - uy) * (y - uy) <= thresh2:
                    parent[find(sj)] = find(si)
    groups: dict[int, list[int]] = {}
    for i, road_i in enumerate(segs):
        groups.setdefault(find(i), []).append(road_i)
    return list(groups.values())


CHAIN_SNAP_M = 18.0


def _polyline(world: MapData, idxs: list[int]) -> list[tuple[float, float]]:
    segs = [list(world.roads[i].points) for i in idxs if len(world.roads[i].points) >= 2]
    if not segs:
        return []
    return _chain_segments(segs)


def _chain_segments(
    segs: list[list[tuple[float, float]]],
    snap_m: float = CHAIN_SNAP_M,
) -> list[tuple[float, float]]:
    unused = [list(seg) for seg in segs]
    path = unused.pop(0)
    steps = 0

    def _join(
        body: list[tuple[float, float]], extra: list[tuple[float, float]], at_head: bool
    ) -> list[tuple[float, float]]:
        if at_head:
            if extra and body and extra[-1] == body[0]:
                extra = extra[:-1]
            return extra + body
        if extra and body and extra[0] == body[-1]:
            extra = extra[1:]
        return body + extra

    steps = 0
    while unused:
        steps = tick("bridge_chain", steps, CHAIN_MAX_ITERS)
        tip = path[-1]
        head = path[0]
        best_i = -1
        best_d = snap_m
        best_rev = False
        best_head = False
        for i, seg in enumerate(unused):
            for at_head, anchor in ((False, tip), (True, head)):
                d0 = hypot(seg[0][0] - anchor[0], seg[0][1] - anchor[1])
                d1 = hypot(seg[-1][0] - anchor[0], seg[-1][1] - anchor[1])
                if d0 <= best_d:
                    best_d = d0
                    best_i = i
                    best_rev = False
                    best_head = at_head
                if d1 <= best_d:
                    best_d = d1
                    best_i = i
                    best_rev = True
                    best_head = at_head
        if best_i < 0:
            break
        extra = unused.pop(best_i)
        if best_rev:
            extra.reverse()
        path = _join(path, extra, best_head)
    cleaned: list[tuple[float, float]] = []
    for pt in path:
        if not cleaned or pt != cleaned[-1]:
            cleaned.append(pt)
    return cleaned


def _islands_of(index: IslandIndex, pts: list[tuple[float, float]]) -> set[int]:
    found: set[int] = set()
    for x, y in pts:
        i = index.at(x, y)
        if i is not None:
            found.add(i)
    if len(found) >= 2:
        return found
    ends = (
        index.nearest(pts[0][0], pts[0][1], END_SNAP_M * 2),
        index.nearest(pts[-1][0], pts[-1][1], END_SNAP_M * 2),
    )
    for i in ends:
        if i is not None:
            found.add(i)
    return found


class CrossingBook:
    """Inter-island bridges. Intra-island spans stay in the island road graph."""

    def __init__(self, world: MapData, islands: IslandIndex) -> None:
        self._items: list[Crossing] = []
        self._used_roads: set[int] = set()
        raw: list[tuple[set[int], list[int], list[tuple[float, float]]]] = []
        for idxs in _cluster_roads(world):
            pts = _polyline(world, idxs)
            if len(pts) < 2:
                continue
            ids = _islands_of(islands, pts)
            if len(ids) != 2:
                continue
            raw.append((ids, idxs, pts))
        for n, (ids, idxs, pts) in enumerate(raw):
            ia, ib = self._orient(islands, pts)
            if ia is None or ib is None or ia == ib:
                continue
            if ia not in ids or ib not in ids:
                continue
            self._used_roads.update(idxs)
            self._items.append(
                Crossing(
                    id=f"span_{n}",
                    island_a=ia,
                    island_b=ib,
                    points=pts,
                    portal_a=pts[0],
                    portal_b=pts[-1],
                )
            )

    @staticmethod
    def _orient(
        islands: IslandIndex,
        pts: list[tuple[float, float]],
    ) -> tuple[int | None, int | None]:
        start = islands.nearest(pts[0][0], pts[0][1], END_SNAP_M * 2)
        end = islands.nearest(pts[-1][0], pts[-1][1], END_SNAP_M * 2)
        return start, end

    def bind_sites(self, sites: list[GameObject]) -> None:
        bridges = [obj for obj in sites if obj.kind == "bridge"]
        used: set[str] = set()
        for crossing in self._items:
            best: GameObject | None = None
            best_d = float(SITE_MATCH_M)
            for obj in bridges:
                if obj.id in used:
                    continue
                d = dist_poly(obj.x, obj.y, crossing.points)
                if d < best_d:
                    best_d = d
                    best = obj
            if best is not None:
                used.add(best.id)
                crossing.id = best.id

    @property
    def items(self) -> list[Crossing]:
        return self._items

    def used_roads(self) -> set[int]:
        return self._used_roads

    def at_point(self, x: float, y: float) -> Crossing | None:
        best: Crossing | None = None
        best_d = ON_BRIDGE_M
        for crossing in self._items:
            d = dist_poly(x, y, crossing.points)
            if d < best_d:
                best_d = d
                best = crossing
        return best

    def by_id(self, oid: str) -> Crossing | None:
        for crossing in self._items:
            if crossing.id == oid:
                return crossing
        return None
