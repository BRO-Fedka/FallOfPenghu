from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter

GRASS_FOREST_OVERLAP_M = 1.0
INSIDE_AREA_FRAC = 0.95


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


def _filled(geom):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    polys = []
    for part in _parts(geom):
        ext = list(part.exterior.coords)
        if len(ext) >= 4:
            polys.append(Polygon(ext))
    if not polys:
        return None
    merged = unary_union(polys)
    return merged if not merged.is_empty else None


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


def _emit_parts(geom, props: dict, base_id: str) -> list[dict]:
    out: list[dict] = []
    parts = _parts(geom)
    for i, part in enumerate(parts):
        feat_id = base_id if len(parts) == 1 else f"{base_id}/{i}"
        written = _feature(part, props, feat_id)
        if written is not None:
            out.append(written)
    return out


def _load_layer(map_dir: Path, filename: str) -> list[dict]:
    path = map_dir / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("features") or [])


def _land_union(map_dir: Path):
    from shapely.ops import unary_union

    geoms = []
    for name in ("coast.geojson", "taiwan.geojson"):
        for feat in _load_layer(map_dir, name):
            geom = _shape(feat)
            if geom is not None:
                geoms.append(geom)
    if not geoms:
        return None
    land = unary_union(geoms)
    if land.is_empty:
        return None
    if not land.is_valid:
        land = land.buffer(0)
    return land if not land.is_empty else None


def clip_veg_to_land(features: list[dict], land) -> list[dict]:
    """Keep only the part of each veg polygon that sits on land."""
    t0 = perf_counter()
    out: list[dict] = []
    clipped = 0
    dropped = 0
    kept = 0
    for feat in features:
        props = dict(feat.get("properties") or {})
        base_id = str(props.get("id") or "veg")
        geom = _shape(feat)
        if geom is None:
            dropped += 1
            continue
        cut = geom.intersection(land)
        if cut.is_empty:
            dropped += 1
            continue
        if cut.area + 1e-6 < geom.area:
            clipped += 1
        else:
            kept += 1
        written = _emit_parts(cut, props, base_id)
        if not written:
            dropped += 1
            if cut.area + 1e-6 < geom.area:
                clipped -= 1
            continue
        out.extend(written)
    print(
        f"Veg clip to land: keep {kept}  trim {clipped}  drop {dropped}  "
        f"in {perf_counter() - t0:.2f}s",
        flush=True,
    )
    return out


def _is_forest(feat: dict) -> bool:
    return (feat.get("properties") or {}).get("class") == "forest"


def drop_islands(
    features: list[dict],
    *,
    drop_class: str,
    host_class: str,
) -> list[dict]:
    """Drop drop_class polygons that sit almost entirely inside host_class."""
    from shapely.ops import unary_union

    if drop_class == "forest":
        guests = [f for f in features if _is_forest(f)]
        hosts = [f for f in features if not _is_forest(f)]
    else:
        guests = [f for f in features if not _is_forest(f)]
        hosts = [f for f in features if _is_forest(f)]
    if not hosts or not guests:
        return features

    t0 = perf_counter()
    filled = []
    for feat in hosts:
        geom = _filled(_shape(feat))
        if geom is not None:
            filled.append(geom)
    if not filled:
        return features
    host_u = unary_union(filled)
    if host_u.is_empty:
        return features

    kept_guests: list[dict] = []
    dropped = 0
    for feat in guests:
        geom = _shape(feat)
        if geom is None or geom.area <= 1e-6:
            dropped += 1
            continue
        overlap = geom.intersection(host_u)
        frac = 0.0 if overlap.is_empty else overlap.area / geom.area
        if frac >= INSIDE_AREA_FRAC:
            dropped += 1
            continue
        kept_guests.append(feat)

    print(
        f"Veg drop {drop_class} inside {host_class}: "
        f"keep {len(kept_guests)}  drop {dropped}  in {perf_counter() - t0:.2f}s",
        flush=True,
    )
    if drop_class == "forest":
        return kept_guests + hosts
    return hosts + kept_guests


def clip_grass_over_forest(features: list[dict]) -> list[dict]:
    """Drop grass fully inside forest. If grass only rides onto forest, keep a 1 m collar."""
    from shapely.ops import unary_union

    forests = [f for f in features if _is_forest(f)]
    grasses = [f for f in features if not _is_forest(f)]
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
        geom = _filled(_shape(feat))
        if geom is None:
            dropped += 1
            continue
        overlap = geom.intersection(forest_u)
        overlap_area = 0.0 if overlap.is_empty else overlap.area
        if overlap_area <= 1e-6:
            written = _emit_parts(geom, props, base_id)
            if written:
                out.extend(written)
                kept_whole += 1
            else:
                dropped += 1
            continue
        if geom.area > 1e-6 and (overlap_area / geom.area) >= INSIDE_AREA_FRAC:
            dropped_inside += 1
            continue
        outside = geom.difference(forest_u)
        collar = overlap.intersection(collar_zone)
        kept = outside.union(collar) if not collar.is_empty else outside
        written = _emit_parts(kept, props, base_id)
        if not written:
            dropped += 1
            continue
        out.extend(written)
        clipped += 1

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
    features = list(data.get("features") or [])

    land = _land_union(map_dir)
    if land is None:
        print("Veg clip to land: no coast/taiwan polygons, skip", flush=True)
    else:
        features = clip_veg_to_land(features, land)

    features = drop_islands(features, drop_class="forest", host_class="grass")
    features = drop_islands(features, drop_class="grass", host_class="forest")
    features = clip_grass_over_forest(features)

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
