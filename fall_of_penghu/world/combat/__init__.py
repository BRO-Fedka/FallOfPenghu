from fall_of_penghu.world.combat.combat import Combat
from fall_of_penghu.world.combat.doctrine import (
    AIR_ONLY,
    DOCTRINES,
    FIRE,
    GUN_DOCTRINES,
    HOLD,
    LABELS,
    MISSILES_ONLY,
    allows_doctrine,
    doctrines_for,
    is_battery,
    is_shooter,
)
from fall_of_penghu.world.combat.priority import (
    hit_chance_for,
    hit_chance_infantry,
    hit_chance_tank,
    target_score,
)

__all__ = [
    "AIR_ONLY",
    "Combat",
    "DOCTRINES",
    "FIRE",
    "GUN_DOCTRINES",
    "HOLD",
    "LABELS",
    "MISSILES_ONLY",
    "allows_doctrine",
    "doctrines_for",
    "hit_chance_for",
    "hit_chance_infantry",
    "hit_chance_tank",
    "is_battery",
    "is_shooter",
    "target_score",
]
