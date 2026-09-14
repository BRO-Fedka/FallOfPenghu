from __future__ import annotations

from typing import TYPE_CHECKING

from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER, GameObject
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind

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
    combat = obj.kind not in SHOT_KINDS and not is_static_kind(obj.kind)
    if world is not None and combat and obj.faction == FACTION_CHINA:
        world.kills[obj.kind] = world.kills.get(obj.kind, 0) + 1
    if world is not None and combat and obj.faction == FACTION_PLAYER:
        from fall_of_penghu.world.victory import check_china_victory

        check_china_victory(world)


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
    """Slow HP recovery for dynamic units at rest. Ammo and statics stay spent."""
    catalog = world.catalog
    now = world.clock.simulation_time
    dt = world.clock.dt_sim
    if dt <= 0.0:
        return
    idle = catalog.rest_idle_sim_s
    heal_span = max(1.0, catalog.heal_full_sim_s)
    for obj in world.entities.items:
        if not obj.active:
            continue
        if getattr(obj, "stowed", False):
            continue
        if is_static_kind(obj.kind):
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
