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
    if obj.hp > 0.0:
        return False
    wreck(obj, world)
    return True
