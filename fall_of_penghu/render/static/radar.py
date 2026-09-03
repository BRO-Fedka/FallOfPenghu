from __future__ import annotations

from pathlib import Path

# Radar look is independent of time of day. Do not mix these into the normal
# palette or into land/veg/sea shaders.
INK = (40, 210, 90)
AIRPORT = (17, 90, 40)
GRID = (8, 48, 22)
CONTOUR = (4, 30, 15)
RADAR = {
    "sea": (0, 0, 0),
    "taiwan": (0, 0, 0),
    "land": (0, 0, 0),
    "rock": (0, 0, 0),
    "forest": (0, 0, 0),
    "grass": (0, 0, 0),
    "building": INK,
    "concrete": (0, 0, 0),
    "road": (0, 0, 0),
    "bridge": (236, 196, 36),
    "airport": AIRPORT,
    "coast": INK,
    "grid": GRID,
    "contour": CONTOUR,
    "hud": (160, 230, 220),
}

GRID_M = 1000.0
COAST_PX = 1.5
LINE_PX_MAX = 2.0
GRID_PX = 2.0
CONTOUR_PX = 1.0
CONTOUR_STEP_M = 10.0
DEM_NAME = "dem.npz"


def dem_path(map_dir: Path | None) -> Path | None:
    if map_dir is None:
        return None
    path = Path(map_dir) / DEM_NAME
    return path if path.is_file() else None
