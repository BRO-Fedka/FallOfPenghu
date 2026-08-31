from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fall_of_penghu.spatial import UniformGrid


def _ring_xy(ring: list) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for pt in ring:
        pts.append((float(pt[0]), float(pt[1])))
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts.pop()
    return pts


def _bbox_of(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _iter_polygons(geom: dict) -> list[list[list[tuple[float, float]]]]:
    gtype = geom["type"]
    coords = geom["coordinates"]
    polys: list[list[list[tuple[float, float]]]] = []
    if gtype == "Polygon":
        polys.append([_ring_xy(r) for r in coords if len(r) >= 4])
    elif gtype == "MultiPolygon":
        for poly in coords:
            rings = [_ring_xy(r) for r in poly if len(r) >= 4]
            if rings:
                polys.append(rings)
    return [p for p in polys if p and len(p[0]) >= 3]


def _iter_lines(geom: dict) -> list[list[tuple[float, float]]]:
    gtype = geom["type"]
    coords = geom["coordinates"]
    lines: list[list[tuple[float, float]]] = []
    if gtype == "LineString":
        line = [(float(p[0]), float(p[1])) for p in coords]
        if len(line) >= 2:
            lines.append(line)
    elif gtype == "MultiLineString":
        for part in coords:
            line = [(float(p[0]), float(p[1])) for p in part]
            if len(line) >= 2:
                lines.append(line)
    return lines


@dataclass
class PolyFeature:
    bbox: tuple[float, float, float, float]
    exterior: list[tuple[float, float]]
    holes: list[list[tuple[float, float]]] = field(default_factory=list)
    area_m2: float = 0.0
    class_name: str = ""
    kind: str = ""
    rect: bool = False
    icao: str = ""
    apt_kind: str = ""


@dataclass
class LineFeature:
    bbox: tuple[float, float, float, float]
    points: list[tuple[float, float]]
    width_m: float = 6.0
    highway: str = ""
    bridge: bool = False


@dataclass
class MapData:
    manifest: dict[str, Any]
    taiwan: list[PolyFeature] = field(default_factory=list)
    coast: list[PolyFeature] = field(default_factory=list)
    vegetation: list[PolyFeature] = field(default_factory=list)
    buildings: list[PolyFeature] = field(default_factory=list)
    roads: list[LineFeature] = field(default_factory=list)
    airports: list[PolyFeature] = field(default_factory=list)
    airport_lines: list[LineFeature] = field(default_factory=list)
    coast_grid: UniformGrid | None = None
    veg_grid: UniformGrid | None = None
    building_grid: UniformGrid | None = None
    road_grid: UniformGrid | None = None


def _load_collection(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("features", [])


def _polys_from_feature(feat: dict, **fields: Any) -> list[PolyFeature]:
    out: list[PolyFeature] = []
    for rings in _iter_polygons(feat["geometry"]):
        exterior = rings[0]
        bbox = _bbox_of(exterior)
        out.append(
            PolyFeature(
                bbox=bbox,
                exterior=exterior,
                holes=list(rings[1:]),
                **fields,
            )
        )
    return out


def _lines_from_feature(feat: dict, **fields: Any) -> list[LineFeature]:
    out: list[LineFeature] = []
    for points in _iter_lines(feat["geometry"]):
        out.append(LineFeature(bbox=_bbox_of(points), points=points, **fields))
    return out


def _index(items: list, cell_m: float) -> UniformGrid:
    grid = UniformGrid(cell_m)
    for i, item in enumerate(items):
        grid.insert(i, *item.bbox)
    return grid


def load_map(map_dir: Path) -> MapData:
    map_dir = Path(map_dir)
    with (map_dir / "manifest.json").open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    if manifest.get("format") != "fall-of-penghu-map":
        raise ValueError("unexpected map format")
    if manifest.get("coordinates") != "EPSG:3825_local_meters":
        raise ValueError("map coordinates must be EPSG:3825_local_meters")

    world = MapData(manifest=manifest)

    for feat in _load_collection(map_dir / "taiwan.geojson"):
        world.taiwan.extend(_polys_from_feature(feat))

    for feat in _load_collection(map_dir / "coast.geojson"):
        props = feat.get("properties") or {}
        world.coast.extend(
            _polys_from_feature(feat, area_m2=float(props.get("area_m2") or 0.0))
        )

    for feat in _load_collection(map_dir / "vegetation.geojson"):
        props = feat.get("properties") or {}
        world.vegetation.extend(
            _polys_from_feature(
                feat,
                area_m2=float(props.get("area_m2") or 0.0),
                class_name=str(props.get("class") or "grass"),
            )
        )

    for feat in _load_collection(map_dir / "buildings.geojson"):
        props = feat.get("properties") or {}
        world.buildings.extend(
            _polys_from_feature(
                feat,
                kind=str(props.get("kind") or "unknown"),
                rect=bool(props.get("rect")),
            )
        )

    for feat in _load_collection(map_dir / "roads.geojson"):
        props = feat.get("properties") or {}
        world.roads.extend(
            _lines_from_feature(
                feat,
                width_m=float(props.get("width_m") or 6.0),
                highway=str(props.get("highway") or ""),
                bridge=bool(props.get("bridge")),
            )
        )

    for feat in _load_collection(map_dir / "airports.geojson"):
        props = feat.get("properties") or {}
        kind = str(props.get("apt_kind") or "")
        extra = {
            "icao": str(props.get("icao") or ""),
            "apt_kind": kind,
        }
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        if gtype in ("LineString", "MultiLineString"):
            world.airport_lines.extend(
                _lines_from_feature(feat, highway=kind, width_m=12.0)
            )
        else:
            world.airports.extend(_polys_from_feature(feat, icao=extra["icao"], apt_kind=kind))

    world.coast_grid = _index(world.coast, 2_000.0)
    world.veg_grid = _index(world.vegetation, 2_000.0)
    world.building_grid = _index(world.buildings, 500.0)
    world.road_grid = _index(world.roads, 1_000.0)
    return world
