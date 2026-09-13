from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pygame

from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_PLAYER
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind

if TYPE_CHECKING:
    from fall_of_penghu.world.world import World


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
    if player_holds_islands(world):
        return
    on_china_victory()


def on_china_victory() -> None:
    """Stub: leave the match. Replace later with a proper end screen."""
    print("Китай победил")
    pygame.quit()
    sys.exit(0)
