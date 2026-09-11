from __future__ import annotations

import random
from dataclasses import dataclass
from math import hypot
from typing import TYPE_CHECKING

from fall_of_penghu.world.entities.command import SetRoute
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER, GameObject
from fall_of_penghu.world.events import ContactNotice

if TYPE_CHECKING:
    from fall_of_penghu.world.world import World

PORT_CAP = 20
# Simulation seconds for embark / disembark.
LOAD_PORT_SIM = 300.0
LOAD_BEACH_SIM = 1800.0
BOARD_M = 90.0
BEACH_ARRIVE_M = 180.0
WATER_ARRIVE_M = 120.0
SHORE_CLICK_M = 500.0
BEACH_LAND_M = 50.0
MAIN_AREA_M2 = 10_000_000.0
SHORE_M = 80.0


@dataclass
class CrossingJob:
    cargo_id: str
    ferry_id: str
    dest: tuple[float, float] | None
    drop: tuple[float, float]
    home_port_id: str
    dest_port_id: str | None
    pickup: tuple[float, float]
    ferry_meet: tuple[float, float]
    drop_meet: tuple[float, float]
    phase: str
    wait_until: float
    beach_load: bool
    beach_drop: bool
    auto: bool = True
    wait_sim: float | None = None
    hold_shore: bool = False
    stage: tuple[float, float] | None = None


class Transport:
    """Port ferries and inter-island crossings. Does not draw."""

    def __init__(self) -> None:
        self._world: World | None = None
        self._jobs: list[CrossingJob] = []
        self._recalls: list[tuple[str, str]] = []
        self._cargo_resume: dict[str, tuple[float, float]] = {}
        self._ferry_n = 0

    def bind(self, world: World) -> None:
        self._world = world

    def seed(self, world: World) -> None:
        planner = world.entities.planner
        if planner is None:
            return
        rng = random.Random(world.seed + 3)
        for port in _ports(world, active_only=True):
            if port.faction != FACTION_PLAYER:
                continue
            island = _island_of(planner, port.x, port.y)
            port.ferries = _start_count(planner, island, rng)

    def request(self, cargo: DynamicObject, dest: tuple[float, float]) -> bool:
        world = self._world
        if world is None:
            return False
        return self._request(world, cargo, dest)

    def _request(self, world: World, cargo: DynamicObject, dest: tuple[float, float]) -> bool:
        if cargo.faction != FACTION_PLAYER:
            return False
        if cargo.mobility != "land" or cargo.stowed:
            return False
        planner = world.entities.planner
        if planner is None:
            return False
        here = _island_of(planner, cargo.x, cargo.y)
        dest_island, dest_pt = _dest_island(planner, dest)
        if here is None or dest_island is None or here == dest_island:
            return False
        self._cancel(world, cargo.id)
        origin_port = _nearest_port(world, planner, here, cargo.x, cargo.y)
        dest_port, dest_full = _dest_port(
            world, planner, dest_island, dest_pt[0], dest_pt[1]
        )
        beach_drop = dest_port is None
        if dest_full:
            _notice(world, cargo.id, dest_pt, "Port full — landing on the beach")
        busy = self._busy_ferries()
        idle = _nearest_idle_ferry(world, cargo.x, cargo.y, busy)
        if origin_port is not None and _ferry_count(origin_port) > 0:
            stock = origin_port
        else:
            stock = _nearest_stocked_port(world, cargo.x, cargo.y)
        use_idle = False
        if idle is not None and stock is not None:
            d_idle = hypot(idle.x - cargo.x, idle.y - cargo.y)
            d_stock = hypot(stock.x - cargo.x, stock.y - cargo.y)
            use_idle = d_idle <= d_stock
        elif idle is not None:
            use_idle = True
        elif stock is None:
            return False
        if origin_port is not None:
            pickup = (origin_port.x, origin_port.y)
            ferry_meet = pickup
            beach_load = False
        else:
            sea_xy = (idle.x, idle.y) if use_idle else (stock.x, stock.y)
            meet = _best_shore_meet(
                planner, here, (cargo.x, cargo.y), sea_xy
            )
            if meet is None:
                return False
            pickup, ferry_meet = meet
            beach_load = True
        if beach_drop:
            sea_from = ferry_meet
            meet = _best_shore_meet(planner, dest_island, dest_pt, sea_from)
            if meet is None:
                drop = dest_pt
                drop_meet = dest_pt
            else:
                drop, drop_meet = meet
        else:
            drop = (dest_port.x, dest_port.y)
            drop_meet = drop
        if use_idle:
            home_id = idle.home_port_id or (stock.id if stock is not None else "")
            if not home_id:
                near = _nearest_player_port(world, pickup[0], pickup[1])
                home_id = near.id if near is not None else ""
            ferry_id = idle.id
            _route(world, idle, ferry_meet)
        else:
            home_id = stock.id
            ferry_id = ""
            if beach_load:
                spawned = self._spawn(world, stock)
                if spawned is None:
                    return False
                ferry_id = spawned.id
                _route(world, spawned, ferry_meet)
        job = CrossingJob(
            cargo_id=cargo.id,
            ferry_id=ferry_id,
            dest=dest,
            drop=drop,
            home_port_id=home_id,
            dest_port_id=None if dest_port is None else dest_port.id,
            pickup=pickup,
            ferry_meet=ferry_meet,
            drop_meet=drop_meet,
            phase="to_pickup",
            wait_until=0.0,
            beach_load=beach_load,
            beach_drop=beach_drop,
            auto=True,
        )
        self._jobs.append(job)
        _route(world, cargo, pickup)
        _notice(
            world,
            cargo.id,
            pickup,
            (
                "Unit proceeding to shore for embarkation"
                if beach_load
                else "Unit proceeding to port for embarkation"
            ),
        )
        return True

    def launch(self, port_id: str, dest: tuple[float, float]) -> DynamicObject | None:
        world = self._world
        if world is None:
            return None
        port = world.entities.get(port_id)
        if port is None or port.kind != "port" or not port.active:
            return None
        ferry = self._spawn(world, port)
        if ferry is None:
            return None
        _route(world, ferry, dest)
        return ferry

    def recall(self, port_id: str, ferry_id: str) -> bool:
        world = self._world
        if world is None:
            return False
        port = world.entities.get(port_id)
        ferry = world.entities.get(ferry_id)
        if port is None or not port.active or port.kind != "port":
            return False
        if not isinstance(ferry, DynamicObject) or ferry.kind != "ferry" or not ferry.active:
            return False
        if _ferry_count(port) >= PORT_CAP:
            return False
        self._detach_ferry_job(ferry)
        ferry.home_port_id = port.id
        _route(world, ferry, (port.x, port.y))
        pair = (ferry.id, port.id)
        self._recalls = [item for item in self._recalls if item[0] != ferry.id]
        self._recalls.append(pair)
        return True

    def load_onto(self, ferry_id: str, cargo_id: str) -> bool:
        world = self._world
        if world is None:
            return False
        ferry = world.entities.get(ferry_id)
        cargo = world.entities.get(cargo_id)
        if not isinstance(ferry, DynamicObject) or ferry.kind != "ferry":
            return False
        if not ferry.active or ferry.cargo_id or ferry.faction != FACTION_PLAYER:
            return False
        if not isinstance(cargo, DynamicObject) or cargo.mobility != "land":
            return False
        if not cargo.active or cargo.stowed or cargo.faction != FACTION_PLAYER:
            return False
        planner = world.entities.planner
        if planner is None:
            return False
        here = _island_of(planner, cargo.x, cargo.y)
        if here is None:
            return False
        self._cancel(world, cargo.id)
        self._cancel(world, ferry.id)
        self._recalls = [item for item in self._recalls if item[0] != ferry.id]
        meet = _best_shore_meet(
            planner, here, (cargo.x, cargo.y), (ferry.x, ferry.y)
        )
        if meet is None:
            return False
        pickup, ferry_meet = meet
        home_id = ferry.home_port_id or ""
        job = CrossingJob(
            cargo_id=cargo.id,
            ferry_id=ferry.id,
            dest=None,
            drop=pickup,
            home_port_id=home_id,
            dest_port_id=None,
            pickup=pickup,
            ferry_meet=ferry_meet,
            drop_meet=ferry_meet,
            phase="to_pickup",
            wait_until=0.0,
            beach_load=True,
            beach_drop=False,
            auto=False,
        )
        self._jobs.append(job)
        _route(world, cargo, pickup)
        _route(world, ferry, ferry_meet)
        return True

    def unload_at(
        self,
        ferry_id: str,
        dest: tuple[float, float],
        *,
        dest_port_id: str | None = None,
    ) -> bool:
        world = self._world
        if world is None:
            return False
        ferry = world.entities.get(ferry_id)
        if not isinstance(ferry, DynamicObject) or ferry.kind != "ferry":
            return False
        if not ferry.active or not ferry.cargo_id:
            return False
        cargo = world.entities.get(ferry.cargo_id)
        if not isinstance(cargo, DynamicObject) or not cargo.stowed:
            return False
        planner = world.entities.planner
        if planner is None:
            return False
        self._jobs = [job for job in self._jobs if job.ferry_id != ferry.id]
        self._recalls = [item for item in self._recalls if item[0] != ferry.id]
        dest_island, dest_pt = _dest_island(planner, dest)
        dest_port = None
        dest_full = False
        if dest_port_id:
            picked = world.entities.get(dest_port_id)
            if (
                picked is not None
                and picked.kind == "port"
                and picked.active
                and picked.faction == FACTION_PLAYER
            ):
                dest_port = picked
                dest_island, dest_pt = _dest_island(planner, (picked.x, picked.y))
                dest = (picked.x, picked.y)
                dest_pt = dest
                if _ferry_count(picked) >= PORT_CAP:
                    dest_full = True
                    dest_port = None
        elif dest_island is not None:
            on_land = planner.land.islands.at(*dest)
            water = planner.nearest_water(*dest)
            near_shore = (
                on_land is not None
                and water is not None
                and hypot(dest[0] - water[0], dest[1] - water[1]) <= SHORE_CLICK_M
            )
            if near_shore:
                coast = planner.land.islands.coast_point(
                    dest[0], dest[1], island=on_land
                )
                land = _nudge_land(
                    planner, on_land, coast[1] if coast is not None else dest
                )
                drop = land
                drop_meet = planner.nearest_water(land[0], land[1]) or water
                beach_drop = True
                dest_port = None
                dest = land
                home_id = ferry.home_port_id or ""
                job = CrossingJob(
                    cargo_id=cargo.id,
                    ferry_id=ferry.id,
                    dest=dest,
                    drop=drop,
                    home_port_id=home_id,
                    dest_port_id=None,
                    pickup=drop,
                    ferry_meet=drop_meet,
                    drop_meet=drop_meet,
                    phase="sailing",
                    wait_until=0.0,
                    beach_load=False,
                    beach_drop=True,
                    auto=False,
                )
                self._jobs.append(job)
                _route(world, ferry, drop_meet)
                return True
            dest_port, dest_full = _dest_port(
                world, planner, dest_island, dest_pt[0], dest_pt[1]
            )
        beach_drop = dest_port is None
        if dest_full:
            _notice(world, cargo.id, dest_pt, "Port full — landing on the beach")
        if dest_port is not None:
            drop = (dest_port.x, dest_port.y)
            drop_meet = drop
        elif dest_island is not None:
            meet = _best_shore_meet(
                planner, dest_island, dest_pt, (ferry.x, ferry.y)
            )
            if meet is None:
                drop = dest_pt
                water = planner.nearest_water(dest_pt[0], dest_pt[1])
                drop_meet = water if water is not None else dest_pt
            else:
                drop, drop_meet = meet
        else:
            drop = dest
            water = planner.nearest_water(dest[0], dest[1])
            drop_meet = water if water is not None else dest
            beach_drop = True
        home_id = ferry.home_port_id or ""
        job = CrossingJob(
            cargo_id=cargo.id,
            ferry_id=ferry.id,
            dest=dest,
            drop=drop,
            home_port_id=home_id,
            dest_port_id=None if dest_port is None else dest_port.id,
            pickup=drop,
            ferry_meet=drop_meet,
            drop_meet=drop_meet,
            phase="sailing",
            wait_until=0.0,
            beach_load=False,
            beach_drop=beach_drop,
            auto=False,
        )
        self._jobs.append(job)
        _route(world, ferry, drop_meet)
        return True

    def assault_beach(
        self,
        ferry: DynamicObject,
        dest: tuple[float, float],
        *,
        home_id: str,
        unload_sim: float | None = None,
        hold_shore: bool = False,
        stage: tuple[float, float] | None = None,
    ) -> bool:
        """PLA boat already carrying stowed cargo. No player notices."""
        world = self._world
        if world is None:
            return False
        cargo = world.entities.get(ferry.cargo_id)
        if not isinstance(cargo, DynamicObject) or not cargo.stowed:
            return False
        planner = world.entities.planner
        if planner is None:
            return False
        island = planner.land.islands.nearest(dest[0], dest[1], 80_000.0)
        if island is None:
            return False
        meet = _best_shore_meet(planner, island, dest, (ferry.x, ferry.y))
        if meet is None:
            return False
        drop, drop_meet = meet
        stand = _beach_stand(planner, island, drop)
        job = CrossingJob(
            cargo_id=cargo.id,
            ferry_id=ferry.id,
            dest=stand,
            drop=drop,
            home_port_id=home_id,
            dest_port_id=None,
            pickup=drop,
            ferry_meet=drop_meet,
            drop_meet=drop_meet,
            phase="sailing",
            wait_until=0.0,
            beach_load=False,
            beach_drop=True,
            auto=True,
            wait_sim=unload_sim,
            hold_shore=hold_shore,
            stage=stage,
        )
        self._jobs.append(job)
        _route(world, ferry, stage or drop_meet)
        if ferry.route is None and stage is not None:
            job.stage = None
            _route(world, ferry, drop_meet)
        if ferry.route is None:
            self._jobs = [item for item in self._jobs if item is not job]
            return False
        return True

    def china_shuttle(
        self,
        ferry: DynamicObject,
        cargo: DynamicObject,
        dest: tuple[float, float],
        *,
        unload_sim: float | None = None,
    ) -> bool:
        """Move already-landed PLA from one island beach to another. Boat stays."""
        world = self._world
        if world is None:
            return False
        if ferry.faction != FACTION_CHINA or cargo.faction != FACTION_CHINA:
            return False
        if not ferry.active or ferry.kind != "ferry" or ferry.cargo_id:
            return False
        if not cargo.active or cargo.mobility != "land" or cargo.stowed:
            return False
        planner = world.entities.planner
        if planner is None:
            return False
        here = _island_of(planner, cargo.x, cargo.y)
        dest_island, dest_pt = _dest_island(planner, dest)
        if here is None or dest_island is None or here == dest_island:
            return False
        self._cancel(world, cargo.id)
        self._cancel(world, ferry.id)
        meet = _best_shore_meet(
            planner, here, (cargo.x, cargo.y), (ferry.x, ferry.y)
        )
        if meet is None:
            return False
        pickup, ferry_meet = meet
        drop_meet_pair = _best_shore_meet(planner, dest_island, dest_pt, ferry_meet)
        if drop_meet_pair is None:
            return False
        drop, drop_meet = drop_meet_pair
        stand = _beach_stand(planner, dest_island, dest_pt)
        home_id = ferry.home_port_id or ""
        job = CrossingJob(
            cargo_id=cargo.id,
            ferry_id=ferry.id,
            dest=stand,
            drop=drop,
            home_port_id=home_id,
            dest_port_id=None,
            pickup=pickup,
            ferry_meet=ferry_meet,
            drop_meet=drop_meet,
            phase="to_pickup",
            wait_until=0.0,
            beach_load=True,
            beach_drop=True,
            auto=True,
            wait_sim=unload_sim,
            hold_shore=True,
        )
        self._jobs.append(job)
        cargo.task = "shuttle"
        ferry.task = "shuttle"
        ferry.route = None
        _route(world, ferry, ferry_meet)
        _route(world, cargo, pickup)
        if (
            ferry.route is None
            and hypot(ferry.x - ferry_meet[0], ferry.y - ferry_meet[1])
            > WATER_ARRIVE_M
        ):
            self._jobs = [item for item in self._jobs if item is not job]
            cargo.task = ""
            ferry.task = "hold_shore"
            return False
        return True

    def busy_ids(self) -> set[str]:
        ids = {job.cargo_id for job in self._jobs if job.cargo_id}
        ids.update(job.ferry_id for job in self._jobs if job.ferry_id)
        ids.update(ferry_id for ferry_id, _port in self._recalls)
        return ids

    def inbound_kinds(self, island: int) -> set[str]:
        world = self._world
        if world is None:
            return set()
        planner = world.entities.planner
        if planner is None:
            return set()
        kinds: set[str] = set()
        for job in self._jobs:
            cargo = world.entities.get(job.cargo_id)
            if not isinstance(cargo, DynamicObject):
                continue
            dest = job.dest or job.drop
            hit = planner.land.islands.at(*dest)
            if hit is None:
                hit = planner.land.islands.nearest(dest[0], dest[1], 400.0)
            if hit == island:
                kinds.add(cargo.kind)
        return kinds

    def on_halt(self, object_id: str) -> None:
        if self._world is not None:
            self._cancel(self._world, object_id)

    def step(self, world: World) -> None:
        now = world.clock.simulation_time
        for obj in world.entities.items:
            if isinstance(obj, DynamicObject):
                obj.xfer = None
                obj.xfer_frac = 0.0
        keep: list[CrossingJob] = []
        for job in self._jobs:
            if self._advance(world, job, now):
                keep.append(job)
        self._jobs = keep
        held: list[tuple[str, str]] = []
        for ferry_id, port_id in self._recalls:
            if not self._try_absorb(world, ferry_id, port_id):
                held.append((ferry_id, port_id))
        self._recalls = held
        for job in self._jobs:
            if job.phase == "loading":
                cargo = world.entities.get(job.cargo_id)
                if isinstance(cargo, DynamicObject):
                    cargo.xfer = "load"
                    cargo.xfer_frac = _xfer_frac(job, now, loading=True)
            elif job.phase == "unloading":
                ferry = world.entities.get(job.ferry_id)
                if isinstance(ferry, DynamicObject):
                    ferry.xfer = "unload"
                    ferry.xfer_frac = _xfer_frac(job, now, loading=False)

    def _advance(self, world: World, job: CrossingJob, now: float) -> bool:
        cargo = world.entities.get(job.cargo_id)
        ferry = world.entities.get(job.ferry_id) if job.ferry_id else None
        if not isinstance(cargo, DynamicObject) or not cargo.active:
            if isinstance(ferry, DynamicObject) and ferry.active:
                self._send_home(world, ferry, job.home_port_id)
            return False
        if job.ferry_id and (
            not isinstance(ferry, DynamicObject) or not ferry.active
        ):
            if cargo.stowed:
                cargo.stowed = False
            return False
        if isinstance(ferry, DynamicObject) and cargo.stowed:
            cargo.x, cargo.y = ferry.x, ferry.y
            cargo.heading = ferry.heading
        if job.phase == "to_pickup":
            cargo_ok = _cargo_at_pickup(world, cargo, job)
            ferry_ok = False
            if isinstance(ferry, DynamicObject):
                ferry_ok = _ferry_at_water(ferry, job.ferry_meet)
            elif cargo_ok:
                home = world.entities.get(job.home_port_id)
                if home is None or not home.active:
                    return False
                same_berth = (
                    not job.beach_load
                    and hypot(home.x - job.pickup[0], home.y - job.pickup[1])
                    <= BOARD_M
                )
                if same_berth:
                    job.phase = "loading"
                    job.wait_until = now + _job_wait(job, loading=True)
                    return True
                ferry = self._spawn(world, home)
                if ferry is None:
                    _notice(world, cargo.id, job.pickup, "No ferry left at port")
                    return False
                job.ferry_id = ferry.id
                _route(world, ferry, job.ferry_meet)
                return True
            if cargo_ok and ferry_ok:
                job.phase = "loading"
                job.wait_until = now + _job_wait(job, loading=True)
            return True
        if job.phase == "ferry_inbound":
            if ferry is not None and _ferry_at_water(ferry, job.ferry_meet):
                job.phase = "loading"
                job.wait_until = now + _job_wait(job, loading=True)
            return True
        if job.phase == "loading":
            if now < job.wait_until:
                return True
            if not isinstance(ferry, DynamicObject):
                home = world.entities.get(job.home_port_id)
                if home is None or not home.active:
                    return False
                ferry = self._spawn(world, home)
                if ferry is None:
                    _notice(world, cargo.id, job.pickup, "No ferry left at port")
                    return False
                job.ferry_id = ferry.id
            _stow(ferry, cargo)
            if not job.auto:
                return False
            job.phase = "sailing"
            _route(world, ferry, job.drop_meet)
            return True
        if job.phase == "sailing":
            if job.stage is not None:
                # Form up abreast off the beach before the run in.
                if ferry is None:
                    return True
                if _ferry_at_water(ferry, job.stage) or ferry.route is None:
                    job.stage = None
                    _route(world, ferry, job.drop_meet)
                return True
            if ferry is not None and _ferry_at_water(ferry, job.drop_meet):
                job.phase = "unloading"
                job.wait_until = now + _job_wait(job, loading=False)
            return True
        if job.phase == "unloading":
            if now < job.wait_until:
                return True
            dest = job.dest
            if ferry is not None:
                _unstow(ferry, cargo)
                if job.beach_drop:
                    _place_on_beach(world, cargo, job.drop)
                else:
                    _drop_on_road(world, cargo, job.drop)
            if dest is not None and hypot(cargo.x - dest[0], cargo.y - dest[1]) > BOARD_M:
                _route(world, cargo, dest)
            if ferry is not None and job.auto:
                if job.hold_shore:
                    ferry.task = "hold_shore"
                    ferry.route = None
                    return False
                job.phase = "returning"
                self._send_home(world, ferry, job.home_port_id)
                return True
            return False
        if job.phase == "returning":
            if ferry is None:
                return False
            if self._try_absorb(world, ferry.id, job.home_port_id):
                return False
            return True
        return False

    def _spawn(self, world: World, port: GameObject) -> DynamicObject | None:
        if _ferry_count(port) <= 0:
            return None
        port.ferries = _ferry_count(port) - 1
        oid = self._next_id(world)
        ferry = DynamicObject(
            id=oid,
            faction=port.faction,
            kind="ferry",
            name=f"Ferry {self._ferry_n}",
            x=port.x,
            y=port.y,
            speed_mps=world.catalog.speed_mps("ferry"),
            mobility="sea",
        )
        ferry.home_port_id = port.id
        world.entities.add(ferry)
        return ferry

    def _try_absorb(self, world: World, ferry_id: str, port_id: str) -> bool:
        ferry = world.entities.get(ferry_id)
        if not isinstance(ferry, DynamicObject) or not ferry.active:
            return True
        home = world.entities.get(port_id)
        if home is None or not home.active:
            self._offload(world, ferry, (ferry.x, ferry.y))
            world.entities.discard(ferry.id)
            return True
        if home.kind == "port":
            if not _at_port(ferry, home):
                return False
            ferry.x, ferry.y = home.x, home.y
            ferry.route = None
            if _ferry_count(home) >= PORT_CAP:
                return False
            home.ferries = _ferry_count(home) + 1
            self._offload(world, ferry, (home.x, home.y))
            world.entities.discard(ferry.id)
            return True
        if home.kind in ("landing_ship", "drone_carrier"):
            return self._recover_boat(world, ferry, home)
        return False

    def _recover_boat(
        self, world: World, ferry: DynamicObject, home: GameObject
    ) -> bool:
        if hypot(ferry.x - home.x, ferry.y - home.y) <= WATER_ARRIVE_M * 2:
            ferry.route = None
            if ferry.cargo_id:
                self._offload(world, ferry, (home.x, home.y))
            world.entities.discard(ferry.id)
            return True
        end = (
            ferry.route.points[-1] if ferry.route is not None else (ferry.x, ferry.y)
        )
        if hypot(end[0] - home.x, end[1] - home.y) > WATER_ARRIVE_M * 2:
            _route(world, ferry, (home.x, home.y))
        return False

    def _busy_ferries(self) -> set[str]:
        busy = {job.ferry_id for job in self._jobs if job.ferry_id}
        busy.update(ferry_id for ferry_id, _port_id in self._recalls)
        return busy

    def _detach_ferry_job(self, ferry: DynamicObject) -> None:
        left: list[CrossingJob] = []
        for job in self._jobs:
            if job.ferry_id != ferry.id:
                left.append(job)
                continue
            if ferry.cargo_id and job.cargo_id == ferry.cargo_id:
                self._cargo_resume[job.cargo_id] = job.dest
        self._jobs = left

    def _offload(
        self,
        world: World,
        ferry: DynamicObject,
        near: tuple[float, float],
    ) -> None:
        cargo_id = ferry.cargo_id
        if not cargo_id:
            return
        cargo = world.entities.get(cargo_id)
        dest = self._cargo_resume.pop(cargo_id, None)
        if not isinstance(cargo, DynamicObject):
            return
        if dest is None:
            dest = self._job_dest(cargo_id)
        _unstow(ferry, cargo)
        _drop_on_road(world, cargo, near)
        if dest is not None and hypot(cargo.x - dest[0], cargo.y - dest[1]) > BOARD_M:
            _route(world, cargo, dest)

    def _job_dest(self, cargo_id: str) -> tuple[float, float] | None:
        for job in self._jobs:
            if job.cargo_id == cargo_id:
                return job.dest
        return None

    def _send_home(self, world: World, ferry: DynamicObject, home_id: str) -> None:
        if not home_id:
            return
        home = world.entities.get(home_id)
        if home is None or not home.active:
            return
        _route(world, ferry, (home.x, home.y))
        pair = (ferry.id, home.id)
        if pair not in self._recalls:
            self._recalls.append(pair)

    def _next_id(self, world: World) -> str:
        while True:
            self._ferry_n += 1
            oid = f"ferry_{self._ferry_n:03d}"
            if world.entities.get(oid) is None:
                return oid

    def _cancel(self, world: World, object_id: str) -> None:
        left: list[CrossingJob] = []
        for job in self._jobs:
            if job.cargo_id != object_id and job.ferry_id != object_id:
                left.append(job)
                continue
            cargo = world.entities.get(job.cargo_id)
            ferry = world.entities.get(job.ferry_id)
            self._cargo_resume.pop(job.cargo_id, None)
            if isinstance(cargo, DynamicObject) and cargo.stowed:
                _unstow(ferry if isinstance(ferry, DynamicObject) else None, cargo)
                _place_on_beach(world, cargo, (cargo.x, cargo.y))
            if isinstance(ferry, DynamicObject) and ferry.active:
                ferry.route = None
        self._jobs = left


def _route(world: World, obj: DynamicObject, target: tuple[float, float]) -> None:
    planner = world.entities.planner
    if planner is None:
        return
    cmd = SetRoute(object_id=obj.id, mode="auto", target=target)
    route = planner.plan(obj, cmd, intact=world.entities.bridge_intact)
    obj.route = route


def _job_wait(job: CrossingJob, *, loading: bool) -> float:
    if job.wait_sim is not None:
        return job.wait_sim
    beach = job.beach_load if loading else job.beach_drop
    return LOAD_BEACH_SIM if beach else LOAD_PORT_SIM


def _xfer_frac(job: CrossingJob, now: float, *, loading: bool) -> float:
    span = _job_wait(job, loading=loading)
    if span <= 1e-6:
        return 1.0 if loading else 0.0
    remain = max(0.0, job.wait_until - now)
    elapsed = min(span, max(0.0, span - remain))
    t = elapsed / span
    return t if loading else 1.0 - t


def _arrived(obj: DynamicObject, target: tuple[float, float]) -> bool:
    if obj.route is not None and obj.route.remaining_length() > 1.0:
        return False
    return hypot(obj.x - target[0], obj.y - target[1]) <= BOARD_M


def _ferry_at_water(obj: DynamicObject, water: tuple[float, float]) -> bool:
    dist = hypot(obj.x - water[0], obj.y - water[1])
    if dist <= WATER_ARRIVE_M:
        obj.route = None
        return True
    return _arrived(obj, water)


def _cargo_at_pickup(world: World, cargo: DynamicObject, job: CrossingJob) -> bool:
    dist = hypot(cargo.x - job.pickup[0], cargo.y - job.pickup[1])
    if not job.beach_load:
        return _arrived(cargo, job.pickup)
    if dist <= BEACH_ARRIVE_M:
        cargo.route = None
        return True
    planner = world.entities.planner
    if planner is None:
        return False
    island = _island_of(planner, job.pickup[0], job.pickup[1])
    here = _island_of(planner, cargo.x, cargo.y)
    if island is not None and here == island and dist <= 280.0:
        cargo.route = None
        return True
    return False


def _stow(ferry: DynamicObject, cargo: DynamicObject) -> None:
    cargo.stowed = True
    cargo.route = None
    cargo.doctrine = "hold"
    ferry.cargo_id = cargo.id
    cargo.x, cargo.y = ferry.x, ferry.y


def _unstow(ferry: DynamicObject | None, cargo: DynamicObject) -> None:
    cargo.stowed = False
    cargo.route = None
    if cargo.kind in ("aaw", "aa_pickup", "infantry", "tank", "artillery"):
        cargo.doctrine = "fire"
    if ferry is not None:
        cargo.x, cargo.y = ferry.x, ferry.y
        ferry.cargo_id = None


def _ferry_count(port: GameObject) -> int:
    return int(getattr(port, "ferries", 0) or 0)


def _at_port(ferry: DynamicObject, port: GameObject) -> bool:
    if ferry.route is not None and ferry.route.remaining_length() > 1.0:
        return False
    return hypot(ferry.x - port.x, ferry.y - port.y) <= 12.0


def _drop_on_road(world: World, cargo: DynamicObject, near: tuple[float, float]) -> None:
    planner = world.entities.planner
    if planner is None:
        cargo.x, cargo.y = near
        return
    spot = planner.land.nearest_road_point(near[0], near[1])
    if spot is None:
        cargo.x, cargo.y = near
        return
    cargo.x, cargo.y = spot


def _place_on_beach(
    world: World, cargo: DynamicObject, hint: tuple[float, float]
) -> None:
    """Stand on land, no farther than BEACH_LAND_M from the coastline. Never a road."""
    planner = world.entities.planner
    if planner is None:
        cargo.x, cargo.y = hint
        return
    island = planner.land.islands.at(*hint)
    shore = hint
    if island is None:
        found = planner.land.islands.nearest_shore(hint[0], hint[1], 800.0)
        if found is not None:
            island, shore = found
        else:
            island = planner.land.islands.nearest(hint[0], hint[1], 800.0)
            if island is None:
                return
            coast = planner.land.islands.coast_point(
                hint[0], hint[1], island=island
            )
            if coast is None:
                return
            island, shore = coast
    else:
        coast = planner.land.islands.coast_point(hint[0], hint[1], island=island)
        if coast is not None:
            shore = coast[1]
    cargo.x, cargo.y = _beach_stand(planner, island, shore)


def _nudge_land(planner, island: int, pt: tuple[float, float]) -> tuple[float, float]:
    return _beach_stand(planner, island, pt)


def _beach_stand(
    planner, island: int, pt: tuple[float, float]
) -> tuple[float, float]:
    feats = planner.land.islands.features(island)
    if not feats:
        return pt
    minx = min(feat.bbox[0] for feat in feats)
    miny = min(feat.bbox[1] for feat in feats)
    maxx = max(feat.bbox[2] for feat in feats)
    maxy = max(feat.bbox[3] for feat in feats)
    cx = (minx + maxx) * 0.5
    cy = (miny + maxy) * 0.5
    coast = planner.land.islands.coast_point(pt[0], pt[1], island=island)
    shore = coast[1] if coast is not None else pt
    if planner.land.islands.at(*pt) == island:
        dist = hypot(pt[0] - shore[0], pt[1] - shore[1])
        if dist <= BEACH_LAND_M:
            return pt
        if dist > 1.0:
            t = BEACH_LAND_M / dist
            q = (shore[0] + (pt[0] - shore[0]) * t, shore[1] + (pt[1] - shore[1]) * t)
            if planner.land.islands.at(*q) == island:
                return q
    dx = cx - shore[0]
    dy = cy - shore[1]
    length = hypot(dx, dy)
    if length <= 1.0:
        return shore
    ux, uy = dx / length, dy / length
    for dist in (12.0, 30.0, BEACH_LAND_M):
        q = (shore[0] + ux * dist, shore[1] + uy * dist)
        if planner.land.islands.at(*q) == island:
            return q
    if planner.land.islands.at(*shore) == island:
        return shore
    return pt


def _best_shore_meet(
    planner, island: int, land_xy: tuple[float, float], sea_xy: tuple[float, float]
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    samples = planner.land.islands.coast_samples(island)
    if not samples:
        return None
    best_land: tuple[float, float] | None = None
    best_water: tuple[float, float] | None = None
    best = 1e30
    for pt in samples:
        land = _nudge_land(planner, island, pt)
        water = planner.nearest_water(pt[0], pt[1])
        if water is None:
            water = land
        score = hypot(land_xy[0] - land[0], land_xy[1] - land[1]) + hypot(
            sea_xy[0] - water[0], sea_xy[1] - water[1]
        )
        if score < best:
            best = score
            best_land = land
            best_water = water
    if best_land is None or best_water is None:
        return None
    return best_land, best_water


def _notice(
    world: World, oid: str, xy: tuple[float, float], text: str
) -> None:
    world.notices.append(
        ContactNotice(
            faction=FACTION_PLAYER,
            object_ids=(oid,),
            x=xy[0],
            y=xy[1],
            text=text,
            slow_time=False,
        )
    )


def _ports(world: World, *, active_only: bool) -> list[GameObject]:
    out: list[GameObject] = []
    for obj in world.entities.items:
        if obj.kind != "port":
            continue
        if active_only and not obj.active:
            continue
        if not hasattr(obj, "ferries"):
            obj.ferries = 0
        out.append(obj)
    return out


def _nearest_stocked_port(
    world: World, x: float, y: float
) -> GameObject | None:
    best: GameObject | None = None
    best_d = 1e30
    for port in _ports(world, active_only=True):
        if port.faction != FACTION_PLAYER or _ferry_count(port) <= 0:
            continue
        d = hypot(port.x - x, port.y - y)
        if d < best_d:
            best_d = d
            best = port
    return best


def _nearest_player_port(world: World, x: float, y: float) -> GameObject | None:
    best: GameObject | None = None
    best_d = 1e30
    for port in _ports(world, active_only=True):
        if port.faction != FACTION_PLAYER:
            continue
        d = hypot(port.x - x, port.y - y)
        if d < best_d:
            best_d = d
            best = port
    return best


def _nearest_idle_ferry(
    world: World, x: float, y: float, busy: set[str]
) -> DynamicObject | None:
    best: DynamicObject | None = None
    best_d = 1e30
    for obj in world.entities.items:
        if not isinstance(obj, DynamicObject):
            continue
        if obj.kind != "ferry" or not obj.active or obj.faction != FACTION_PLAYER:
            continue
        if obj.id in busy or obj.cargo_id or obj.stowed:
            continue
        d = hypot(obj.x - x, obj.y - y)
        if d < best_d:
            best_d = d
            best = obj
    return best


def _island_of(planner, x: float, y: float) -> int | None:
    hit = planner.land.islands.at(x, y)
    if hit is not None:
        return hit
    return planner.land.islands.nearest(x, y, SHORE_M)


def _dest_island(planner, dest: tuple[float, float]) -> tuple[int | None, tuple[float, float]]:
    island = planner.land.islands.at(*dest)
    if island is not None:
        return island, dest
    shore = planner.land.islands.nearest_shore(dest[0], dest[1], 400.0)
    if shore is None:
        return None, dest
    return shore[0], shore[1]


def _island_area(planner, island: int) -> float:
    return sum(feat.area_m2 for feat in planner.land.islands.features(island))


def _start_count(planner, island: int | None, rng: random.Random) -> int:
    if island is None:
        return rng.randint(3, 10)
    if _island_area(planner, island) >= MAIN_AREA_M2:
        return rng.randint(10, PORT_CAP)
    return rng.randint(3, 10)


def _nearest_port(world: World, planner, island: int, x: float, y: float) -> GameObject | None:
    best: GameObject | None = None
    best_d = 1e30
    for port in _ports(world, active_only=True):
        if port.faction != FACTION_PLAYER:
            continue
        if _island_of(planner, port.x, port.y) != island:
            continue
        d = hypot(port.x - x, port.y - y)
        if d < best_d:
            best_d = d
            best = port
    return best


def _dest_port(
    world: World, planner, island: int, x: float, y: float
) -> tuple[GameObject | None, bool]:
    ports = [
        port
        for port in _ports(world, active_only=True)
        if port.faction == FACTION_PLAYER
        and _island_of(planner, port.x, port.y) == island
    ]
    free = [port for port in ports if _ferry_count(port) < PORT_CAP]
    if free:
        free.sort(key=lambda p: hypot(p.x - x, p.y - y))
        return free[0], False
    return None, bool(ports)
