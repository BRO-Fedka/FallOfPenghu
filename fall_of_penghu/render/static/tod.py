"""Time-of-day palettes. Radar is never graded; noon is scene.NORMAL.

Dawn / dusk / night are authored keyframes. Colours mix in linear RGB
along calendar time-of-day (0 = midnight, 1 = next midnight).
"""

from __future__ import annotations

from fall_of_penghu.render.static.scene import NORMAL

NOON: dict[str, tuple[int, int, int]] = dict(NORMAL)

DAWN: dict[str, tuple[int, int, int]] = {
    "sea": (42, 150, 178),
    "sea_shallow": (148, 198, 208),
    "sea_deep": (22, 85, 125),
    "taiwan": (150, 130, 128),
    "land": (130, 155, 118),
    "rock": (235, 205, 198),
    "forest": (55, 88, 68),
    "grass": (110, 128, 88),
    "building": (75, 70, 74),
    "concrete": (115, 145, 152),
    "road": (40, 38, 44),
    "bridge": (125, 90, 82),
    "airport": (95, 100, 112),
    "hud": (235, 215, 220),
}

DUSK: dict[str, tuple[int, int, int]] = {
    "sea": (38, 158, 178),
    "sea_shallow": (118, 198, 188),
    "sea_deep": (18, 105, 145),
    "taiwan": (165, 125, 88),
    "land": (155, 145, 82),
    "rock": (255, 205, 155),
    "forest": (72, 78, 42),
    "grass": (145, 118, 58),
    "building": (88, 72, 58),
    "concrete": (165, 135, 108),
    "road": (44, 38, 32),
    "bridge": (155, 95, 52),
    "airport": (115, 98, 82),
    "hud": (255, 228, 195),
}

NIGHT: dict[str, tuple[int, int, int]] = {
    "sea": (6, 22, 38),
    "sea_shallow": (16, 46, 66),
    "sea_deep": (3, 12, 26),
    "taiwan": (34, 40, 52),
    "rock": (46, 52, 68),
    # Moonlit and dark. Open land stays lighter than grass; grass darker than land.
    "land": (48, 66, 72),
    "grass": (20, 40, 46),
    "forest": (12, 26, 36),
    # Streetlights on: urban returns to the noon albedo.
    "building": NOON["building"],
    "concrete": NOON["concrete"],
    "road": NOON["road"],
    "bridge": NOON["bridge"],
    "airport": NOON["airport"],
    "hud": (140, 160, 175),
}

# t is fraction of a day (0 = midnight). Hold night until 04:00 so
# dawn pink cannot leak after midnight. Dawn itself is ≤ 1 hour (04:00–05:00).
# Dusk is a short window around 18:00; day holds until then.
KEYFRAMES: list[tuple[float, str, dict[str, tuple[int, int, int]]]] = [
    (0.00, "night", NIGHT),
    (4 / 24, "night", NIGHT),
    (4.5 / 24, "dawn", DAWN),
    (5 / 24, "day", NOON),
    (17.75 / 24, "day", NOON),
    (18.25 / 24, "dusk", DUSK),
    (19 / 24, "night", NIGHT),
]

GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("water", ("sea", "sea_shallow", "sea_deep")),
    ("land", ("taiwan", "land", "rock")),
    ("vegetation", ("forest", "grass")),
    ("urban", ("building", "concrete", "road", "bridge", "airport")),
    ("ui", ("hud",)),
]

PHASE_EN = {
    "night": "Night",
    "dawn": "Dawn",
    "day": "Day",
    "dusk": "Dusk",
}

PALETTE_KEYS: tuple[str, ...] = tuple(key for _, keys in GROUPS for key in keys)


def _srgb_to_linear(channel: int) -> float:
    c = max(0, min(255, channel)) / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(channel: float) -> int:
    c = max(0.0, min(1.0, channel))
    if c <= 0.0031308:
        v = 12.92 * c
    else:
        v = 1.055 * (c ** (1.0 / 2.4)) - 0.055
    return int(round(v * 255.0))


def _smooth(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _lerp_rgb(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    t: float,
) -> tuple[int, int, int]:
    u = _smooth(t)
    return (
        _linear_to_srgb(_srgb_to_linear(a[0]) * (1.0 - u) + _srgb_to_linear(b[0]) * u),
        _linear_to_srgb(_srgb_to_linear(a[1]) * (1.0 - u) + _srgb_to_linear(b[1]) * u),
        _linear_to_srgb(_srgb_to_linear(a[2]) * (1.0 - u) + _srgb_to_linear(b[2]) * u),
    )


def _segment(tod: float) -> tuple[float, str, dict, str, dict, float]:
    t = tod % 1.0
    framed = list(KEYFRAMES) + [(1.0, KEYFRAMES[0][1], KEYFRAMES[0][2])]
    for i in range(len(framed) - 1):
        t0, n0, p0 = framed[i]
        t1, n1, p1 = framed[i + 1]
        if t0 <= t < t1 or (i == len(framed) - 2 and t >= t0):
            span = max(t1 - t0, 1e-9)
            u = (t - t0) / span
            return t0, n0, p0, n1, p1, u
    _, n0, p0 = KEYFRAMES[0]
    return 0.0, n0, p0, n0, p0, 0.0


def palette_at(tod: float) -> dict[str, tuple[int, int, int]]:
    _, _, a, _, b, u = _segment(tod)
    return {key: _lerp_rgb(a[key], b[key], u) for key in PALETTE_KEYS}


def phase_label(tod: float) -> str:
    _, n0, _, n1, _, u = _segment(tod)
    left = PHASE_EN[n0]
    right = PHASE_EN[n1]
    if n0 == n1 or u < 0.08:
        return left
    if u > 0.92:
        return right
    return f"{left} -> {right}"
