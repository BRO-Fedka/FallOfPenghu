from __future__ import annotations

from math import hypot
from typing import TYPE_CHECKING

from fall_of_penghu.world.entities.command import SetRoute
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind
from fall_of_penghu.world.entities.land.geom import dist_poly, point_in_poly

if TYPE_CHECKING:
    from fall_of_penghu.ai.log import DecisionLog
    from fall_of_penghu.world.world import World

STANDOFF_M = 20_000.0
TAIWAN_CLEAR_M = 20_000.0
AXES = ("west", "north", "south", "east")
AXIS_VECS = {
    "west": (-1.0, 0.0),
    "east": (1.0, 0.0),
    "north": (0.0, 1.0),
    "south": (0.0, -1.0),
}
EDGE_INSET_M = 600.0
CARRIER_MAGAZINE = 30
LANDING_MAGAZINE = 20
LAUNCH_SIM_S = 6.0
LANDING_LAUNCH_S = 12.0
ASSAULT_UNLOAD_SIM = 40.0
SHIP_SPAWN_SIM = 1400.0
MAX_ASSAULT_SHIPS = 2
MAX_LANDING_SHIPS = 3
MAX_FORCE_HULLS = 12


def campaign_day(world: "World") -> int:
    """0 on the opening noon. Clock label D1 is this plus one."""
    return max(0, int(world.clock.calendar_day))


def landing_ship_cap(world: "World") -> int:
    return min(MAX_FORCE_HULLS, 1 + campaign_day(world))


def carrier_cap(world: "World") -> int:
    return min(MAX_FORCE_HULLS, 1 + campaign_day(world))
MAX_SHORE_BOATS = 6
KEEP_SHORE_BOATS = 4
ARRIVE_M = 400.0
LAND_KINDS = ("infantry", "tank", "artillery", "aa_pickup")
MIN_ASSAULT = {"infantry": 4, "artillery": 1, "tank": 1, "aa_pickup": 1}
MIN_HOLD = {"infantry": 1, "artillery": 1, "tank": 0, "aa_pickup": 0}
SLOT_SPACING_M = 7_000.0
LEAVE_ARRIVE_M = 800.0


def map_frame(world: World) -> tuple[float, float, float, float]:
    mn = world.map.manifest.get("frame_min_xy") or [-100000.0, -100000.0]
    mx = world.map.manifest.get("frame_max_xy") or [100000.0, 100000.0]
    return (float(mn[0]), float(mn[1]), float(mx[0]), float(mx[1]))


def penghu_bbox(world: World) -> tuple[float, float, float, float]:
    bbox = world.map.manifest.get("bbox_penghu") or [
        -22000.0,
        -32000.0,
        21000.0,
        35000.0,
    ]
    return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))


def axis_vec(axis: str) -> tuple[float, float]:
    """Unit vector from the islands toward the chosen approach side."""
    return AXIS_VECS.get(axis, AXIS_VECS["west"])


def axis_order(world: World) -> tuple[str, ...]:
    """Approach sides China may use. Taiwan's coastal strip is not one of them."""
    out = [
        axis
        for axis in AXES
        if taiwan_dist_m(world, *_edge_center(world, axis)) >= TAIWAN_CLEAR_M
    ]
    return tuple(out) or ("west",)


def approach_axis(world: World, wave: int) -> str:
    """One side per wave, rotated so consecutive landings come from elsewhere."""
    order = axis_order(world)
    seed = int(getattr(world, "seed", 0) or 0)
    return order[(wave * 2 + seed) % len(order)]


def standoff_xy(world: World, axis: str = "west") -> tuple[float, float]:
    minx, miny, maxx, maxy = penghu_bbox(world)
    cx = (minx + maxx) * 0.5
    cy = (miny + maxy) * 0.5
    vx, vy = axis_vec(axis)
    x = (minx - STANDOFF_M) if vx < 0 else (maxx + STANDOFF_M) if vx > 0 else cx
    y = (miny - STANDOFF_M) if vy < 0 else (maxy + STANDOFF_M) if vy > 0 else cy
    return _in_frame(world, (x, y))


def standoff_slot(
    world: World, index: int, axis: str = "west"
) -> tuple[float, float]:
    x, y = standoff_xy(world, axis)
    n = (index + 1) // 2
    sign = 1.0 if index % 2 else -1.0
    px, py = _lateral(axis)
    off = sign * n * SLOT_SPACING_M
    return _in_frame(world, (x + px * off, y + py * off))


def taiwan_dist_m(world: World, x: float, y: float) -> float:
    best = 1e30
    for feat in world.map.taiwan:
        if point_in_poly(x, y, feat):
            return 0.0
        d = dist_poly(x, y, feat.exterior)
        if d < best:
            best = d
    return best


def border_xy(world: World, slot: int = 0, axis: str = "west") -> tuple[float, float]:
    """Spawn and reload point on the map border, on the wave's approach side."""
    anchor = _edge_center(world, axis)
    px, py = _lateral(axis)
    n = (abs(slot) + 1) // 2
    sign = 1.0 if slot % 2 else -1.0
    off = sign * n * SLOT_SPACING_M
    pt = _in_frame(world, (anchor[0] + px * off, anchor[1] + py * off))
    planner = world.entities.planner
    if planner is not None:
        water = planner.nearest_water(pt[0], pt[1])
        if water is not None:
            pt = water
    if taiwan_dist_m(world, pt[0], pt[1]) >= TAIWAN_CLEAR_M:
        return pt
    fallback = _edge_center(world, "west")
    if planner is not None:
        water = planner.nearest_water(fallback[0], fallback[1])
        if water is not None:
            return water
    return fallback


def _edge_center(world: World, axis: str) -> tuple[float, float]:
    minx, miny, maxx, maxy = map_frame(world)
    bminx, bminy, bmaxx, bmaxy = penghu_bbox(world)
    cx = (bminx + bmaxx) * 0.5
    cy = (bminy + bmaxy) * 0.5
    vx, vy = axis_vec(axis)
    x = (minx + EDGE_INSET_M) if vx < 0 else (maxx - EDGE_INSET_M) if vx > 0 else cx
    y = (miny + EDGE_INSET_M) if vy < 0 else (maxy - EDGE_INSET_M) if vy > 0 else cy
    return _in_frame(world, (x, y))


def _lateral(axis: str) -> tuple[float, float]:
    vx, vy = axis_vec(axis)
    return (-vy, vx)


def _in_frame(world: World, pt: tuple[float, float]) -> tuple[float, float]:
    minx, miny, maxx, maxy = map_frame(world)
    return (
        min(max(pt[0], minx + EDGE_INSET_M), maxx - EDGE_INSET_M),
        min(max(pt[1], miny + EDGE_INSET_M), maxy - EDGE_INSET_M),
    )


def sail(world: World, ship: DynamicObject, xy: tuple[float, float]) -> None:
    world.entities.dispatch(
        SetRoute(object_id=ship.id, mode="auto", target=xy),
        as_faction=FACTION_CHINA,
    )


def at_xy(obj: DynamicObject, xy: tuple[float, float], rad: float) -> bool:
    if hypot(obj.x - xy[0], obj.y - xy[1]) <= rad:
        obj.route = None
        return True
    return False


def leave_off_map(
    world: World,
    ship: DynamicObject,
    station: tuple[float, float],
    log: DecisionLog | None = None,
    slot: int = 0,
    axis: str = "west",
) -> bool:
    """True while the ship is arriving, leaving, or just despawned."""
    now = world.clock.simulation_time
    task = ship.task or "station"
    if task == "to_station":
        if at_xy(ship, station, ARRIVE_M):
            ship.task = "station"
            ship.route = None
            if log is not None:
                log.emit(now, "arrive", f"{ship.id} station {station[0]:.0f},{station[1]:.0f}")
            return False
        if ship.route is None:
            sail(world, ship, station)
        return True
    if task != "leave":
        return False
    edge = border_xy(world, slot, axis)
    if at_xy(ship, edge, LEAVE_ARRIVE_M):
        if log is not None:
            log.emit(now, "despawn", f"{ship.id} edge {edge[0]:.0f},{edge[1]:.0f}")
        world.entities.discard(ship.id)
        return True
    if ship.route is None:
        sail(world, ship, edge)
        if log is not None:
            log.emit(now, "leave", f"{ship.id} -> edge {edge[0]:.0f},{edge[1]:.0f}")
    return True


def port_islands(world: World) -> list[int]:
    planner = world.entities.planner
    if planner is None:
        return []
    islands = planner.land.islands
    found: set[int] = set()
    for obj in world.entities.items:
        if obj.kind != "port" or not obj.active:
            continue
        iid = islands.at(obj.x, obj.y)
        if iid is None:
            iid = islands.nearest(obj.x, obj.y, 400.0)
        if iid is not None:
            found.add(iid)
    return sorted(found, key=lambda i: _south_key(islands, i))


def china_by_island(world: World) -> dict[int, list[DynamicObject]]:
    planner = world.entities.planner
    out: dict[int, list[DynamicObject]] = {}
    if planner is None:
        return out
    islands = planner.land.islands
    for obj in world.entities.items:
        if not isinstance(obj, DynamicObject) or not obj.active:
            continue
        if obj.faction != FACTION_CHINA or obj.stowed:
            continue
        if obj.mobility != "land" or obj.kind not in LAND_KINDS:
            continue
        iid = islands.at(obj.x, obj.y)
        if iid is None:
            iid = islands.nearest(obj.x, obj.y, 120.0)
        if iid is None:
            continue
        out.setdefault(iid, []).append(obj)
    return out


def empty_port_islands(world: World) -> list[int]:
    held = china_by_island(world)
    return [iid for iid in port_islands(world) if not held.get(iid)]


def china_owned(world: World, island: int) -> bool:
    return world.control.is_china(island)


def capture_islands(world: World) -> list[int]:
    """Inhabited islands first (deny player lookouts), then other ports."""
    planner = world.entities.planner
    if planner is None:
        return []
    islands = planner.land.islands
    held = china_by_island(world)
    owned = world.control.china_islands()
    lookouts = world.perception.lookouts
    inhabited = list(lookouts.inhabited) if lookouts is not None else []
    inhabited.sort(key=lambda i: _south_key(islands, i))
    out: list[int] = []
    for iid in inhabited:
        if iid in owned or held.get(iid):
            continue
        out.append(iid)
    for iid in port_islands(world):
        if iid in out or iid in owned or held.get(iid):
            continue
        out.append(iid)
    return out


def island_has_foe(world: World, island: int) -> bool:
    """Visible player ground on that island. Air overhead does not defend it."""
    planner = world.entities.planner
    if planner is None:
        return False
    islands = planner.land.islands
    for obj in world.perception.visible_objects(FACTION_CHINA):
        if obj.faction == FACTION_CHINA or not obj.active:
            continue
        if is_static_kind(obj.kind) or obj.kind in SHOT_KINDS:
            continue
        if getattr(obj, "stowed", False):
            continue
        if getattr(obj, "mobility", "") != "land":
            continue
        if islands.at(obj.x, obj.y) == island:
            return True
    return False


def island_stand(world: World, island: int) -> tuple[float, float] | None:
    planner = world.entities.planner
    if planner is None:
        return None
    islands = planner.land.islands
    minx, miny, maxx, maxy = islands.bbox(island)
    cx = (minx + maxx) * 0.5
    cy = (miny + maxy) * 0.5
    if islands.at(cx, cy) == island:
        return (cx, cy)
    coast = islands.coast_point(cx, cy, island=island, max_m=80_000.0)
    if coast is None:
        return None
    _, (sx, sy) = coast
    dx = cx - sx
    dy = cy - sy
    n = hypot(dx, dy) or 1.0
    for dist in (220.0, 80.0, 30.0):
        q = (sx + dx / n * dist, sy + dy / n * dist)
        if islands.at(*q) == island:
            return q
    if islands.at(sx, sy) == island:
        return (sx, sy)
    return None


def islands_linked(world: World, src: int, dst: int) -> bool:
    planner = world.entities.planner
    if planner is None:
        return src == dst
    return planner.land.connected(src, dst, world.entities.bridge_intact)


def is_surplus(
    unit: DynamicObject,
    island: int,
    assault: int | None,
    by_island: dict[int, list[DynamicObject]],
    world: "World | None" = None,
) -> bool:
    owned = world is not None and china_owned(world, island)
    if owned:
        mins = MIN_HOLD
    elif assault is not None and island == assault:
        mins = MIN_ASSAULT
    else:
        mins = MIN_HOLD
    need = mins.get(unit.kind, 1)
    n = sum(1 for obj in by_island.get(island, ()) if obj.kind == unit.kind)
    return n > need


def _south_key(islands, island: int) -> tuple[float, float]:
    minx, miny, maxx, maxy = islands.bbox(island)
    return ((miny + maxy) * 0.5, (minx + maxx) * 0.5)
