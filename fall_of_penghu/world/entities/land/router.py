from __future__ import annotations

from collections import deque
from math import hypot
from typing import Callable

from fall_of_penghu.world.entities.game_object import GameObject
from fall_of_penghu.world.entities.land.crossing import Crossing, CrossingBook
from fall_of_penghu.world.entities.land.geom import extend
from fall_of_penghu.world.entities.land.islands import IslandIndex
from fall_of_penghu.world.entities.land.limits import (
    HOPS_MAX_ITERS,
    SearchLimitError,
    tick,
)
from fall_of_penghu.world.entities.land.raster import IslandRaster
from fall_of_penghu.world.entities.land.roads import IslandRoads, build_island_roads
from fall_of_penghu.world.entities.route import Route
from fall_of_penghu.world.map import MapData

Intact = Callable[[str], bool]
DIRECT_M = 80.0
PORTAL_SNAP_M = 180.0
ROAD_SNAP_M = 350.0
ROAD_ON_M = 18.0
WATER_SAMPLE_M = 20.0
OFFROAD_TIME = 1.45


class LandRouter:
    """Island or inter-island bridge. Asks the live object if a span is intact."""

    def __init__(self, world: MapData) -> None:
        self._islands = IslandIndex(world)
        self._book = CrossingBook(world, self._islands)
        self._roads = build_island_roads(world, self._islands, self._book.used_roads())
        self._rasters: dict[int, IslandRaster] = {}
        self._skip_raster: set[int] = set()

    @property
    def islands(self) -> IslandIndex:
        return self._islands

    def bind_bridges(self, sites: list[GameObject]) -> None:
        self._book.bind_sites(sites)

    def connected(self, src: int, dst: int, intact: Intact) -> bool:
        """True if intact bridges join the two islands (or they are the same)."""
        return self._island_hops(src, dst, intact) is not None

    def nearest_road_point(
        self, x: float, y: float, max_m: float = 800.0
    ) -> tuple[float, float] | None:
        island = self._islands.at(x, y)
        if island is None:
            near = self._islands.nearest(x, y, 80.0)
            if near is None:
                return None
            island = near
        graph = self._roads.get(island)
        if graph is None or not graph.nodes:
            return None
        node = graph.nearest(x, y, max_m=max_m)
        if node is None:
            return None
        return graph.nodes[node]

    def on_road(self, x: float, y: float) -> bool:
        spot = self.locate(x, y)
        if spot is None:
            return False
        if spot[0] == "bridge":
            return True
        graph = self._roads.get(int(spot[1]))
        if graph is None or not graph.nodes:
            return False
        if graph.near_edge(x, y, ROAD_ON_M) is not None:
            return True
        return graph.nearest(x, y, max_m=ROAD_ON_M) is not None

    def locate(self, x: float, y: float) -> tuple[str, int | str] | None:
        crossing = self._book.at_point(x, y)
        if crossing is not None:
            return ("bridge", crossing.id)
        island = self._islands.at(x, y)
        if island is not None:
            return ("island", island)
        return None

    def plan(
        self,
        start: tuple[float, float],
        goal: tuple[float, float],
        intact: Intact,
    ) -> Route | None:
        if hypot(goal[0] - start[0], goal[1] - start[1]) <= 1.0:
            return None
        try:
            return self._plan(start, goal, intact)
        except SearchLimitError as exc:
            print(f"route search limit: {exc}", flush=True)
            return None

    def _plan(
        self,
        start: tuple[float, float],
        goal: tuple[float, float],
        intact: Intact,
    ) -> Route | None:
        here = self.locate(*start)
        if here is None:
            near = self._islands.nearest(*start, 25.0)
            if near is None:
                return None
            here = ("island", near)
        dest = self.locate(*goal)
        if dest is None:
            shore = self._islands.nearest_shore(*goal, 40.0)
            if shore is None:
                return None
            goal_island, goal = shore
        elif dest[0] == "island":
            goal_island = int(dest[1])
        else:
            crossing = self._book.by_id(str(dest[1]))
            if crossing is None or not intact(crossing.id):
                return None
            if here[0] == "bridge" and here[1] == dest[1]:
                toward = self._along_bridge(crossing, start, goal)
                return self._route(toward, [(0.0, _arclen(toward), crossing.id)])
            da = hypot(start[0] - crossing.portal_a[0], start[1] - crossing.portal_a[1])
            db = hypot(start[0] - crossing.portal_b[0], start[1] - crossing.portal_b[1])
            goal_island = crossing.island_a if da <= db else crossing.island_b
            portal = crossing.portal_a if da <= db else crossing.portal_b
            if here[0] == "island":
                body = self._from_island(int(here[1]), start, goal_island, portal, intact)
            else:
                start_cross = self._book.by_id(str(here[1]))
                if start_cross is None:
                    return None
                body = self._from_bridge(start_cross, start, goal_island, portal, intact)
            if body is None:
                return None
            tail = self._along_bridge(crossing, body.points[-1], goal)
            pts = list(body.points)
            s0 = _arclen(pts)
            extend(pts, tail)
            spans = list(body.bridges)
            spans.append((s0, _arclen(pts), crossing.id))
            return self._route(pts, spans)
        if here[0] == "island":
            return self._from_island(int(here[1]), start, goal_island, goal, intact)
        crossing = self._book.by_id(str(here[1]))
        if crossing is None or not intact(crossing.id):
            return None
        return self._from_bridge(crossing, start, goal_island, goal, intact)

    def _from_island(
        self,
        island: int,
        start: tuple[float, float],
        goal_island: int,
        goal: tuple[float, float],
        intact: Intact,
    ) -> Route | None:
        if island == goal_island:
            pts = self._on_island(island, start, goal)
            return self._route(pts, [])
        hops = self._island_hops(island, goal_island, intact)
        if hops is None:
            return None
        pts: list[tuple[float, float]] = []
        spans: list[tuple[float, float, str]] = []
        cur = start
        cur_island = island
        for crossing in hops:
            if not intact(crossing.id):
                return None
            enter, leave, toward = self._portals(crossing, cur_island)
            next_island = (
                crossing.island_b if cur_island == crossing.island_a else crossing.island_a
            )
            enter = self._snap_portal(cur_island, enter) or enter
            leave = self._snap_portal(next_island, leave) or leave
            hop = self._on_island(cur_island, cur, enter)
            if hop is None:
                return None
            extend(pts, hop)
            s0 = _arclen(pts)
            extend(pts, toward)
            if hypot(pts[-1][0] - leave[0], pts[-1][1] - leave[1]) > 1.0:
                extend(pts, [leave])
            s1 = _arclen(pts)
            spans.append((s0, s1, crossing.id))
            cur = leave
            cur_island = next_island
        hop = self._on_island(cur_island, cur, goal)
        if hop is None:
            return None
        extend(pts, hop)
        return self._route(pts, spans)

    def _from_bridge(
        self,
        crossing: Crossing,
        start: tuple[float, float],
        goal_island: int,
        goal: tuple[float, float],
        intact: Intact,
    ) -> Route | None:
        if not intact(crossing.id):
            return None
        via_a = self._island_hops(crossing.island_a, goal_island, intact)
        via_b = self._island_hops(crossing.island_b, goal_island, intact)
        pick_a = via_a is not None and (via_b is None or len(via_a) <= len(via_b))
        if via_a is None and via_b is None:
            return None
        end_island = crossing.island_a if pick_a else crossing.island_b
        leave = crossing.portal_a if pick_a else crossing.portal_b
        leave = self._snap_portal(end_island, leave) or leave
        toward = self._along_bridge(crossing, start, leave)
        pts: list[tuple[float, float]] = []
        extend(pts, toward)
        s1 = _arclen(pts)
        spans = [(0.0, s1, crossing.id)]
        rest = self._from_island(end_island, leave, goal_island, goal, intact)
        if rest is None:
            return self._route(pts, spans)
        extend(pts, rest.points)
        shifted = [
            (a + s1, b + s1, oid) for a, b, oid in rest.bridges if b > a
        ]
        return self._route(pts, spans + shifted)

    def _snap_portal(
        self, island: int, portal: tuple[float, float]
    ) -> tuple[float, float] | None:
        graph = self._roads.get(island)
        if graph is not None and graph.nodes:
            i = graph.nearest(*portal, max_m=PORTAL_SNAP_M)
            if i is not None:
                return graph.nodes[i]
        hit = self._islands.nearest(portal[0], portal[1], PORTAL_SNAP_M)
        if hit == island:
            feat = self._islands.feature(island)
            return min(
                feat.exterior[:: max(1, len(feat.exterior) // 40)],
                key=lambda p: (p[0] - portal[0]) ** 2 + (p[1] - portal[1]) ** 2,
            )
        return None

    def _portals(
        self, crossing: Crossing, from_island: int
    ) -> tuple[tuple[float, float], tuple[float, float], list[tuple[float, float]]]:
        if from_island == crossing.island_a:
            return crossing.portal_a, crossing.portal_b, list(crossing.points)
        return crossing.portal_b, crossing.portal_a, list(reversed(crossing.points))

    def _along_bridge(
        self,
        crossing: Crossing,
        start: tuple[float, float],
        leave: tuple[float, float],
    ) -> list[tuple[float, float]]:
        pts = list(crossing.points)
        da = hypot(leave[0] - crossing.portal_a[0], leave[1] - crossing.portal_a[1])
        db = hypot(leave[0] - crossing.portal_b[0], leave[1] - crossing.portal_b[1])
        if da < db:
            pts = list(reversed(pts))
        best_i = 0
        best_d = 1e30
        for i, pt in enumerate(pts):
            d = hypot(start[0] - pt[0], start[1] - pt[1])
            if d < best_d:
                best_d = d
                best_i = i
        rest = pts[best_i:]
        if not rest:
            return [start, leave]
        if start != rest[0]:
            return [start, *rest]
        return rest

    def _island_hops(
        self, src: int, dst: int, intact: Intact
    ) -> list[Crossing] | None:
        if src == dst:
            return []
        adj: dict[int, list[Crossing]] = {}
        for crossing in self._book.items:
            if not intact(crossing.id):
                continue
            adj.setdefault(crossing.island_a, []).append(crossing)
            adj.setdefault(crossing.island_b, []).append(crossing)
        prev: dict[int, tuple[int, Crossing]] = {}
        q = deque([src])
        seen = {src}
        steps = 0
        while q:
            steps = tick("island_hops", steps, HOPS_MAX_ITERS)
            u = q.popleft()
            if u == dst:
                hops: list[Crossing] = []
                cur = dst
                while cur != src:
                    prv, crossing = prev[cur]
                    hops.append(crossing)
                    cur = prv
                hops.reverse()
                return hops
            for crossing in adj.get(u, ()):
                v = crossing.island_b if crossing.island_a == u else crossing.island_a
                if v in seen:
                    continue
                seen.add(v)
                prev[v] = (u, crossing)
                q.append(v)
        return None

    def _on_island(
        self,
        island: int,
        start: tuple[float, float],
        goal: tuple[float, float],
    ) -> list[tuple[float, float]] | None:
        """Road or field, whichever is quicker.

        Roads are faster per metre, so the router used to take any road it could
        reach: a hundred metre move across a field turned into a kilometre loop.
        Both routes are built and compared in travel time.
        """
        if hypot(goal[0] - start[0], goal[1] - start[1]) <= DIRECT_M:
            short = self._safe_direct(island, start, goal)
            if short is not None:
                return short
        field = self._offroad(island, start, goal)
        graph = self._roads.get(island)
        if graph is None or not graph.nodes:
            return field
        sa = graph.nearest(*start, max_m=ROAD_SNAP_M)
        sb = graph.nearest(*goal, max_m=ROAD_SNAP_M)
        if sa is None or sb is None:
            return field
        via = self._via_roads(island, start, goal, graph, sa, sb)
        if via is None:
            return field
        if field is None:
            return via
        if _arclen(field) * OFFROAD_TIME < _arclen(via):
            return field
        return via

    def _via_roads(
        self,
        island: int,
        start: tuple[float, float],
        goal: tuple[float, float],
        graph: IslandRoads,
        sa: int,
        sb: int,
    ) -> list[tuple[float, float]] | None:
        pts: list[tuple[float, float]] = []
        head = self._to_node(island, start, graph, sa)
        if head is None:
            return None
        extend(pts, head)
        if sa != sb:
            nodes = graph.astar(sa, sb)
            if nodes is None:
                return None
            extend(pts, graph.points_of(nodes))
        tail = self._link(island, pts[-1], goal)
        if tail is None:
            return None
        extend(pts, tail)
        return pts if len(pts) >= 2 else None

    def _to_node(
        self,
        island: int,
        start: tuple[float, float],
        graph: IslandRoads,
        node: int,
    ) -> list[tuple[float, float]] | None:
        return self._link(island, start, graph.nodes[node])

    def _safe_direct(
        self,
        island: int,
        a: tuple[float, float],
        b: tuple[float, float],
    ) -> list[tuple[float, float]] | None:
        """Straight hop, but only if the whole line stays ashore.

        Checking the two ends alone let short links cut across bays and inlets.
        """
        if self._islands.at(*a) != island or self._islands.at(*b) != island:
            return None
        if self._crosses_water(island, a, b):
            return None
        return [a, b]

    def _crosses_water(
        self, island: int, a: tuple[float, float], b: tuple[float, float]
    ) -> bool:
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        length = hypot(dx, dy)
        steps = max(2, int(length / WATER_SAMPLE_M))
        for i in range(1, steps):
            t = i / steps
            x = a[0] + dx * t
            y = a[1] + dy * t
            if self._islands.at(x, y) is None:
                return True
        return False

    def _link(
        self,
        island: int,
        a: tuple[float, float],
        b: tuple[float, float],
    ) -> list[tuple[float, float]] | None:
        if a == b:
            return [a]
        if hypot(b[0] - a[0], b[1] - a[1]) <= DIRECT_M * 4:
            short = self._safe_direct(island, a, b)
            if short is not None:
                return short
        return self._offroad(island, a, b)

    def _offroad(
        self, island: int, a: tuple[float, float], b: tuple[float, float]
    ) -> list[tuple[float, float]] | None:
        if self._islands.at(*a) != island or self._islands.at(*b) != island:
            return None
        rast = self._raster(island)
        if rast is None:
            return None
        return rast.path(a, b)

    def _raster(self, island: int) -> IslandRaster | None:
        if island in self._skip_raster:
            return None
        got = self._rasters.get(island)
        if got is not None:
            return got
        try:
            rast = IslandRaster(self._islands.features(island))
        except SearchLimitError:
            self._skip_raster.add(island)
            raise
        self._rasters[island] = rast
        return rast

    @staticmethod
    def _route(
        pts: list[tuple[float, float]] | None,
        spans: list[tuple[float, float, str]],
    ) -> Route | None:
        if pts is None or len(pts) < 2:
            return None
        return Route(pts, bridges=spans)


def _arclen(pts: list[tuple[float, float]]) -> float:
    s = 0.0
    for a, b in zip(pts, pts[1:]):
        s += hypot(b[0] - a[0], b[1] - a[1])
    return s
