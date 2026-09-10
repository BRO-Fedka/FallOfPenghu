from __future__ import annotations

from fall_of_penghu.world.entities.game_object import GameObject

FIRE = "fire"
HOLD = "hold"
AIR_ONLY = "air_only"
MISSILES_ONLY = "missiles_only"

DOCTRINES = (FIRE, HOLD, AIR_ONLY, MISSILES_ONLY)

LABELS = {
    FIRE: "FIRE",
    HOLD: "HOLD",
    AIR_ONLY: "AIR",
    MISSILES_ONLY: "MSL",
}


def accepts(doctrine: str, target: GameObject) -> bool:
    if doctrine == HOLD:
        return False
    if doctrine == AIR_ONLY:
        mobility = getattr(target, "mobility", "")
        return mobility == "air"
    return True


LAND_GUNS = frozenset({"infantry", "tank", "artillery"})
GUNS = frozenset({"aaw", "aa_pickup"}) | LAND_GUNS
MISSILE_DOCTRINES = (FIRE, HOLD, AIR_ONLY, MISSILES_ONLY)
GUN_DOCTRINES = (FIRE, HOLD, AIR_ONLY)
LAND_DOCTRINES = (FIRE, HOLD)


def is_battery(obj: GameObject | None) -> bool:
    return obj is not None and obj.kind in GUNS and hasattr(obj, "speed_mps")


def is_shooter(obj: GameObject | None) -> bool:
    if obj is None or not hasattr(obj, "speed_mps"):
        return False
    if obj.kind in GUNS or obj.kind == "drone":
        return True
    return False


def doctrines_for(kinds: set[str]) -> tuple[str, ...]:
    if not kinds:
        return ()
    if kinds <= LAND_GUNS:
        return LAND_DOCTRINES
    if kinds <= ({"aa_pickup"} | LAND_GUNS):
        return GUN_DOCTRINES
    return MISSILE_DOCTRINES


def allows_doctrine(kind: str, doctrine: str) -> bool:
    if kind in LAND_GUNS:
        return doctrine in LAND_DOCTRINES
    if kind == "aa_pickup":
        return doctrine in GUN_DOCTRINES
    if kind == "aaw":
        return doctrine in MISSILE_DOCTRINES
    return False
