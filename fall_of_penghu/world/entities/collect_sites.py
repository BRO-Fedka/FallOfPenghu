"""Bake static site centroids (and seed units) into sites.json once."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from fall_of_penghu.world.map import MapData, PolyFeature, load_map

SITES_NAME = "sites.json"
PIER_FIELD_NAME = "piers_field.npz"
BRIDGE_CLUSTER_M = 100.0
BRIDGE_ISLAND_SNAP_M = 150.0
BRIDGE_KEEP_M = 250.0
# Centroids (or click) of water spans that fail the two-island test but are real sites.
BRIDGE_KEEP_XY = (
    (1979.0, 19021.0),
)
REMOVED_PORT_MATCH_M = 40.0
SHIP_OFFSHORE_M = 350.0

AIRFIELD_NAMES = {
    "RCQC": "Magong Airfield",
    "RCCM": "Qimei Airfield",
    "RCWA": "Wang-an Airfield",
}


def _point_in_ring(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            xint = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xint:
                inside = not inside
        j = i
    return inside


def _point_in_poly(x: float, y: float, feat: PolyFeature) -> bool:
    minx, miny, maxx, maxy = feat.bbox
    if x < minx or x > maxx or y < miny or y > maxy:
        return False
    if not _point_in_ring(x, y, feat.exterior):
        return False
    for hole in feat.holes:
        if _point_in_ring(x, y, hole):
            return False
    return True


def _is_land(world: MapData, x: float, y: float) -> bool:
    if world.coast_grid is not None:
        for i in world.coast_grid.query(x, y, x, y):
            if _point_in_poly(x, y, world.coast[i]):
                return True
    for feat in world.taiwan:
        if _point_in_poly(x, y, feat):
            return True
    return False


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _pier_centroids(map_dir: Path) -> list[tuple[float, float]]:
    path = map_dir / PIER_FIELD_NAME
    with np.load(path) as z:
        mask = z["mask"]
        frame = [float(v) for v in z["frame"]]
    ys, xs = np.nonzero(mask)
    n = int(ys.size)
    if n == 0:
        return []
    index = {(int(xs[i]), int(ys[i])): i for i in range(n)}
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        x = int(xs[i])
        y = int(ys[i])
        right = index.get((x + 1, y))
        up = index.get((x, y + 1))
        if right is not None:
            union(i, right)
        if up is not None:
            union(i, up)

    buckets: dict[int, list[int]] = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(i)

    minx, miny, maxx, maxy = frame
    h, w = mask.shape
    sx = (maxx - minx) / max(w - 1, 1)
    sy = (maxy - miny) / max(h - 1, 1)
    out: list[tuple[float, float]] = []
    for members in buckets.values():
        if len(members) < 3:
            continue
        px = sum(int(xs[i]) for i in members) / len(members)
        py = sum(int(ys[i]) for i in members) / len(members)
        out.append((minx + px * sx, miny + py * sy))
    out.sort(key=lambda p: (p[1], p[0]))
    return out


def _island_at(world: MapData, x: float, y: float) -> int | None:
    if world.coast_grid is not None:
        for i in world.coast_grid.query(x, y, x, y):
            if _point_in_poly(x, y, world.coast[i]):
                return i
    else:
        for i, feat in enumerate(world.coast):
            if _point_in_poly(x, y, feat):
                return i
    return None


def _nearest_island(world: MapData, x: float, y: float, max_m: float) -> int | None:
    hit = _island_at(world, x, y)
    if hit is not None:
        return hit
    pad = max_m
    if world.coast_grid is not None:
        ids = world.coast_grid.query(x - pad, y - pad, x + pad, y + pad)
    else:
        ids = range(len(world.coast))
    best_i: int | None = None
    best_d = max_m * max_m
    for i in ids:
        feat = world.coast[i]
        step = max(1, len(feat.exterior) // 48)
        for px, py in feat.exterior[::step]:
            d = (px - x) * (px - x) + (py - y) * (py - y)
            if d < best_d:
                best_d = d
                best_i = i
    return best_i


def _cluster_islands(world: MapData, pts: list[tuple[float, float]]) -> set[int]:
    islands: set[int] = set()
    for x, y in pts:
        i = _island_at(world, x, y)
        if i is not None:
            islands.add(i)
    if len(islands) >= 2:
        return islands
    for x, y in (pts[0], pts[-1]):
        i = _nearest_island(world, x, y, BRIDGE_ISLAND_SNAP_M)
        if i is not None:
            islands.add(i)
    return islands


def _near_keep_bridge(x: float, y: float) -> bool:
    thresh2 = BRIDGE_KEEP_M * BRIDGE_KEEP_M
    for kx, ky in BRIDGE_KEEP_XY:
        dx = x - kx
        dy = y - ky
        if dx * dx + dy * dy <= thresh2:
            return True
    return False


def _airfield_sites(world: MapData) -> list[dict]:
    groups: dict[str, list[tuple[float, float]]] = {}
    for feat in world.airports:
        icao = feat.icao or "UNK"
        groups.setdefault(icao, []).extend(feat.exterior)
    sites: list[dict] = []
    for icao in sorted(groups):
        x, y = _centroid(groups[icao])
        sites.append(
            {
                "id": f"airfield_{icao}",
                "kind": "airfield",
                "name": AIRFIELD_NAMES.get(icao, f"{icao} Airfield"),
                "x": x,
                "y": y,
            }
        )
    return sites


def _bridge_sites(world: MapData) -> list[dict]:
    segs = [r for r in world.roads if r.bridge]
    if not segs:
        return []
    parent = list(range(len(segs)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    thresh2 = BRIDGE_CLUSTER_M * BRIDGE_CLUSTER_M
    for i, a in enumerate(segs):
        for j in range(i + 1, len(segs)):
            b = segs[j]
            hit = False
            for ax, ay in a.points:
                for bx, by in b.points:
                    dx = ax - bx
                    dy = ay - by
                    if dx * dx + dy * dy <= thresh2:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                parent[find(j)] = find(i)

    clusters: dict[int, list[int]] = {}
    for i in range(len(segs)):
        clusters.setdefault(find(i), []).append(i)

    sites: list[dict] = []
    ordered = sorted(clusters.values(), key=lambda idxs: segs[idxs[0]].bbox)
    n = 0
    for idxs in ordered:
        pts: list[tuple[float, float]] = []
        for i in idxs:
            pts.extend(segs[i].points)
        x, y = _centroid(pts)
        islands = _cluster_islands(world, pts)
        keep = len(islands) >= 2 or _near_keep_bridge(x, y)
        if not keep:
            continue
        n += 1
        sites.append(
            {
                "id": f"bridge_{n:02d}",
                "kind": "bridge",
                "name": f"Bridge {n}",
                "x": x,
                "y": y,
            }
        )
    return sites


def _main_island(world: MapData) -> PolyFeature:
    return max(world.coast, key=lambda f: f.area_m2)


def _seed_units(world: MapData) -> list[dict]:
    island = _main_island(world)
    cx, cy = _centroid(island.exterior)
    if not _point_in_poly(cx, cy, island):
        cx, cy = island.exterior[0]

    road_pt = (cx, cy)
    best = 1e30
    for road in world.roads:
        for x, y in road.points:
            if not _point_in_poly(x, y, island):
                continue
            d = (x - cx) * (x - cx) + (y - cy) * (y - cy)
            if d < best:
                best = d
                road_pt = (x, y)

    left = min(island.exterior, key=lambda p: p[0])
    ship = (left[0] - SHIP_OFFSHORE_M, left[1])
    for dist in range(200, 2500, 50):
        cand = (left[0] - float(dist), left[1])
        if not _is_land(world, cand[0], cand[1]):
            ship = cand
            break

    return [
        {
            "id": "ship_1",
            "kind": "ship",
            "name": "Patrol craft",
            "x": ship[0],
            "y": ship[1],
            "heading": 0.0,
            "speed_mps": 7.5,
            "mobility": "sea",
        },
        {
            "id": "drone_1",
            "kind": "drone",
            "name": "Recon UAV",
            "x": cx,
            "y": cy,
            "heading": 0.0,
            "speed_mps": 30.0,
            "mobility": "air",
        },
        {
            "id": "aa_1",
            "kind": "aaw",
            "name": "AAW",
            "x": road_pt[0],
            "y": road_pt[1],
            "heading": 0.0,
            "speed_mps": 11.0,
            "mobility": "land",
        },
    ]


def _load_existing(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _port_removed(x: float, y: float, removed: list[dict]) -> bool:
    thresh2 = REMOVED_PORT_MATCH_M * REMOVED_PORT_MATCH_M
    for rec in removed:
        dx = float(rec["x"]) - x
        dy = float(rec["y"]) - y
        if dx * dx + dy * dy <= thresh2:
            return True
    return False


def persist_removed_ports(sites_path: Path, points: list[tuple[float, float]]) -> None:
    path = Path(sites_path)
    data = _load_existing(path)
    if data.get("format") != "fall-of-penghu-sites":
        raise ValueError("unexpected sites format")
    removed = list(data.get("removed_ports") or [])
    keep_sites = []
    for site in data.get("sites") or []:
        if str(site.get("kind")) != "port":
            keep_sites.append(site)
            continue
        if _port_removed(float(site["x"]), float(site["y"]), [{"x": x, "y": y} for x, y in points]):
            continue
        keep_sites.append(site)
    for x, y in points:
        if not _port_removed(x, y, removed):
            removed.append({"x": x, "y": y})
    data["sites"] = keep_sites
    data["removed_ports"] = removed
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def collect_sites(map_dir: Path) -> dict:
    map_dir = Path(map_dir)
    world = load_map(map_dir)
    existing = _load_existing(map_dir / SITES_NAME)
    removed = list(existing.get("removed_ports") or [])
    ports = []
    n = 0
    for x, y in _pier_centroids(map_dir):
        if _port_removed(x, y, removed):
            continue
        n += 1
        ports.append(
            {
                "id": f"port_{n:03d}",
                "kind": "port",
                "name": f"Port {n}",
                "x": x,
                "y": y,
            }
        )
    payload = {
        "format": "fall-of-penghu-sites",
        "format_version": 1,
        "removed_ports": removed,
        "sites": ports + _airfield_sites(world) + _bridge_sites(world),
        "units": _seed_units(world),
    }
    return payload


def write_sites(map_dir: Path) -> Path:
    map_dir = Path(map_dir)
    payload = collect_sites(map_dir)
    out = map_dir / SITES_NAME
    with out.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    counts: dict[str, int] = {}
    for site in payload["sites"]:
        counts[site["kind"]] = counts.get(site["kind"], 0) + 1
    print(
        f"Wrote {out}  "
        + "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        + f"  units={len(payload['units'])}",
        flush=True,
    )
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("penghu_map_v1")
    write_sites(target)
