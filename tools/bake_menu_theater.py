"""Bake a static Taiwan-strait poster for the menu camera.

One situation, three looks (day / night / radar). Land is all taiwan-ink.
Penghu comes from the match coast; China and Taiwan from Natural Earth 10m.

    python tools/bake_menu_theater.py
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shapely.geometry import Point, Polygon, box, mapping, shape
from shapely.ops import nearest_points, unary_union
from shapely.prepared import prep

from fall_of_penghu.render.dynamic.icons import CHIP, IconStore
from fall_of_penghu.render.dynamic.renderer import (
    INACTIVE_X,
    _heading_arrow,
)
from fall_of_penghu.render.static.radar import COAST_PX, GRID_PX, INK as RADAR_INK
from fall_of_penghu.render.static.scene import palette_for
from fall_of_penghu.render.static.tod import contrast_rgb
from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER
from fall_of_penghu.world.map import _load_collection, _polys_from_feature

RADAR_TURN = frozenset({"drone", "scout", "intercept"})
CARGO_KINDS = ("infantry", "truck", "tank", "artillery", "aa_pickup")
SHIP_KINDS = ("ship", "ship", "landing_ship", "landing_ship")
AA = 2
CLEAR_SHIP = 2_200.0
CLEAR_FERRY = 3_300.0

OUT_DIR = ROOT / "assets" / "menu_theater"
SRC_DIR = OUT_DIR / "source"
MAP_DIR = ROOT / "penghu_map_v1"
NE_PATH = SRC_DIR / "ne_10m_land.geojson"
NE_URLS = (
    "https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/geojson/ne_10m_land.geojson",
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_land.geojson",
)

LAT0 = 23 + 49 / 60 + 18 / 3600
LON0 = 119 + 56 / 3600
WIDTH_M = 320_000.0
HEIGHT_M = 166_000.0
PX_W = 1920 * 3
PX_H = 1080 * 3
SEED = 20260913
TILE = 1920, 1080

# Match data is TWD97 TM2 zone 119 (EPSG:3826), not 3825.
_A = 6378137.0
_F = 1.0 / 298.257222101
_E2 = _F * (2.0 - _F)
_EP2 = _E2 / (1.0 - _E2)
_K0 = 0.9999
_TM_LON0 = math.radians(119.0)
_FE = 250_000.0
_ORIGIN_E = 303629.30711733666
_ORIGIN_N = 2596980.7306913873

_M_LAT = 111132.92 - 559.82 * math.cos(2.0 * math.radians(LAT0))
_M_LON = 111412.84 * math.cos(math.radians(LAT0)) - 93.5 * math.cos(3.0 * math.radians(LAT0))


def tm_inverse(easting: float, northing: float) -> tuple[float, float]:
    mu = (northing / _K0) / (_A * (1 - _E2 / 4 - 3 * _E2**2 / 64 - 5 * _E2**3 / 256))
    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    lat = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
    )
    n = _A / math.sqrt(1 - _E2 * math.sin(lat) ** 2)
    r = _A * (1 - _E2) / (1 - _E2 * math.sin(lat) ** 2) ** 1.5
    t = math.tan(lat)
    c = _EP2 * math.cos(lat) ** 2
    d = (easting - _FE) / (n * _K0)
    lat = lat - (n * t / r) * (d * d / 2 - (5 + 3 * t * t + 10 * c - 4 * c * c - 9 * _EP2) * d**4 / 24)
    n = _A / math.sqrt(1 - _E2 * math.sin(lat) ** 2)
    t = math.tan(lat)
    c = _EP2 * math.cos(lat) ** 2
    d = (easting - _FE) / (n * _K0)
    lon = _TM_LON0 + (
        d - (1 + 2 * t * t + c) * d**3 / 6 + (5 - 2 * c + 28 * t * t - 3 * c * c + 8 * _EP2 + 24 * t**4) * d**5 / 120
    ) / math.cos(lat)
    return math.degrees(lon), math.degrees(lat)


def game_to_lonlat(gx: float, gy: float) -> tuple[float, float]:
    return tm_inverse(gx + _ORIGIN_E, gy + _ORIGIN_N)


def lonlat_to_xy(lon: float, lat: float) -> tuple[float, float]:
    return (lon - LON0) * _M_LON, (lat - LAT0) * _M_LAT


def game_to_xy(gx: float, gy: float) -> tuple[float, float]:
    return lonlat_to_xy(*game_to_lonlat(gx, gy))


def ensure_natural_earth() -> Path:
    if NE_PATH.is_file() and NE_PATH.stat().st_size > 1_000_000:
        return NE_PATH
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    last = None
    for url in NE_URLS:
        print(f"Downloading land... {url}", flush=True)
        try:
            urllib.request.urlretrieve(url, NE_PATH)
            if NE_PATH.stat().st_size > 1_000_000:
                return NE_PATH
        except Exception as exc:
            last = exc
            print(f"  failed: {exc}", flush=True)
    raise RuntimeError(f"could not download Natural Earth land: {last}")


def _ring_xy(ring: list[tuple[float, float]], convert) -> list[tuple[float, float]]:
    return [convert(x, y) for x, y in ring]


def _poly_from_rings(
    exterior: list[tuple[float, float]],
    holes: list[list[tuple[float, float]]],
) -> Polygon | None:
    if len(exterior) < 3:
        return None
    ring = exterior if exterior[0] == exterior[-1] else exterior + [exterior[0]]
    inner = []
    for hole in holes:
        if len(hole) < 3:
            continue
        closed = hole if hole[0] == hole[-1] else hole + [hole[0]]
        inner.append(closed)
    try:
        poly = Polygon(ring, inner)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            return None
        return poly
    except Exception:
        return None


def load_ne_land() -> list[Polygon]:
    ensure_natural_earth()
    data = json.loads(NE_PATH.read_text(encoding="utf-8"))
    pad_lon = (WIDTH_M * 0.55) / _M_LON
    pad_lat = (HEIGHT_M * 0.55) / _M_LAT
    clip = box(LON0 - pad_lon, LAT0 - pad_lat, LON0 + pad_lon, LAT0 + pad_lat)
    out: list[Polygon] = []
    for feat in data.get("features") or []:
        geom = shape(feat["geometry"])
        if not geom.intersects(clip):
            continue
        part = geom.intersection(clip)
        if part.is_empty:
            continue
        geoms = [part] if part.geom_type == "Polygon" else getattr(part, "geoms", [])
        for g in geoms:
            if g.geom_type != "Polygon" or g.is_empty:
                continue
            ext = [lonlat_to_xy(x, y) for x, y in g.exterior.coords]
            holes = [[lonlat_to_xy(x, y) for x, y in hole.coords] for hole in g.interiors]
            poly = _poly_from_rings(ext, holes)
            if poly is not None:
                out.append(poly.simplify(150.0, preserve_topology=True))
    return [p for p in out if p is not None and not p.is_empty]


def load_penghu() -> list[Polygon]:
    out: list[Polygon] = []
    for feat in _load_collection(MAP_DIR / "coast.geojson"):
        for rec in _polys_from_feature(feat):
            ext = _ring_xy(rec.exterior, game_to_xy)
            holes = [_ring_xy(h, game_to_xy) for h in rec.holes]
            poly = _poly_from_rings(ext, holes)
            if poly is None or poly.area < 40_000:
                continue
            out.append(poly.simplify(40.0, preserve_topology=True))
    return [p for p in out if p is not None and not p.is_empty]


def _parts(geom) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon" and not g.is_empty]


def clip_to_frame(polys: list[Polygon]) -> list[Polygon]:
    frame = box(-WIDTH_M * 0.5, -HEIGHT_M * 0.5, WIDTH_M * 0.5, HEIGHT_M * 0.5)
    out: list[Polygon] = []
    for poly in polys:
        for g in _parts(poly.intersection(frame)):
            if g.area > 20_000:
                out.append(g)
    return out


def merge_land(ne: list[Polygon], penghu: list[Polygon]) -> list[Polygon]:
    if penghu:
        cut = unary_union(penghu).envelope.buffer(8_000.0)
        ne = [g for p in ne for g in _parts(p.difference(cut))]
    return clip_to_frame(ne + penghu)


def dump_land(polys: list[Polygon], path: Path) -> None:
    feats = []
    for poly in polys:
        feats.append({"type": "Feature", "properties": {}, "geometry": mapping(poly)})
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")),
        encoding="utf-8",
    )


def load_land_file(path: Path) -> list[Polygon]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[Polygon] = []
    for feat in data.get("features") or []:
        geom = shape(feat["geometry"])
        if geom.geom_type == "Polygon":
            out.append(geom)
        elif geom.geom_type == "MultiPolygon":
            out.extend(g for g in geom.geoms if g.geom_type == "Polygon")
    return out


def build_land(force: bool) -> list[Polygon]:
    dest = OUT_DIR / "land.geojson"
    if dest.is_file() and not force:
        print("Land cache hit", flush=True)
        return load_land_file(dest)
    print("Building land...", flush=True)
    polys = merge_land(load_ne_land(), load_penghu())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dump_land(polys, dest)
    print(f"  {len(polys)} polygons -> {dest}", flush=True)
    return polys


def _union_where(polys: list[Polygon], pred) -> Polygon | None:
    picked = [p for p in polys if pred(p)]
    if not picked:
        return None
    return unary_union(picked)


def _far_enough(
    x: float, y: float, taken: list[tuple[float, float, float]], need: float
) -> bool:
    for px, py, pad in taken:
        if math.hypot(x - px, y - py) < max(need, pad):
            return False
    return True


def _water_box(
    rng: random.Random,
    land,
    land_geom,
    *,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    d0: float,
    d1: float,
    taken: list[tuple[float, float, float]],
    clear: float,
    coast=None,
) -> tuple[float, float] | None:
    measure = coast if coast is not None else land_geom
    for _ in range(140):
        x = rng.uniform(x0, x1)
        y = rng.uniform(y0, y1)
        pt = Point(x, y)
        if land.covers(pt):
            continue
        dist = measure.distance(pt)
        if dist < d0 or dist > d1:
            continue
        if not _far_enough(x, y, taken, clear):
            continue
        return x, y
    return None


def _water_any(
    rng: random.Random,
    land,
    taken: list[tuple[float, float, float]],
    clear: float,
    margin: float,
) -> tuple[float, float] | None:
    for _ in range(100):
        x = rng.uniform(-WIDTH_M * 0.46, WIDTH_M * 0.46)
        y = rng.uniform(-HEIGHT_M * 0.44, HEIGHT_M * 0.44)
        if land.covers(Point(x, y)) or land.intersects(Point(x, y).buffer(margin)):
            continue
        if not _far_enough(x, y, taken, clear):
            continue
        return x, y
    return None


def _aim(x: float, y: float, tx: float, ty: float, spread: float, rng: random.Random) -> float:
    return math.atan2(ty - y, tx - x) + rng.uniform(-spread, spread)


def _aim_land(x: float, y: float, geom, spread: float, rng: random.Random) -> float:
    if geom is None:
        return rng.uniform(0.0, math.tau)
    _, hit = nearest_points(Point(x, y), geom)
    return math.atan2(hit.y - y, hit.x - x) + rng.uniform(-spread, spread)


def place_situation(land_polys: list[Polygon]) -> list[dict]:
    dest = OUT_DIR / "situation.json"
    print("Placing marks...", flush=True)
    union = unary_union(land_polys)
    land = prep(union)
    china = _union_where(land_polys, lambda p: p.centroid.x < 0.0)
    taiwan = _union_where(land_polys, lambda p: p.centroid.x > 100_000.0)
    penghu = _union_where(
        land_polys,
        lambda p: 30_000.0 < p.centroid.x < 90_000.0 and -70_000.0 < p.centroid.y < 5_000.0,
    )
    cx_t, cy_t = (taiwan.centroid.x, taiwan.centroid.y) if taiwan is not None else (140_000.0, -20_000.0)
    cx_c, cy_c = (china.centroid.x, china.centroid.y) if china is not None else (-140_000.0, 20_000.0)
    if penghu is not None:
        px, py = penghu.centroid.x, penghu.centroid.y
    else:
        px, py = 57_000.0, -28_000.0
    rng = random.Random(SEED)
    marks: list[dict] = []
    taken: list[tuple[float, float, float]] = []

    def add(
        kind: str,
        faction: str,
        x: float,
        y: float,
        heading: float,
        *,
        wrecked: bool = False,
        cargo: str | None = None,
        clear: float = CLEAR_SHIP,
    ) -> None:
        marks.append(
            {
                "kind": kind,
                "faction": faction,
                "x": round(x, 1),
                "y": round(y, 1),
                "heading": round(heading, 4),
                "wrecked": wrecked,
                "cargo": cargo,
            }
        )
        taken.append((x, y, clear))

    half_w = WIDTH_M * 0.5
    half_h = HEIGHT_M * 0.5

    for _ in range(20):
        pt = _water_box(
            rng,
            land,
            union,
            x0=-half_w + 8_000.0,
            x1=-70_000.0,
            y0=-half_h + 8_000.0,
            y1=half_h - 8_000.0,
            d0=2_000.0,
            d1=11_000.0,
            taken=taken,
            clear=CLEAR_FERRY,
            coast=china,
        )
        if pt is None:
            continue
        x, y = pt
        add(
            "ferry",
            FACTION_CHINA,
            x,
            y,
            _aim_land(x, y, china, 0.15, rng),
            clear=CLEAR_FERRY,
        )

    for _ in range(12):
        pt = _water_box(
            rng,
            land,
            union,
            x0=-half_w + 8_000.0,
            x1=-50_000.0,
            y0=-half_h + 8_000.0,
            y1=half_h - 8_000.0,
            d0=3_000.0,
            d1=18_000.0,
            taken=taken,
            clear=CLEAR_SHIP,
            coast=china,
        )
        if pt is None:
            continue
        x, y = pt
        shore = china if rng.random() < 0.55 else taiwan
        add(rng.choice(SHIP_KINDS), FACTION_CHINA, x, y, _aim_land(x, y, shore, 0.2, rng))

    for _g in range(7):
        pt = _water_box(
            rng,
            land,
            union,
            x0=95_000.0,
            x1=half_w - 6_000.0,
            y0=-half_h + 10_000.0,
            y1=half_h - 10_000.0,
            d0=3_000.0,
            d1=14_000.0,
            taken=taken,
            clear=CLEAR_FERRY * 2.2,
            coast=taiwan,
        )
        if pt is None:
            continue
        gx, gy = pt
        heading = _aim_land(gx, gy, taiwan, 0.1, rng)
        n = rng.randint(3, 4)
        cargo = rng.choice(CARGO_KINDS)
        along = heading + math.pi * 0.5
        for i in range(n):
            x = gx + math.cos(along) * (i - (n - 1) / 2) * 3_400.0
            y = gy + math.sin(along) * (i - (n - 1) / 2) * 3_400.0
            if land.covers(Point(x, y).buffer(800.0)):
                continue
            if not _far_enough(x, y, taken, CLEAR_FERRY):
                continue
            add(
                "ferry",
                FACTION_CHINA,
                x,
                y,
                heading + rng.uniform(-0.08, 0.08),
                cargo=cargo,
                clear=CLEAR_FERRY,
            )

    for _ in range(10):
        pt = _water_box(
            rng,
            land,
            union,
            x0=80_000.0,
            x1=half_w - 8_000.0,
            y0=-half_h + 8_000.0,
            y1=half_h - 8_000.0,
            d0=4_000.0,
            d1=20_000.0,
            taken=taken,
            clear=CLEAR_SHIP,
            coast=taiwan,
        )
        if pt is None:
            continue
        x, y = pt
        shore = taiwan if rng.random() < 0.65 else china
        add(rng.choice(SHIP_KINDS), FACTION_CHINA, x, y, _aim_land(x, y, shore, 0.22, rng))

    for _ in range(10):
        cx = rng.uniform(-40_000.0, 70_000.0)
        cy = rng.uniform(-half_h + 12_000.0, half_h - 12_000.0)
        if land.covers(Point(cx, cy).buffer(2_000.0)):
            pt = _water_any(rng, land, taken, CLEAR_SHIP, 2_000.0)
            if pt is None:
                continue
            cx, cy = pt
        heading = _aim_land(cx, cy, taiwan if rng.random() < 0.5 else china, 0.35, rng)
        n = rng.randint(3, 6)
        for i in range(n):
            ang = heading + (i - n / 2) * 0.14
            dist = 800.0 + i * rng.uniform(420.0, 680.0)
            x = cx + math.cos(ang) * dist
            y = cy + math.sin(ang) * dist
            if land.intersects(Point(x, y).buffer(700.0)):
                continue
            if not _far_enough(x, y, taken, 1_600.0):
                continue
            add(rng.choice(SHIP_KINDS), FACTION_CHINA, x, y, heading + rng.uniform(-0.2, 0.2))

    for _ in range(18):
        pt = _water_any(rng, land, taken, 3_000.0, 400.0)
        if pt is None:
            continue
        x, y = pt
        add("scout", FACTION_CHINA, x, y, rng.uniform(0.0, math.tau), clear=3_000.0)

    for _ in range(12):
        pt = _water_any(rng, land, taken, 6_000.0, 1_000.0)
        if pt is None:
            continue
        sx, sy = pt
        heading = _aim(sx, sy, px, py, 0.35, rng)
        for _i in range(rng.randint(10, 18)):
            x = sx + rng.gauss(0.0, 850.0)
            y = sy + rng.gauss(0.0, 850.0)
            if land.covers(Point(x, y)):
                continue
            add("drone", FACTION_CHINA, x, y, heading + rng.uniform(-0.18, 0.18), clear=280.0)

    for _ in range(5):
        pt = _water_any(rng, land, taken, CLEAR_SHIP, 1_600.0)
        if pt is None:
            continue
        x, y = pt
        if x < 0.0:
            x = min(x + 70_000.0, half_w - 10_000.0)
        add("ship", FACTION_PLAYER, x, y, rng.uniform(0.0, math.tau), wrecked=True)

    dest.write_text(
        json.dumps(
            {
                "seed": SEED,
                "china": [cx_c, cy_c],
                "taiwan": [cx_t, cy_t],
                "penghu": [px, py],
                "marks": marks,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"  {len(marks)} marks -> {dest}", flush=True)
    return marks


def xy_to_px(x: float, y: float, scale: int = 1) -> tuple[int, int]:
    sx = (x + WIDTH_M * 0.5) / WIDTH_M * PX_W * scale
    sy = (HEIGHT_M * 0.5 - y) / HEIGHT_M * PX_H * scale
    return int(round(sx)), int(round(sy))


def paint_land(surf, polys: list[Polygon], fill, edge, hole_fill, scale: int) -> None:
    import pygame

    for poly in polys:
        pts = [xy_to_px(x, y, scale) for x, y in poly.exterior.coords]
        if len(pts) < 3:
            continue
        pygame.draw.polygon(surf, fill, pts)
        if edge is not None:
            pygame.draw.lines(surf, edge, True, pts, max(1, int(round(COAST_PX * scale))))
        for hole in poly.interiors:
            hpts = [xy_to_px(x, y, scale) for x, y in hole.coords]
            if len(hpts) >= 3:
                pygame.draw.polygon(surf, hole_fill, hpts)


def paint_radar_grid(surf, color) -> None:
    """Square cells in pixels. Coarser than the in-match 1 km grid."""
    import pygame

    step_m = 2_000.0
    step_px = step_m * PX_W / WIDTH_M
    ox, oy = xy_to_px(0.0, 0.0)
    width = max(1, int(round(GRID_PX)))
    k = math.floor(-ox / step_px) - 1
    while True:
        sx = int(round(ox + k * step_px))
        if sx > PX_W:
            break
        if 0 <= sx <= PX_W:
            pygame.draw.line(surf, color, (sx, 0), (sx, PX_H), width)
        k += 1
    k = math.floor(-oy / step_px) - 1
    while True:
        sy = int(round(oy + k * step_px))
        if sy > PX_H:
            break
        if 0 <= sy <= PX_H:
            pygame.draw.line(surf, color, (0, sy), (PX_W, sy), width)
        k += 1


def rotate_nearest(src, heading: float):
    """Snap to 45 deg. 90-deg turns stay exact; diagonals are nearest-neighbour."""
    import pygame

    deg = heading * 180.0 / math.pi
    snap = int(round(deg / 45.0) * 45) % 360
    if snap == 0:
        return src
    if snap % 90 == 0:
        return pygame.transform.rotate(src, snap)
    w, h = src.get_size()
    side = int(math.ceil(math.hypot(w, h)))
    out = pygame.Surface((side, side), pygame.SRCALPHA)
    rad = -math.radians(snap)
    ca, sa = math.cos(rad), math.sin(rad)
    ocx, ocy = side * 0.5, side * 0.5
    scx, scy = w * 0.5, h * 0.5
    for y in range(side):
        for x in range(side):
            dx, dy = x - ocx, y - ocy
            ix = int(round(dx * ca - dy * sa + scx))
            iy = int(round(dx * sa + dy * ca + scy))
            if 0 <= ix < w and 0 <= iy < h:
                out.set_at((x, y), src.get_at((ix, iy)))
    return out


def paint_marks(
    surf,
    marks: list[dict],
    icons: IconStore,
    *,
    radar: bool,
    tod: float,
) -> None:
    import pygame

    ink = RADAR_INK if radar else contrast_rgb(tod)
    for mark in marks:
        kind = mark["kind"]
        sx, sy = xy_to_px(mark["x"], mark["y"])
        icon = icons.get(kind, mark["faction"], radar)
        if icon is not None:
            if radar and kind in RADAR_TURN:
                chip = rotate_nearest(icon, mark["heading"])
                surf.blit(chip, chip.get_rect(center=(sx, sy)))
            else:
                surf.blit(icon, icon.get_rect(center=(sx, sy)))
        cargo = mark.get("cargo")
        if cargo:
            badge = icons.get(cargo, mark["faction"], False)
            if badge is not None:
                surf.blit(badge, (sx - CHIP // 2, sy - CHIP - CHIP // 2))
        wrecked = bool(mark.get("wrecked"))
        if wrecked:
            half = CHIP // 2
            pygame.draw.line(surf, INACTIVE_X, (sx - half, sy - half), (sx + half, sy + half), 3)
            pygame.draw.line(surf, INACTIVE_X, (sx - half, sy + half), (sx + half, sy - half), 3)
            continue
        if radar:
            continue
        for a, b in ((seg[0], seg[1]) for seg in _heading_arrow(float(sx), float(sy), mark["heading"])):
            pygame.draw.aaline(surf, ink, a, b)


def render_variant(
    name: str,
    polys: list[Polygon],
    marks: list[dict],
    icons: IconStore,
    *,
    radar: bool,
    tod: float,
) -> Path:
    import pygame

    pal = palette_for(radar, tod)
    if radar:
        surf = pygame.Surface((PX_W, PX_H))
        surf.fill(pal["sea"])
        paint_radar_grid(surf, pal["grid"])
        land = pygame.Surface((PX_W * AA, PX_H * AA), pygame.SRCALPHA)
        paint_land(land, polys, (*pal["land"], 255), pal["coast"], (0, 0, 0, 0), AA)
        surf.blit(pygame.transform.smoothscale(land, (PX_W, PX_H)), (0, 0))
    else:
        big = pygame.Surface((PX_W * AA, PX_H * AA))
        big.fill(pal["sea"])
        paint_land(big, polys, pal["taiwan"], None, pal["sea"], AA)
        surf = pygame.transform.smoothscale(big, (PX_W, PX_H))
    paint_marks(surf, marks, icons, radar=radar, tod=tod)
    path = OUT_DIR / f"{name}.png"
    pygame.image.save(surf, str(path))
    tw, th = TILE
    tile_dir = OUT_DIR / "tiles" / name
    tile_dir.mkdir(parents=True, exist_ok=True)
    cols = PX_W // tw
    rows = PX_H // th
    for row in range(rows):
        for col in range(cols):
            cell = surf.subsurface((col * tw, row * th, tw, th))
            pygame.image.save(cell, str(tile_dir / f"c{col}_r{row}.png"))
    print(f"  {name}: {path}  + {cols}x{rows} tiles", flush=True)
    return path


def write_manifest(n_land: int, n_marks: int) -> None:
    data = {
        "format": "fall-of-penghu-menu-theater",
        "center_lonlat": [LON0, LAT0],
        "size_m": [WIDTH_M, HEIGHT_M],
        "pixels": [PX_W, PX_H],
        "tile": list(TILE),
        "seed": SEED,
        "land_polygons": n_land,
        "marks": n_marks,
        "variants": ["day", "night", "radar"],
        "notes": "All land uses in-game taiwan ink. Same marks on every variant.",
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    force = "--force" in sys.argv
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame

    pygame.init()
    try:
        pygame.display.set_mode((8, 8), getattr(pygame, "HIDDEN", 0))
    except pygame.error:
        pygame.display.set_mode((8, 8))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    polys = build_land(force)
    marks = place_situation(polys)
    icons = IconStore()
    print("Rendering...", flush=True)
    render_variant("day", polys, marks, icons, radar=False, tod=0.5)
    render_variant("night", polys, marks, icons, radar=False, tod=0.0)
    render_variant("radar", polys, marks, icons, radar=True, tod=0.5)
    write_manifest(len(polys), len(marks))
    print(f"Done  {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
