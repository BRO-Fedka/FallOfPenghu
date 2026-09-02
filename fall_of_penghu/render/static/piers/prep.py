from __future__ import annotations

import json
import sys
from pathlib import Path
from time import perf_counter

import numpy as np

from fall_of_penghu.mapdata import load_map
from fall_of_penghu.render.static.geom import triangulate
from fall_of_penghu.render.static.piers.pier_params import PierParams
from fall_of_penghu.render.static.piers.piers import find_pier_rings
from fall_of_penghu.render.static.veg.vegfield import _penghu_frame

PIER_TEX_MAX_DIM = 8192
PIER_FIELD_NAME = "piers_field.npz"


def _sdf_tex_size(
    frame: tuple[float, float, float, float], max_dim: int
) -> tuple[int, int]:
    minx, miny, maxx, maxy = frame
    span_x = max(maxx - minx, 1.0)
    span_y = max(maxy - miny, 1.0)
    cell = max(span_x, span_y) / max(max_dim - 1, 1)
    width = max(2, int(round(span_x / cell)) + 1)
    height = max(2, int(round(span_y / cell)) + 1)
    return width, height


def _world_to_px(
    x: float,
    y: float,
    frame: tuple[float, float, float, float],
    size: tuple[int, int],
) -> tuple[float, float]:
    minx, miny, maxx, maxy = frame
    w, h = size
    px = (x - minx) / max(maxx - minx, 1e-6) * (w - 1)
    py = (y - miny) / max(maxy - miny, 1e-6) * (h - 1)
    return px, py


def _fill_triangle(
    mask: np.ndarray,
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> None:
    h, w = mask.shape
    minx = max(int(min(a[0], b[0], c[0])), 0)
    maxx = min(int(max(a[0], b[0], c[0])) + 1, w - 1)
    miny = max(int(min(a[1], b[1], c[1])), 0)
    maxy = min(int(max(a[1], b[1], c[1])) + 1, h - 1)
    if minx > maxx or miny > maxy:
        return
    ax, ay = a
    bx, by = b
    cx, cy = c
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if abs(area) < 1e-8:
        return
    inv = 1.0 / area
    for y in range(miny, maxy + 1):
        py = y + 0.5
        row = mask[y]
        for x in range(minx, maxx + 1):
            px = x + 0.5
            w0 = ((bx - px) * (cy - py) - (by - py) * (cx - px)) * inv
            w1 = ((cx - px) * (ay - py) - (cy - py) * (ax - px)) * inv
            w2 = 1.0 - w0 - w1
            if w0 >= -1e-5 and w1 >= -1e-5 and w2 >= -1e-5:
                row[x] = 1


def rasterize_pier_rings(
    rings: list[list[tuple[float, float]]],
    frame: tuple[float, float, float, float],
    size: tuple[int, int],
) -> np.ndarray:
    w, h = size
    mask = np.zeros((h, w), dtype=np.uint8)
    for ring in rings:
        tris = triangulate(ring, None)
        if len(tris) < 3:
            continue
        px = [_world_to_px(x, y, frame, size) for x, y in tris]
        for i in range(0, len(px), 3):
            _fill_triangle(mask, px[i], px[i + 1], px[i + 2])
    return mask


def preprocess_piers(map_dir: Path, params: PierParams | None = None) -> Path:
    map_dir = Path(map_dir)
    params = params or PierParams()
    world = load_map(map_dir)
    t0 = perf_counter()
    rings = find_pier_rings(world.coast, params)
    detect_s = perf_counter() - t0
    frame = _penghu_frame(world)
    size = _sdf_tex_size(frame, PIER_TEX_MAX_DIM)
    t1 = perf_counter()
    mask = rasterize_pier_rings(rings, frame, size)
    raster_s = perf_counter() - t1
    out_path = map_dir / PIER_FIELD_NAME
    np.savez_compressed(
        out_path,
        mask=mask,
        frame=np.asarray(frame, dtype=np.float64),
        stamp_value=np.float32(params.stamp_value),
        n_rings=np.int32(len(rings)),
    )
    n_pix = int(mask.sum())
    print(
        f"Pier field {size[0]}x{size[1]}  rings {len(rings)}  "
        f"pixels {n_pix}  detect {detect_s:.1f}s  raster {raster_s:.1f}s",
        flush=True,
    )
    manifest_path = map_dir / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    layers = manifest.setdefault("layers", {})
    layers["piers"] = {
        "file": PIER_FIELD_NAME,
        "width": size[0],
        "height": size[1],
        "rings": len(rings),
        "pixels": n_pix,
        "stamp_value": float(params.stamp_value),
    }
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print(f"Wrote {out_path}", flush=True)
    return out_path


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("penghu_map_v1")
    preprocess_piers(target)
