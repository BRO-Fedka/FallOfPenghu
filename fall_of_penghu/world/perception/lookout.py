from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from fall_of_penghu.world.entities.game_object import GameObject
from fall_of_penghu.world.entities.land.geom import point_in_poly
from fall_of_penghu.world.entities.land.islands import IslandIndex
from fall_of_penghu.world.map import MapData

CACHE_NAME = "lookouts.json"
CACHE_FORMAT = "fall-of-penghu-lookouts"
SHORE_OCCUPY_M = 50.0


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


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


def _simplify(feat, simplify_m: float):
    try:
        poly = Polygon(feat.exterior, feat.holes)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            return None
        simple = poly.simplify(simplify_m, preserve_topology=True)
        if simple.is_empty:
            return None
        return simple
    except (ValueError, TypeError):
        return None


class IslandLookouts:
    """Coastal watch from inhabited islands plus islands holding allied ground units."""

    def __init__(
        self,
        world: MapData,
        islands: IslandIndex | None,
        simplify_m: float,
    ) -> None:
        self._world = world
        self._islands = islands
        self._simplify_m = simplify_m
        raw = self._load_or_scan_raw()
        if islands is not None:
            self._inhabited = frozenset(islands.canonical(i) for i in raw)
        else:
            self._inhabited = frozenset(raw)
        self._geoms: dict[int, object] = {}
        for iid in self._inhabited:
            self._geom(iid)

    def occupied_by(
        self, units: list[GameObject], *, ground_kinds: frozenset[str]
    ) -> set[int]:
        extra: set[int] = set()
        if self._islands is None:
            return extra
        for obj in units:
            if obj.kind not in ground_kinds:
                continue
            iid = self._islands.at(obj.x, obj.y)
            if iid is None:
                iid = self._islands.nearest(obj.x, obj.y, SHORE_OCCUPY_M)
            if iid is not None:
                extra.add(iid)
        return extra

    def distance_m(self, x: float, y: float, extra_islands: set[int] | None = None) -> float:
        """0 on a providing island, otherwise meters to its simplified shore."""
        ids = set(self._inhabited)
        if extra_islands:
            ids.update(extra_islands)
        if not ids:
            return 1e30
        pt = Point(x, y)
        best = 1e30
        for iid in ids:
            geom = self._geom(iid)
            if geom is None:
                continue
            if geom.contains(pt):
                return 0.0
            d = geom.distance(pt)
            if d < best:
                best = d
        return best

    def _geom(self, island: int):
        if island in self._geoms:
            return self._geoms[island]
        feats = []
        if self._islands is not None:
            feats = self._islands.features(island)
        elif 0 <= island < len(self._world.coast):
            feats = [self._world.coast[island]]
        polys = []
        for feat in feats:
            simple = _simplify(feat, self._simplify_m)
            if simple is not None:
                polys.append(simple)
        geom = None
        if len(polys) == 1:
            geom = polys[0]
        elif polys:
            geom = unary_union(polys)
        self._geoms[island] = geom
        return geom

    def _fingerprint(self) -> dict:
        return {
            "format": CACHE_FORMAT,
            "simplify_m": self._simplify_m,
            "coast_count": len(self._world.coast),
            "building_count": len(self._world.buildings),
            "coast_hash": _layer_hash(self._world.map_dir, "coast.geojson"),
            "buildings_hash": _layer_hash(self._world.map_dir, "buildings.geojson"),
        }

    def _cache_path(self) -> Path | None:
        if self._world.map_dir is None:
            return None
        return self._world.map_dir / CACHE_NAME

    def _load_or_scan_raw(self) -> set[int]:
        cached = self._read_cache()
        if cached is not None:
            return cached
        found = self._scan_raw()
        self._write_cache(found)
        return found

    def _read_cache(self) -> set[int] | None:
        path = self._cache_path()
        if path is None or not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
        expected = self._fingerprint()
        for key, value in expected.items():
            if key == "simplify_m":
                try:
                    if abs(float(data.get(key)) - float(value)) > 1e-6:
                        return None
                except (TypeError, ValueError):
                    return None
            elif data.get(key) != value:
                return None
        raw = data.get("inhabited_raw")
        if not isinstance(raw, list):
            return None
        out: set[int] = set()
        n = len(self._world.coast)
        for item in raw:
            try:
                i = int(item)
            except (TypeError, ValueError):
                return None
            if 0 <= i < n:
                out.add(i)
        return out

    def _write_cache(self, raw: set[int]) -> None:
        path = self._cache_path()
        if path is None:
            return
        payload = self._fingerprint()
        payload["inhabited_raw"] = sorted(raw)
        try:
            with path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.write("\n")
        except OSError:
            return

    def _scan_raw(self) -> set[int]:
        found: set[int] = set()
        world = self._world
        if world.coast_grid is None:
            return found
        for building in world.buildings:
            x, y = _centroid(building.exterior)
            for i in world.coast_grid.query(x, y, x, y):
                if i in found:
                    continue
                if point_in_poly(x, y, world.coast[i]):
                    found.add(i)
                    break
        return found
