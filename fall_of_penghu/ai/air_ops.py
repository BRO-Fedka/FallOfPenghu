from __future__ import annotations

from math import atan2, cos, hypot, pi, sin
from random import Random
from typing import TYPE_CHECKING

from fall_of_penghu.profile import slice_round_robin
from fall_of_penghu.ai.china_util import (
    CARRIER_MAGAZINE,
    LAUNCH_SIM_S,
    approach_axis,
    border_xy,
    carrier_cap,
    leave_off_map,
    sail,
    standoff_xy,
)
from fall_of_penghu.world.entities.command import SetRoute
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind

if TYPE_CHECKING:
    from fall_of_penghu.ai.intel import IntelOps
    from fall_of_penghu.ai.log import DecisionLog
    from fall_of_penghu.world.world import World

STRIKE_FIRST = (
    "aaw",
    "aa_pickup",
    "artillery",
    "tank",
    "infantry",
    "truck",
    "ferry",
    "ship",
    "landing_ship",
    "scout",
    "drone",
)
MAX_PER_TARGET = 5
VOLLEY = 8
CLOUD_SPAWN_M = 1400.0
CLOUD_PATH_M = 3200.0
TRACK_DRIFT_M = 90.0
AA_HOT = 0.75
TERMINAL_M = 700.0


class AirOps:
    """Kamikaze swarm. Does not own scouts."""

    def __init__(self, log: DecisionLog, seed: int = 0) -> None:
        self.log = log
        self._rng = Random(seed + 19)
        self._drone_n = 0
        self._carrier_n = 0
        self._drone_i = 0

    def ensure_carrier(self, world: World) -> DynamicObject | None:
        hulls = _carriers(world)
        if hulls:
            return hulls[0]
        return self._spawn_carrier(world, 1)

    def _ensure_carriers(self, world: World) -> None:
        alive = _carriers(world)
        cap = carrier_cap(world)
        spawned = 0
        while len(alive) < cap and spawned < 2:
            nxt = max((_slot_from_id(obj.id, 0) for obj in alive), default=0) + 1
            hull = self._spawn_carrier(world, nxt)
            if hull is None:
                break
            alive.append(hull)
            spawned += 1

    def _spawn_carrier(self, world: World, slot: int) -> DynamicObject | None:
        self._carrier_n = max(self._carrier_n + 1, slot)
        oid = f"c_carrier_{self._carrier_n}"
        if world.entities.get(oid) is not None or oid in world.entities.forgotten_ids:
            return None
        axis = approach_axis(world, self._carrier_n)
        x, y = border_xy(world, self._carrier_n * 2, axis)
        station = standoff_xy(world, axis)
        carrier = DynamicObject(
            id=oid,
            faction=FACTION_CHINA,
            kind="drone_carrier",
            name=f"PLA drone carrier {self._carrier_n}",
            x=x,
            y=y,
            heading=atan2(station[1] - y, station[0] - x),
            speed_mps=world.catalog.speed_mps("drone_carrier"),
            mobility="sea",
        )
        carrier.magazine = CARRIER_MAGAZINE
        carrier.task = "to_station"
        world.entities.add(carrier)
        sail(world, carrier, station)
        self.log.emit(
            world.clock.simulation_time,
            "spawn",
            f"{oid} {axis} border {x:.0f},{y:.0f}",
        )
        return carrier

    def step(self, world: World, intel: IntelOps) -> None:
        from fall_of_penghu.profile import scope

        with scope("air.carriers"):
            self._ensure_carriers(world)
        now = world.clock.simulation_time
        drones = [
            obj
            for obj in world.entities.items
            if isinstance(obj, DynamicObject)
            and obj.active
            and obj.faction == FACTION_CHINA
            and obj.kind == "drone"
        ]
        load = _load_by_target(drones)
        with scope("air.steer"):
            self._drone_i = slice_round_robin(
                drones,
                self._drone_i,
                lambda drone: self._steer(world, drone, intel, now, load),
            )
        with scope("air.launch"):
            self._step_carriers(world, intel, now, load)

    def _step_carriers(self, world: World, intel: IntelOps, now: float, load) -> None:
        for carrier in list(_carriers(world)):
            n = _slot_from_id(carrier.id, 1)
            axis = approach_axis(world, n)
            station = standoff_xy(world, axis)
            slot = n * 2
            if carrier.magazine <= 0:
                if (carrier.task or "") != "leave":
                    carrier.task = "leave"
                    self.log.emit(now, "empty", f"{carrier.id} magazine empty")
                leave_off_map(world, carrier, station, self.log, slot, axis)
                continue
            if leave_off_map(world, carrier, station, self.log, slot, axis):
                continue
            if now < float(carrier.weapon_ready_sim or 0.0):
                continue
            launched = 0
            while launched < VOLLEY and carrier.magazine > 0:
                target = self._pick_target(world, intel, load, (carrier.x, carrier.y))
                if target is None:
                    if launched == 0 and now >= float(
                        getattr(self, "_no_tgt_log", 0.0) or 0.0
                    ):
                        self.log.emit(now, "no-target", f"{carrier.id} hold launch")
                        self._no_tgt_log = now + 30.0
                    break
                if not self._launch_one(world, carrier, target, intel, load):
                    break
                carrier.magazine -= 1
                launched += 1
            if launched:
                carrier.weapon_ready_sim = now + LAUNCH_SIM_S
                self.log.emit(
                    now,
                    "volley",
                    f"{carrier.id} launched {launched} mag={carrier.magazine}",
                )

    def _steer(
        self,
        world: World,
        drone: DynamicObject,
        intel: IntelOps,
        now: float,
        load: dict[str, int],
    ) -> None:
        assigned = _live_assigned(world, drone)
        seen = _visible_prey(world, drone, load)
        if seen is not None and _better_strike(drone, seen, assigned):
            old = drone.strike_id
            _bind(drone, seen, now)
            load[seen.id] = load.get(seen.id, 0) + 1
            if old:
                load[old] = max(0, load.get(old, 1) - 1)
            _fly(world, drone, (seen.x, seen.y))
            self.log.emit(
                now,
                "retarget",
                f"{drone.id} sees {seen.kind}:{seen.id} "
                f"d={hypot(drone.x - seen.x, drone.y - seen.y):.0f}",
            )
            return
        if assigned is not None:
            dest = (assigned.x, assigned.y)
            drone.strike_xy = dest
            if hypot(drone.x - dest[0], drone.y - dest[1]) <= 40.0:
                return
            if _aim_drift(drone, dest) > TRACK_DRIFT_M or drone.route is None:
                _fly(world, drone, dest)
                drone._aimed = dest
            return
        remaining = drone.route.remaining_length() if drone.route is not None else 0.0
        if remaining > 60.0:
            return
        nxt = self._pick_target(world, intel, load, (drone.x, drone.y))
        if nxt is None:
            return
        old = drone.strike_id
        tid = str(getattr(nxt, "id", "") or getattr(nxt, "source_id", ""))
        _bind(drone, nxt, now)
        load[tid] = load.get(tid, 0) + 1
        if old:
            load[old] = max(0, load.get(old, 1) - 1)
        dest = (nxt.x, nxt.y)
        _swarm_fly(world, drone, dest, self._rng, intel)
        self.log.emit(
            now,
            "retarget",
            f"{drone.id} switch {getattr(nxt, 'kind', '?')}:{tid}",
        )

    def _pick_target(
        self,
        world: World,
        intel: IntelOps,
        load: dict[str, int],
        origin: tuple[float, float],
    ):
        live = _strike_live(world)
        pick = _nearest_rank(live, origin, load)
        if pick is not None:
            return pick
        mark = _strike_imprint(world, load)
        if mark is not None:
            return mark
        static = _nearest_static(world, intel)
        if static is None or load.get(static.id, 0) >= MAX_PER_TARGET:
            return None
        return static

    def _launch_one(
        self,
        world: World,
        carrier: DynamicObject,
        target,
        intel: IntelOps,
        load: dict[str, int],
    ) -> bool:
        self._drone_n += 1
        oid = f"c_kamikaze_{self._drone_n:03d}"
        tx, ty = target.x, target.y
        jx, jy = _disk(self._rng, CLOUD_SPAWN_M)
        sx, sy = carrier.x + jx, carrier.y + jy
        drone = DynamicObject(
            id=oid,
            faction=FACTION_CHINA,
            kind="drone",
            name=f"PLA UAV {self._drone_n}",
            x=sx,
            y=sy,
            heading=atan2(ty - sy, tx - sx),
            speed_mps=world.catalog.speed_mps("drone"),
            mobility="air",
        )
        drone.armed = True
        _bind(drone, target, world.clock.simulation_time)
        if intel.assault is not None and _on_island(world, target, intel.assault.island):
            drone.task = "support"
        elif intel.assault is None:
            drone.task = "suppress"
        else:
            drone.task = "hunt"
        world.entities.add(drone)
        dest = (tx, ty)
        _swarm_fly(world, drone, dest, self._rng, intel)
        if drone.route is None:
            world.entities.discard(oid)
            self._drone_n -= 1
            return False
        tid = getattr(target, "id", None) or getattr(target, "source_id", "")
        load[str(tid)] = load.get(str(tid), 0) + 1
        self.log.emit(
            world.clock.simulation_time,
            "launch",
            f"{oid} {drone.task} -> {getattr(target, 'kind', '?')}:{tid} "
            f"from {sx:.0f},{sy:.0f} mag={carrier.magazine - 1}",
        )
        return True


def _bind(drone: DynamicObject, target, now: float) -> None:
    drone.strike_id = getattr(target, "id", None) or getattr(target, "source_id", None)
    drone.strike_kind = getattr(target, "kind", "")
    drone.strike_xy = (target.x, target.y)
    drone.task_sim = now
    drone._aimed = (target.x, target.y)


def _fly(world: World, drone: DynamicObject, xy: tuple[float, float]) -> None:
    world.entities.dispatch(
        SetRoute(object_id=drone.id, mode="auto", target=xy),
        as_faction=FACTION_CHINA,
    )


def _swarm_fly(
    world: World,
    drone: DynamicObject,
    dest: tuple[float, float],
    rng: Random,
    intel: IntelOps,
) -> None:
    start = (drone.x, drone.y)
    if hypot(dest[0] - start[0], dest[1] - start[1]) <= TERMINAL_M:
        _fly(world, drone, dest)
        return
    verts = _swarm_points(rng, start, dest, intel)
    world.entities.dispatch(
        SetRoute(object_id=drone.id, mode="manual", vertices=verts),
        as_faction=FACTION_CHINA,
    )
    if drone.route is None:
        _fly(world, drone, dest)


def _aa_at(intel: IntelOps, x: float, y: float) -> float:
    sample = intel.sample(x, y)
    return 0.0 if sample is None else sample[2]


def _swarm_points(
    rng: Random,
    start: tuple[float, float],
    dest: tuple[float, float],
    intel: IntelOps,
) -> tuple[tuple[float, float], ...]:
    sx, sy = start
    tx, ty = dest
    dx, dy = tx - sx, ty - sy
    dist = hypot(dx, dy) or 1.0
    px, py = -dy / dist, dx / dist
    t = 0.28 + rng.random() * 0.4
    off = (rng.random() * 2.0 - 1.0) * CLOUD_PATH_M
    mid = (sx + dx * t + px * off, sy + dy * t + py * off)
    side = 1.0 if rng.random() < 0.5 else -1.0
    via = None
    hot = max(_aa_at(intel, tx, ty), _aa_at(intel, mid[0], mid[1]))
    if hot >= AA_HOT:
        best = hot
        for dist_off in (1800.0, 3200.0, 4800.0):
            cand = (tx + px * side * dist_off, ty + py * side * dist_off)
            score = _aa_at(intel, cand[0], cand[1])
            if score < best:
                best = score
                via = cand
    if via is not None:
        return (mid, via, dest)
    return (mid, dest)


def _disk(rng: Random, radius: float) -> tuple[float, float]:
    ang = rng.random() * 2.0 * pi
    r = (rng.random() ** 0.5) * radius
    return (r * cos(ang), r * sin(ang))


def _aim_drift(drone: DynamicObject, dest: tuple[float, float]) -> float:
    old = getattr(drone, "_aimed", None)
    if old is None:
        return 1e9
    return hypot(old[0] - dest[0], old[1] - dest[1])


def _load_by_target(drones: list[DynamicObject]) -> dict[str, int]:
    load: dict[str, int] = {}
    for drone in drones:
        sid = drone.strike_id
        if sid:
            load[sid] = load.get(sid, 0) + 1
    return load


def _live_assigned(world: World, drone: DynamicObject):
    sid = drone.strike_id
    if not sid:
        return None
    obj = world.entities.get(sid)
    if obj is None or not obj.active or obj.faction == FACTION_CHINA:
        return None
    if getattr(obj, "stowed", False) or obj.kind in SHOT_KINDS:
        return None
    if obj.kind == "bridge":
        return None
    ids = {item.id for item in world.perception.visible_objects(FACTION_CHINA)}
    if obj.id not in ids:
        return None
    if not world.catalog.can_engage("drone", obj):
        return None
    return obj


def _carriers(world: World) -> list[DynamicObject]:
    out: list[DynamicObject] = []
    for obj in world.entities.items:
        if (
            isinstance(obj, DynamicObject)
            and obj.active
            and obj.faction == FACTION_CHINA
            and obj.kind == "drone_carrier"
        ):
            out.append(obj)
    return out


def _slot_from_id(oid: str, default: int) -> int:
    try:
        return int(oid.rsplit("_", 1)[-1])
    except ValueError:
        return default


def _strike_rank(obj) -> int:
    if is_static_kind(getattr(obj, "kind", "")):
        return 100
    rank = {kind: i for i, kind in enumerate(STRIKE_FIRST)}
    return rank.get(obj.kind, 50)


def _nearest_rank(cands, origin: tuple[float, float], load: dict[str, int]):
    best = None
    best_key = None
    ox, oy = origin
    for obj in cands:
        oid = getattr(obj, "id", None) or getattr(obj, "source_id", "")
        if load.get(str(oid), 0) >= MAX_PER_TARGET:
            continue
        key = (_strike_rank(obj), hypot(obj.x - ox, obj.y - oy))
        if best_key is None or key < best_key:
            best = obj
            best_key = key
    return best


def _better_strike(drone: DynamicObject, seen, assigned) -> bool:
    if assigned is None:
        return True
    seen_r = _strike_rank(seen)
    hold_r = _strike_rank(assigned)
    if seen_r < hold_r:
        return True
    if seen_r > hold_r:
        return False
    closer = hypot(drone.x - seen.x, drone.y - seen.y) + 400.0
    return closer < hypot(drone.x - assigned.x, drone.y - assigned.y)


def _strike_live(world: World) -> list:
    return [
        obj
        for obj in world.perception.visible_objects(FACTION_CHINA)
        if obj.faction == FACTION_PLAYER
        and obj.active
        and obj.kind not in SHOT_KINDS
        and obj.kind != "bridge"
        and not is_static_kind(obj.kind)
        and world.catalog.can_engage("drone", obj)
        and not getattr(obj, "stowed", False)
    ]


def _strike_imprint(world: World, load: dict[str, int]):
    now = world.clock.simulation_time
    best = None
    best_key = None
    rank = {kind: i for i, kind in enumerate(STRIKE_FIRST)}
    for mark in world.perception.imprints(FACTION_CHINA):
        if mark.faction != FACTION_PLAYER or not mark.active:
            continue
        if is_static_kind(mark.kind) or mark.kind in SHOT_KINDS:
            continue
        if mark.dead(now):
            continue
        if load.get(mark.source_id, 0) >= MAX_PER_TARGET:
            continue
        key = (rank.get(mark.kind, 50), mark.age(now))
        if best_key is None or key < best_key:
            best = mark
            best_key = key
    return best


def _visible_prey(world: World, drone: DynamicObject, load: dict[str, int]):
    catalog = world.catalog
    pool = []
    for obj in world.perception.visible_objects(FACTION_CHINA):
        if obj.faction != FACTION_PLAYER or not obj.active:
            continue
        if not catalog.can_engage("drone", obj):
            continue
        if getattr(obj, "stowed", False) or obj.kind in SHOT_KINDS:
            continue
        if obj.kind == "bridge":
            continue
        radius = catalog.scaled_range_m(
            "visual_primitive",
            obj.kind,
            world.clock.darkness,
            emitter_kind="drone",
        )
        if radius is None or radius <= 0.0:
            continue
        d = hypot(obj.x - drone.x, obj.y - drone.y)
        if d > radius:
            continue
        pool.append(obj)
    combat = [obj for obj in pool if not is_static_kind(obj.kind)]
    return _nearest_rank(combat or pool, (drone.x, drone.y), load)


def _nearest_static(world: World, intel: IntelOps):
    island = intel.assault.island if intel.assault is not None else None
    planner = world.entities.planner
    best = None
    best_d = 1e30
    origin = intel.assault
    ox = origin.x if origin is not None else 0.0
    oy = origin.y if origin is not None else 0.0
    for obj in world.entities.items:
        if not obj.active or obj.faction == FACTION_CHINA:
            continue
        if not is_static_kind(obj.kind) or obj.kind == "bridge":
            continue
        if island is not None and planner is not None:
            if planner.land.islands.at(obj.x, obj.y) != island:
                continue
        d = hypot(obj.x - ox, obj.y - oy)
        if d < best_d:
            best = obj
            best_d = d
    return best


def _on_island(world: World, obj, island: int) -> bool:
    planner = world.entities.planner
    if planner is None:
        return False
    hit = planner.land.islands.at(obj.x, obj.y)
    if hit is None:
        hit = planner.land.islands.nearest(obj.x, obj.y, 800.0)
    return hit == island
