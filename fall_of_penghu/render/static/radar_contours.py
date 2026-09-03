from __future__ import annotations

from array import array

import numpy as np

from fall_of_penghu.render.static.radar import CONTOUR_STEP_M, GRID_M

# Isoline through a DEM cell. Bits: SW=1, SE=2, NE=4, NW=8.
# Edges: 0 bottom, 1 right, 2 top, 3 left.
_CASES: dict[int, tuple[tuple[int, int], ...]] = {
    1: ((3, 0),),
    2: ((0, 1),),
    3: ((3, 1),),
    4: ((1, 2),),
    5: ((3, 0), (1, 2)),
    6: ((0, 2),),
    7: ((3, 2),),
    8: ((2, 3),),
    9: ((0, 2),),
    10: ((0, 1), (2, 3)),
    11: ((1, 2),),
    12: ((3, 1),),
    13: ((0, 1),),
    14: ((3, 0),),
}
_SADDLE_ALT = {
    5: ((0, 1), (2, 3)),
    10: ((3, 0), (1, 2)),
}


def _t(h0: np.ndarray, h1: np.ndarray, level: float) -> np.ndarray:
    den = h1 - h0
    out = np.full(h0.shape, 0.5, dtype=np.float64)
    ok = np.abs(den) > 1e-9
    out[ok] = (level - h0[ok]) / den[ok]
    return np.clip(out, 0.0, 1.0)


def _edge_xy(
    edge: int,
    j: np.ndarray,
    i: np.ndarray,
    z00: np.ndarray,
    z10: np.ndarray,
    z11: np.ndarray,
    z01: np.ndarray,
    level: float,
    minx: float,
    miny: float,
    dx: float,
    dy: float,
) -> np.ndarray:
    x = minx + j.astype(np.float64) * dx
    y = miny + i.astype(np.float64) * dy
    if edge == 0:
        t = _t(z00, z10, level)
        return np.stack((x + t * dx, y), axis=-1)
    if edge == 1:
        t = _t(z10, z11, level)
        return np.stack((x + dx, y + t * dy), axis=-1)
    if edge == 2:
        t = _t(z01, z11, level)
        return np.stack((x + t * dx, y + dy), axis=-1)
    t = _t(z00, z01, level)
    return np.stack((x, y + t * dy), axis=-1)


def isoline_segments(
    height: np.ndarray,
    frame: tuple[float, float, float, float],
    nodata: float,
    step_m: float = CONTOUR_STEP_M,
    min_level: float = CONTOUR_STEP_M,
) -> np.ndarray:
    """World-meter segments (N, 2, 2). Row 0 of height is south."""
    z = np.asarray(height, dtype=np.float64)
    if z.ndim != 2 or z.shape[0] < 2 or z.shape[1] < 2:
        return np.zeros((0, 2, 2), dtype=np.float64)
    rows, cols = z.shape
    minx, miny, maxx, maxy = (float(v) for v in frame)
    dx = (maxx - minx) / max(cols - 1, 1)
    dy = (maxy - miny) / max(rows - 1, 1)
    land = z > float(nodata) + 0.5
    if not np.any(land):
        return np.zeros((0, 2, 2), dtype=np.float64)
    zmax = float(np.max(z[land]))
    levels = np.arange(min_level, zmax + step_m * 0.5, step_m)
    if levels.size == 0:
        return np.zeros((0, 2, 2), dtype=np.float64)

    z00 = z[:-1, :-1]
    z10 = z[:-1, 1:]
    z11 = z[1:, 1:]
    z01 = z[1:, :-1]
    ok = land[:-1, :-1] & land[:-1, 1:] & land[1:, 1:] & land[1:, :-1]
    ii0, jj0 = np.nonzero(ok)
    if ii0.size == 0:
        return np.zeros((0, 2, 2), dtype=np.float64)
    a00, a10, a11, a01 = z00[ii0, jj0], z10[ii0, jj0], z11[ii0, jj0], z01[ii0, jj0]
    mean = 0.25 * (a00 + a10 + a11 + a01)
    chunks: list[np.ndarray] = []
    for level in levels:
        bits = (
            (a00 >= level).astype(np.int32)
            | ((a10 >= level).astype(np.int32) << 1)
            | ((a11 >= level).astype(np.int32) << 2)
            | ((a01 >= level).astype(np.int32) << 3)
        )
        for case, pairs in _CASES.items():
            mask = bits == case
            if case in _SADDLE_ALT:
                alt = mean < level
                groups = ((mask & ~alt, pairs), (mask & alt, _SADDLE_ALT[case]))
            else:
                groups = ((mask, pairs),)
            for sel, pset in groups:
                if not np.any(sel):
                    continue
                ii, jj = ii0[sel], jj0[sel]
                c00, c10, c11, c01 = a00[sel], a10[sel], a11[sel], a01[sel]
                for e0, e1 in pset:
                    p0 = _edge_xy(e0, jj, ii, c00, c10, c11, c01, level, minx, miny, dx, dy)
                    p1 = _edge_xy(e1, jj, ii, c00, c10, c11, c01, level, minx, miny, dx, dy)
                    chunks.append(np.stack((p0, p1), axis=1))
    if not chunks:
        return np.zeros((0, 2, 2), dtype=np.float64)
    return np.concatenate(chunks, axis=0)


def stroke_segments(segments: np.ndarray) -> array:
    """x y sx sy quads for radar_line.vert. Width applied in the shader."""
    data = array("f")
    if segments.size == 0:
        return data
    p0 = segments[:, 0]
    p1 = segments[:, 1]
    dx = p1[:, 0] - p0[:, 0]
    dy = p1[:, 1] - p0[:, 1]
    length = np.hypot(dx, dy)
    keep = length > 1e-4
    if not np.any(keep):
        return data
    p0 = p0[keep]
    p1 = p1[keep]
    dx = dx[keep]
    dy = dy[keep]
    length = length[keep]
    nx = -dy / length
    ny = dx / length
    verts = np.empty((p0.shape[0], 6, 4), dtype=np.float32)
    verts[:, 0, 0] = p0[:, 0]
    verts[:, 0, 1] = p0[:, 1]
    verts[:, 0, 2] = nx
    verts[:, 0, 3] = ny
    verts[:, 1, 0] = p0[:, 0]
    verts[:, 1, 1] = p0[:, 1]
    verts[:, 1, 2] = -nx
    verts[:, 1, 3] = -ny
    verts[:, 2, 0] = p1[:, 0]
    verts[:, 2, 1] = p1[:, 1]
    verts[:, 2, 2] = nx
    verts[:, 2, 3] = ny
    verts[:, 3] = verts[:, 1]
    verts[:, 4, 0] = p1[:, 0]
    verts[:, 4, 1] = p1[:, 1]
    verts[:, 4, 2] = -nx
    verts[:, 4, 3] = -ny
    verts[:, 5] = verts[:, 2]
    data.frombytes(np.ascontiguousarray(verts).tobytes())
    return data


def km_grid_segments(
    frame: tuple[float, float, float, float],
    cell_m: float = GRID_M,
) -> np.ndarray:
    """Axis-aligned 1 km lines in world metres. Cell size does not depend on zoom."""
    minx, miny, maxx, maxy = (float(v) for v in frame)
    cell = float(cell_m)
    xs = np.arange(np.floor(minx / cell) * cell, maxx + cell * 0.5, cell)
    ys = np.arange(np.floor(miny / cell) * cell, maxy + cell * 0.5, cell)
    segs = np.empty((xs.size + ys.size, 2, 2), dtype=np.float64)
    segs[: xs.size, 0, 0] = xs
    segs[: xs.size, 0, 1] = miny
    segs[: xs.size, 1, 0] = xs
    segs[: xs.size, 1, 1] = maxy
    segs[xs.size :, 0, 0] = minx
    segs[xs.size :, 0, 1] = ys
    segs[xs.size :, 1, 0] = maxx
    segs[xs.size :, 1, 1] = ys
    return segs
