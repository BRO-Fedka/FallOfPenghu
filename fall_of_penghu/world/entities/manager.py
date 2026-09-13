from __future__ import annotations

import json
from pathlib import Path

from fall_of_penghu.world.entities.collect_sites import (
    SITES_NAME,
    persist_forget,
    persist_spawn,
)
from fall_of_penghu.world.entities.kinds import is_static_kind, kind_label
from fall_of_penghu.world.entities.command import (
    Command,
    Halt,
    SetAim,
    SetDoctrine,
    SetEngageFilter,
    SetFocus,
    SetRoute,
    WreckObject,
)
from fall_of_penghu.world.combat.health import wreck
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import (
    FACTION_CHINA,
    FACTION_PLAYER,
    GameObject,
)
from fall_of_penghu.world.entities.planner import Planner
from fall_of_penghu.world.entities.static import StaticObject
from fall_of_penghu.world.map import MapData


class ObjectManager:
    """Registry, sim step, snapshot, and the only command door."""

    def __init__(self) -> None:
        self._by_id: dict[str, GameObject] = {}
        self.planner: Planner | None = None
        self._sites_path: Path | None = None
        self._view = None
        self._catalog = None
        self._cover = None
        self.forgotten_ids: set[str] = set()
        self._transport = None

    @property
    def items(self) -> list[GameObject]:
        return list(self._by_id.values())

    def get(self, object_id: str) -> GameObject | None:
        return self._by_id.get(object_id)

    def add(self, obj: GameObject) -> None:
        if self._catalog is not None:
            self._stamp(obj)
        self._by_id[obj.id] = obj

    def _stamp(self, obj: GameObject) -> None:
        catalog = self._catalog
        if catalog is None:
            return
        if isinstance(obj, DynamicObject):
            obj.speed_mps = catalog.speed_mps(obj.kind)
            if catalog.engagement_m(obj.kind) is not None:
                obj.doctrine = catalog.default_doctrine(obj.kind)
        obj.max_hp = catalog.max_hp(obj.kind)
        obj.hp = obj.max_hp
        if isinstance(obj, DynamicObject) and catalog.limited_ammo(obj.kind):
            obj.clip = catalog.clip_size(obj.kind)
            obj.reserve = catalog.reserve_size(obj.kind)
            obj.reloading = False
            obj.rest_ammo_acc = 0.0

    def discard(self, object_id: str) -> None:
        self._by_id.pop(object_id, None)

    def populate(self, world: MapData, sites_path: Path | None = None) -> None:
        path = sites_path
        if path is None:
            if world.map_dir is None:
                raise FileNotFoundError("sites.json path is unknown")
            path = world.map_dir / SITES_NAME
        self._sites_path = Path(path)
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("format") != "fall-of-penghu-sites":
            raise ValueError("unexpected sites format")
        self.forgotten_ids = {str(item) for item in (data.get("removed_ids") or [])}
        for rec in data.get("sites") or []:
            if str(rec.get("id")) in self.forgotten_ids:
                continue
            self.add(
                StaticObject(
                    id=str(rec["id"]),
                    faction=str(rec.get("faction") or FACTION_PLAYER),
                    kind=str(rec["kind"]),
                    name=str(rec["name"]),
                    x=float(rec["x"]),
                    y=float(rec["y"]),
                )
            )
        for rec in data.get("units") or []:
            if str(rec.get("id")) in self.forgotten_ids:
                continue
            self.add(
                DynamicObject(
                    id=str(rec["id"]),
                    faction=str(rec.get("faction") or FACTION_PLAYER),
                    kind=str(rec["kind"]),
                    name=str(rec["name"]),
                    x=float(rec["x"]),
                    y=float(rec["y"]),
                    heading=float(rec.get("heading") or 0.0),
                    speed_mps=float(rec.get("speed_mps") or 10.0),
                    mobility=str(rec.get("mobility") or "land"),
                )
            )
        self.planner = Planner(world)
        self.planner.land.bind_bridges(
            [obj for obj in self._by_id.values() if obj.kind == "bridge"]
        )

    def bind_transport(self, transport) -> None:
        self._transport = transport

    def launch_ferry(
        self, port_id: str, dest: tuple[float, float]
    ) -> DynamicObject | None:
        if self._transport is None:
            return None
        return self._transport.launch(port_id, dest)

    def recall_ferry(self, port_id: str, ferry_id: str) -> bool:
        if self._transport is None:
            return False
        return self._transport.recall(port_id, ferry_id)

    def load_ferry(self, ferry_id: str, cargo_id: str) -> bool:
        if self._transport is None:
            return False
        return self._transport.load_onto(ferry_id, cargo_id)

    def unload_ferry(
        self,
        ferry_id: str,
        dest: tuple[float, float],
        dest_port_id: str | None = None,
    ) -> bool:
        if self._transport is None:
            return False
        return self._transport.unload_at(
            ferry_id, dest, dest_port_id=dest_port_id
        )

    def bind_motion(self, catalog, cover) -> None:
        self._catalog = catalog
        self._cover = cover
        for obj in self._by_id.values():
            self._stamp(obj)

    def forget_ports(self, object_ids: set[str]) -> list[str]:
        """Remove selected ports from the match and from sites.json for good."""
        ports = {
            oid
            for oid in object_ids
            if getattr(self.get(oid), "kind", "") == "port"
        }
        return self.forget_objects(ports)

    def spawn_debug(
        self, kind: str, x: float, y: float, faction: str = FACTION_PLAYER
    ) -> GameObject | None:
        owner = faction if faction in (FACTION_PLAYER, FACTION_CHINA) else FACTION_PLAYER
        oid = self._next_id(kind)
        name = kind_label(kind)
        if is_static_kind(kind):
            obj = StaticObject(
                id=oid,
                faction=owner,
                kind=kind,
                name=name,
                x=x,
                y=y,
            )
        else:
            mobility = self._mobility(kind)
            speed = self._catalog.speed_mps(kind) if self._catalog is not None else 10.0
            obj = DynamicObject(
                id=oid,
                faction=owner,
                kind=kind,
                name=name,
                x=x,
                y=y,
                speed_mps=speed,
                mobility=mobility,
            )
        self.add(obj)
        self.forgotten_ids.discard(oid)
        if kind == "bridge":
            self._rebind_bridges()
        if self._sites_path is not None:
            persist_spawn(self._sites_path, self._site_rec(obj), static=is_static_kind(kind))
        return obj

    def forget_objects(self, object_ids: set[str]) -> list[str]:
        """Remove selected objects from the match and from sites.json."""
        dropped: list[str] = []
        ports: list[tuple[float, float]] = []
        lost_bridge = False
        for oid in list(object_ids):
            obj = self._by_id.get(oid)
            if obj is None:
                continue
            if obj.kind == "port":
                ports.append((obj.x, obj.y))
            if obj.kind == "bridge":
                lost_bridge = True
            del self._by_id[oid]
            dropped.append(oid)
            self.forgotten_ids.add(oid)
        if dropped and self._sites_path is not None:
            persist_forget(self._sites_path, dropped, ports)
        if lost_bridge:
            self._rebind_bridges()
        return dropped

    def _rebind_bridges(self) -> None:
        if self.planner is None:
            return
        self.planner.land.bind_bridges(
            [obj for obj in self._by_id.values() if obj.kind == "bridge"]
        )

    def _next_id(self, kind: str) -> str:
        n = 1
        while True:
            oid = f"dbg_{kind}_{n:03d}"
            if oid not in self._by_id:
                return oid
            n += 1

    def _mobility(self, kind: str) -> str:
        if self._catalog is None:
            return "land"
        role = self._catalog.cover_role(kind)
        if role == "air":
            return "air"
        if role == "sea":
            return "sea"
        return "land"

    @staticmethod
    def _site_rec(obj: GameObject) -> dict:
        rec = {
            "id": obj.id,
            "kind": obj.kind,
            "name": obj.name,
            "faction": obj.faction,
            "x": obj.x,
            "y": obj.y,
        }
        if isinstance(obj, DynamicObject):
            rec["heading"] = obj.heading
            rec["speed_mps"] = obj.speed_mps
            rec["mobility"] = obj.mobility
        return rec

    def snapshot(self, faction: str) -> list[GameObject]:
        """Own units always. Enemies as live instances if currently sensed."""
        if self._view is not None:
            return self._view(faction)
        return [obj for obj in self._by_id.values() if obj.faction == faction]

    def dispatch(self, cmd: Command, *, as_faction: str) -> None:
        """Apply a command only if the object belongs to `as_faction`."""
        if isinstance(cmd, WreckObject):
            obj = self._by_id.get(cmd.object_id)
            if obj is None or obj.kind != "bridge" or not obj.active:
                return
            if as_faction != FACTION_PLAYER:
                return
            wreck(obj)
            return
        obj = self._by_id.get(cmd.object_id)
        if not isinstance(obj, DynamicObject) or obj.faction != as_faction:
            return
        if obj.kind in ("intercept", "tracer", "shell"):
            return
        if isinstance(cmd, Halt):
            obj.route = None
            obj.armed = False
            obj.strike_id = None
            if self._transport is not None:
                self._transport.on_halt(obj.id)
            return
        if isinstance(cmd, SetDoctrine):
            allowed = {
                "aaw": ("fire", "hold", "air_only", "missiles_only"),
                "aa_pickup": ("fire", "hold", "air_only"),
                "infantry": ("fire", "hold"),
                "tank": ("fire", "hold"),
                "artillery": ("fire", "hold"),
            }
            if cmd.doctrine in allowed.get(obj.kind, ()):
                obj.doctrine = cmd.doctrine
            return
        if isinstance(cmd, SetEngageFilter):
            catalog = self._catalog
            if catalog is None or catalog.engage_mobility(obj.kind) is None:
                return
            allowed = catalog.engage_kinds_for(obj.kind)
            if not allowed:
                return
            if cmd.kinds is None:
                obj.engage_kinds = None
                return
            picked = frozenset(k for k in cmd.kinds if k in allowed)
            obj.engage_kinds = None if picked == allowed else picked
            return
        if isinstance(cmd, SetAim):
            if obj.kind != "artillery":
                return
            obj.aim_xy = cmd.target
            return
        if isinstance(cmd, SetFocus):
            if cmd.ids is None:
                obj.focus_ids = frozenset()
            else:
                obj.focus_ids = frozenset(cmd.ids)
            return
        if isinstance(cmd, SetRoute):
            if not obj.active or self.planner is None:
                return
            if obj.stowed:
                return
            if obj.mobility == "land" and self._transport is not None:
                self._transport.on_halt(obj.id)
            route = self.planner.plan(obj, cmd, intact=self.bridge_intact)
            if route is None or route.remaining_length() <= 1.0:
                if (
                    obj.mobility == "land"
                    and cmd.target is not None
                    and self._transport is not None
                ):
                    self._transport.request(obj, cmd.target)
                return
            obj.route = route
            if obj.kind == "drone":
                obj.armed = True

    def bridge_intact(self, bridge_id: str) -> bool:
        obj = self._by_id.get(bridge_id)
        if obj is None:
            return True
        return bool(obj.active)

    def update(self, dt_sim: float) -> None:
        from fall_of_penghu.profile import scope

        with scope("entities.locate"):
            for obj in self._by_id.values():
                if not isinstance(obj, DynamicObject) or obj.stowed:
                    continue
                if self.planner is None or obj.kind in (
                    "intercept",
                    "tracer",
                    "shell",
                ):
                    continue
                spot = self.planner.land.locate(obj.x, obj.y)
                if spot is None:
                    obj.ground = None
                    obj.ground_id = None
                else:
                    obj.ground, obj.ground_id = spot
        with scope("entities.move"):
            for obj in self._by_id.values():
                if not isinstance(obj, DynamicObject) or obj.stowed:
                    continue
                speed = self._move_speed(obj)
                if obj.route is not None:
                    bid = obj.route.bridge_entering(
                        obj.route.s, speed * max(dt_sim, 0.0)
                    ) or obj.route.bridge_at(obj.route.s)
                    if bid is not None and not self.bridge_intact(bid):
                        obj.route = None
                obj.update(dt_sim, speed)

    def _move_speed(self, obj: DynamicObject) -> float:
        speed = obj.speed_mps
        if obj.mobility != "land" or self._catalog is None:
            return speed
        if self.planner is not None and self.planner.land.on_road(obj.x, obj.y):
            return speed
        cover = "open"
        if self._cover is not None:
            cover = self._cover.at(obj.x, obj.y, "ground")
        return speed * self._catalog.offroad_factor(obj.kind, cover)

    def step(self, dt_sim: float) -> None:
        self.update(dt_sim)


Entities = ObjectManager
