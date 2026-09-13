from __future__ import annotations

from math import hypot
from typing import TYPE_CHECKING

from fall_of_penghu.profile import scope
from fall_of_penghu.world.entities.game_object import (
    FACTION_CHINA,
    FACTION_PLAYER,
    FACTION_TAIWAN,
    GameObject,
)
from fall_of_penghu.world.entities.kinds import is_static_kind
from fall_of_penghu.world.perception.alerts import AlertTracker
from fall_of_penghu.world.perception.catalog import DetectionCatalog
from fall_of_penghu.world.perception.cover import CoverIndex
from fall_of_penghu.world.perception.imprint import ContactImprint
from fall_of_penghu.world.perception.lookout import (
    IslandLookouts,
    china_held,
    occupants,
)
from fall_of_penghu.world.perception.satellite import SatelliteStatus, SatelliteWindows

if TYPE_CHECKING:
    from fall_of_penghu.world.world import World

FACTIONS = (FACTION_PLAYER, FACTION_CHINA, FACTION_TAIWAN)


class Perception:
    """Who a faction sees. Snapshot returns live GameObject instances."""

    def __init__(self, catalog: DetectionCatalog) -> None:
        self.catalog = catalog
        self.cover: CoverIndex | None = None
        self.lookouts: IslandLookouts | None = None
        self.satellite = SatelliteWindows(
            period_s=catalog.sat_period_s,
            duration_s=catalog.sat_duration_s,
            offset_s=catalog.sat_offset_s,
            always_day=catalog.sat_always_day,
        )
        self.alerts = AlertTracker(catalog)
        self._visible: dict[str, list[GameObject]] = {f: [] for f in FACTIONS}
        self._prev_ids: dict[str, set[str]] = {f: set() for f in FACTIONS}
        self._imprints: dict[str, list[ContactImprint]] = {f: [] for f in FACTIONS}
        self._pose: dict[
            str,
            tuple[
                float,
                float,
                float,
                str,
                str,
                str,
                bool,
                tuple[tuple[float, float], ...],
                bool,
                bool,
            ],
        ] = {}
        self._imprint_n = 0
        self._darkness = 0.0
        self.china_held: set[int] = set()

    def bind_map(self, world: World) -> None:
        self.cover = CoverIndex(world.map)
        planner = world.entities.planner
        islands = planner.land.islands if planner is not None else None
        self.lookouts = IslandLookouts(
            world.map, islands, self.catalog.lookout_simplify_m
        )

    def visible_objects(self, faction: str) -> list[GameObject]:
        return list(self._visible.get(faction, ()))

    def imprints(self, faction: str) -> list[ContactImprint]:
        return list(self._imprints.get(faction, ()))

    def radar_rings(self, faction: str) -> list[tuple[float, float, float]]:
        return self.sensor_rings(faction, "radar")

    def sensor_rings(
        self, faction: str, channel: str, cover: str = "open"
    ) -> list[tuple[float, float, float]]:
        rings: list[tuple[float, float, float]] = []
        for obj in self._visible.get(faction, ()):
            if obj.faction != faction:
                continue
            if channel not in self.catalog.emitters(obj.kind):
                continue
            radius = self.catalog.emitter_range_m(channel, obj.kind)
            if radius is None or radius <= 0.0:
                continue
            radius *= self.catalog.darkness_scale(channel, self._darkness)
            radius *= self.catalog.cover_factor(channel, cover)
            if radius <= 0.0:
                continue
            rings.append((obj.x, obj.y, radius))
        return rings

    def engagement_rings(
        self,
        faction: str,
        kinds: set[str],
    ) -> list[tuple[float, float, float]]:
        rings: list[tuple[float, float, float]] = []
        if not kinds:
            return rings
        for obj in self._visible.get(faction, ()):
            if obj.kind not in kinds:
                continue
            radius = self.catalog.engagement_m(obj.kind)
            if radius is None:
                continue
            rings.append((obj.x, obj.y, radius))
            inner = self.catalog.min_engagement_m(obj.kind)
            if inner > 0.0:
                rings.append((obj.x, obj.y, inner))
        return rings

    def satellite_status(self, calendar_time: float) -> SatelliteStatus:
        return self.satellite.status(calendar_time)

    def step(self, world: World) -> None:
        now = world.clock.simulation_time
        darkness = world.clock.darkness
        self._darkness = darkness
        sat = self.satellite.status(world.clock.calendar_time)
        sat_on = sat.active and (
            self.catalog.darkness_scale("satellite", darkness) > 1e-6
        )
        with scope("perception.snapshot"):
            objects = [
                obj
                for obj in world.entities.items
                if obj.active or is_static_kind(obj.kind)
            ]
            for obj in objects:
                self._pose[obj.id] = (
                    obj.x,
                    obj.y,
                    obj.heading,
                    obj.kind,
                    obj.name,
                    obj.faction,
                    bool(getattr(obj, "moving", False)),
                    tuple(getattr(obj, "trail", ()) or ()),
                    bool(getattr(obj, "orient_radar", False)),
                    bool(obj.active),
                )
        lookouts = self.lookouts
        if lookouts is not None:
            with scope("perception.lookouts"):
                occ = occupants(lookouts.islands, objects)
                self.china_held = china_held(lookouts.inhabited, occ)
        else:
            self.china_held = set()
        for faction in FACTIONS:
            with scope(f"perception.compute.{faction}"):
                seen = self._compute(faction, objects, darkness, sat_on)
                ids = {obj.id for obj in seen}
                prev = self._prev_ids[faction]
                for oid in prev - ids:
                    self._remember(faction, oid, now)
                for obj in seen:
                    if is_static_kind(obj.kind) and obj.faction != faction:
                        self._remember(faction, obj.id, now)
                    if obj.id not in prev and obj.faction != faction:
                        self.alerts.on_enter(
                            faction=faction,
                            object_id=obj.id,
                            kind=obj.kind,
                            x=obj.x,
                            y=obj.y,
                            now_sim=now,
                        )
                self._visible[faction] = seen
                self._prev_ids[faction] = ids
                self._imprints[faction] = [
                    mark for mark in self._imprints[faction] if not mark.dead(now)
                ]
        world.notices.extend(self.alerts.flush(now))

    def _remember(self, faction: str, source_id: str, now_sim: float) -> None:
        pose = self._pose.get(source_id)
        if pose is None:
            return
        (
            x,
            y,
            heading,
            kind,
            name,
            owner,
            moving,
            trail,
            orient_radar,
            active,
        ) = pose
        permanent = is_static_kind(kind)
        if permanent:
            for mark in self._imprints[faction]:
                if mark.source_id == source_id and mark.permanent:
                    mark.x = x
                    mark.y = y
                    mark.heading = heading
                    mark.kind = kind
                    mark.name = name
                    mark.faction = owner
                    mark.moving = moving
                    mark.trail = trail
                    mark.orient_radar = orient_radar
                    mark.active = active
                    return
        self._imprint_n += 1
        self._imprints[faction].append(
            ContactImprint(
                id=f"imprint_{self._imprint_n}",
                source_id=source_id,
                faction=owner,
                kind=kind,
                name=name,
                x=x,
                y=y,
                heading=heading,
                born_sim=now_sim,
                fade_sim_s=self.catalog.fade_sim_s(kind),
                moving=moving,
                trail=trail,
                orient_radar=orient_radar,
                active=active,
                permanent=permanent,
            )
        )

    def _compute(
        self,
        faction: str,
        objects: list[GameObject],
        darkness: float,
        sat_on: bool,
        ) -> list[GameObject]:
        own: list[GameObject] = []
        others: list[GameObject] = []
        for obj in objects:
            if getattr(obj, "stowed", False):
                continue
            if obj.faction == faction:
                own.append(obj)
            else:
                others.append(obj)
        if not others:
            return own
        emitters: list[tuple[GameObject, str]] = []
        for obj in own:
            for channel in self.catalog.emitters(obj.kind):
                if self.catalog.is_global(channel):
                    continue
                if self.catalog.darkness_scale(channel, darkness) <= 0.0:
                    continue
                emitters.append((obj, channel))
        lookouts = self.lookouts
        occupied: set[int] = set()
        base: frozenset[int] | set[int] | None = None
        deny: set[int] | None = None
        if lookouts is not None and faction in (FACTION_PLAYER, FACTION_CHINA):
            occupied = lookouts.occupied_by(
                own,
                ground_kinds=frozenset(
                    kind
                    for kind in {obj.kind for obj in own}
                    if self.catalog.cover_role(kind) == "ground"
                ),
            )
            if faction == FACTION_PLAYER:
                deny = self.china_held
            else:
                base = self.china_held
        else:
            lookouts = None
        sat_for_faction = sat_on and faction == self.catalog.sat_faction
        cover = self.cover
        seen = list(own)
        for target in others:
            channels = self.catalog.detectable_by(target.kind)
            role = self.catalog.cover_role(target.kind)
            ground = cover.at(target.x, target.y, role) if cover is not None else "open"
            if self._detected(
                target,
                channels,
                ground,
                emitters,
                lookouts,
                occupied,
                sat_for_faction,
                darkness,
                base=base,
                deny=deny,
            ):
                seen.append(target)
        return seen

    def _detected(
        self,
        target: GameObject,
        channels: frozenset[str],
        cover: str,
        emitters: list[tuple[GameObject, str]],
        lookouts: IslandLookouts | None,
        occupied: set[int],
        sat_on: bool,
        darkness: float,
        *,
        base: frozenset[int] | set[int] | None = None,
        deny: set[int] | None = None,
    ) -> bool:
        if "satellite" in channels and sat_on:
            if self.catalog.cover_factor("satellite", cover) > 0.0:
                return True
        if lookouts is not None and "lookout" in channels:
            radius = self.catalog.scaled_range_m("lookout", target.kind, darkness)
            if radius is not None:
                radius *= self.catalog.cover_factor("lookout", cover)
                if radius > 0.0 and lookouts.distance_m(
                    target.x, target.y, occupied, base=base, deny=deny
                ) <= radius:
                    return True
        tx, ty = target.x, target.y
        for src, channel in emitters:
            if channel not in channels:
                continue
            radius = self.catalog.scaled_range_m(
                channel, target.kind, darkness, emitter_kind=src.kind
            )
            if radius is None:
                continue
            radius *= self.catalog.cover_factor(channel, cover)
            if radius <= 0.0:
                continue
            if hypot(src.x - tx, src.y - ty) <= radius:
                return True
        return False
