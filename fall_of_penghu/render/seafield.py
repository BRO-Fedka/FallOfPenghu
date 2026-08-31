from __future__ import annotations

import pickle
from pathlib import Path
from time import perf_counter

import pygame

from fall_of_penghu.mapdata import MapData

SEA_TEX_SIZE = 1024
SEA_MAX_DIST_M = 14_000.0
SEA_CACHE = Path(__file__).resolve().parents[2] / "output" / "sea_dist_v2.pkl"


def _frame(world: MapData) -> tuple[float, float, float, float]:
    mn = world.manifest.get("frame_min_xy") or [-100_000.0, -100_000.0]
    mx = world.manifest.get("frame_max_xy") or [100_000.0, 100_000.0]
    return float(mn[0]), float(mn[1]), float(mx[0]), float(mx[1])


def _cache_key(world: MapData) -> str:
    return "|".join(
        (
            str(world.manifest.get("content_version")),
            str(len(world.taiwan)),
            str(len(world.coast)),
            str(SEA_TEX_SIZE),
            str(int(SEA_MAX_DIST_M)),
            "round-texel",
        )
    )


def _to_px(
    pts: list[tuple[float, float]],
    frame: tuple[float, float, float, float],
    size: int,
) -> list[tuple[int, int]]:
    minx, miny, maxx, maxy = frame
    fw = max(maxx - minx, 1.0)
    fh = max(maxy - miny, 1.0)
    last = size - 1
    out: list[tuple[int, int]] = []
    for wx, wy in pts:
        sx = int(round((wx - minx) / fw * last))
        sy = int(round((maxy - wy) / fh * last))
        if sx < 0:
            sx = 0
        elif sx > last:
            sx = last
        if sy < 0:
            sy = 0
        elif sy > last:
            sy = last
        out.append((sx, sy))
    return out


def _raster_land(world: MapData, frame: tuple[float, float, float, float], size: int) -> bytes:
    surf = pygame.Surface((size, size))
    surf.fill((0, 0, 0))
    for group in (world.taiwan, world.coast):
        for feat in group:
            pts = _to_px(feat.exterior, frame, size)
            if len(pts) >= 3:
                pygame.draw.polygon(surf, (255, 255, 255), pts)
    return pygame.image.tobytes(surf, "RGB", False)[::3]


def _chamfer_r8(mask: bytes, width: int, height: int, cell_m: float, max_dist: float) -> bytes:
    n = width * height
    inf = max_dist * 4.0
    dist = [inf] * n
    for i, pixel in enumerate(mask):
        if pixel:
            dist[i] = 0.0
    ortho = cell_m
    diag = cell_m * 1.41421356
    for y in range(height):
        row = y * width
        for x in range(width):
            i = row + x
            v = dist[i]
            if x:
                v = min(v, dist[i - 1] + ortho)
            if y:
                v = min(v, dist[i - width] + ortho)
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
                v = min(v, dist[i + 1] + ortho)
            if y + 1 < height:
                v = min(v, dist[i + width] + ortho)
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


def build_sea_distance(world: MapData) -> tuple[bytes, int, tuple[float, float, float, float]]:
    """R8 distance-to-land, v=0 at south. Cached. Dist 0 at shore, 255 at SEA_MAX_DIST_M."""
    frame = _frame(world)
    key = _cache_key(world)
    if SEA_CACHE.is_file():
        try:
            payload = pickle.loads(SEA_CACHE.read_bytes())
            if payload.get("key") == key:
                return payload["data"], SEA_TEX_SIZE, frame
        except Exception:
            pass
    t0 = perf_counter()
    size = SEA_TEX_SIZE
    mask = _raster_land(world, frame, size)
    cell_m = (frame[2] - frame[0]) / max(size - 1, 1)
    data = _chamfer_r8(mask, size, size, cell_m, SEA_MAX_DIST_M)
    SEA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SEA_CACHE.write_bytes(pickle.dumps({"key": key, "data": data}, protocol=4))
    print(f"Sea distance field {size}px in {perf_counter() - t0:.3f}s", flush=True)
    return data, size, frame
