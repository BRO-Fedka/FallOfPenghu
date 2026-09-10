from __future__ import annotations

from math import atan2, hypot

from fall_of_penghu.world.entities.command import SetRoute
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER
from fall_of_penghu.world.world import World

# 50 km west of the northwest corner of bbox_penghu. Fujian is not in the map pack.
CHINA_PORT_WEST_M = 50_000.0
STANDOFF_M = 20_000.0
CARRIER_ID = "c_carrier_1"
CARRIER_MAGAZINE = 30
LANDING_MAGAZINE = 20
LAUNCH_SIM_S = 40.0
LANDING_LAUNCH_S = 40.0
ASSAULT_UNLOAD_SIM = 40.0
RELOAD_DOCK_SIM = 300.0
SCOUT_LAUNCH_S = 120.0
SHIP_SPAWN_SIM = 900.0
ARRIVE_M = 400.0
SLOT_SPACING_M = 7_000.0
CARGO_KINDS = ("infantry", "artillery", "tank")
STRIKE_FIRST = (
    "aaw",
    "aa_pickup",
    "truck",
    "ship",
    "ferry",
    "landing_ship",
    "infantry",
    "artillery",
    "tank",
    "port",
    "airfield",
    "bridge",
)


def china_port_xy(world: World) -> tuple[float, float]:
    bbox = world.map.manifest.get("bbox_penghu") or [-22000.0, -32000.0, 21000.0, 35000.0]
    return (float(bbox[0]) - CHINA_PORT_WEST_M, float(bbox[3]))


def standoff_xy(world: World) -> tuple[float, float]:
    bbox = world.map.manifest.get("bbox_penghu") or [-22000.0, -32000.0, 21000.0, 35000.0]
    return (float(bbox[0]) - STANDOFF_M, (float(bbox[1]) + float(bbox[3])) * 0.5)


def standoff_slot(world: World, index: int) -> tuple[float, float]:
    x, y = standoff_xy(world)
    n = (index + 1) // 2
    sign = 1.0 if index % 2 else -1.0
    return (x, y + sign * n * SLOT_SPACING_M)


class ChinaDirector:
    """PLA arrives from the sea. No enemy units start on the archipelago."""

    def __init__(self, world: World) -> None:
        self._port = china_port_xy(world)
        self._station = standoff_xy(world)
        self._drone_n = 0
        self._scout_n = 0
        self._scout_ready_sim = 0.0
        self._ship_seq = 0
        self._next_ship_sim = 0.0
        self._ferry_n = 0
        self._cargo_n = 0

    def step(self, world: World) -> None:
        self._ensure_carrier(world)
        self._spawn_landing_ships(world)
        carrier = world.entities.get(CARRIER_ID)
        if isinstance(carrier, DynamicObject) and carrier.active:
            self._step_scouts(world, carrier)
            self._step_carrier(world, carrier)
        for ship in self._landing_ships(world):
            self._step_landing_ship(world, ship)

    def _ensure_carrier(self, world: World) -> DynamicObject | None:
        obj = world.entities.get(CARRIER_ID)
        if isinstance(obj, DynamicObject):
            return obj
        if CARRIER_ID in world.entities.forgotten_ids:
            return None
        x, y = self._station
        carrier = DynamicObject(
            id=CARRIER_ID,
            faction=FACTION_CHINA,
            kind="drone_carrier",
            name="PLA drone carrier",
            x=x,
            y=y,
            heading=0.0,
            speed_mps=world.catalog.speed_mps("drone_carrier"),
            mobility="sea",
        )
        carrier.magazine = CARRIER_MAGAZINE
        carrier.task = "station"
        world.entities.add(carrier)
        return carrier

    def _spawn_landing_ships(self, world: World) -> None:
        now = world.clock.simulation_time
        if self._ship_seq > 0 and now < self._next_ship_sim:
            return
        self._ship_seq += 1
        self._next_ship_sim = now + SHIP_SPAWN_SIM
        oid = f"c_landing_{self._ship_seq}"
        if world.entities.get(oid) is not None or oid in world.entities.forgotten_ids:
            return
        at_station = self._ship_seq == 1
        xy = standoff_slot(world, self._ship_seq) if at_station else self._dock_xy(world)
        ship = DynamicObject(
            id=oid,
            faction=FACTION_CHINA,
            kind="landing_ship",
            name=f"PLA landing ship {self._ship_seq}",
            x=xy[0],
            y=xy[1],
            heading=0.0,
            speed_mps=world.catalog.speed_mps("landing_ship"),
            mobility="sea",
        )
        ship.magazine = LANDING_MAGAZINE
        ship.task = "station" if at_station else "to_station"
        world.entities.add(ship)
        if not at_station:
            self._sail(world, ship, standoff_slot(world, self._ship_seq))

    def _step_carrier(self, world: World, carrier: DynamicObject) -> None:
        if self._reload_cycle(world, carrier, CARRIER_MAGAZINE, self._station):
            return
        now = world.clock.simulation_time
        if now < float(carrier.weapon_ready_sim or 0.0):
            return
        target = self._pick_strike(world)
        if target is None:
            return
        if not self._launch_drone(world, carrier, target):
            return
        carrier.magazine -= 1
        carrier.weapon_ready_sim = now + LAUNCH_SIM_S

    def _step_scouts(self, world: World, carrier: DynamicObject) -> None:
        now = world.clock.simulation_time
        if now < self._scout_ready_sim:
            return
        if not self._launch_scout(world, carrier):
            return
        self._scout_ready_sim = now + SCOUT_LAUNCH_S

    def _launch_scout(self, world: World, carrier: DynamicObject) -> bool:
        hover = _scout_hover(world, self._scout_n + 1)
        self._scout_n += 1
        oid = f"c_scout_{self._scout_n:03d}"
        scout = DynamicObject(
            id=oid,
            faction=FACTION_CHINA,
            kind="scout",
            name=f"PLA scout {self._scout_n}",
            x=carrier.x,
            y=carrier.y,
            heading=atan2(hover[1] - carrier.y, hover[0] - carrier.x),
            speed_mps=world.catalog.speed_mps("scout"),
            mobility="air",
        )
        world.entities.add(scout)
        world.entities.dispatch(
            SetRoute(object_id=oid, mode="auto", target=hover),
            as_faction=FACTION_CHINA,
        )
        if scout.route is None:
            world.entities.discard(oid)
            self._scout_n -= 1
            return False
        return True

    def _step_landing_ship(self, world: World, ship: DynamicObject) -> None:
        station = standoff_slot(world, self._slot_index(ship))
        if ship.magazine <= 0:
            if self._boats_out(world, ship.id) > 0:
                return
            self._reload_cycle(world, ship, LANDING_MAGAZINE, station)
            return
        if self._reload_cycle(world, ship, LANDING_MAGAZINE, station):
            return
        now = world.clock.simulation_time
        if now < float(ship.weapon_ready_sim or 0.0):
            return
        beach = self._pick_beach(world, ship)
        if beach is None:
            return
        if not self._launch_landing(world, ship, beach):
            return
        ship.magazine -= 1
        ship.weapon_ready_sim = now + LANDING_LAUNCH_S

    def _reload_cycle(
        self,
        world: World,
        ship: DynamicObject,
        mag_full: int,
        station: tuple[float, float],
    ) -> bool:
        now = world.clock.simulation_time
        dock = self._dock_xy(world)
        task = ship.task or "station"
        if ship.magazine > 0 and task not in ("port", "reload", "to_station"):
            return False
        if task == "reload":
            if now < float(ship.weapon_ready_sim or 0.0):
                return True
            ship.magazine = mag_full
            ship.task = "to_station"
            self._sail(world, ship, station)
            return True
        if task == "to_station":
            if _at_xy(ship, station, ARRIVE_M):
                ship.task = "station"
                ship.route = None
                return False
            if ship.route is None:
                self._sail(world, ship, station)
            return True
        if _at_xy(ship, dock, ARRIVE_M):
            ship.route = None
            ship.task = "reload"
            ship.weapon_ready_sim = now + RELOAD_DOCK_SIM
            return True
        ship.task = "port"
        if ship.route is None:
            self._sail(world, ship, dock)
        return True

    def _launch_drone(self, world: World, carrier: DynamicObject, target) -> bool:
        self._drone_n += 1
        oid = f"c_kamikaze_{self._drone_n:03d}"
        drone = DynamicObject(
            id=oid,
            faction=FACTION_CHINA,
            kind="drone",
            name=f"PLA UAV {self._drone_n}",
            x=carrier.x,
            y=carrier.y,
            heading=atan2(target.y - carrier.y, target.x - carrier.x),
            speed_mps=world.catalog.speed_mps("drone"),
            mobility="air",
        )
        drone.strike_id = target.id
        world.entities.add(drone)
        world.entities.dispatch(
            SetRoute(object_id=oid, mode="auto", target=(target.x, target.y)),
            as_faction=FACTION_CHINA,
        )
        if drone.route is None:
            world.entities.discard(oid)
            return False
        return True

    def _launch_landing(
        self,
        world: World,
        ship: DynamicObject,
        beach: tuple[float, float],
    ) -> bool:
        kind = CARGO_KINDS[self._cargo_n % len(CARGO_KINDS)]
        self._cargo_n += 1
        self._ferry_n += 1
        cargo_id = f"c_{kind}_{self._cargo_n:03d}"
        ferry_id = f"c_ferry_{self._ferry_n:03d}"
        cargo = DynamicObject(
            id=cargo_id,
            faction=FACTION_CHINA,
            kind=kind,
            name=f"PLA {kind} {self._cargo_n}",
            x=ship.x,
            y=ship.y,
            heading=ship.heading,
            speed_mps=world.catalog.speed_mps(kind),
            mobility="land",
        )
        ferry = DynamicObject(
            id=ferry_id,
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
        cargo.stowed = True
        ferry.cargo_id = cargo.id
        world.entities.add(cargo)
        world.entities.add(ferry)
        if not world.transport.assault_beach(
            ferry,
            beach,
            home_id=ship.id,
            unload_sim=ASSAULT_UNLOAD_SIM,
        ):
            world.entities.discard(ferry_id)
            world.entities.discard(cargo_id)
            return False
        return True

    def _pick_strike(self, world: World):
        visible = [
            obj
            for obj in world.perception.visible_objects(FACTION_CHINA)
            if obj.faction == FACTION_PLAYER
            and obj.active
            and obj.kind not in ("intercept", "tracer", "shell")
            and world.catalog.can_engage("drone", obj)
        ]
        if not visible:
            return None
        rank = {kind: i for i, kind in enumerate(STRIKE_FIRST)}
        visible.sort(key=lambda obj: (rank.get(obj.kind, 50), obj.id))
        return visible[0]

    def _pick_beach(
        self, world: World, ship: DynamicObject
    ) -> tuple[float, float] | None:
        planner = world.entities.planner
        if planner is None:
            return None
        bbox = world.map.manifest.get("bbox_penghu") or [
            -22000.0,
            -32000.0,
            21000.0,
            35000.0,
        ]
        aim = (float(bbox[0]) + 1500.0, ship.y)
        island = planner.land.islands.nearest(aim[0], aim[1], 80_000.0)
        if island is None:
            mid = (
                (float(bbox[0]) + float(bbox[2])) * 0.5,
                (float(bbox[1]) + float(bbox[3])) * 0.5,
            )
            island = planner.land.islands.nearest(mid[0], mid[1], 80_000.0)
        if island is None:
            return None
        samples = planner.land.islands.coast_samples(island)
        if samples:
            west = min(pt[0] for pt in samples)
            band = [pt for pt in samples if pt[0] <= west + 4000.0]
            if not band:
                band = samples
            jitter = ((self._cargo_n % 7) - 3) * 350.0
            y_aim = ship.y + jitter
            return min(band, key=lambda pt: abs(pt[1] - y_aim))
        coast = planner.land.islands.coast_point(
            aim[0], aim[1], island=island, max_m=80_000.0
        )
        if coast is None:
            return None
        return coast[1]

    def _landing_ships(self, world: World) -> list[DynamicObject]:
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

    def _boats_out(self, world: World, ship_id: str) -> int:
        n = 0
        for obj in world.entities.items:
            if (
                isinstance(obj, DynamicObject)
                and obj.active
                and obj.kind == "ferry"
                and obj.home_port_id == ship_id
            ):
                n += 1
        return n

    def _slot_index(self, ship: DynamicObject) -> int:
        try:
            return int(ship.id.rsplit("_", 1)[-1])
        except ValueError:
            return 1

    def _dock_xy(self, world: World) -> tuple[float, float]:
        planner = world.entities.planner
        if planner is None:
            return self._port
        water = planner.nearest_water(self._port[0], self._port[1])
        return water if water is not None else self._port

    def _sail(
        self, world: World, ship: DynamicObject, xy: tuple[float, float]
    ) -> None:
        world.entities.dispatch(
            SetRoute(object_id=ship.id, mode="auto", target=xy),
            as_faction=FACTION_CHINA,
        )


def _at_xy(obj: DynamicObject, xy: tuple[float, float], rad: float) -> bool:
    if hypot(obj.x - xy[0], obj.y - xy[1]) <= rad:
        obj.route = None
        return True
    return False


def _scout_hover(world: World, index: int) -> tuple[float, float]:
    bbox = world.map.manifest.get("bbox_penghu") or [-22000.0, -32000.0, 21000.0, 35000.0]
    cx = (float(bbox[0]) + float(bbox[2])) * 0.5
    cy = (float(bbox[1]) + float(bbox[3])) * 0.5
    n = (index + 1) // 2
    sign = 1.0 if index % 2 else -1.0
    return (cx - 2500.0, cy + sign * n * 4500.0)
