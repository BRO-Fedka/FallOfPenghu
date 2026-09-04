from __future__ import annotations

from heapq import heappop, heappush
from math import hypot

from fall_of_penghu.world.entities.command import SetRoute
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.route import Route
from fall_of_penghu.world.map import MapData, PolyFeature

LAND_SNAP_M = 12.0
LAND_SAMPLE_M = 40.0
LAND_OFFROAD_COST = 1.55
SEA_CELL_M = 150.0
SEA_SAMPLE_M = 80.0
SEA_PAD_M = 2_000.0


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


def _point_in_poly(x: float, y: float, feat: PolyFeature) -> bool:
    minx, miny, maxx, maxy = feat.bbox
    if x < minx or x > maxx or y < miny or y > maxy:
        return False
    if not _point_in_ring(x, y, feat.exterior):
        return False
    for hole in feat.holes:
        if _point_in_ring(x, y, hole):
            return False
    return True


class Planner:
    """Build a Route polyline. Does not move units."""

    def __init__(self, world: MapData) -> None:
        self._map = world
        self._land_nodes: list[tuple[float, float]] = []
        self._land_adj: list[list[tuple[int, float]]] = []
        self._land_grid: dict[tuple[int, int], list[int]] = {}
        self._sea_origin = (0.0, 0.0)
        self._sea_w = 0
        self._sea_h = 0
        self._sea_block: list[bool] = []
        self._land_walk: list[bool] = []
        self._road_cells: set[int] = set()
        self._build_land()
        self._build_sea()
        self._build_land_walk()

    def plan(self, unit: DynamicObject, cmd: SetRoute) -> Route | None:
        start = (unit.x, unit.y)
        if cmd.mode == "manual" and cmd.vertices:
            return self._constrain(unit.mobility, start, list(cmd.vertices))
        if cmd.target is None:
            return None
        return self._auto(unit.mobility, start, cmd.target)

    def _auto(
        self, mobility: str, start: tuple[float, float], goal: tuple[float, float]
    ) -> Route | None:
        if mobility == "air":
            return self._air([start, goal])
        if mobility == "land":
            return self._land_path(start, goal)
        if mobility == "sea":
            return self._sea_path(start, goal)
        return None

    def _constrain(
        self,
        mobility: str,
        start: tuple[float, float],
        vertices: list[tuple[float, float]],
    ) -> Route | None:
        if not vertices:
            return None
        if mobility == "air":
            pts = [start, *vertices] if vertices[0] != start else list(vertices)
            return self._air(pts)
        chain = [start, *vertices]
        parts: list[tuple[float, float]] = []
        for a, b in zip(chain, chain[1:]):
            hop = self._auto(mobility, a, b)
            if hop is None:
                return None
            if parts and hop.points[0] == parts[-1]:
                parts.extend(hop.points[1:])
            else:
                parts.extend(hop.points)
        if len(parts) < 2:
            return None
        return Route(parts)

    def _air(self, points: list[tuple[float, float]]) -> Route | None:
        cleaned = [points[0]]
        for pt in points[1:]:
            if pt != cleaned[-1]:
                cleaned.append(pt)
        if len(cleaned) < 2:
            return None
        return Route(cleaned)

    def is_land(self, x: float, y: float) -> bool:
        world = self._map
        if world.coast_grid is not None:
            for i in world.coast_grid.query(x, y, x, y):
                if _point_in_poly(x, y, world.coast[i]):
                    return True
        for feat in world.taiwan:
            if _point_in_poly(x, y, feat):
                return True
        return False

    def _build_land(self) -> None:
        raw: list[tuple[float, float]] = []
        edges: list[tuple[int, int]] = []
        for road in self._map.roads:
            if len(road.points) < 2:
                continue
            first = len(raw)
            raw.extend(road.points)
            for i in range(first, len(raw) - 1):
                edges.append((i, i + 1))
        if not raw:
            return
        parent = list(range(len(raw)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        cell = LAND_SNAP_M
        buckets: dict[tuple[int, int], list[int]] = {}
        for i, (x, y) in enumerate(raw):
            buckets.setdefault((int(x // cell), int(y // cell)), []).append(i)
        thresh2 = LAND_SNAP_M * LAND_SNAP_M
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
        nodes: list[tuple[float, float]] = []
        acc: dict[int, list[tuple[float, float]]] = {}
        for i, pt in enumerate(raw):
            root = find(i)
            acc.setdefault(root, []).append(pt)
        roots = sorted(acc)
        for n, root in enumerate(roots):
            pts = acc[root]
            nodes.append(
                (
                    sum(p[0] for p in pts) / len(pts),
                    sum(p[1] for p in pts) / len(pts),
                )
            )
            remap[root] = n
        for i in range(len(raw)):
            remap[i] = remap[find(i)]

        adj: list[list[tuple[int, float]]] = [[] for _ in nodes]
        seen: set[tuple[int, int]] = set()
        for a, b in edges:
            ia, ib = remap[a], remap[b]
            if ia == ib:
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
            grid.setdefault((int(x // 400.0), int(y // 400.0)), []).append(i)

        self._land_nodes = nodes
        self._land_adj = adj
        self._land_grid = grid

    def _nearest_land(self, x: float, y: float) -> int | None:
        if not self._land_nodes:
            return None
        gx, gy = int(x // 400.0), int(y // 400.0)
        best_i = None
        best_d = 1e30
        for rad in range(0, 40):
            for ox in range(gx - rad, gx + rad + 1):
                for oy in range(gy - rad, gy + rad + 1):
                    if rad and abs(ox - gx) != rad and abs(oy - gy) != rad:
                        continue
                    for i in self._land_grid.get((ox, oy), ()):
                        nx, ny = self._land_nodes[i]
                        d = (nx - x) * (nx - x) + (ny - y) * (ny - y)
                        if d < best_d:
                            best_d = d
                            best_i = i
            if best_i is not None and rad >= 1:
                return best_i
        if best_i is not None:
            return best_i
        for i, (nx, ny) in enumerate(self._land_nodes):
            d = (nx - x) * (nx - x) + (ny - y) * (ny - y)
            if d < best_d:
                best_d = d
                best_i = i
        return best_i

    def _cell_index(self, x: float, y: float) -> int | None:
        gx = int((x - self._sea_origin[0]) / SEA_CELL_M)
        gy = int((y - self._sea_origin[1]) / SEA_CELL_M)
        if gx < 0 or gy < 0 or gx >= self._sea_w or gy >= self._sea_h:
            return None
        return gy * self._sea_w + gx

    def _land_ok(self, x: float, y: float) -> bool:
        if self.is_land(x, y):
            return True
        i = self._cell_index(x, y)
        return i is not None and bool(self._land_walk) and self._land_walk[i]

    def _seg_leaves_land(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        length = hypot(dx, dy)
        steps = max(2, int(length / LAND_SAMPLE_M))
        for i in range(steps + 1):
            t = i / steps
            if not self._land_ok(a[0] + dx * t, a[1] + dy * t):
                return True
        return False

    def _build_land_walk(self) -> None:
        self._land_walk = list(self._sea_block)
        self._road_cells = set()
        step = SEA_CELL_M * 0.5
        for road in self._map.roads:
            pts = road.points
            if len(pts) < 2:
                continue
            for a, b in zip(pts, pts[1:]):
                dx = b[0] - a[0]
                dy = b[1] - a[1]
                length = hypot(dx, dy)
                n = max(1, int(length / step))
                for k in range(n + 1):
                    t = k / n
                    i = self._cell_index(a[0] + dx * t, a[1] + dy * t)
                    if i is None:
                        continue
                    self._land_walk[i] = True
                    self._road_cells.add(i)

    def _nearest_walk_cell(self, x: float, y: float) -> int | None:
        if not self._land_ok(x, y):
            return None
        gx = int((x - self._sea_origin[0]) / SEA_CELL_M)
        gy = int((y - self._sea_origin[1]) / SEA_CELL_M)
        w, h = self._sea_w, self._sea_h
        walk = self._land_walk
        best_i: int | None = None
        best_d = 1e30
        for rad in range(0, 48):
            for dx in range(-rad, rad + 1):
                for dy in range(-rad, rad + 1):
                    if rad and abs(dx) != rad and abs(dy) != rad:
                        continue
                    vx, vy = gx + dx, gy + dy
                    if vx < 0 or vy < 0 or vx >= w or vy >= h:
                        continue
                    i = vy * w + vx
                    if not walk[i]:
                        continue
                    cx, cy = self._sea_xy(i)
                    d = (cx - x) * (cx - x) + (cy - y) * (cy - y)
                    if d < best_d:
                        best_d = d
                        best_i = i
            if best_i is not None:
                return best_i
        return None

    def _land_path(
        self, start: tuple[float, float], goal: tuple[float, float]
    ) -> Route | None:
        if not self._land_ok(*start) or not self._land_ok(*goal):
            return None
        if hypot(goal[0] - start[0], goal[1] - start[1]) <= 1.0:
            return None
        if not self._seg_leaves_land(start, goal):
            return Route([start, goal])
        sa = self._nearest_walk_cell(*start)
        sb = self._nearest_walk_cell(*goal)
        if sa is None or sb is None:
            return None
        if sa == sb:
            mid = self._sea_xy(sa)
            pts = [start]
            if mid != pts[-1]:
                pts.append(mid)
            if goal != pts[-1]:
                pts.append(goal)
            return Route(pts) if len(pts) >= 2 else None
        came = self._astar_land(sa, sb)
        if came is None:
            return None
        pts = [start]
        for i in came:
            pt = self._sea_xy(i)
            if pt != pts[-1]:
                pts.append(pt)
        if goal != pts[-1]:
            pts.append(goal)
        return Route(pts) if len(pts) >= 2 else None

    def _build_sea(self) -> None:
        bbox = self._map.manifest.get("bbox_penghu") or [-22000, -32000, 21000, 35000]
        minx = float(bbox[0]) - SEA_PAD_M
        miny = float(bbox[1]) - SEA_PAD_M
        maxx = float(bbox[2]) + SEA_PAD_M
        maxy = float(bbox[3]) + SEA_PAD_M
        cell = SEA_CELL_M
        w = max(2, int((maxx - minx) / cell) + 1)
        h = max(2, int((maxy - miny) / cell) + 1)
        block = [False] * (w * h)
        lands = list(self._map.coast) + list(self._map.taiwan)
        for feat in lands:
            gx0 = max(0, int((feat.bbox[0] - minx) / cell) - 1)
            gy0 = max(0, int((feat.bbox[1] - miny) / cell) - 1)
            gx1 = min(w - 1, int((feat.bbox[2] - minx) / cell) + 1)
            gy1 = min(h - 1, int((feat.bbox[3] - miny) / cell) + 1)
            for gy in range(gy0, gy1 + 1):
                y = miny + (gy + 0.5) * cell
                row = gy * w
                for gx in range(gx0, gx1 + 1):
                    x = minx + (gx + 0.5) * cell
                    if _point_in_poly(x, y, feat):
                        block[row + gx] = True
        self._sea_origin = (minx, miny)
        self._sea_w = w
        self._sea_h = h
        self._sea_block = block

    def _sea_index(self, x: float, y: float) -> int | None:
        gx = int((x - self._sea_origin[0]) / SEA_CELL_M)
        gy = int((y - self._sea_origin[1]) / SEA_CELL_M)
        if gx < 0 or gy < 0 or gx >= self._sea_w or gy >= self._sea_h:
            return None
        i = gy * self._sea_w + gx
        if self._sea_block[i]:
            return None
        return i

    def _sea_xy(self, i: int) -> tuple[float, float]:
        gx = i % self._sea_w
        gy = i // self._sea_w
        ox, oy = self._sea_origin
        return ox + (gx + 0.5) * SEA_CELL_M, oy + (gy + 0.5) * SEA_CELL_M

    def _seg_hits_land(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        length = hypot(dx, dy)
        steps = max(2, int(length / SEA_SAMPLE_M))
        for i in range(steps + 1):
            t = i / steps
            if self.is_land(a[0] + dx * t, a[1] + dy * t):
                return True
        return False

    def _nearest_sea_index(self, x: float, y: float) -> int | None:
        if self.is_land(x, y):
            return None
        gx = int((x - self._sea_origin[0]) / SEA_CELL_M)
        gy = int((y - self._sea_origin[1]) / SEA_CELL_M)
        w, h = self._sea_w, self._sea_h
        block = self._sea_block
        best_i: int | None = None
        best_d = 1e30
        for rad in range(0, 48):
            for dx in range(-rad, rad + 1):
                for dy in range(-rad, rad + 1):
                    if rad and abs(dx) != rad and abs(dy) != rad:
                        continue
                    vx, vy = gx + dx, gy + dy
                    if vx < 0 or vy < 0 or vx >= w or vy >= h:
                        continue
                    i = vy * w + vx
                    if block[i]:
                        continue
                    cx, cy = self._sea_xy(i)
                    d = (cx - x) * (cx - x) + (cy - y) * (cy - y)
                    if d < best_d:
                        best_d = d
                        best_i = i
            if best_i is not None:
                return best_i
        return None

    def _sea_path(
        self, start: tuple[float, float], goal: tuple[float, float]
    ) -> Route | None:
        if self.is_land(*start) or self.is_land(*goal):
            return None
        if not self._seg_hits_land(start, goal):
            return Route([start, goal])
        sa = self._nearest_sea_index(*start)
        sb = self._nearest_sea_index(*goal)
        if sa is None or sb is None:
            return None
        came = self._astar_sea(sa, sb)
        if came is None:
            return None
        pts = [start]
        for i in came:
            pt = self._sea_xy(i)
            if pt != pts[-1]:
                pts.append(pt)
        if goal != pts[-1]:
            pts.append(goal)
        return Route(pts) if len(pts) >= 2 else None

    def _astar_nodes(
        self,
        start: int,
        goal: int,
        nodes: list[tuple[float, float]],
        adj: list[list[tuple[int, float]]],
    ) -> list[int] | None:
        gx, gy = nodes[goal]
        heap: list[tuple[float, int]] = [(0.0, start)]
        cost = {start: 0.0}
        prev: dict[int, int] = {}
        while heap:
            _, u = heappop(heap)
            if u == goal:
                path = [u]
                while u in prev:
                    u = prev[u]
                    path.append(u)
                path.reverse()
                return path
            for v, w in adj[u]:
                nxt = cost[u] + w
                if nxt < cost.get(v, 1e30):
                    cost[v] = nxt
                    prev[v] = u
                    hx, hy = nodes[v]
                    heappush(heap, (nxt + hypot(hx - gx, hy - gy), v))
        return None

    def _astar_sea(self, start: int, goal: int) -> list[int] | None:
        w, h = self._sea_w, self._sea_h
        gx, gy = goal % w, goal // w
        heap: list[tuple[float, int]] = [(0.0, start)]
        cost = {start: 0.0}
        prev: dict[int, int] = {}
        block = self._sea_block
        while heap:
            _, u = heappop(heap)
            if u == goal:
                path = [u]
                while u in prev:
                    u = prev[u]
                    path.append(u)
                path.reverse()
                return path
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
                if block[v]:
                    continue
                nxt = cost[u] + step
                if nxt < cost.get(v, 1e30):
                    cost[v] = nxt
                    prev[v] = u
                    heappush(heap, (nxt + hypot(vx - gx, vy - gy), v))
        return None

    def _astar_land(self, start: int, goal: int) -> list[int] | None:
        w, h = self._sea_w, self._sea_h
        gx, gy = goal % w, goal // w
        heap: list[tuple[float, int]] = [(0.0, start)]
        cost = {start: 0.0}
        prev: dict[int, int] = {}
        walk = self._land_walk
        roads = self._road_cells
        while heap:
            _, u = heappop(heap)
            if u == goal:
                path = [u]
                while u in prev:
                    u = prev[u]
                    path.append(u)
                path.reverse()
                return path
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
                if not walk[v]:
                    continue
                terrain = 1.0 if v in roads else LAND_OFFROAD_COST
                nxt = cost[u] + step * terrain
                if nxt < cost.get(v, 1e30):
                    cost[v] = nxt
                    prev[v] = u
                    heappush(heap, (nxt + hypot(vx - gx, vy - gy) * terrain, v))
        return None
