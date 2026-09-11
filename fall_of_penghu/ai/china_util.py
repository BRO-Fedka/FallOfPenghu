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
TAIWAN_CLEAR_M = 30_000.0
EDGE_INSET_M = 600.0
CARRIER_MAGAZINE = 30
LANDING_MAGAZINE = 20
LAUNCH_SIM_S = 6.0
LANDING_LAUNCH_S = 12.0
ASSAULT_UNLOAD_SIM = 40.0
SHIP_SPAWN_SIM = 1400.0
MAX_ASSAULT_SHIPS = 2
MAX_LANDING_SHIPS = 3
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


def standoff_xy(world: World) -> tuple[float, float]:
    bbox = world.map.manifest.get("bbox_penghu") or [-22000.0, -32000.0, 21000.0, 35000.0]
    return (float(bbox[0]) - STANDOFF_M, (float(bbox[1]) + float(bbox[3])) * 0.5)


def standoff_slot(world: World, index: int) -> tuple[float, float]:
    x, y = standoff_xy(world)
    n = (index + 1) // 2
    sign = 1.0 if index % 2 else -1.0
    return (x, y + sign * n * SLOT_SPACING_M)


def taiwan_dist_m(world: World, x: float, y: float) -> float:
    best = 1e30
    for feat in world.map.taiwan:
        if point_in_poly(x, y, feat):
            return 0.0
        d = dist_poly(x, y, feat.exterior)
        if d < best:
            best = d
    return best


def border_xy(world: World, slot: int = 0) -> tuple[float, float]:
    minx, miny, maxx, maxy = map_frame(world)
    x = minx + EDGE_INSET_M
    _, cy = standoff_xy(world)
    n = (abs(slot) + 1) // 2
    sign = 1.0 if slot % 2 else -1.0
    y = cy + sign * n * SLOT_SPACING_M
    y = min(max(y, miny + EDGE_INSET_M), maxy - EDGE_INSET_M)
    planner = world.entities.planner
    if planner is not None:
        water = planner.nearest_water(x, y)
        if water is not None:
            x, y = water
    if taiwan_dist_m(world, x, y) < TAIWAN_CLEAR_M:
        x = minx + EDGE_INSET_M
        if planner is not None:
            water = planner.nearest_water(x, cy)
            if water is not None:
                return water
    return (x, y)


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
    edge = border_xy(world, slot)
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


def capture_islands(world: World) -> list[int]:
    """Inhabited islands first (deny player lookouts), then other ports."""
    planner = world.entities.planner
    if planner is None:
        return []
    islands = planner.land.islands
    held = china_by_island(world)
    lookouts = world.perception.lookouts
    inhabited = list(lookouts.inhabited) if lookouts is not None else []
    inhabited.sort(key=lambda i: _south_key(islands, i))
    out: list[int] = []
    for iid in inhabited:
        if not held.get(iid):
            out.append(iid)
    for iid in port_islands(world):
        if iid not in out and not held.get(iid):
            out.append(iid)
    return out


def island_has_foe(world: World, island: int) -> bool:
    """Any live player unit China can see standing on that island."""
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
) -> bool:
    mins = MIN_ASSAULT if assault is not None and island == assault else MIN_HOLD
    need = mins.get(unit.kind, 1)
    n = sum(1 for obj in by_island.get(island, ()) if obj.kind == unit.kind)
    return n > need


def _south_key(islands, island: int) -> tuple[float, float]:
    minx, miny, maxx, maxy = islands.bbox(island)
    return ((miny + maxy) * 0.5, (minx + maxx) * 0.5)
