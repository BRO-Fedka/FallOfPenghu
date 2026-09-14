"""Bake HUD chrome icons from the author's colored sources.

Every pixel keeps its alpha; RGB is replaced with a flat color.
White glyphs for pause / help / map / radar. Satellite gets green and red.

    python tools/bake_hud_icons.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "assets" / "icons" / "hud" / "source"
OUT_DIR = ROOT / "assets" / "icons" / "hud"

WHITE = (255, 255, 255)
SAT_GREEN = (72, 220, 96)
SAT_RED = (220, 56, 48)

JOBS = (
    ("pause.png", "pause.png", WHITE),
    ("help.png", "help.png", WHITE),
    ("map.png", "map.png", WHITE),
    ("radar.png", "radar.png", WHITE),
    ("satellite.png", "satellite_green.png", SAT_GREEN),
    ("satellite.png", "satellite_red.png", SAT_RED),
)


def paint(src: pygame.Surface, rgb: tuple[int, int, int]) -> pygame.Surface:
    surf = src.convert_alpha()
    out = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    r, g, b = rgb
    w, h = surf.get_size()
    for y in range(h):
        for x in range(w):
            _r, _g, _b, a = surf.get_at((x, y))
            out.set_at((x, y), (r, g, b, a))
    return out


def main() -> int:
    pygame.init()
    pygame.display.set_mode((1, 1))
    if not SRC_DIR.is_dir():
        print(f"missing {SRC_DIR}", flush=True)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for src_name, dest_name, rgb in JOBS:
        path = SRC_DIR / src_name
        if not path.is_file():
            print(f"skip {src_name}: not found", flush=True)
            continue
        src = pygame.image.load(str(path)).convert_alpha()
        baked = paint(src, rgb)
        dest = OUT_DIR / dest_name
        pygame.image.save(baked, str(dest))
        print(f"{src_name} -> {dest_name}  {rgb}  {baked.get_size()}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
