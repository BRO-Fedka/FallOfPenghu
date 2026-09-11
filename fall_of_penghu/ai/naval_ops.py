from __future__ import annotations

from math import atan2, hypot
from typing import TYPE_CHECKING

from fall_of_penghu.ai.china_util import (
    ARRIVE_M,
    ASSAULT_UNLOAD_SIM,
    KEEP_SHORE_BOATS,
    LANDING_LAUNCH_S,
    LANDING_MAGAZINE,
    MAX_ASSAULT_SHIPS,
    MAX_LANDING_SHIPS,
    MAX_SHORE_BOATS,
    SHIP_SPAWN_SIM,
    border_xy,
    capture_islands,
    china_by_island,
    island_stand,
    islands_linked,
    is_surplus,
    leave_off_map,
    sail,
    standoff_slot,
)
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER

if TYPE_CHECKING:
    from fall_of_penghu.ai.intel import IntelOps
    from fall_of_penghu.ai.log import DecisionLog
    from fall_of_penghu.world.world import World

CARGO_KINDS = ("infantry", "artillery", "tank")


class NavalOps:
    """Few ships per landing. Shore boats stay for the next beach."""

    def __init__(self, log: DecisionLog) -> None:
        self.log = log
        self._ship_seq = 0
        self._next_ship_sim = 0.0
        self._ferry_n = 0
        self._cargo_n = 0
        self._beach_i = 0

    def step(self, world: World, intel: IntelOps) -> None:
        self._spawn_landing_ships(world)
        ships = _landing_ships(world)
        self._drive_hops(world, intel)
        self._drive_reloading(world, intel, ships)
        active = _assault_ships(ships)
        for ship in ships:
            self._step_ship(world, ship, intel, ships, active)

    def _spawn_landing_ships(self, world: World) -> None:
        now = world.clock.simulation_time
        alive = _landing_ships(world)
        if len(alive) >= MAX_LANDING_SHIPS:
            return
        if self._ship_seq > 0 and now < self._next_ship_sim:
            return
        self._ship_seq += 1
        self._next_ship_sim = now + SHIP_SPAWN_SIM
        oid = f"c_landing_{self._ship_seq}"
        if world.entities.get(oid) is not None or oid in world.entities.forgotten_ids:
            return
        edge = border_xy(world, self._ship_seq * 2 - 1)
        station = standoff_slot(world, self._ship_seq)
        ship = DynamicObject(
            id=oid,
            faction=FACTION_CHINA,
            kind="landing_ship",
            name=f"PLA landing ship {self._ship_seq}",
            x=edge[0],
            y=edge[1],
            heading=atan2(station[1] - edge[1], station[0] - edge[0]),
            speed_mps=world.catalog.speed_mps("landing_ship"),
            mobility="sea",
        )
        ship.magazine = LANDING_MAGAZINE
        ship.task = "to_station"
        world.entities.add(ship)
        sail(world, ship, station)
        self.log.emit(now, "spawn", f"{oid} border {edge[0]:.0f},{edge[1]:.0f}")

    def _drive_hops(self, world: World, intel: IntelOps) -> None:
        idle = [
            boat
            for boat in _idle_shore_boats(world)
            if (boat.task or "") == "hold_shore"
        ]
        if not idle:
            return
        need = capture_islands(world)
        if not need:
            return
        busy = world.transport.busy_ids()
        held = china_by_island(world)
        assault = None if intel.assault is None else intel.assault.island
        now = world.clock.simulation_time
        planner = world.entities.planner
        if planner is None:
            return
        islands = planner.land.islands
        for dest_iid in need:
            dest = _garrison_point(world, dest_iid, intel)
            if dest is None:
                continue
            inbound = world.transport.inbound_kinds(dest_iid)
            sent = 0
            for kind in ("infantry", "artillery"):
                if kind in inbound or sent >= 2 or not idle:
                    continue
                unit = _surplus_unit(world, held, assault, dest_iid, kind, busy)
                if unit is None:
                    continue
                here = islands.at(unit.x, unit.y)
                if here is None:
                    here = islands.nearest(unit.x, unit.y, 120.0)
                if here is not None and islands_linked(world, here, dest_iid):
                    continue
                ferry = min(
                    idle, key=lambda boat: hypot(boat.x - unit.x, boat.y - unit.y)
                )
                if not world.transport.china_shuttle(
                    ferry, unit, dest, unload_sim=ASSAULT_UNLOAD_SIM
                ):
                    continue
                idle = [boat for boat in idle if boat.id != ferry.id]
                busy.add(unit.id)
                busy.add(ferry.id)
                sent += 1
                self.log.emit(
                    now,
                    "shuttle",
                    f"{ferry.id} {unit.kind}:{unit.id} -> island {dest_iid}",
                )

    def _drive_reloading(
        self, world: World, intel: IntelOps, ships: list[DynamicObject]
    ) -> None:
        if intel.assault is None:
            return
        now = world.clock.simulation_time
        donors = [
            ship
            for ship in _assault_ships(ships)
            if ship.magazine > 0 and now >= float(ship.weapon_ready_sim or 0.0)
        ]
        idle = sorted(_idle_shore_boats(world), key=lambda boat: boat.id)
        for ferry in idle[:KEEP_SHORE_BOATS]:
            if ferry.task == "reload":
                ferry.task = "hold_shore"
                ferry.route = None
        if not donors:
            return
        extras = [
            boat
            for boat in idle[KEEP_SHORE_BOATS:]
            if (boat.task or "") in ("hold_shore", "reload")
        ]
        for ferry in extras:
            ship = min(donors, key=lambda s: hypot(s.x - ferry.x, s.y - ferry.y))
            if hypot(ferry.x - ship.x, ferry.y - ship.y) > ARRIVE_M:
                if ferry.task != "reload":
                    ferry.task = "reload"
                    sail(world, ferry, (ship.x, ship.y))
                continue
            beach = _next_beach(world, intel, MAX_SHORE_BOATS, self._beach_i)
            if beach is None:
                ferry.task = "hold_shore"
                ferry.route = None
                continue
            if not self._load_idle(world, ship, ferry, beach):
                continue
            self._beach_i += 1
            ship.magazine -= 1
            ship.weapon_ready_sim = now + LANDING_LAUNCH_S
            self.log.emit(
                now,
                "reuse",
                f"{ferry.id} -> {beach[0]:.0f},{beach[1]:.0f} mag={ship.magazine}",
            )
            if ship.magazine <= 0:
                donors = [s for s in donors if s.id != ship.id]
            if not donors:
                return

    def _step_ship(
        self,
        world: World,
        ship: DynamicObject,
        intel: IntelOps,
        ships: list[DynamicObject],
        active: list[DynamicObject],
    ) -> None:
        station = standoff_slot(world, _slot_index(ship))
        slot = _slot_index(ship) * 2 - 1
        if ship.magazine <= 0:
            if (ship.task or "") != "leave":
                ship.task = "leave"
                self.log.emit(
                    world.clock.simulation_time, "empty", f"{ship.id} magazine empty"
                )
            leave_off_map(world, ship, station, self.log, slot)
            return
        if leave_off_map(world, ship, station, self.log, slot):
            return
        if ship not in active:
            return
        now = world.clock.simulation_time
        if now < float(ship.weapon_ready_sim or 0.0):
            return
        if intel.assault is None:
            return
        if _china_ferry_count(world) >= MAX_SHORE_BOATS:
            return
        beach = _next_beach(world, intel, MAX_SHORE_BOATS, self._beach_i)
        if beach is None:
            return
        if not self._launch_landing(world, ship, beach):
            return
        self._beach_i += 1
        ship.magazine -= 1
        ship.weapon_ready_sim = now + LANDING_LAUNCH_S
        self.log.emit(
            now,
            "land",
            f"{ship.id} boat -> {beach[0]:.0f},{beach[1]:.0f} mag={ship.magazine}",
        )

    def _launch_landing(
        self,
        world: World,
        ship: DynamicObject,
        beach: tuple[float, float],
    ) -> bool:
        cargo, ferry = self._make_boat(world, ship)
        world.entities.add(cargo)
        world.entities.add(ferry)
        if not world.transport.assault_beach(
            ferry,
            beach,
            home_id=ship.id,
            unload_sim=ASSAULT_UNLOAD_SIM,
            hold_shore=True,
        ):
            world.entities.discard(ferry.id)
            world.entities.discard(cargo.id)
            return False
        return True

    def _load_idle(
        self,
        world: World,
        ship: DynamicObject,
        ferry: DynamicObject,
        beach: tuple[float, float],
    ) -> bool:
        cargo, _ = self._make_boat(world, ship, ferry=ferry)
        world.entities.add(cargo)
        ferry.task = ""
        ferry.route = None
        if not world.transport.assault_beach(
            ferry,
            beach,
            home_id=ship.id,
            unload_sim=ASSAULT_UNLOAD_SIM,
            hold_shore=True,
        ):
            world.entities.discard(cargo.id)
            ferry.cargo_id = None
            ferry.task = "hold_shore"
            return False
        return True

    def _make_boat(
        self,
        world: World,
        ship: DynamicObject,
        ferry: DynamicObject | None = None,
    ) -> tuple[DynamicObject, DynamicObject]:
        kind = CARGO_KINDS[self._cargo_n % len(CARGO_KINDS)]
        self._cargo_n += 1
        cargo = DynamicObject(
            id=f"c_{kind}_{self._cargo_n:03d}",
            faction=FACTION_CHINA,
            kind=kind,
            name=f"PLA {kind} {self._cargo_n}",
            x=ship.x if ferry is None else ferry.x,
            y=ship.y if ferry is None else ferry.y,
            heading=ship.heading if ferry is None else ferry.heading,
            speed_mps=world.catalog.speed_mps(kind),
            mobility="land",
        )
        cargo.stowed = True
        if ferry is None:
            self._ferry_n += 1
            ferry = DynamicObject(
                id=f"c_ferry_{self._ferry_n:03d}",
                faction=FACTION_CHINA,
                kind="ferry",
                name=f"PLA ferry {self._ferry_n}",
                x=ship.x,
                y=ship.y,
                heading=ship.heading,
                speed_mps=world.catalog.speed_mps("ferry"),
                mobility="sea",
            )
        ferry.home_port_id = ship.id
        ferry.cargo_id = cargo.id
        return cargo, ferry


def _landing_ships(world: World) -> list[DynamicObject]:
    out: list[DynamicObject] = []
    for obj in world.entities.items:
        if (
            isinstance(obj, DynamicObject)
            and obj.active
            and obj.faction == FACTION_CHINA
            and obj.kind == "landing_ship"
        ):
            out.append(obj)
    return out


def _assault_ships(ships: list[DynamicObject]) -> list[DynamicObject]:
    ready = [
        ship
        for ship in ships
        if (ship.task or "station") == "station" and ship.magazine > 0
    ]
    ready.sort(key=lambda ship: ship.id)
    return ready[:MAX_ASSAULT_SHIPS]


def _china_ferry_count(world: World) -> int:
    n = 0
    for obj in world.entities.items:
        if (
            isinstance(obj, DynamicObject)
            and obj.active
            and obj.faction == FACTION_CHINA
            and obj.kind == "ferry"
        ):
            n += 1
    return n


def _idle_shore_boats(world: World) -> list[DynamicObject]:
    out: list[DynamicObject] = []
    for obj in world.entities.items:
        if not isinstance(obj, DynamicObject) or not obj.active:
            continue
        if obj.faction != FACTION_CHINA or obj.kind != "ferry":
            continue
        if obj.cargo_id:
            continue
        if (obj.task or "") not in ("hold_shore", "reload"):
            continue
        out.append(obj)
    return out


def _surplus_unit(
    world: World,
    held: dict[int, list[DynamicObject]],
    assault: int | None,
    dest_iid: int,
    kind: str,
    busy: set[str],
) -> DynamicObject | None:
    planner = world.entities.planner
    if planner is None:
        return None
    islands = planner.land.islands
    best = None
    best_d = 1e30
    dest = island_stand(world, dest_iid)
    if dest is None:
        return None
    for island, units in held.items():
        if island == dest_iid:
            continue
        fighting = False
        for obj in world.perception.visible_objects(FACTION_CHINA):
            if obj.faction != FACTION_PLAYER or not obj.active:
                continue
            if getattr(obj, "stowed", False):
                continue
            at = islands.at(obj.x, obj.y)
            if at == island:
                fighting = True
                break
        if fighting:
            continue
        for unit in units:
            if unit.kind != kind or unit.id in busy or unit.stowed:
                continue
            if unit.task in ("shuttle", "garrison"):
                continue
            if not is_surplus(unit, island, assault, held):
                continue
            d = hypot(unit.x - dest[0], unit.y - dest[1])
            if d < best_d:
                best = unit
                best_d = d
    return best


def _garrison_point(world: World, island: int, intel: IntelOps) -> tuple[float, float] | None:
    grid = intel.heat.grids.get(island)
    cover = world.perception.cover
    if grid is not None and cover is not None:
        for i, land in enumerate(grid.land):
            if not land:
                continue
            pt = grid.center(i)
            if cover.at(pt[0], pt[1], "ground") == "forest":
                return pt
        for i, land in enumerate(grid.land):
            if land and not grid.coastal[i]:
                return grid.center(i)
    return island_stand(world, island)


def _island_beach(world: World, island: int) -> tuple[float, float] | None:
    planner = world.entities.planner
    if planner is None:
        return None
    samples = planner.land.islands.coast_samples(island)
    if samples:
        return samples[len(samples) // 2]
    return island_stand(world, island)


def _next_beach(
    world: World, intel: IntelOps, n_boats: int, index: int
) -> tuple[float, float] | None:
    assault = intel.assault
    if assault is None:
        return None
    empty = capture_islands(world)
    held = china_by_island(world)
    assault_n = len(held.get(assault.island, ()))
    if empty and assault_n >= 4 and index % 4 == 3:
        iid = empty[(index // 4) % len(empty)]
        beach = _island_beach(world, iid)
        if beach is not None:
            return beach
    return _spread_beach(world, intel, n_boats, index)


def _slot_index(ship: DynamicObject) -> int:
    try:
        return int(ship.id.rsplit("_", 1)[-1])
    except ValueError:
        return 1


def _spread_beach(
    world: World, intel: IntelOps, n_boats: int, index: int
) -> tuple[float, float] | None:
    assault = intel.assault
    if assault is None:
        return None
    planner = world.entities.planner
    if planner is None:
        return None
    samples = planner.land.islands.coast_samples(assault.island)
    if not samples:
        coast = planner.land.islands.coast_point(
            assault.x, assault.y, island=assault.island, max_m=80_000.0
        )
        return None if coast is None else coast[1]
    idx = min(
        range(len(samples)),
        key=lambda i: hypot(samples[i][0] - assault.x, samples[i][1] - assault.y),
    )
    n = max(n_boats, 1)
    step = max(1, int(round(len(samples) / max(n * 2, 8))))
    half = n // 2
    j = (idx + (index % n - half) * step) % len(samples)
    return samples[j]
