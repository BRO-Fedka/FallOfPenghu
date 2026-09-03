"""Time-of-day palettes for the Test viewer.

The mix rule lives in fall_of_penghu.render.static.tod. This module keeps
the 30-second viewer clock and re-exports the same keyframes.
Radar is a separate look and is never TOD-graded.
"""

from __future__ import annotations

from fall_of_penghu.render.static.tod import (
    DAWN,
    DUSK,
    GROUPS,
    KEYFRAMES,
    NIGHT,
    NOON,
    PALETTE_KEYS,
    palette_at,
    _segment,
)

DAY_SECONDS = 30.0

PHASE_RU = {
    "night": "Ночь",
    "dawn": "Рассвет",
    "day": "День",
    "dusk": "Закат",
}


def phase_label(tod: float) -> str:
    _, n0, _, n1, _, u = _segment(tod)
    left = PHASE_RU[n0]
    right = PHASE_RU[n1]
    if n0 == n1 or u < 0.08:
        return left
    if u > 0.92:
        return right
    return f"{left} -> {right}"


def clock_label(tod: float) -> str:
    minutes = int((tod % 1.0) * 24.0 * 60.0) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def tod_from_elapsed(seconds: float) -> float:
    return (seconds / DAY_SECONDS) % 1.0
