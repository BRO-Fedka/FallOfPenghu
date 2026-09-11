from __future__ import annotations

from math import hypot
from typing import TYPE_CHECKING

from fall_of_penghu.ai.china_util import (
    china_by_island,
    capture_islands,
    island_stand,
    islands_linked,
    is_surplus,
)
from fall_of_penghu.world.entities.command import SetRoute
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind

if TYPE_CHECKING:
    from fall_of_penghu.ai.intel import IntelOps
    from fall_of_penghu.ai.log import DecisionLog
    from fall_of_penghu.world.world import World

INLAND_M = 450.0
GROUND_REPATH_S = 25.0
SWEEP_ARRIVE_M = 70.0


class GroundOps:
    """Landed PLA: fight, sweep forest, cross intact bridges, garrison ports."""

    def __init__(self, log: DecisionLog) -> None:
        self.log = log

    def step(self, world: World, intel: IntelOps) -> None:
        now = world.clock.simulation_time
        planner = world.entities.planner
        if planner is None:
            return
        islands = planner.land.islands
        busy = world.transport.busy_ids()
        held = china_by_island(world)
        assault = None if intel.assault is None else intel.assault.island
        hops = _assign_garrison(world, intel, held, assault, busy)
        for obj in world.entities.items:
            if not isinstance(obj, DynamicObject):
                continue
            if not obj.active or obj.faction != FACTION_CHINA:
                continue
            if obj.mobility != "land" or obj.stowed:
                continue
            if obj.kind not in ("infantry", "tank", "artillery", "aa_pickup"):
                continue
            if obj.id in busy:
                continue
            if obj.task == "shuttle":
                obj.task = ""
            island = islands.at(obj.x, obj.y)
            if island is None:
                near = islands.nearest(obj.x, obj.y, 120.0)
                if near is None:
                    continue
                island = near
            last = float(getattr(obj, "task_sim", 0.0) or 0.0)
            if obj.kind == "artillery" and obj.task == "deployed":
                if not is_surplus(obj, island, assault, held):
                    continue
                obj.task = ""
            if obj.moving and now - last < GROUND_REPATH_S:
                continue
            dest = _push_dest(world, obj, island, intel, hops.get(obj.id))
            if dest is None:
                continue
            if hypot(dest[0] - obj.x, dest[1] - obj.y) < 40.0:
                if obj.kind == "artillery":
                    obj.task = "deployed"
                    obj.route = None
                continue
            world.entities.dispatch(
                SetRoute(object_id=obj.id, mode="auto", target=dest),
                as_faction=FACTION_CHINA,
            )
            first = last <= 0.0
            obj.task_sim = now
            if hops.get(obj.id) is not None:
                obj.task = "garrison"
            elif obj.kind == "artillery":
                obj.task = "deploying"
            if first:
                self.log.emit(
                    now,
                    "ground",
                    f"{obj.id} {obj.kind} -> {dest[0]:.0f},{dest[1]:.0f}",
                )


def _push_dest(
    world: World,
    unit: DynamicObject,
    island: int,
    intel: IntelOps,
    hop: tuple[float, float] | None,
):
    planner = world.entities.planner
    if planner is None:
        return None
    foe = _nearest_foe(world, unit, island)
    if foe is not None:
        return (foe.x, foe.y)
    if unit.kind == "infantry":
        lane = _forest_dest(unit, island, intel)
        if lane is not None:
            return lane
    if hop is not None:
        return hop
    if unit.kind == "artillery":
        grid = intel.heat.grids.get(island)
        if grid is not None:
            hot = _hottest_cell(grid)
            if hot is not None:
                return hot
        return _inland(planner, unit, island)
    other = _nearest_foe(world, unit, None)
    if other is not None:
        oid = world.entities.planner.land.islands.at(other.x, other.y)
        if oid is not None and islands_linked(world, island, oid):
            return (other.x, other.y)
    sweep = _sweep_cell(world, unit, island, intel)
    if sweep is not None:
        return sweep
    if intel.assault is not None and intel.assault.island != island:
        if islands_linked(world, island, intel.assault.island):
            return (intel.assault.x, intel.assault.y)
    return _inland(planner, unit, island)


def _assign_garrison(
    world: World,
    intel: IntelOps,
    held: dict[int, list[DynamicObject]],
    assault: int | None,
    busy: set[str],
) -> dict[str, tuple[float, float]]:
    orders: dict[str, tuple[float, float]] = {}
    used: set[str] = set()
    for dest_iid in capture_islands(world):
        taken = set(world.transport.inbound_kinds(dest_iid))
        taken.update(_enroute_kinds(world, dest_iid))
        for kind in ("infantry", "artillery"):
            if kind in taken:
                continue
            pick = None
            best_d = 1e30
            dest = _garrison_stand(world, dest_iid, kind, intel)
            if dest is None:
                continue
            for island, units in held.items():
                if island == dest_iid or not islands_linked(world, island, dest_iid):
                    continue
                if _island_has_foe(world, island):
                    continue
                for unit in units:
                    if unit.id in busy or unit.id in used or unit.kind != kind:
                        continue
                    if not is_surplus(unit, island, assault, held):
                        continue
                    if kind == "infantry" and _forest_dest(unit, island, intel):
                        continue
                    d = hypot(unit.x - dest[0], unit.y - dest[1])
                    if d < best_d:
                        pick = unit
                        best_d = d
            if pick is None:
                continue
            orders[pick.id] = dest
            used.add(pick.id)
    return orders


def _garrison_stand(
    world: World, island: int, kind: str, intel: IntelOps
) -> tuple[float, float] | None:
    grid = intel.heat.grids.get(island)
    cover = world.perception.cover
    if kind == "infantry" and grid is not None and cover is not None:
        for i, land in enumerate(grid.land):
            if land and cover.at(*grid.center(i), "ground") == "forest":
                return grid.center(i)
    if kind == "artillery" and grid is not None:
        hot = _hottest_cell(grid)
        if hot is not None:
            return hot
        for i, land in enumerate(grid.land):
            if land and not grid.coastal[i]:
                return grid.center(i)
    return island_stand(world, island)


def _enroute_kinds(world: World, dest_iid: int) -> set[str]:
    planner = world.entities.planner
    if planner is None:
        return set()
    islands = planner.land.islands
    kinds: set[str] = set()
    for obj in world.entities.items:
        if not isinstance(obj, DynamicObject) or not obj.active:
            continue
        if obj.faction != FACTION_CHINA or obj.route is None:
            continue
        if obj.kind not in ("infantry", "artillery", "tank"):
            continue
        end = obj.route.points[-1]
        at = islands.at(*end)
        if at is None:
            at = islands.nearest(end[0], end[1], 200.0)
        if at == dest_iid:
            kinds.add(obj.kind)
    return kinds


def _island_has_foe(world: World, island: int) -> bool:
    planner = world.entities.planner
    if planner is None:
        return False
    islands = planner.land.islands
    for obj in world.perception.visible_objects(FACTION_CHINA):
        if obj.faction != FACTION_PLAYER or not obj.active:
            continue
        if is_static_kind(obj.kind) or obj.kind in SHOT_KINDS:
            continue
        if getattr(obj, "stowed", False):
            continue
        if islands.at(obj.x, obj.y) == island:
            return True
    return False


def _forest_dest(
    unit: DynamicObject, island: int, intel: IntelOps
) -> tuple[float, float] | None:
    """Nearest forest lane never looked at. Lanes barred to drones come first."""
    todo = intel.forest.ground_debt(island) or intel.forest.pending(island)
    if not todo:
        return None
    return min(todo, key=lambda pt: hypot(pt[0] - unit.x, pt[1] - unit.y))


def _sweep_cell(world: World, unit: DynamicObject, island: int, intel: IntelOps):
    """Walk the forest lanes nobody has looked at, nearest first.

    Canopy hides a squad from a drone at 210 m, and more than half the lanes sit
    under a live AA umbrella no drone may enter, so boots are the only way those
    forests ever get searched. Lanes the air could not reach come first.
    """
    lane = _forest_dest(unit, island, intel)
    if lane is not None:
        return lane
    stale = intel.forest.pending(island, now=world.clock.simulation_time)
    if stale:
        return min(stale, key=lambda pt: hypot(pt[0] - unit.x, pt[1] - unit.y))
    grid = intel.heat.grids.get(island)
    if grid is None:
        return None
    inland = [
        grid.center(i)
        for i, land in enumerate(grid.land)
        if land and not grid.coastal[i]
    ]
    if not inland:
        return None
    idx = int(getattr(unit, "sweep_i", 0) or 0) % len(inland)
    dest = inland[idx]
    if hypot(dest[0] - unit.x, dest[1] - unit.y) < SWEEP_ARRIVE_M:
        unit.sweep_i = idx + 1
        dest = inland[unit.sweep_i % len(inland)]
    return dest


def _nearest_foe(world: World, unit: DynamicObject, island: int | None):
    planner = world.entities.planner
    if planner is None:
        return None
    islands = planner.land.islands
    best = None
    best_d = 1e30
    for obj in world.perception.visible_objects(FACTION_CHINA):
        if obj.faction != FACTION_PLAYER or not obj.active:
            continue
        if obj.kind in SHOT_KINDS or is_static_kind(obj.kind):
            continue
        if getattr(obj, "stowed", False):
            continue
        if obj.kind in ("ferry", "ship", "landing_ship", "drone_carrier", "drone", "scout"):
            continue
        at = islands.at(obj.x, obj.y)
        if at is None:
            continue
        if island is not None and at != island:
            continue
        d = hypot(obj.x - unit.x, obj.y - unit.y)
        if d < best_d:
            best = obj
            best_d = d
    return best


def _hottest_cell(grid) -> tuple[float, float] | None:
    best_i = None
    best_v = 0.0
    for i, land in enumerate(grid.land):
        if not land:
            continue
        v = grid.threat[i]
        if v > best_v:
            best_v = v
            best_i = i
    if best_i is None:
        return None
    return grid.center(best_i)


def _inland(planner, unit: DynamicObject, island: int) -> tuple[float, float] | None:
    coast = planner.land.islands.coast_point(unit.x, unit.y, island=island, max_m=4000.0)
    if coast is None:
        return None
    _, (cx, cy) = coast
    dx = unit.x - cx
    dy = unit.y - cy
    n = hypot(dx, dy) or 1.0
    x = unit.x + dx / n * INLAND_M
    y = unit.y + dy / n * INLAND_M
    if planner.land.islands.at(x, y) != island:
        return (unit.x + dx / n * 80.0, unit.y + dy / n * 80.0)
    return (x, y)
