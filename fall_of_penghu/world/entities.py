from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Entity:
    """Something that lives in map meters. Render.dynamic draws these."""

    x: float
    y: float
    kind: str = "marker"


@dataclass
class Entities:
    items: list[Entity] = field(default_factory=list)

    def step(self, dt_sim: float) -> None:
        del dt_sim
