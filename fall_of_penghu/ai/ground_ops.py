from __future__ import annotations

from math import hypot
from typing import TYPE_CHECKING

from fall_of_penghu.ai.china_util import (
    china_by_island,
    china_owned,
    capture_islands,
    island_has_foe,
    island_stand,
    islands_linked,
    is_surplus,
)
from fall_of_penghu.world.entities.command import SetRoute
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER
from fall_of_penghu.profile import slice_round_robin
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind

if TYPE_CHECKING:
    from fall_of_penghu.ai.intel import IntelOps
    from fall_of_penghu.ai.log import DecisionLog
    from fall_of_penghu.world.world import World

INLAND_M = 450.0
GROUND_REPATH_S = 25.0
SWEEP_ARRIVE_M = 70.0
ASSIGN_SIM_S = 0.35


class GroundOps:
    """Landed PLA: fight, sweep forest, cross intact bridges, garrison ports."""

    def __init__(self, log: DecisionLog) -> None:
        self.log = log
        self._hops: dict[str, tuple[float, float]] = {}
        self._hop_dest: dict[str, int] = {}
        self._assign_due: dict[int, float] = {}
        self._assign_i = 0
        self._repath_i = 0

    def step(self, world: World, intel: IntelOps) -> None:
        now = world.clock.simulation_time
        planner = world.entities.planner
        if planner is None:
            return
        islands = planner.land.islands
        from fall_of_penghu.profile import scope

        busy = world.transport.busy_ids()
        held = china_by_island(world)
        assault = None if intel.assault is None else intel.assault.island
        if world.clock.dt_sim > 0.0:
            with scope("ground.assign"):
                self._slice_assign(world, intel, held, assault, busy, now)
        if world.clock.dt_sim <= 0.0:
            return
        with scope("ground.repath"):
            self._drive_units(
                world, intel, islands, busy, held, assault, self._hops, now
            )

    def _slice_assign(
        self,
        world: World,
        intel: IntelOps,
        held: dict[int, list[DynamicObject]],
        assault: int | None,
        busy: set[str],
        now: float,
    ) -> None:
        dests = capture_islands(world, held=held)
        want = set(dests)
        for uid, iid in list(self._hop_dest.items()):
            if iid in want:
                continue
            self._hops.pop(uid, None)
            self._hop_dest.pop(uid, None)
        due = [
            iid
            for iid in dests
            if now - self._assign_due.get(iid, -1e9) >= ASSIGN_SIM_S
        ]
        if not due:
            return
        self._assign_i = slice_round_robin(
            due,
            self._assign_i,
            lambda iid: self._assign_island(
                world, intel, held, assault, busy, iid, now
            ),
        )

    def _assign_island(
        self,
        world: World,
        intel: IntelOps,
        held: dict[int, list[DynamicObject]],
        assault: int | None,
        busy: set[str],
        dest_iid: int,
        now: float,
    ) -> None:
        self._assign_due[dest_iid] = now
        for uid, iid in list(self._hop_dest.items()):
            if iid != dest_iid:
                continue
            self._hops.pop(uid, None)
            self._hop_dest.pop(uid, None)
        taken = set(world.transport.inbound_kinds(dest_iid))
        taken.update(_enroute_kinds(world, dest_iid))
        used = set(self._hops)
        for kind in ("infantry", "artillery"):
            if kind in taken:
                continue
            dest = _garrison_stand(world, dest_iid, kind, intel)
            if dest is None:
                continue
            pick = None
            best_d = 1e30
            for island, units in held.items():
                if island == dest_iid or not islands_linked(world, island, dest_iid):
                    continue
                if island_has_foe(world, island):
                    continue
                for unit in units:
                    if unit.id in busy or unit.id in used or unit.kind != kind:
                        continue
                    if not is_surplus(unit, island, assault, held, world):
                        continue
                    if (
                        kind == "infantry"
                        and not china_owned(world, island)
                        and _forest_dest(unit, island, intel)
                    ):
                        continue
                    d = hypot(unit.x - dest[0], unit.y - dest[1])
                    if d < best_d:
                        pick = unit
                        best_d = d
            if pick is None:
                continue
            self._hops[pick.id] = dest
            self._hop_dest[pick.id] = dest_iid
            used.add(pick.id)

    def _drive_units(
        self,
        world: World,
        intel: IntelOps,
        islands,
        busy,
        held,
        assault,
        hops,
        now: float,
    ) -> None:
        units = [
            obj
            for obj in world.entities.items
            if isinstance(obj, DynamicObject)
            and obj.active
            and obj.faction == FACTION_CHINA
            and obj.mobility == "land"
            and not obj.stowed
            and obj.kind in ("infantry", "tank", "artillery", "aa_pickup")
            and obj.id not in busy
        ]
        self._repath_i = slice_round_robin(
            units,
            self._repath_i,
            lambda obj: self._drive_one(
                world, obj, intel, busy, held, assault, hops, now
            ),
        )

    def _drive_one(
        self,
        world: World,
        obj: DynamicObject,
        intel: IntelOps,
        busy,
        held,
        assault,
        hops,
        now: float,
    ) -> None:
        if obj.task == "shuttle":
            obj.task = ""
        island = obj.island_id()
        if island is None:
            return
        last = float(getattr(obj, "task_sim", 0.0) or 0.0)
        if obj.kind == "artillery" and obj.task == "deployed":
            if not is_surplus(obj, island, assault, held, world):
                return
            obj.task = ""
        if obj.moving and now - last < GROUND_REPATH_S:
            return
        dest = _push_dest(world, obj, island, intel, hops.get(obj.id))
        if dest is None:
            return
        if hypot(dest[0] - obj.x, dest[1] - obj.y) < 40.0:
            if obj.kind == "artillery":
                obj.task = "deployed"
                obj.route = None
            return
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
    if hop is not None and china_owned(world, island):
        return hop
    if unit.kind == "infantry" and not china_owned(world, island):
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
        oid = other.island_id() if isinstance(other, DynamicObject) else None
        if oid is not None and islands_linked(world, island, oid):
            return (other.x, other.y)
    sweep = _sweep_cell(world, unit, island, intel)
    if sweep is not None:
        return sweep
    if intel.assault is not None and intel.assault.island != island:
        if islands_linked(world, island, intel.assault.island):
            return (intel.assault.x, intel.assault.y)
    return _inland(planner, unit, island)


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


def _forest_dest(
    unit: DynamicObject, island: int, intel: IntelOps
) -> tuple[float, float] | None:
    """Next forest lane on this island's snake, not the geographically nearest.

    Nearest-first made squads hop across the wood and skip whole rows. Walking
    the baked order (debt first) is the sequential comb the player asked for.
    """
    lanes = intel.forest.lanes.get(island) or ()
    if not lanes:
        return None
    now = getattr(intel, "_now", None)
    debt = set(intel.forest.ground_debt(island, now=now))
    open_l = set(intel.forest.pending(island, now=now))
    want = debt or open_l
    if not want:
        return None
    idx = int(getattr(unit, "sweep_i", 0) or 0)
    if 0 <= idx < len(lanes) and hypot(unit.x - lanes[idx][0], unit.y - lanes[idx][1]) < SWEEP_ARRIVE_M:
        idx += 1
    order = [i for i, pt in enumerate(lanes) if pt in want]
    if not order:
        return None
    for start in (idx, 0):
        for i in order:
            if i >= start:
                unit.sweep_i = i
                return lanes[i]
    unit.sweep_i = order[0]
    return lanes[order[0]]


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
        at = obj.island_id() if isinstance(obj, DynamicObject) else islands.at(obj.x, obj.y)
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
