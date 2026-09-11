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


@dataclass(frozen=True)
class SetDoctrine:
    object_id: str
    doctrine: str


@dataclass(frozen=True)
class SetEngageFilter:
    object_id: str
    kinds: tuple[str, ...] | None


@dataclass(frozen=True)
class SetAim:
    object_id: str
    target: tuple[float, float] | None


@dataclass(frozen=True)
class SetFocus:
    object_id: str
    ids: tuple[str, ...] | None


@dataclass(frozen=True)
class WreckObject:
    object_id: str


Command = SetRoute | Halt | SetDoctrine | SetEngageFilter | SetAim | SetFocus | WreckObject
