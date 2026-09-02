from __future__ import annotations

from pathlib import Path

from fall_of_penghu.world.clock import Clock
from fall_of_penghu.world.entities import Entities
from fall_of_penghu.world.map import MapData, load_map


class World:
    """Match truth in meters. Imports nobody from input, ui, render, or ai."""

    def __init__(
        self,
        map_data: MapData,
        *,
        clock: Clock | None = None,
        entities: Entities | None = None,
        seed: int = 0,
    ) -> None:
        self.map = map_data
        self.clock = clock if clock is not None else Clock()
        self.entities = entities if entities is not None else Entities()
        self.seed = seed

    @classmethod
    def load(cls, map_dir: Path) -> World:
        return cls(load_map(map_dir))
