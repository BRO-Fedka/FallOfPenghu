from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SetRoute:
    object_id: str
    mode: str = "auto"
    target: tuple[float, float] | None = None
    vertices: tuple[tuple[float, float], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Halt:
    object_id: str


Command = SetRoute | Halt
