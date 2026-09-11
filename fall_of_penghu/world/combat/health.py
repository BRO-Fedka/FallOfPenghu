from __future__ import annotations

from typing import TYPE_CHECKING

from fall_of_penghu.world.entities.game_object import GameObject

if TYPE_CHECKING:
    from fall_of_penghu.world.world import World


def wreck(obj: GameObject, world: World | None = None) -> None:
    """Mark destroyed. Statics stay in the world; a sunk ferry wrecks cargo."""
    if not obj.active and float(getattr(obj, "hp", 0.0) or 0.0) <= 0.0:
        return
    obj.active = False
    obj.hp = 0.0
    if getattr(obj, "route", None) is not None:
        obj.route = None
    cargo_id = getattr(obj, "cargo_id", None)
    if cargo_id and world is not None:
        cargo = world.entities.get(cargo_id)
        if cargo is not None:
            wreck(cargo, world)


def apply_damage(obj: GameObject, amount: float, world: World | None = None) -> bool:
    """Subtract HP. Returns True if the object was wrecked by this hit."""
    if not obj.active or amount <= 0.0:
        return False
    hp = float(getattr(obj, "hp", 0.0) or 0.0)
    obj.hp = max(0.0, hp - float(amount))
    if world is not None:
        obj.last_hurt_sim = world.clock.simulation_time
    if obj.hp > 0.0:
        return False
    wreck(obj, world)
    return True


def restock(world: World) -> None:
    """Slow full recovery of HP and limited ammo after a long idle."""
    catalog = world.catalog
    now = world.clock.simulation_time
    dt = world.clock.dt_sim
    if dt <= 0.0:
        return
    idle = catalog.rest_idle_sim_s
    heal_span = max(1.0, catalog.heal_full_sim_s)
    ammo_span = max(1.0, catalog.ammo_full_sim_s)
    for obj in world.entities.items:
        if not obj.active:
            continue
        if getattr(obj, "stowed", False):
            continue
        if getattr(obj, "moving", False):
            obj.last_moved_sim = now
            continue
        last_hurt = float(getattr(obj, "last_hurt_sim", 0.0) or 0.0)
        last_moved = float(getattr(obj, "last_moved_sim", 0.0) or 0.0)
        if now - last_hurt < idle or now - last_moved < idle:
            continue
        cap = float(getattr(obj, "max_hp", 0.0) or 0.0)
        hp = float(getattr(obj, "hp", 0.0) or 0.0)
        if cap > 1.5 and hp < cap:
            obj.hp = min(cap, hp + cap * dt / heal_span)
        if not catalog.limited_ammo(obj.kind):
            continue
        clip_max = catalog.clip_size(obj.kind)
        res_max = catalog.reserve_size(obj.kind)
        stock = clip_max + res_max
        if stock <= 0:
            continue
        clip = int(getattr(obj, "clip", 0) or 0)
        reserve = int(getattr(obj, "reserve", 0) or 0)
        if clip >= clip_max and reserve >= res_max:
            obj.rest_ammo_acc = 0.0
            continue
        acc = float(getattr(obj, "rest_ammo_acc", 0.0) or 0.0)
        acc += stock * dt / ammo_span
        while acc >= 1.0 and (clip < clip_max or reserve < res_max):
            acc -= 1.0
            if clip < clip_max:
                clip += 1
            else:
                reserve += 1
        obj.clip = clip
        obj.reserve = reserve
        obj.rest_ammo_acc = acc
        if clip > 0:
            obj.reloading = False
