from __future__ import annotations

from dataclasses import dataclass

FACTION_PLAYER = "P"
FACTION_CHINA = "C"
FACTION_TAIWAN = "T"

FACTION_COLORS = {
    FACTION_PLAYER: (60, 110, 210),
    FACTION_CHINA: (200, 50, 45),
    FACTION_TAIWAN: (40, 160, 90),
}


@dataclass
class GameObject:
    """World instance in map meters. Render.dynamic only reads these fields."""

    id: str
    faction: str
    kind: str
    name: str
    x: float
    y: float
    heading: float = 0.0
    active: bool = True
    orient_icon: bool = False
