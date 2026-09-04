from __future__ import annotations

import json
from pathlib import Path

from fall_of_penghu.world.entities.collect_sites import SITES_NAME, persist_removed_ports
from fall_of_penghu.world.entities.command import Command, Halt, SetRoute
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_PLAYER, GameObject
from fall_of_penghu.world.entities.planner import Planner
from fall_of_penghu.world.entities.static import StaticObject
from fall_of_penghu.world.map import MapData


class ObjectManager:
    """Registry, sim step, snapshot, and the only command door."""

    def __init__(self) -> None:
        self._by_id: dict[str, GameObject] = {}
        self.planner: Planner | None = None
        self._sites_path: Path | None = None

    @property
    def items(self) -> list[GameObject]:
        return list(self._by_id.values())

    def get(self, object_id: str) -> GameObject | None:
        return self._by_id.get(object_id)

    def add(self, obj: GameObject) -> None:
        self._by_id[obj.id] = obj

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
        for rec in data.get("sites") or []:
            self.add(
                StaticObject(
                    id=str(rec["id"]),
                    faction=FACTION_PLAYER,
                    kind=str(rec["kind"]),
                    name=str(rec["name"]),
                    x=float(rec["x"]),
                    y=float(rec["y"]),
                )
            )
        for rec in data.get("units") or []:
            self.add(
                DynamicObject(
                    id=str(rec["id"]),
                    faction=FACTION_PLAYER,
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

    def forget_ports(self, object_ids: set[str]) -> list[str]:
        """Remove selected ports from the match and from sites.json for good."""
        dropped: list[str] = []
        points: list[tuple[float, float]] = []
        for oid in list(object_ids):
            obj = self._by_id.get(oid)
            if obj is None or obj.kind != "port":
                continue
            points.append((obj.x, obj.y))
            del self._by_id[oid]
            dropped.append(oid)
        if points and self._sites_path is not None:
            persist_removed_ports(self._sites_path, points)
        return dropped

    def snapshot(self, faction: str) -> list[GameObject]:
        """Own units always. Enemies later, 1:1 if in sensor range."""
        out: list[GameObject] = []
        for obj in self._by_id.values():
            if obj.faction == faction:
                out.append(obj)
        return out

    def dispatch(self, cmd: Command) -> None:
        if isinstance(cmd, Halt):
            obj = self._by_id.get(cmd.object_id)
            if isinstance(obj, DynamicObject):
                obj.route = None
            return
        if isinstance(cmd, SetRoute):
            obj = self._by_id.get(cmd.object_id)
            if not isinstance(obj, DynamicObject) or not obj.active:
                return
            if self.planner is None:
                return
            route = self.planner.plan(obj, cmd)
            if route is None or route.remaining_length() <= 1.0:
                return
            obj.route = route

    def update(self, dt_sim: float) -> None:
        for obj in self._by_id.values():
            if isinstance(obj, DynamicObject):
                obj.update(dt_sim)

    def step(self, dt_sim: float) -> None:
        self.update(dt_sim)


Entities = ObjectManager
