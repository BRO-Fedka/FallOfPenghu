from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fall_of_penghu.world.clock import CALENDAR_DAY_S
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_PLAYER
from fall_of_penghu.world.entities.kinds import KIND_LABELS, SHOT_KINDS, is_static_kind

if TYPE_CHECKING:
    from fall_of_penghu.world.world import World

WAR_START_CALENDAR_S = 0.5 * CALENDAR_DAY_S


@dataclass
class DefeatReport:
    held_s: float
    kills: dict[str, int]


def player_holds_islands(world: World) -> bool:
    """True if player ground dynamics still stand on any island. Air does not hold."""
    for obj in world.entities.items:
        if not isinstance(obj, DynamicObject) or not obj.active:
            continue
        if obj.faction != FACTION_PLAYER or obj.stowed:
            continue
        if obj.mobility != "land":
            continue
        if obj.kind in SHOT_KINDS or is_static_kind(obj.kind):
            continue
        if obj.island_id() is not None:
            return True
    return False


def check_china_victory(world: World) -> None:
    """China wins when no player ground dynamics remain on any island."""
    if world.defeat is not None:
        return
    if player_holds_islands(world):
        return
    held = max(0.0, world.clock.calendar_time - WAR_START_CALENDAR_S)
    tally = {kind: int(n) for kind, n in world.kills.items() if int(n) > 0}
    world.defeat = DefeatReport(held_s=held, kills=tally)
    print(
        f"China victory  held {held_label(held)}  killed {kill_total(tally)}",
        flush=True,
    )


def kill_total(kills: dict[str, int] | None) -> int:
    if not kills:
        return 0
    return sum(int(n) for n in kills.values())


def ordered_kills(kills: dict[str, int] | None) -> list[tuple[str, int]]:
    tally = {str(kind): int(n) for kind, n in (kills or {}).items() if int(n) > 0}
    out: list[tuple[str, int]] = []
    seen: set[str] = set()
    for kind in KIND_LABELS:
        n = tally.get(kind)
        if n:
            out.append((kind, n))
            seen.add(kind)
    for kind in sorted(tally):
        if kind not in seen:
            out.append((kind, tally[kind]))
    return out


def held_label(elapsed_s: float) -> str:
    minutes = int(max(0.0, float(elapsed_s)) // 60)
    if minutes < 1:
        return "less than a minute"
    if minutes < 60:
        return f"{minutes} {_en(minutes, 'minute')}"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} {_en(hours, 'hour')}"
    days = hours // 24
    rest = hours % 24
    day_s = f"{days} {_en(days, 'day')}"
    if rest == 0:
        return day_s
    return f"{day_s}, {rest} {_en(rest, 'hour')}"


def _en(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"
