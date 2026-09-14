"""Load pre-baked HUD chrome glyphs. Recolor happens in tools/bake_hud_icons.py."""

from __future__ import annotations

from pathlib import Path

import pygame

from fall_of_penghu.paths import resource_root

ROOT = resource_root()
HUD_ICON_DIR = ROOT / "assets" / "icons" / "hud"


class HudIcons:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else HUD_ICON_DIR
        self._src: dict[str, pygame.Surface | None] = {}
        self._cache: dict[tuple[str, int], pygame.Surface] = {}

    def get(self, name: str, size: int) -> pygame.Surface | None:
        key = (name, int(size))
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        src = self._load(name)
        if src is None:
            return None
        if size > 0 and (src.get_width() != size or src.get_height() != size):
            src = pygame.transform.smoothscale(src, (size, size))
        self._cache[key] = src
        return src

    def _load(self, name: str) -> pygame.Surface | None:
        if name in self._src:
            return self._src[name]
        path = self._root / f"{name}.png"
        surf: pygame.Surface | None = None
        if path.is_file():
            try:
                surf = pygame.image.load(str(path)).convert_alpha()
            except pygame.error:
                surf = None
        self._src[name] = surf
        return surf
