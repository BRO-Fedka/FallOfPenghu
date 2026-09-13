from __future__ import annotations

import json
from dataclasses import dataclass
from math import hypot
from pathlib import Path

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from fall_of_penghu.world.entities.game_object import (
    FACTION_CHINA,
    FACTION_PLAYER,
    GameObject,
)
from fall_of_penghu.world.entities.kinds import is_static_kind
from fall_of_penghu.world.entities.land.geom import point_in_poly
from fall_of_penghu.world.entities.land.islands import IslandIndex
from fall_of_penghu.world.map import MapData

CACHE_NAME = "lookouts.json"
CACHE_FORMAT = "fall-of-penghu-lookouts"
SHORE_OCCUPY_M = 50.0
SKIP_PRESENCE = frozenset({"intercept", "tracer", "shell"})


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


@dataclass
class _Shore:
    geom: object
    minx: float
    miny: float
    maxx: float
    maxy: float
    cx: float
    cy: float
    cr: float


def _aabb_dist(x: float, y: float, shore: _Shore) -> float:
    dx = max(shore.minx - x, 0.0, x - shore.maxx)
    dy = max(shore.miny - y, 0.0, y - shore.maxy)
    return hypot(dx, dy)


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
        baked=None,
    ) -> None:
        self._world = world
        self._islands = islands
        self._simplify_m = simplify_m
        self._shores: dict[int, _Shore | None] = {}
        if baked is not None:
            from fall_of_penghu.world.map_bake import restore_shores

            row = baked.payload["lookouts"]
            self._inhabited = frozenset(int(i) for i in row["inhabited"])
            self._shores = restore_shores(row["shores"])
            return
        raw = self._load_or_scan_raw()
        if islands is not None:
            self._inhabited = frozenset(islands.canonical(i) for i in raw)
        else:
            self._inhabited = frozenset(raw)
        for iid in self._inhabited:
            self._shore(iid)

    @property
    def inhabited(self) -> frozenset[int]:
        return self._inhabited

    @property
    def islands(self) -> IslandIndex | None:
        return self._islands

    def occupied_by(
        self, units: list[GameObject], *, ground_kinds: frozenset[str]
    ) -> set[int]:
        extra: set[int] = set()
        if self._islands is None:
            return extra
        for obj in units:
            if obj.kind not in ground_kinds:
                continue
            iid = island_under(self._islands, obj)
            if iid is not None:
                extra.add(iid)
        return extra

    def covers(
        self,
        x: float,
        y: float,
        radius: float,
        extra_islands: set[int] | None = None,
        *,
        base: frozenset[int] | set[int] | None = None,
        deny: set[int] | None = None,
        on_island: int | None = None,
    ) -> bool:
        """True if a providing shore is within radius. Circles/AABB first."""
        ids = set(self._inhabited if base is None else base)
        if deny:
            ids -= deny
        if extra_islands:
            ids.update(extra_islands)
        if not ids:
            return False
        if on_island is not None and on_island in ids:
            return True
        pt = None
        for iid in ids:
            shore = self._shore(iid)
            if shore is None:
                continue
            if hypot(x - shore.cx, y - shore.cy) > shore.cr + radius:
                continue
            if _aabb_dist(x, y, shore) > radius:
                continue
            if pt is None:
                pt = Point(x, y)
            if shore.geom.contains(pt):
                return True
            if shore.geom.distance(pt) <= radius:
                return True
        return False

    def distance_m(
        self,
        x: float,
        y: float,
        extra_islands: set[int] | None = None,
        *,
        base: frozenset[int] | set[int] | None = None,
        deny: set[int] | None = None,
    ) -> float:
        """0 on a providing island, otherwise meters to its simplified shore."""
        ids = set(self._inhabited if base is None else base)
        if deny:
            ids -= deny
        if extra_islands:
            ids.update(extra_islands)
        if not ids:
            return 1e30
        pt = Point(x, y)
        best = 1e30
        for iid in ids:
            shore = self._shore(iid)
            if shore is None:
                continue
            if _aabb_dist(x, y, shore) >= best:
                continue
            if shore.geom.contains(pt):
                return 0.0
            d = shore.geom.distance(pt)
            if d < best:
                best = d
        return best

    def _shore(self, island: int) -> _Shore | None:
        if island in self._shores:
            return self._shores[island]
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
        shore = None
        if geom is not None and not geom.is_empty:
            minx, miny, maxx, maxy = geom.bounds
            cx = (minx + maxx) * 0.5
            cy = (miny + maxy) * 0.5
            shore = _Shore(
                geom=geom,
                minx=minx,
                miny=miny,
                maxx=maxx,
                maxy=maxy,
                cx=cx,
                cy=cy,
                cr=hypot(maxx - cx, maxy - cy),
            )
        self._shores[island] = shore
        return shore

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


def island_under(islands: IslandIndex | None, obj: GameObject) -> int | None:
    if not obj.active or getattr(obj, "stowed", False):
        return None
    if obj.kind in SKIP_PRESENCE or is_static_kind(obj.kind):
        return None
    iid = getattr(obj, "island_id", None)
    if callable(iid):
        found = iid()
        if found is not None:
            return found
    if islands is None:
        return None
    hit = islands.at(obj.x, obj.y)
    if hit is not None:
        return hit
    return islands.nearest(obj.x, obj.y, SHORE_OCCUPY_M)


def occupants(
    islands: IslandIndex | None, units: list[GameObject]
) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {}
    if islands is None:
        return out
    for obj in units:
        iid = island_under(islands, obj)
        if iid is None:
            continue
        row = out.setdefault(iid, {})
        row[obj.faction] = row.get(obj.faction, 0) + 1
    return out


def china_held(
    inhabited: frozenset[int], occ: dict[int, dict[str, int]]
) -> set[int]:
    held: set[int] = set()
    for iid in inhabited:
        row = occ.get(iid) or {}
        if row.get(FACTION_CHINA, 0) > 0 and row.get(FACTION_PLAYER, 0) <= 0:
            held.add(iid)
    return held


def faction_on_islands(
    islands: IslandIndex | None, units: list[GameObject], faction: str
) -> bool:
    if islands is None:
        return False
    for obj in units:
        if obj.faction != faction:
            continue
        if island_under(islands, obj) is not None:
            return True
    return False
