from __future__ import annotations

import pickle
from array import array
from math import hypot
from pathlib import Path
from time import perf_counter

import pygame

from fall_of_penghu.mapdata import MapData, PolyFeature

VEG_CELL_M = 20.0
VEG_MAX_DIST_M = 64.0
VEG_PAD_M = 500.0
VEG_CACHE = Path(__file__).resolve().parents[2] / "output" / "veg_dist_v1.pkl"
ROAD_EXCLUDE_MIN_M = 12.0


def _penghu_frame(world: MapData) -> tuple[float, float, float, float]:
    bbox = world.manifest.get("bbox_penghu") or [-22_000.0, -32_000.0, 21_000.0, 35_000.0]
    return (
        float(bbox[0]) - VEG_PAD_M,
        float(bbox[1]) - VEG_PAD_M,
        float(bbox[2]) + VEG_PAD_M,
        float(bbox[3]) + VEG_PAD_M,
    )


def _tex_size(frame: tuple[float, float, float, float]) -> tuple[int, int]:
    minx, miny, maxx, maxy = frame
    width = max(2, int(round((maxx - minx) / VEG_CELL_M)) + 1)
    height = max(2, int(round((maxy - miny) / VEG_CELL_M)) + 1)
    return width, height


def _cache_key(world: MapData, width: int, height: int) -> str:
    layers = world.manifest.get("layers") or {}
    veg = layers.get("vegetation") or {}
    return "|".join(
        (
            str(world.manifest.get("content_version")),
            str(veg.get("hash")),
            str(len(world.vegetation)),
            str(len(world.buildings)),
            str(len(world.roads)),
            str(len(world.airports)),
            str(width),
            str(height),
            str(int(VEG_CELL_M)),
            str(int(VEG_MAX_DIST_M)),
        )
    )


def _to_px(
    pts: list[tuple[float, float]],
    frame: tuple[float, float, float, float],
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    minx, miny, maxx, maxy = frame
    fw = max(maxx - minx, 1.0)
    fh = max(maxy - miny, 1.0)
    last_x = width - 1
    last_y = height - 1
    out: list[tuple[int, int]] = []
    for wx, wy in pts:
        sx = int(round((wx - minx) / fw * last_x))
        sy = int(round((maxy - wy) / fh * last_y))
        if sx < 0:
            sx = 0
        elif sx > last_x:
            sx = last_x
        if sy < 0:
            sy = 0
        elif sy > last_y:
            sy = last_y
        out.append((sx, sy))
    return out


def _raster_polys(
    feats: list[PolyFeature],
    frame: tuple[float, float, float, float],
    width: int,
    height: int,
) -> bytes:
    surf = pygame.Surface((width, height))
    surf.fill((0, 0, 0))
    for feat in feats:
        pts = _to_px(feat.exterior, frame, width, height)
        if len(pts) >= 3:
            pygame.draw.polygon(surf, (255, 255, 255), pts)
    return pygame.image.tobytes(surf, "RGB", False)[::3]


def _raster_blockers(
    world: MapData,
    frame: tuple[float, float, float, float],
    width: int,
    height: int,
) -> bytes:
    surf = pygame.Surface((width, height))
    surf.fill((0, 0, 0))
    for feat in world.buildings:
        pts = _to_px(feat.exterior, frame, width, height)
        if len(pts) >= 3:
            pygame.draw.polygon(surf, (255, 255, 255), pts)
    for feat in world.airports:
        pts = _to_px(feat.exterior, frame, width, height)
        if len(pts) >= 3:
            pygame.draw.polygon(surf, (255, 255, 255), pts)
    cell = VEG_CELL_M
    for feat in world.roads:
        pts = _to_px(feat.points, frame, width, height)
        if len(pts) < 2:
            continue
        px = max(1, int(round(max(feat.width_m, ROAD_EXCLUDE_MIN_M) / cell)))
        pygame.draw.lines(surf, (255, 255, 255), False, pts, px)
    for feat in world.airport_lines:
        pts = _to_px(feat.points, frame, width, height)
        if len(pts) < 2:
            continue
        px = max(1, int(round(max(feat.width_m, 12.0) / cell)))
        pygame.draw.lines(surf, (255, 255, 255), False, pts, px)
    return pygame.image.tobytes(surf, "RGB", False)[::3]


def _invert(mask: bytes) -> bytes:
    return bytes(0 if pixel else 255 for pixel in mask)


def _chamfer(
    mask: bytes,
    width: int,
    height: int,
    cell_x: float,
    cell_y: float,
    max_dist: float,
) -> bytes:
    n = width * height
    inf = max_dist * 4.0
    dist = array("f", (inf,)) * n
    for i, pixel in enumerate(mask):
        if pixel:
            dist[i] = 0.0
    ortho_x = cell_x
    ortho_y = cell_y
    diag = hypot(cell_x, cell_y)
    for y in range(height):
        row = y * width
        for x in range(width):
            i = row + x
            v = dist[i]
            if x:
                v = min(v, dist[i - 1] + ortho_x)
            if y:
                v = min(v, dist[i - width] + ortho_y)
                if x:
                    v = min(v, dist[i - width - 1] + diag)
                if x + 1 < width:
                    v = min(v, dist[i - width + 1] + diag)
            dist[i] = v
    for y in range(height - 1, -1, -1):
        row = y * width
        for x in range(width - 1, -1, -1):
            i = row + x
            v = dist[i]
            if x + 1 < width:
                v = min(v, dist[i + 1] + ortho_x)
            if y + 1 < height:
                v = min(v, dist[i + width] + ortho_y)
                if x:
                    v = min(v, dist[i + width - 1] + diag)
                if x + 1 < width:
                    v = min(v, dist[i + width + 1] + diag)
            dist[i] = v
    scale = 255.0 / max_dist
    out = bytearray(n)
    for y in range(height):
        src = (height - 1 - y) * width
        dst = y * width
        for x in range(width):
            v = dist[src + x]
            out[dst + x] = 255 if v >= max_dist else int(v * scale)
    return bytes(out)


def build_veg_field(
    world: MapData,
) -> tuple[bytes, tuple[int, int], tuple[float, float, float, float]]:
    """RGBA8: R forest-in, G grass-in, B grass-out, A blockers. v=0 at south."""
    frame = _penghu_frame(world)
    width, height = _tex_size(frame)
    key = _cache_key(world, width, height)
    if VEG_CACHE.is_file():
        try:
            payload = pickle.loads(VEG_CACHE.read_bytes())
            if payload.get("key") == key:
                return payload["data"], (width, height), frame
        except Exception:
            pass
    t0 = perf_counter()
    forest = [f for f in world.vegetation if f.class_name == "forest"]
    grass = [f for f in world.vegetation if f.class_name != "forest"]
    forest_mask = _raster_polys(forest, frame, width, height)
    grass_mask = _raster_polys(grass, frame, width, height)
    blockers = _raster_blockers(world, frame, width, height)
    cell_x = (frame[2] - frame[0]) / max(width - 1, 1)
    cell_y = (frame[3] - frame[1]) / max(height - 1, 1)
    print(
        f"Veg field raster {width}x{height} ({cell_x:.1f}x{cell_y:.1f} m/px)...",
        flush=True,
    )
    forest_in = _chamfer(_invert(forest_mask), width, height, cell_x, cell_y, VEG_MAX_DIST_M)
    grass_in = _chamfer(_invert(grass_mask), width, height, cell_x, cell_y, VEG_MAX_DIST_M)
    grass_out = _chamfer(grass_mask, width, height, cell_x, cell_y, VEG_MAX_DIST_M)
    # Blockers were rasterized pygame-y-down; flip to match the chamfer outputs.
    block_flip = bytearray(width * height)
    for y in range(height):
        src = (height - 1 - y) * width
        dst = y * width
        block_flip[dst : dst + width] = blockers[src : src + width]
    rgba = bytearray(width * height * 4)
    n = width * height
    for i in range(n):
        o = i * 4
        rgba[o] = forest_in[i]
        rgba[o + 1] = grass_in[i]
        rgba[o + 2] = grass_out[i]
        rgba[o + 3] = block_flip[i]
    data = bytes(rgba)
    VEG_CACHE.parent.mkdir(parents=True, exist_ok=True)
    VEG_CACHE.write_bytes(pickle.dumps({"key": key, "data": data}, protocol=4))
    print(f"Veg distance field {width}x{height} in {perf_counter() - t0:.2f}s", flush=True)
    return data, (width, height), frame
