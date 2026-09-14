from __future__ import annotations

from math import hypot
from typing import TYPE_CHECKING

from fall_of_penghu.profile import scope
from fall_of_penghu.spatial import UniformGrid
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
CHINA_PERIOD_WALL = 0.25
EMITTER_CELL_M = 4_000.0


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
        self._china_wall = -1e9
        self._pose_n = 0
        self._live_ids: set[str] = set()
        self._stowed: dict[str, bool] = {}
        self._sat_was: bool | None = None
        self._spotted: set[tuple[str, str]] = set()

    def bind_map(self, world: World) -> None:
        baked = getattr(world, "sim_bake", None)
        self.cover = CoverIndex(world.map, baked=baked)
        planner = world.entities.planner
        islands = planner.land.islands if planner is not None else None
        self.lookouts = IslandLookouts(
            world.map, islands, self.catalog.lookout_simplify_m, baked=baked
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

    def sensor_rings_for(
        self,
        objects: list[GameObject],
        channel: str,
        cover: str = "open",
    ) -> list[tuple[float, float, float]]:
        rings: list[tuple[float, float, float]] = []
        for obj in objects:
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

    def engagement_rings_for(
        self, objects: list[GameObject]
    ) -> list[tuple[float, float, float]]:
        rings: list[tuple[float, float, float]] = []
        for obj in objects:
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
            moved = self._snapshot(objects)
        if world.clock.dt_sim <= 0.0 and not moved:
            return
        lookouts = self.lookouts
        if lookouts is not None:
            with scope("perception.lookouts"):
                occ = occupants(lookouts.islands, objects)
                self.china_held = china_held(lookouts.inhabited, occ)
        else:
            self.china_held = set()
        china_due = (
            moved and world.clock.dt_sim <= 0.0
        ) or (world.clock.wall_time - self._china_wall) >= CHINA_PERIOD_WALL
        for faction in FACTIONS:
            if faction != FACTION_PLAYER and not china_due:
                continue
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
        if china_due:
            self._china_wall = world.clock.wall_time
        world.notices.extend(self.alerts.flush(now, world.clock.calendar_time, world))
        self._watch_sat(world, sat_on)
        self._watch_spotted(world, sat_on)

    def _watch_sat(self, world: World, sat_on: bool) -> None:
        from fall_of_penghu.world.notices import SAT, post

        if self._sat_was is None:
            self._sat_was = sat_on
            return
        if sat_on == self._sat_was:
            return
        self._sat_was = sat_on
        if sat_on:
            post(world, SAT, "SAT up", 0.0, 0.0)
        else:
            post(world, SAT, "SAT down", 0.0, 0.0, sat_down=True)

    def _watch_spotted(self, world: World, sat_on: bool) -> None:
        from fall_of_penghu.world.entities.dynamic import DynamicObject
        from fall_of_penghu.world.entities.kinds import SHOT_KINDS, kind_label
        from fall_of_penghu.world.notices import SPOTTED, post

        cover = self.cover
        if cover is None:
            return
        live = {obj.id for obj in world.entities.items if obj.active}
        self._spotted = {
            key for key in self._spotted if key[0] in live and key[1] in live
        }
        spotters = [
            obj
            for obj in self._visible.get(FACTION_PLAYER, ())
            if obj.faction == FACTION_CHINA
            and obj.active
            and obj.kind in ("drone", "scout")
        ]
        if not spotters:
            return
        darkness = self._darkness
        for eye in spotters:
            channel = "visual_primitive" if eye.kind == "drone" else "visual_advanced"
            by = "drone" if eye.kind == "drone" else "scout"
            for unit in world.entities.items:
                if not isinstance(unit, DynamicObject) or not unit.active:
                    continue
                if unit.faction != FACTION_PLAYER or unit.mobility != "land":
                    continue
                if unit.stowed or unit.kind in SHOT_KINDS:
                    continue
                key = (unit.id, eye.id)
                if key in self._spotted:
                    continue
                terrain = cover.at(unit.x, unit.y, "ground")
                if sat_on and terrain != "forest":
                    continue
                radius = self.catalog.scaled_range_m(
                    channel, unit.kind, darkness, emitter_kind=eye.kind
                )
                if radius is None:
                    continue
                radius *= self.catalog.cover_factor(channel, terrain)
                if radius <= 0.0:
                    continue
                if hypot(unit.x - eye.x, unit.y - eye.y) > radius:
                    continue
                self._spotted.add(key)
                post(
                    world,
                    SPOTTED,
                    f"{kind_label(unit.kind)} spotted by {by}",
                    unit.x,
                    unit.y,
                    object_ids=(unit.id, eye.id),
                    filter_kind=unit.kind,
                    icon_kinds=(unit.kind,),
                )

    def _snapshot(self, objects: list[GameObject]) -> bool:
        moved = len(objects) != self._pose_n
        live: set[str] = set()
        for obj in objects:
            live.add(obj.id)
            stowed = bool(getattr(obj, "stowed", False))
            old = self._pose.get(obj.id)
            if (
                old is None
                or old[0] != obj.x
                or old[1] != obj.y
                or old[3] != obj.kind
                or old[5] != obj.faction
                or old[9] != obj.active
                or self._stowed.get(obj.id) != stowed
            ):
                moved = True
            self._stowed[obj.id] = stowed
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
        if live != self._live_ids:
            moved = True
            for oid in self._live_ids - live:
                self._pose.pop(oid, None)
                self._stowed.pop(oid, None)
            self._live_ids = live
        self._pose_n = len(objects)
        return moved

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
        nearby, reach = self._index_emitters(emitters, darkness)
        seen = list(own)
        for target in others:
            channels = self.catalog.detectable_by(target.kind)
            role = self.catalog.cover_role(target.kind)
            ground = cover.at(target.x, target.y, role) if cover is not None else "open"
            if self._detected(
                target,
                channels,
                ground,
                nearby,
                reach,
                lookouts,
                occupied,
                sat_for_faction,
                darkness,
                base=base,
                deny=deny,
            ):
                seen.append(target)
        return seen

    def _index_emitters(
        self,
        emitters: list[tuple[GameObject, str]],
        darkness: float,
    ) -> tuple[UniformGrid, list[tuple[GameObject, str]]]:
        grid = UniformGrid(EMITTER_CELL_M)
        rows: list[tuple[GameObject, str]] = []
        for src, channel in emitters:
            radius = self.catalog.emitter_range_m(channel, src.kind)
            if radius is None:
                radius = self.catalog.default_range_m(channel)
            if radius is None or radius <= 0.0:
                continue
            radius *= self.catalog.darkness_scale(channel, darkness)
            if radius <= 0.0:
                continue
            i = len(rows)
            rows.append((src, channel))
            grid.insert(
                i, src.x - radius, src.y - radius, src.x + radius, src.y + radius
            )
        return grid, rows

    def _detected(
        self,
        target: GameObject,
        channels: frozenset[str],
        cover: str,
        nearby: UniformGrid,
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
        tx, ty = target.x, target.y
        circles: list[tuple[float, float, float]] = []
        for i in nearby.at(tx, ty):
            src, channel = emitters[i]
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
            circles.append((src.x, src.y, radius))
        circles.sort(key=lambda row: row[2], reverse=True)
        for sx, sy, radius in circles:
            if hypot(sx - tx, sy - ty) <= radius:
                return True
        if lookouts is not None and "lookout" in channels:
            radius = self.catalog.scaled_range_m("lookout", target.kind, darkness)
            if radius is not None:
                radius *= self.catalog.cover_factor("lookout", cover)
                here = getattr(target, "island_id", None)
                on_island = here() if callable(here) else None
                if radius > 0.0 and lookouts.covers(
                    tx,
                    ty,
                    radius,
                    occupied,
                    base=base,
                    deny=deny,
                    on_island=on_island,
                ):
                    return True
        return False
