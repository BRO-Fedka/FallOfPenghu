from __future__ import annotations

from typing import TYPE_CHECKING

from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import (
    FACTION_CHINA,
    FACTION_PLAYER,
)
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind
from fall_of_penghu.world.events import ContactNotice

if TYPE_CHECKING:
    from fall_of_penghu.world.world import World

SITE_KINDS = frozenset({"port", "airfield", "seaport", "airport"})


class IslandControl:
    """Who holds each island. Statics follow the holder; bridges need both ends."""

    def __init__(self) -> None:
        self.owner: dict[int, str] = {}
        self._ready = False

    def bake(self, world: World) -> None:
        planner = world.entities.planner
        if planner is None:
            return
        for iid in planner.land.islands.ids():
            self.owner.setdefault(iid, FACTION_PLAYER)
        self._ready = True
        self._sync_bridges(world)

    def china_islands(self) -> set[int]:
        return {iid for iid, fac in self.owner.items() if fac == FACTION_CHINA}

    def is_china(self, island: int) -> bool:
        return self.owner.get(island, FACTION_PLAYER) == FACTION_CHINA

    def step(self, world: World) -> None:
        if not self._ready:
            self.bake(world)
        planner = world.entities.planner
        if planner is None:
            return
        islands = planner.land.islands
        from fall_of_penghu.profile import scope

        with scope("control.ground_count"):
            here = _ground(world)
        flipped: list[tuple[int, str]] = []
        for iid in islands.ids():
            row = here.get(iid) or {}
            player = row.get(FACTION_PLAYER, 0)
            china = row.get(FACTION_CHINA, 0)
            if china > 0 and player <= 0:
                nxt = FACTION_CHINA
            elif player > 0 and china <= 0:
                nxt = FACTION_PLAYER
            else:
                continue
            if self.owner.get(iid, FACTION_PLAYER) == nxt:
                continue
            self.owner[iid] = nxt
            _flip_sites(world, iid, nxt)
            flipped.append((iid, nxt))
        if flipped:
            self._sync_bridges(world)
            for iid, fac in flipped:
                _announce(world, iid, fac)
        if not any(row.get(FACTION_PLAYER, 0) > 0 for row in here.values()):
            from fall_of_penghu.world.victory import check_china_victory

            check_china_victory(world)

    def _sync_bridges(self, world: World) -> None:
        planner = world.entities.planner
        if planner is None:
            return
        for span in planner.land.crossings:
            obj = world.entities.get(span.id)
            if obj is None or obj.kind != "bridge":
                continue
            a = self.owner.get(span.island_a, FACTION_PLAYER)
            b = self.owner.get(span.island_b, FACTION_PLAYER)
            if a == FACTION_CHINA and b == FACTION_CHINA:
                obj.faction = FACTION_CHINA
            else:
                obj.faction = FACTION_PLAYER


def _ground(world: World) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {}
    for obj in world.entities.items:
        if not isinstance(obj, DynamicObject) or not obj.active:
            continue
        if obj.stowed or obj.mobility != "land":
            continue
        if obj.kind in SHOT_KINDS or is_static_kind(obj.kind):
            continue
        iid = obj.island_id()
        if iid is None:
            continue
        row = out.setdefault(iid, {})
        row[obj.faction] = row.get(obj.faction, 0) + 1
    return out


def _flip_sites(world: World, island: int, faction: str) -> None:
    planner = world.entities.planner
    if planner is None:
        return
    islands = planner.land.islands
    for obj in world.entities.items:
        if obj.kind == "bridge":
            continue
        if faction == FACTION_CHINA:
            if obj.kind not in SITE_KINDS:
                continue
        elif not is_static_kind(obj.kind):
            continue
        at = islands.at(obj.x, obj.y)
        if at is None:
            at = islands.nearest(obj.x, obj.y, 400.0)
        if at == island:
            obj.faction = faction


def _announce(world: World, island: int, faction: str) -> None:
    planner = world.entities.planner
    x = y = 0.0
    if planner is not None:
        box = planner.land.islands.bbox(island)
        x = (box[0] + box[2]) * 0.5
        y = (box[1] + box[3]) * 0.5
    if faction == FACTION_CHINA:
        text = f"Island {island} lost: ports and airfields seized"
    else:
        text = f"Island {island} recaptured"
    world.notices.append(
        ContactNotice(
            faction=FACTION_PLAYER,
            object_ids=(),
            x=x,
            y=y,
            text=text,
            slow_time=False,
        )
    )
