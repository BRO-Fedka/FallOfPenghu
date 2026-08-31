from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter

GRASS_FOREST_OVERLAP_M = 1.0
CLEARING_AREA_FRAC = 0.95


def _shape(feat: dict):
    from shapely.geometry import shape

    geom = shape(feat.get("geometry") or {})
    if geom.is_empty:
        return None
    if not geom.is_valid:
        geom = geom.buffer(0)
    if geom.is_empty:
        return None
    return geom


def _parts(geom) -> list:
    if geom is None or geom.is_empty:
        return []
    gtype = geom.geom_type
    if gtype == "Polygon":
        return [geom]
    if gtype == "MultiPolygon":
        return [p for p in geom.geoms if not p.is_empty]
    if gtype == "GeometryCollection":
        out: list = []
        for item in geom.geoms:
            out.extend(_parts(item))
        return out
    return []


def _feature(poly, props: dict, feat_id: str) -> dict | None:
    if poly.is_empty or poly.area < 1.0:
        return None
    coords = [[float(x), float(y)] for x, y in poly.exterior.coords]
    if len(coords) < 4:
        return None
    holes = []
    for ring in poly.interiors:
        hole = [[float(x), float(y)] for x, y in ring.coords]
        if len(hole) >= 4:
            holes.append(hole)
    new_props = dict(props)
    new_props["id"] = feat_id
    new_props["area_m2"] = round(float(poly.area), 2)
    return {
        "type": "Feature",
        "properties": new_props,
        "geometry": {"type": "Polygon", "coordinates": [coords, *holes]},
    }


def clip_grass_over_forest(features: list[dict]) -> list[dict]:
    """Drop grass fully inside forest. If it only rides onto forest, keep a 1 m collar."""
    from shapely.ops import unary_union

    forests = [f for f in features if (f.get("properties") or {}).get("class") == "forest"]
    grasses = [f for f in features if (f.get("properties") or {}).get("class") != "forest"]
    if not forests or not grasses:
        return features

    t0 = perf_counter()
    forest_geoms = [g for g in (_shape(f) for f in forests) if g is not None]
    if not forest_geoms:
        return features
    forest_u = unary_union(forest_geoms)
    if forest_u.is_empty:
        return features
    collar_zone = forest_u.boundary.buffer(GRASS_FOREST_OVERLAP_M)

    out: list[dict] = list(forests)
    kept_whole = 0
    clipped = 0
    dropped = 0
    dropped_inside = 0
    for feat in grasses:
        props = dict(feat.get("properties") or {})
        base_id = str(props.get("id") or "veg/grass")
        geom = _shape(feat)
        if geom is None:
            dropped += 1
            continue
        overlap = geom.intersection(forest_u)
        overlap_area = 0.0 if overlap.is_empty else overlap.area
        if overlap_area <= 1e-6:
            written = _feature(geom, props, base_id)
            if written is not None:
                out.append(written)
                kept_whole += 1
            else:
                dropped += 1
            continue
        if geom.area > 1e-6 and (overlap_area / geom.area) >= CLEARING_AREA_FRAC:
            dropped_inside += 1
            continue
        outside = geom.difference(forest_u)
        collar = overlap.intersection(collar_zone)
        kept = outside.union(collar) if not collar.is_empty else outside
        parts = _parts(kept)
        if not parts:
            dropped += 1
            continue
        for i, part in enumerate(parts):
            feat_id = base_id if len(parts) == 1 else f"{base_id}/{i}"
            written = _feature(part, props, feat_id)
            if written is not None:
                out.append(written)
                clipped += 1
            else:
                dropped += 1

    print(
        f"Veg clip grass-forest: keep {kept_whole}  collar {clipped}  "
        f"drop {dropped}  inside {dropped_inside}  in {perf_counter() - t0:.2f}s",
        flush=True,
    )
    return out


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preprocess_map(map_dir: Path) -> None:
    map_dir = Path(map_dir)
    veg_path = map_dir / "vegetation.geojson"
    data = json.loads(veg_path.read_text(encoding="utf-8"))
    features = clip_grass_over_forest(data.get("features") or [])
    data["features"] = features
    veg_path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    digest = _sha256(veg_path)
    n_feat = len(features)
    n_holes = 0
    for feat in features:
        geom = feat.get("geometry") or {}
        if geom.get("type") == "Polygon":
            n_holes += max(len(geom.get("coordinates") or []) - 1, 0)

    manifest_path = map_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    veg = manifest.setdefault("layers", {}).setdefault("vegetation", {})
    veg["file"] = "vegetation.geojson"
    veg["features"] = n_feat
    veg["holes"] = n_holes
    veg["hash"] = digest[:12]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    checksums_path = map_dir / "CHECKSUMS.txt"
    lines = []
    if checksums_path.is_file():
        for line in checksums_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            name = line.split()[-1]
            if name in ("vegetation.geojson", "manifest.json"):
                continue
            lines.append(line)
    lines.append(f"{digest}  vegetation.geojson")
    lines.append(f"{_sha256(manifest_path)}  manifest.json")
    checksums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {veg_path}  features={n_feat}  hash={digest[:12]}", flush=True)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("penghu_map_v1")
    preprocess_map(target)
