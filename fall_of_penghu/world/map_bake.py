from __future__ import annotations

import pickle
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shapely import wkb

from fall_of_penghu.spatial import UniformGrid
from fall_of_penghu.world.perception.cover import CELL_M, ROAD_ON_M
from fall_of_penghu.world.perception.lookout import _Shore

if TYPE_CHECKING:
    from fall_of_penghu.ai.coverage import ForestCoverage
    from fall_of_penghu.ai.heatmap import IslandHeatmaps
    from fall_of_penghu.world.perception.cover import CoverIndex
    from fall_of_penghu.world.perception.lookout import IslandLookouts
    from fall_of_penghu.world.world import World

FORMAT = "fall-of-penghu-sim-bake"
VERSION = 1
BAKE_NAME = "sim_bake.pkl"
LANE_OVERLAP = 0.70


class MapBake:
    """Cover grids, lookout shores, heat land masks, forest lanes."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    @classmethod
    def try_load(cls, world: World) -> MapBake | None:
        path = _path(world)
        if path is None or not path.is_file():
            return None
        try:
            with path.open("rb") as fh:
                data = pickle.load(fh)
        except (OSError, pickle.UnpicklingError, EOFError, TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        if data.get("format") != FORMAT or data.get("version") != VERSION:
            return None
        if data.get("fingerprint") != fingerprint(world):
            return None
        for key in ("cover", "lookouts", "heat", "forest"):
            if key not in data:
                return None
        return cls(data)

    def save(self, world: World) -> None:
        path = _path(world)
        if path is None:
            return
        try:
            with path.open("wb") as fh:
                pickle.dump(self.payload, fh, protocol=4)
        except OSError:
            return

    @classmethod
    def capture(
        cls,
        world: World,
        cover: CoverIndex,
        lookouts: IslandLookouts,
        heat: IslandHeatmaps,
        forest: ForestCoverage,
    ) -> MapBake:
        shores: dict[int, dict[str, Any] | None] = {}
        for iid, shore in lookouts._shores.items():
            if shore is None or shore.geom is None:
                shores[int(iid)] = None
                continue
            shores[int(iid)] = {
                "wkb": bytes(shore.geom.wkb),
                "minx": float(shore.minx),
                "miny": float(shore.miny),
                "maxx": float(shore.maxx),
                "maxy": float(shore.maxy),
                "cx": float(shore.cx),
                "cy": float(shore.cy),
                "cr": float(shore.cr),
            }
        grids = []
        for iid, grid in heat.grids.items():
            grids.append(
                {
                    "island": int(iid),
                    "origin": (float(grid.origin[0]), float(grid.origin[1])),
                    "cell_m": float(grid.cell_m),
                    "w": int(grid.w),
                    "h": int(grid.h),
                    "n_land": int(grid.n_land),
                    "land": bytes(grid.land),
                    "coastal": bytes(grid.coastal),
                }
            )
        return cls(
            {
                "format": FORMAT,
                "version": VERSION,
                "fingerprint": fingerprint(world),
                "cover": {
                    "forest": cover._forest.dump_cells(),
                    "grass": cover._grass.dump_cells(),
                    "roads": cover._roads.dump_cells(),
                },
                "lookouts": {
                    "inhabited": sorted(int(i) for i in lookouts.inhabited),
                    "shores": shores,
                },
                "heat": {
                    "cell_m": float(heat.cell_m),
                    "inhabited": sorted(int(i) for i in heat.inhabited),
                    "grids": grids,
                },
                "forest": {
                    "lane_m": float(forest.lane_m),
                    "lanes": {
                        int(iid): list(pts) for iid, pts in forest.lanes.items()
                    },
                },
            }
        )


def fingerprint(world: World) -> dict[str, Any]:
    catalog = world.catalog
    cell = max(50.0, catalog.heat_cell_m)
    reach = catalog.emitter_range_m("visual_advanced", "scout") or 0.0
    reach *= catalog.darkness_scale("visual_advanced", 0.0)
    reach *= catalog.cover_factor("visual_advanced", "forest")
    lane_m = min(cell, 160.0) if reach <= 0.0 else max(80.0, reach * LANE_OVERLAP)
    md = world.map
    return {
        "format": FORMAT,
        "version": VERSION,
        "coast_hash": _layer_hash(md.map_dir, "coast.geojson"),
        "vegetation_hash": _layer_hash(md.map_dir, "vegetation.geojson"),
        "roads_hash": _layer_hash(md.map_dir, "roads.geojson"),
        "buildings_hash": _layer_hash(md.map_dir, "buildings.geojson"),
        "coast_count": len(md.coast),
        "vegetation_count": len(md.vegetation),
        "roads_count": len(md.roads),
        "buildings_count": len(md.buildings),
        "heat_cell_m": float(catalog.heat_cell_m),
        "lookout_simplify_m": float(catalog.lookout_simplify_m),
        "cover_cell_m": float(CELL_M),
        "road_on_m": float(ROAD_ON_M),
        "lane_m": float(lane_m),
    }


def restore_grid(cells: dict, cell_m: float) -> UniformGrid:
    packed: dict[tuple[int, int], list[int]] = {}
    for key, ids in cells.items():
        gx, gy = key
        packed[(int(gx), int(gy))] = [int(i) for i in ids]
    return UniformGrid.from_cells(cell_m, packed)


def restore_shores(raw: dict) -> dict[int, _Shore | None]:
    out: dict[int, _Shore | None] = {}
    for key, row in raw.items():
        iid = int(key)
        if row is None:
            out[iid] = None
            continue
        geom = wkb.loads(row["wkb"])
        out[iid] = _Shore(
            geom=geom,
            minx=float(row["minx"]),
            miny=float(row["miny"]),
            maxx=float(row["maxx"]),
            maxy=float(row["maxy"]),
            cx=float(row["cx"]),
            cy=float(row["cy"]),
            cr=float(row["cr"]),
        )
    return out


def _path(world: World) -> Path | None:
    if world.map.map_dir is None:
        return None
    return world.map.map_dir / BAKE_NAME


def _layer_hash(map_dir: Path | None, name: str) -> str:
    if map_dir is None:
        return ""
    path = map_dir / "CHECKSUMS.txt"
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == name:
            return parts[0]
    return ""
