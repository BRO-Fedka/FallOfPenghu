"""Vision range rings the player can toggle.

Edit VISION_RINGS to change channels, cover, colours, or labels.
Cover must exist in detection.json → cover.<channel>.
"""

from __future__ import annotations

# id, channel, cover, rgba, label
VISION_RINGS: tuple[tuple[str, str, str, tuple[int, int, int, int], str], ...] = (
    ("primitive", "visual_primitive", "open", (70, 170, 220, 140), "Primitive"),
    (
        "primitive_grass",
        "visual_primitive",
        "grass",
        (70, 170, 220, 80),
        "Primitive grass",
    ),
    (
        "primitive_forest",
        "visual_primitive",
        "forest",
        (40, 110, 150, 100),
        "Primitive forest",
    ),
    ("advanced", "visual_advanced", "open", (170, 90, 220, 140), "Advanced"),
    (
        "advanced_grass",
        "visual_advanced",
        "grass",
        (170, 90, 220, 80),
        "Advanced grass",
    ),
    (
        "advanced_forest",
        "visual_advanced",
        "forest",
        (120, 50, 170, 100),
        "Advanced forest",
    ),
)

VISION_DEFAULT_ON: frozenset[str] = frozenset({"primitive", "advanced"})

# Artillery aim / scatter draw (normal map only).
SCATTER_COLOR = (230, 120, 40, 180)
SCATTER_LINE = (230, 120, 40, 160)
