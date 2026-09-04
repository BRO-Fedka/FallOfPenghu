"""Load map/radar icons and bake faction colour once.

Layout: assets/icons/<static|units>/<name>/{map,radar}.png
Art is native size (sites ~20px, units ~16px) and is centered on a 24px chip.
Pink pixels drop R (P), B (C), or both (T) once at import.
"""

from __future__ import annotations

from pathlib import Path

import pygame

from fall_of_penghu.world.entities.game_object import (
    FACTION_CHINA,
    FACTION_PLAYER,
    FACTION_TAIWAN,
)

ROOT = Path(__file__).resolve().parents[3]
ICON_DIR = ROOT / "assets" / "icons"
CHIP = 24

# Game kind -> folder under assets/icons/. Unlisted kinds use static/<kind> or units/<kind>.
KIND_FOLDERS: dict[str, str] = {
    "port": "static/seaport",
    "seaport": "static/seaport",
    "airfield": "static/airport",
    "airport": "static/airport",
    "bridge": "static/bridge",
    "aaw": "units/aaw",
}

_PINK_FLOOR = 32
_PINK_BIAS = 16


def _is_pink(r: int, g: int, b: int, radar: bool) -> bool:
   # return r > _PINK_FLOOR and b > _PINK_FLOOR and (r + b) > (2 * g + _PINK_BIAS)
    # return 
    return radar or (0<r+g+b<255*3)


def apply_faction(src: pygame.Surface, faction: str,radar: bool) -> pygame.Surface:
    """Copy a pink source and strip R and/or B on magenta pixels only."""
    surf = src.convert_alpha()
    w, h = surf.get_size()
    drop_r = faction in (FACTION_PLAYER, FACTION_TAIWAN)
    drop_b = faction in (FACTION_CHINA, FACTION_TAIWAN)
    if not drop_r and not drop_b:
        return surf
    for y in range(h):
        for x in range(w):
            r, g, b, a = surf.get_at((x, y))
            if a == 0 or not _is_pink(r, g, b,radar):
                continue
            if drop_r:
                r = 0
            if drop_b:
                b = 0
            surf.set_at((x, y), (r, g, b, a))
    return surf


def _center_on_chip(src: pygame.Surface) -> pygame.Surface:
    chip = pygame.Surface((CHIP, CHIP), pygame.SRCALPHA)
    chip.blit(src, src.get_rect(center=(CHIP // 2, CHIP // 2)))
    return chip


def _folder_for(kind: str, root: Path) -> Path | None:
    rel = KIND_FOLDERS.get(kind)
    if rel is not None:
        path = root / rel
        return path if path.is_dir() else None
    for group in ("static", "units"):
        path = root / group / kind
        if path.is_dir():
            return path
    return None


class IconStore:
    """Kind + faction + radar → 24px chip. Missing files stay None."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else ICON_DIR
        self._sources: dict[tuple[str, bool], pygame.Surface | None] = {}
        self._cache: dict[tuple[str, str, bool], pygame.Surface | None] = {}

    def get(self, kind: str, faction: str, radar: bool) -> pygame.Surface | None:
        key = (kind, faction, radar)
        if key in self._cache:
            return self._cache[key]
        src = self._load_source(kind, radar)
        baked = apply_faction(src, faction, radar) if src is not None else None
        if baked is not None:
            baked = _center_on_chip(baked)
        self._cache[key] = baked
        return baked

    def _load_source(self, kind: str, radar: bool) -> pygame.Surface | None:
        key = (kind, radar)
        if key in self._sources:
            return self._sources[key]
        folder = _folder_for(kind, self._root)
        if folder is None:
            self._sources[key] = None
            return None
        names = ("radar.png", "map.png") if radar else ("map.png",)
        surf: pygame.Surface | None = None
        for name in names:
            path = folder / name
            if not path.is_file():
                continue
            try:
                surf = pygame.image.load(str(path)).convert_alpha()
                break
            except pygame.error:
                surf = None
                break
        self._sources[key] = surf
        return surf
