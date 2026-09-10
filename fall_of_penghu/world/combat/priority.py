"""Hit chance curves and target priority.

Edit the hit_chance_* functions for tank / infantry / pickup.
Edit target_score (and RETURN_FIRE_WEIGHT / DANGER_WEIGHT) for who gets shot first.
Danger numbers per class: detection.json → threat.
"""

from __future__ import annotations

from math import hypot

from fall_of_penghu.world.combat.doctrine import HOLD
from fall_of_penghu.world.entities.game_object import GameObject
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind
from fall_of_penghu.world.perception.catalog import DetectionCatalog

# Who can shoot us now outranks kind-danger; kind-danger outranks distance.
RETURN_FIRE_WEIGHT = 1000.0
DANGER_WEIGHT = 10.0


def hit_chance_infantry(dist_m: float, reach_m: float, p0: float) -> float:
    """Infantry small-arms. p0 at point-blank, ~0 at max range."""
    return _range_falloff(dist_m, reach_m, p0)


def hit_chance_tank(dist_m: float, reach_m: float, p0: float) -> float:
    """Tank cannon. Same curve shape as infantry; change here independently."""
    return _range_falloff(dist_m, reach_m, p0)


def hit_chance_pickup(dist_m: float, reach_m: float, p0: float) -> float:
    """AA pickup gun. Land units except artillery use a distance roll."""
    return _range_falloff(dist_m, reach_m, p0)


def hit_chance_default(dist_m: float, reach_m: float, p0: float) -> float:
    return _range_falloff(dist_m, reach_m, p0)


def _range_falloff(dist_m: float, reach_m: float, p0: float) -> float:
    if reach_m <= 0.0:
        return 0.0
    t = min(1.0, max(0.0, float(dist_m) / reach_m))
    return max(0.0, float(p0) * (1.0 - t * t))


def hit_chance_for(kind: str, dist_m: float, catalog: DetectionCatalog) -> float:
    reach = catalog.engagement_m(kind) or 0.0
    p0 = catalog.hit_p0(kind)
    if kind == "infantry":
        return hit_chance_infantry(dist_m, reach, p0)
    if kind == "tank":
        return hit_chance_tank(dist_m, reach, p0)
    if kind == "aa_pickup":
        return hit_chance_pickup(dist_m, reach, p0)
    return hit_chance_default(dist_m, reach, p0)


def can_return_fire(
    battery: GameObject, foe: GameObject, catalog: DetectionCatalog
) -> bool:
    """True if the foe can shoot this battery right now."""
    if not foe.active or getattr(foe, "stowed", False):
        return False
    if foe.kind in SHOT_KINDS or is_static_kind(foe.kind):
        return False
    if getattr(foe, "doctrine", HOLD) == HOLD:
        return False
    reach = catalog.engagement_m(foe.kind)
    if reach is None:
        return False
    if not catalog.can_engage(foe.kind, battery):
        return False
    dist = hypot(foe.x - battery.x, foe.y - battery.y)
    min_r = catalog.min_engagement_m(foe.kind)
    return min_r <= dist <= reach


def target_score(
    battery: GameObject,
    foe: GameObject,
    dist_m: float,
    reach_m: float,
    catalog: DetectionCatalog,
) -> float:
    """Higher wins. Return-fire first, then danger, then closer range."""
    fire_back = 1.0 if can_return_fire(battery, foe, catalog) else 0.0
    danger = catalog.threat(battery.kind, foe.kind)
    span = max(float(reach_m), 1.0)
    closeness = 1.0 - min(1.0, max(0.0, float(dist_m) / span))
    return RETURN_FIRE_WEIGHT * fire_back + DANGER_WEIGHT * danger + closeness
