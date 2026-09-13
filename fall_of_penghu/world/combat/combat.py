from __future__ import annotations

import random
from math import atan2, cos, hypot, pi, sin, sqrt
from typing import TYPE_CHECKING

from fall_of_penghu.world.combat.doctrine import HOLD, accepts, is_battery
from fall_of_penghu.world.combat.health import apply_damage, restock, wreck
from fall_of_penghu.world.combat.priority import hit_chance_for, target_score
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import GameObject
from fall_of_penghu.world.entities.intercept import Intercept
from fall_of_penghu.world.entities.tracer import Tracer
from fall_of_penghu.world.entities.kinds import SHOT_KINDS
from fall_of_penghu.world.perception.catalog import DetectionCatalog

if TYPE_CHECKING:
    from fall_of_penghu.world.world import World


class Combat:
    """Guns fire on snapshot-visible targets inside engagement range."""

    def __init__(self, seed: int = 0) -> None:
        self._seq = 0
        self._rng = random.Random(int(seed) + 17)

    def step(self, world: World) -> None:
        from fall_of_penghu.profile import scope

        now = world.clock.simulation_time
        dt = world.clock.dt_sim
        if dt <= 0.0:
            return
        with scope("combat.projectiles"):
            missiles = [
                obj for obj in world.entities.items if isinstance(obj, Intercept)
            ]
            tracers = [obj for obj in world.entities.items if isinstance(obj, Tracer)]
            for shot in missiles:
                shot.steer(world.entities.get(shot.target_id), now, dt)
            for shot in tracers:
                if shot.fly(now, dt):
                    if shot.blast_m > 0.0:
                        shooter = world.entities.get(shot.shooter_id)
                        _splash(
                            world,
                            shot.x,
                            shot.y,
                            shot.blast_m,
                            shot.damage,
                            shot.faction,
                            shooter,
                            world.catalog,
                        )
                    elif shot.will_hit:
                        target = world.entities.get(shot.target_id)
                        if target is not None and target.active:
                            apply_damage(target, shot.damage, world)
        with scope("combat.kamikaze"):
            self._kamikaze(world)
        with scope("combat.restock"):
            restock(world)
        with scope("combat.engage"):
            factions = {obj.faction for obj in world.entities.items if is_battery(obj)}
            for faction in factions:
                self._engage(world, faction, now, missiles, tracers)
        for obj in list(world.entities.items):
            if obj.kind in SHOT_KINDS and not obj.active:
                world.entities.discard(obj.id)

    def _kamikaze(self, world: World) -> None:
        catalog = world.catalog
        damage = catalog.weapon_damage("drone")
        blast = catalog.blast_m("drone")
        for obj in list(world.entities.items):
            if not isinstance(obj, DynamicObject):
                continue
            if obj.kind != "drone" or not obj.active or not obj.armed:
                continue
            target = _blast_target(world, obj, blast, catalog)
            if target is not None:
                apply_damage(target, damage, world)
                wreck(obj, world)
                continue
            if obj.route is not None:
                continue
            wreck(obj, world)

    def _engage(
        self,
        world: World,
        faction: str,
        now: float,
        missiles: list[Intercept],
        tracers: list[Tracer],
    ) -> None:
        catalog = world.catalog
        visible = world.perception.visible_objects(faction)
        batteries = [
            obj
            for obj in visible
            if is_battery(obj) and obj.faction == faction and obj.active and not getattr(obj, "stowed", False)
        ]
        foes = [
            obj
            for obj in visible
            if obj.faction != faction and obj.active and obj.kind not in SHOT_KINDS and not getattr(obj, "stowed", False)
        ]
        in_flight: dict[str, int] = {}
        claimed: set[str] = set()
        for shot in missiles:
            if not shot.active or shot.faction != faction:
                continue
            in_flight[shot.shooter_id] = in_flight.get(shot.shooter_id, 0) + 1
            claimed.add(shot.target_id)
        for shot in tracers:
            if not shot.active or shot.faction != faction:
                continue
            in_flight[shot.shooter_id] = in_flight.get(shot.shooter_id, 0) + 1
        for battery in batteries:
            doctrine = getattr(battery, "doctrine", HOLD)
            reach = catalog.engagement_m(battery.kind)
            if reach is None:
                continue
            if not _weapon_ready(battery, catalog, now):
                continue
            if catalog.must_halt(battery.kind) and getattr(battery, "moving", False):
                continue
            if in_flight.get(battery.id, 0) >= catalog.max_in_flight(battery.kind):
                continue
            ammo = catalog.weapon_ammo(battery.kind)
            if ammo == "shell":
                if self._engage_artillery(
                    world, battery, foes, reach, doctrine, now, catalog
                ):
                    _spend_shot(battery, catalog, now)
                    in_flight[battery.id] = in_flight.get(battery.id, 0) + 1
                continue
            if doctrine == HOLD:
                continue
            reserve = ammo == "intercept"
            target = self._pick(
                battery, foes, reach, doctrine, claimed if reserve else set(), catalog
            )
            if target is None:
                continue
            self._spawn(world, battery, target, now, catalog)
            _spend_shot(battery, catalog, now)
            if reserve:
                claimed.add(target.id)
            in_flight[battery.id] = in_flight.get(battery.id, 0) + 1

    def _engage_artillery(
        self,
        world: World,
        battery: DynamicObject,
        foes: list[GameObject],
        reach: float,
        doctrine: str,
        now: float,
        catalog: DetectionCatalog,
    ) -> bool:
        aim = getattr(battery, "aim_xy", None)
        if doctrine == HOLD:
            return self._fire_aim(world, battery, aim, reach, now, catalog)
        focused = [
            foe
            for foe in foes
            if foe.id in (getattr(battery, "focus_ids", None) or ())
            and _eligible(battery, foe, reach, doctrine, catalog)
        ]
        if focused:
            target = _best(battery, focused, reach, catalog)
            if target is not None:
                self._spawn_shell(world, battery, target, now, catalog)
                return True
        auto = self._pick(battery, foes, reach, doctrine, set(), catalog)
        if auto is not None:
            self._spawn_shell(world, battery, auto, now, catalog)
            return True
        return self._fire_aim(world, battery, aim, reach, now, catalog)

    def _fire_aim(
        self,
        world: World,
        battery: DynamicObject,
        aim: tuple[float, float] | None,
        reach: float,
        now: float,
        catalog: DetectionCatalog,
    ) -> bool:
        if aim is None:
            return False
        dist = hypot(aim[0] - battery.x, aim[1] - battery.y)
        min_r = catalog.min_engagement_m(battery.kind)
        if dist < min_r or dist > reach:
            return False
        self._spawn_shell_at(world, battery, aim[0], aim[1], now, catalog)
        return True

    @staticmethod
    def _pick(
        battery: DynamicObject,
        foes: list[GameObject],
        reach: float,
        doctrine: str,
        claimed: set[str],
        catalog: DetectionCatalog,
    ) -> GameObject | None:
        focus = getattr(battery, "focus_ids", None) or frozenset()
        focused = [
            foe
            for foe in foes
            if foe.id in focus and foe.id not in claimed
            and _eligible(battery, foe, reach, doctrine, catalog)
        ]
        pool = focused if focused else [
            foe
            for foe in foes
            if foe.id not in claimed and _eligible(battery, foe, reach, doctrine, catalog)
        ]
        return _best(battery, pool, reach, catalog)

    def _spawn(
        self,
        world: World,
        battery: DynamicObject,
        target: GameObject,
        now: float,
        catalog: DetectionCatalog,
    ) -> None:
        ammo = catalog.weapon_ammo(battery.kind)
        if ammo == "shell":
            self._spawn_shell(world, battery, target, now, catalog)
            return
        if ammo in ("tracer", "small_arms", "cannon"):
            self._spawn_tracer(world, battery, target, now, catalog)
            return
        self._seq += 1
        dx = target.x - battery.x
        dy = target.y - battery.y
        world.entities.add(
            Intercept(
                id=f"ix_{self._seq}",
                faction=battery.faction,
                x=battery.x,
                y=battery.y,
                heading=atan2(dy, dx),
                speed_mps=catalog.intercept_speed_mps(),
                shooter_id=battery.id,
                target_id=target.id,
                kill_m=catalog.intercept_kill_m(),
                born_sim=now,
                life_sim_s=catalog.intercept_life_sim_s(),
                damage=catalog.weapon_damage(battery.kind),
            )
        )

    def _spawn_tracer(
        self,
        world: World,
        battery: DynamicObject,
        target: GameObject,
        now: float,
        catalog: DetectionCatalog,
    ) -> None:
        speed = catalog.ammo_speed_mps(battery.kind)
        aim_x, aim_y = _lead_point(battery, target, speed)
        dist = hypot(target.x - battery.x, target.y - battery.y)
        chance = hit_chance_for(battery.kind, dist, catalog)
        self._seq += 1
        world.entities.add(
            Tracer(
                id=f"tr_{self._seq}",
                faction=battery.faction,
                x=battery.x,
                y=battery.y,
                heading=atan2(aim_y - battery.y, aim_x - battery.x),
                speed_mps=speed,
                shooter_id=battery.id,
                target_id=target.id,
                aim_x=aim_x,
                aim_y=aim_y,
                will_hit=self._rng.random() < chance,
                damage=catalog.weapon_damage(battery.kind),
                born_sim=now,
                life_sim_s=catalog.ammo_life_sim_s(battery.kind),
            )
        )

    def _spawn_shell(
        self,
        world: World,
        battery: DynamicObject,
        target: GameObject,
        now: float,
        catalog: DetectionCatalog,
    ) -> None:
        mark_x, mark_y = _lead_point(battery, target, catalog.ammo_speed_mps(battery.kind))
        self._spawn_shell_at(world, battery, mark_x, mark_y, now, catalog, target_id=target.id)

    def _spawn_shell_at(
        self,
        world: World,
        battery: DynamicObject,
        mark_x: float,
        mark_y: float,
        now: float,
        catalog: DetectionCatalog,
        target_id: str = "",
    ) -> None:
        speed = catalog.ammo_speed_mps(battery.kind)
        life = catalog.ammo_life_sim_s(battery.kind)
        dist = hypot(mark_x - battery.x, mark_y - battery.y)
        scatter = catalog.scatter_m(battery.kind, dist)
        aim_x, aim_y = _scatter_point(self._rng, mark_x, mark_y, scatter)
        self._seq += 1
        world.entities.add(
            Tracer(
                id=f"sh_{self._seq}",
                faction=battery.faction,
                x=battery.x,
                y=battery.y,
                heading=atan2(aim_y - battery.y, aim_x - battery.x),
                speed_mps=speed,
                shooter_id=battery.id,
                target_id=target_id,
                aim_x=aim_x,
                aim_y=aim_y,
                will_hit=True,
                damage=catalog.weapon_damage(battery.kind),
                born_sim=now,
                life_sim_s=life,
                kind="shell",
                blast_m=catalog.blast_m(battery.kind),
                from_x=battery.x,
                from_y=battery.y,
                mark_x=mark_x,
                mark_y=mark_y,
                scatter_m=scatter,
            )
        )


def _weapon_ready(battery: DynamicObject, catalog: DetectionCatalog, now: float) -> bool:
    """Finish a magazine reload if due, then say whether a shot may leave now."""
    _finish_reload(battery, catalog, now)
    if now < float(getattr(battery, "weapon_ready_sim", 0.0) or 0.0):
        return False
    if getattr(battery, "reloading", False):
        return False
    if catalog.limited_ammo(battery.kind) and int(getattr(battery, "clip", 0) or 0) <= 0:
        return False
    return True


def _finish_reload(battery: DynamicObject, catalog: DetectionCatalog, now: float) -> None:
    if not catalog.limited_ammo(battery.kind):
        return
    if int(getattr(battery, "clip", 0) or 0) > 0:
        battery.reloading = False
        return
    reserve = int(getattr(battery, "reserve", 0) or 0)
    if reserve <= 0:
        battery.reloading = False
        return
    if not getattr(battery, "reloading", False):
        battery.reloading = True
        battery.weapon_ready_sim = now + catalog.reload_sim_s(battery.kind)
        return
    if now < float(getattr(battery, "weapon_ready_sim", 0.0) or 0.0):
        return
    take = min(catalog.clip_size(battery.kind), reserve)
    battery.reserve = reserve - take
    battery.clip = take
    battery.reloading = False


def _spend_shot(battery: DynamicObject, catalog: DetectionCatalog, now: float) -> None:
    if catalog.limited_ammo(battery.kind):
        battery.clip = max(0, int(getattr(battery, "clip", 0) or 0) - 1)
        if battery.clip <= 0 and int(getattr(battery, "reserve", 0) or 0) > 0:
            battery.reloading = True
            battery.weapon_ready_sim = now + catalog.reload_sim_s(battery.kind)
            return
    battery.weapon_ready_sim = now + catalog.cooldown_sim_s(battery.kind)


def _eligible(
    battery: DynamicObject,
    foe: GameObject,
    reach: float,
    doctrine: str,
    catalog: DetectionCatalog,
) -> bool:
    if foe.kind == "bridge":
        return False
    if not catalog.can_engage(battery.kind, foe):
        return False
    if not catalog.wants_target(battery, foe):
        return False
    if not accepts(doctrine, foe):
        return False
    d = hypot(foe.x - battery.x, foe.y - battery.y)
    min_r = catalog.min_engagement_m(battery.kind)
    return min_r <= d <= reach


def _best(
    battery: DynamicObject,
    foes: list[GameObject],
    reach: float,
    catalog: DetectionCatalog,
) -> GameObject | None:
    chosen: GameObject | None = None
    best = -1.0
    for foe in foes:
        dist = hypot(foe.x - battery.x, foe.y - battery.y)
        score = target_score(battery, foe, dist, reach, catalog)
        if chosen is None or score > best:
            best = score
            chosen = foe
    return chosen


def _scatter_point(
    rng: random.Random, x: float, y: float, radius: float
) -> tuple[float, float]:
    if radius <= 0.0:
        return (x, y)
    ang = rng.random() * 2.0 * pi
    r = radius * sqrt(rng.random())
    return (x + cos(ang) * r, y + sin(ang) * r)


def _lead_point(
    shooter: GameObject, target: GameObject, shot_speed: float
) -> tuple[float, float]:
    dx = target.x - shooter.x
    dy = target.y - shooter.y
    dist = hypot(dx, dy)
    vx = 0.0
    vy = 0.0
    if getattr(target, "moving", False):
        spd = float(getattr(target, "speed_mps", 0.0) or 0.0)
        heading = float(getattr(target, "heading", 0.0) or 0.0)
        vx = cos(heading) * spd
        vy = sin(heading) * spd
    speed = max(float(shot_speed), 1.0)
    t = dist / speed
    ax = target.x + vx * t
    ay = target.y + vy * t
    t = hypot(ax - shooter.x, ay - shooter.y) / speed
    return (target.x + vx * t, target.y + vy * t)


def _blast_target(
    world: World,
    drone: DynamicObject,
    blast_m: float,
    catalog: DetectionCatalog,
) -> GameObject | None:
    if blast_m <= 0.0:
        return None
    strike = world.entities.get(getattr(drone, "strike_id", "") or "")
    if (
        strike is not None
        and strike.active
        and strike.id != drone.id
        and strike.kind != "bridge"
        and hypot(strike.x - drone.x, strike.y - drone.y) <= blast_m
        and catalog.wants_target(drone, strike)
    ):
        return strike
    best: GameObject | None = None
    best_d = blast_m
    for obj in world.entities.items:
        if not obj.active or obj.id == drone.id or obj.faction == drone.faction:
            continue
        if obj.kind in SHOT_KINDS or obj.kind == "bridge":
            continue
        if not catalog.wants_target(drone, obj):
            continue
        d = hypot(obj.x - drone.x, obj.y - drone.y)
        if d <= best_d:
            best_d = d
            best = obj
    return best


def _splash(
    world: World,
    x: float,
    y: float,
    blast_m: float,
    damage: float,
    faction: str,
    shooter: GameObject | None,
    catalog: DetectionCatalog,
) -> None:
    if blast_m <= 0.0 or damage <= 0.0:
        return
    for obj in list(world.entities.items):
        if not obj.active or obj.faction == faction:
            continue
        if obj.kind in SHOT_KINDS:
            continue
        if hypot(obj.x - x, obj.y - y) <= blast_m:
            apply_damage(obj, damage, world)
