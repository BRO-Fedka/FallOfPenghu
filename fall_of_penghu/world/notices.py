"""Chat notice categories, colours, and a single post helper."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fall_of_penghu.world.entities.game_object import FACTION_PLAYER
from fall_of_penghu.world.events import ContactNotice

if TYPE_CHECKING:
    from fall_of_penghu.world.world import World

CONTACT = "contact"
SPOTTED = "spotted"
LOSSES = "losses"
AMMO = "ammo"
SAT = "sat"
THEATER = "theater"
LIFT = "lift"

CATEGORIES = (CONTACT, SPOTTED, LOSSES, AMMO, SAT, THEATER, LIFT)
CATEGORY_LABELS = {
    CONTACT: "CONTACT",
    SPOTTED: "SPOTTED",
    LOSSES: "LOSSES",
    AMMO: "AMMO",
    SAT: "SAT",
    THEATER: "THEATER",
    LIFT: "LIFT",
}
CATEGORY_HINTS = {
    CONTACT: "Enemy unit first entered our snapshot.",
    SPOTTED: "A visible drone or scout sees us. Vehicles off-forest need the No SAT toggle.",
    LOSSES: "One of our units was wrecked.",
    AMMO: "Last magazine left, or the gun is empty.",
    SAT: "Our satellite window opened or closed.",
    THEATER: "Island taken or recaptured, or an enemy landing.",
    LIFT: "Embark, ferry loaded, or cargo put ashore.",
}
SPEED_OFF = "off"
SPEED_1X = "1x"
SPEED_0X = "0x"
SPEED_MODES = (SPEED_OFF, SPEED_1X, SPEED_0X)
COLORS = {
    CONTACT: (86, 196, 214),
    SPOTTED: (232, 176, 64),
    LOSSES: (214, 72, 64),
    AMMO: (232, 140, 56),
    SAT: (72, 220, 96),
    THEATER: (214, 196, 120),
    LIFT: (80, 186, 150),
}
SAT_DOWN = (220, 56, 48)

KIND_FILTERS: dict[str, tuple[str, ...]] = {
    CONTACT: (
        "drone",
        "scout",
        "ship",
        "drone_carrier",
        "ferry",
        "landing_ship",
        "infantry",
        "artillery",
        "tank",
        "aa_pickup",
    ),
    SPOTTED: (
        "infantry",
        "artillery",
        "tank",
        "aaw",
        "aa_pickup",
        "truck",
        "ferry",
    ),
    LOSSES: (
        "infantry",
        "artillery",
        "tank",
        "aaw",
        "aa_pickup",
        "truck",
        "ferry",
        "drone",
        "scout",
    ),
    AMMO: ("aaw", "aa_pickup", "artillery"),
    LIFT: ("ferry", "infantry", "artillery", "tank", "aaw", "aa_pickup", "truck"),
}

DEFAULT_SHOW = {name: True for name in CATEGORIES}
DEFAULT_SLOW = {
    CONTACT: SPEED_1X,
    SPOTTED: SPEED_OFF,
    LOSSES: SPEED_OFF,
    AMMO: SPEED_OFF,
    SAT: SPEED_OFF,
    THEATER: SPEED_1X,
    LIFT: SPEED_OFF,
}


def category_label(category: str) -> str:
    from fall_of_penghu.shell.i18n import t

    return t(f"notice.{category}", default=CATEGORY_LABELS.get(category, category.upper()))


def category_hint(category: str) -> str:
    from fall_of_penghu.shell.i18n import t

    return t(
        f"notice.{category}.hint",
        default=CATEGORY_HINTS.get(category, ""),
    )


def default_kinds(category: str) -> dict[str, bool] | None:
    names = KIND_FILTERS.get(category)
    if not names:
        return None
    return {name: True for name in names}


def color_for(category: str, *, sat_down: bool = False) -> tuple[int, int, int]:
    if category == SAT and sat_down:
        return SAT_DOWN
    return COLORS.get(category, COLORS[CONTACT])


def post(
    world: World,
    category: str,
    text: str,
    x: float,
    y: float,
    *,
    object_ids: tuple[str, ...] = (),
    filter_kind: str | None = None,
    icon_kinds: tuple[str, ...] = (),
    sat_down: bool = False,
    slow: bool | None = None,
) -> None:
    if slow is None:
        slow = DEFAULT_SLOW.get(category, SPEED_OFF) != SPEED_OFF
    world.notices.append(
        ContactNotice(
            faction=FACTION_PLAYER,
            object_ids=object_ids,
            x=x,
            y=y,
            text=text,
            slow_time=slow,
            category=category,
            filter_kind=filter_kind,
            icon_kinds=icon_kinds,
            calendar_time=world.clock.calendar_time,
            sat_down=sat_down,
        )
    )
