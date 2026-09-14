from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContactNotice:
    """Posted after a cluster window closes. UI and clock read this."""

    faction: str
    object_ids: tuple[str, ...]
    x: float
    y: float
    text: str
    slow_time: bool
    category: str = "contact"
    filter_kind: str | None = None
    icon_kinds: tuple[str, ...] = ()
    calendar_time: float = 0.0
    sat_down: bool = False
