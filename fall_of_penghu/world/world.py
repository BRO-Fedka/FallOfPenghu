from __future__ import annotations

from pathlib import Path

from fall_of_penghu.world.clock import Clock
from fall_of_penghu.world.combat import Combat
from fall_of_penghu.world.control import IslandControl
from fall_of_penghu.world.entities import Entities
from fall_of_penghu.world.entities.transport import Transport
from fall_of_penghu.world.events import ContactNotice
from fall_of_penghu.world.map import MapData, load_map
from fall_of_penghu.world.perception import DetectionCatalog, Perception
from fall_of_penghu.world.victory import DefeatReport


class World:
    """Match truth in meters. Imports nobody from input, ui, render, or ai."""

    def __init__(
        self,
        map_data: MapData,
        *,
        clock: Clock | None = None,
        entities: Entities | None = None,
        seed: int = 0,
        catalog: DetectionCatalog | None = None,
    ) -> None:
        self.map = map_data
        self.clock = clock if clock is not None else Clock()
        self.entities = entities if entities is not None else Entities()
        self.seed = seed
        self.catalog = catalog if catalog is not None else DetectionCatalog.load()
        self.perception = Perception(self.catalog)
        self.combat = Combat(seed)
        self.transport = Transport()
        self.control = IslandControl()
        self.entities._view = self.perception.visible_objects
        self.notices: list[ContactNotice] = []
        self.sim_bake = None
        self.kills: dict[str, int] = {}
        self.defeat: DefeatReport | None = None

    @classmethod
    def load(cls, map_dir: Path) -> World:
        from fall_of_penghu.world.map_bake import MapBake

        map_dir = Path(map_dir)
        world = cls(load_map(map_dir))
        world.sim_bake = MapBake.try_load(world)
        if world.sim_bake is not None:
            print("Sim bake cache hit", flush=True)
        world.entities.populate(world.map, bake=world.sim_bake)
        planner = world.entities.planner
        if planner is not None and planner.sea_from_bake:
            print("Sea nav cache hit", flush=True)
        elif (
            world.sim_bake is not None
            and planner is not None
            and world.sim_bake.put_sea(world)
        ):
            print("Writing sea nav into sim bake…", flush=True)
            world.sim_bake.save(world)
        world.perception.bind_map(world)
        world.entities.bind_motion(world.catalog, world.perception.cover)
        world.transport.bind(world)
        world.entities.bind_transport(world.transport)
        world.transport.seed(world)
        world.control.bake(world)
        world.perception.step(world)
        return world

    def step(self) -> None:
        self.entities.step(self.clock.dt_sim)
        self.transport.step(self)
        self.control.step(self)
        self.perception.step(self)
        self.combat.step(self)

    def drain_notices(self) -> list[ContactNotice]:
        out = self.notices
        self.notices = []
        return out
