"""Engagement range rings the player can toggle.

Edit RANGE_RINGS to change kinds, colours, or labels.
Kinds must have engagement_m in detection.json → weapons.
"""

from __future__ import annotations

# kind, rgba, label
RANGE_RINGS: tuple[tuple[str, tuple[int, int, int, int], str], ...] = (
    ("infantry", (255, 255, 255, 180), "Infantry"),
    ("aa_pickup", (255, 50, 180, 180), "AA pickup"),
    ("tank", (140, 80, 35, 180), "Tank"),
    ("aaw", (40, 80, 160, 180), "AAW"),
    ("artillery", (255, 90, 0, 180), "Artillery"),
)

RANGE_DEFAULT_ON: frozenset[str] = frozenset(item[0] for item in RANGE_RINGS)
