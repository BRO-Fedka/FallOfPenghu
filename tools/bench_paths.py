"""Time route planning: world build, long sea legs, land legs, worst cases."""

from __future__ import annotations

import sys
import time
from math import cos, sin
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fall_of_penghu.world.entities.command import SetRoute
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA
from fall_of_penghu.world.world import World

SEA_LEGS = (
    ((-7454.0, 99400.0), (-500.0, 40000.0), "north edge -> north stand"),
    ((-7454.0, -99400.0), (-500.0, -40000.0), "south edge -> south stand"),
    ((-99325.0, 1353.0), (-42000.0, 1500.0), "west edge -> west stand"),
    ((-99325.0, 1353.0), (41000.0, 1500.0), "west edge -> east of islands"),
    ((-7454.0, 99400.0), (-7000.0, -99000.0), "north edge -> south edge"),
)


def probe(world: World, mobility: str, a, b, label: str) -> None:
    unit = DynamicObject(
        id=f"bench_{mobility}",
        faction=FACTION_CHINA,
        kind="ship" if mobility == "sea" else "infantry",
        name="bench",
        x=a[0],
        y=a[1],
        heading=0.0,
        speed_mps=10.0,
        mobility=mobility,
    )
    planner = world.entities.planner
    t0 = time.perf_counter()
    route = planner.plan(unit, SetRoute(object_id=unit.id, mode="auto", target=b))
    dt = (time.perf_counter() - t0) * 1000.0
    if route is None:
        print(f"  {label:34s} {dt:8.1f} ms  NO ROUTE")
        return
    print(
        f"  {label:34s} {dt:8.1f} ms  pts={len(route.points):4d} "
        f"len={route.length:9.0f}"
    )


def _land_pairs(world: World, rng: Random, dist: float, n: int):
    planner = world.entities.planner
    islands = planner.land.islands
    minx, miny, maxx, maxy = -22_000.0, -32_000.0, 21_000.0, 35_000.0
    pairs = []
    guard = 0
    while len(pairs) < n and guard < n * 400:
        guard += 1
        a = (rng.uniform(minx, maxx), rng.uniform(miny, maxy))
        iid = islands.at(*a)
        if iid is None:
            continue
        ang = rng.uniform(0.0, 6.2832)
        b = (a[0] + cos(ang) * dist, a[1] + sin(ang) * dist)
        if islands.at(*b) != iid:
            continue
        pairs.append((a, b))
    return pairs


def _sea_pairs(world: World, rng: Random, n: int):
    planner = world.entities.planner
    pairs = []
    guard = 0
    while len(pairs) < n and guard < n * 400:
        guard += 1
        a = (rng.uniform(-99_000.0, 25_000.0), rng.uniform(-60_000.0, 60_000.0))
        b = (rng.uniform(-99_000.0, 25_000.0), rng.uniform(-60_000.0, 60_000.0))
        if planner.is_land(*a) or planner.is_land(*b):
            continue
        pairs.append((a, b))
    return pairs


def _land_near(islands, iid: int, origin, dist: float):
    from math import cos, sin

    for i in range(24):
        ang = i * 3.14159 / 12.0
        pt = (origin[0] + cos(ang) * dist, origin[1] + sin(ang) * dist)
        if islands.at(*pt) == iid:
            return pt
    return None


def _area(bbox: tuple[float, float, float, float]) -> float:
    return (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])


def bad_points(world: World, route, mobility: str, step: float = 10.0) -> int:
    """Sampled points on the wrong element: land route over water or vice versa."""
    planner = world.entities.planner
    bad = 0
    pts = route.points
    for a, b in zip(pts, pts[1:]):
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        n = max(1, int(((dx * dx + dy * dy) ** 0.5) / step))
        for k in range(n + 1):
            t = k / n
            x = a[0] + dx * t
            y = a[1] + dy * t
            on_land = planner.is_land(x, y)
            if mobility == "sea" and on_land:
                bad += 1
            elif mobility == "land" and not on_land:
                bad += 1
    return bad


def audit(world: World, mobility: str, pairs, label: str) -> None:
    planner = world.entities.planner
    times: list[float] = []
    fails = 0
    illegal = 0
    worst = 0
    spans = 0
    detour = 0.0
    for a, b in pairs:
        unit = DynamicObject(
            id="audit",
            faction=FACTION_CHINA,
            kind="ship" if mobility == "sea" else "infantry",
            name="audit",
            x=a[0],
            y=a[1],
            heading=0.0,
            speed_mps=10.0,
            mobility=mobility,
        )
        t0 = time.perf_counter()
        route = planner.plan(unit, SetRoute(object_id="audit", mode="auto", target=b))
        times.append((time.perf_counter() - t0) * 1000.0)
        if route is None:
            fails += 1
            continue
        bad = bad_points(world, route, mobility)
        if bad:
            illegal += 1
            worst = max(worst, bad)
            if getattr(route, "bridges", None):
                spans += 1
            else:
                print(f"    wet route {a} -> {b} pts={len(route.points)} bad={bad}")
        direct = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 or 1.0
        detour = max(detour, route.length / direct)
    times.sort()
    hi = times[-1] if times else 0.0
    mid = times[len(times) // 2] if times else 0.0
    print(
        f"  {label:22s} n={len(pairs):3d} no_route={fails:3d} "
        f"illegal={illegal:3d} bridged={spans:3d} worst_pts={worst:3d} "
        f"max_detour={detour:5.2f}x  median={mid:6.1f} ms  max={hi:8.1f} ms"
    )


def road_speed(world: World, islands, iid: int, mid) -> None:
    """How much of a road route actually counts as 'on road' for speed."""
    planner = world.entities.planner
    land = planner.land
    graph = land._roads.get(iid)
    if graph is None or not graph.nodes:
        print("  no road graph on that island")
        return
    far = max(graph.nodes, key=lambda p: (p[0] - mid[0]) ** 2 + (p[1] - mid[1]) ** 2)
    near = land.nearest_road_point(mid[0], mid[1], 8_000.0)
    if near is None:
        print("  no road near island centre")
        return
    unit = DynamicObject(
        id="road",
        faction=FACTION_CHINA,
        kind="truck",
        name="road",
        x=near[0],
        y=near[1],
        heading=0.0,
        speed_mps=20.0,
        mobility="land",
    )
    route = planner.plan(unit, SetRoute(object_id="road", mode="auto", target=far))
    if route is None:
        print("  no road route")
        return
    pts = route.points
    on = 0
    nodes = 0
    total = 0
    forest = 0
    cover = world.entities._cover
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = max(1, int((dx * dx + dy * dy) ** 0.5 / 25.0))
        for k in range(n + 1):
            t = k / n
            x, y = a[0] + dx * t, a[1] + dy * t
            total += 1
            if land.on_road(x, y):
                on += 1
            g = land._roads.get(islands.at(x, y) or -1)
            if g is not None and g.nearest(x, y, max_m=18.0) is not None:
                nodes += 1
            if cover is not None and cover.at(x, y, "ground") == "forest":
                forest += 1
    mgr = world.entities
    unit.x, unit.y = pts[len(pts) // 2]
    speed = mgr._move_speed(unit)
    print(
        f"  road route len={route.length:7.0f} on_road {on}/{total} "
        f"(by node {nodes}/{total})  mid speed {speed:.1f}/{unit.speed_mps:.1f}  "
        f"forest cover {forest}/{total}"
    )


def main() -> None:
    t0 = time.perf_counter()
    world = World.load(ROOT / "penghu_map_v1")
    print(f"world load {(time.perf_counter() - t0):.2f} s")
    print("sea legs")
    for a, b, label in SEA_LEGS:
        probe(world, "sea", a, b, label)
    print("land legs")
    planner = world.entities.planner
    islands = planner.land.islands
    ids = sorted(islands.ids())
    iid = max(ids, key=lambda i: _area(islands.bbox(i)))
    minx, miny, maxx, maxy = islands.bbox(iid)
    mid = ((minx + maxx) / 2.0, (miny + maxy) / 2.0)
    if islands.at(*mid) != iid:
        shore = islands.nearest_shore(mid[0], mid[1], 20_000.0)
        if shore is not None:
            mid = shore[1]
    print(f"  island {iid} at {mid[0]:.0f},{mid[1]:.0f}")
    for dist in (100.0, 600.0, 3000.0):
        target = _land_near(islands, iid, mid, dist)
        if target is None:
            print(f"  {dist:.0f} m hop: no land target")
            continue
        probe(world, "land", mid, target, f"{dist:.0f} m hop")
    print("road speed")
    road_speed(world, islands, iid, mid)
    print("audit")
    rng = Random(7)
    for dist, label in ((150.0, "land 150 m"), (800.0, "land 800 m"), (4000.0, "land 4 km")):
        pairs = _land_pairs(world, rng, dist, 40)
        audit(world, "land", pairs, label)
    sea = _sea_pairs(world, rng, 40)
    audit(world, "sea", sea, "sea cold")
    audit(world, "sea", sea, "sea warm")
    planner = world.entities.planner
    print(
        f"  coast cells {len(planner._sea_coast)}  "
        f"sea leaves {len(planner.sea.nodes)}"
    )


if __name__ == "__main__":
    main()
