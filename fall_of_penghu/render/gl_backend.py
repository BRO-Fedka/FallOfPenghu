from __future__ import annotations

import pickle
from array import array
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from fall_of_penghu.camera import Camera
from fall_of_penghu.mapdata import MapData
from fall_of_penghu.render.geom import pack_xy, stroke_polyline, stroke_seaward_band, triangulate
from fall_of_penghu.render.seafield import SEA_MAX_DIST_M, SEA_TEX_SIZE, build_sea_distance
from fall_of_penghu.render.veg import VEG_DETAIL_CROWNS, VegParams
from fall_of_penghu.render.urban import UrbanParams, RoadParams
from fall_of_penghu.render.pier_params import PierParams
from fall_of_penghu.render.vegfield import _penghu_frame
from fall_of_penghu.render.water import WaterParams
from fall_of_penghu.render.scene import (
    AIRPORTS_FADE_FULL_M,
    AIRPORTS_FADE_GONE_M,
    BUILDINGS_FADE_FULL_M,
    BUILDINGS_FADE_GONE_M,
    ROADS_FADE_FULL_M,
    ROADS_FADE_GONE_M,
    layer_opacity,
    palette_for,
)

SHADER_DIR = Path(__file__).resolve().parent / "shaders"
MESH_CACHE = Path(__file__).resolve().parents[2] / "output" / "gl_meshes_v1.pkl"
FULLSCREEN_TRI = array("f", [-1.0, -1.0, 3.0, -1.0, -1.0, 3.0])
MSAA_SAMPLES = 4
MIN_ROAD_WIDTH_M = 2.0
RADAR_OUTLINE_M = 8.0
PIER_FIELD_NAME = "piers_field.npz"
FIELD_CACHE_NAME = "gl_fields_v1.npz"
SDF_TEX_MAX_DIM = 8192


def _poly_groups(world: MapData):
    return (
        world.taiwan,
        world.coast,
        world.vegetation,
        world.buildings,
        world.airports,
    )


def _mesh_cache_key(world: MapData) -> str:
    layers = world.manifest.get("layers") or {}
    veg = layers.get("vegetation") or {}
    return "|".join(
        (
            str(world.manifest.get("content_version")),
            str(veg.get("hash")),
            str(len(world.taiwan)),
            str(len(world.coast)),
            str(len(world.vegetation)),
            str(len(world.buildings)),
            str(len(world.airports)),
        )
    )


def _shader(name: str) -> str:
    src = (SHADER_DIR / name).read_text(encoding="utf-8")
    common = (SHADER_DIR / "common.glsl").read_text(encoding="utf-8")
    return src.replace('#include "common.glsl"', common)


def _set_uniform(prog, name: str, value) -> None:
    if name in prog:
        prog[name].value = value


def _concat(chunks: list[array]) -> array:
    out = array("f")
    for chunk in chunks:
        if chunk:
            out.extend(chunk)
    return out


def _ring_xy_closed(coords) -> list[tuple[float, float]]:
    pts = [(float(x), float(y)) for x, y in coords]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts.pop()
    return pts


def _shapely_polys(geom) -> list:
    if geom is None or geom.is_empty:
        return []
    gtype = geom.geom_type
    if gtype == "Polygon":
        return [geom]
    if gtype == "MultiPolygon":
        return [p for p in geom.geoms if not p.is_empty]
    if gtype == "GeometryCollection":
        out = []
        for item in geom.geoms:
            out.extend(_shapely_polys(item))
        return out
    return []


def _union_veg_rings(vegetation) -> list[tuple[list[tuple[float, float]], list[list[tuple[float, float]]]]]:
    """Exterior + holes of forest∪grass. Shared forest/grass edges disappear."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    geoms = []
    for feat in vegetation:
        try:
            poly = Polygon(feat.exterior, feat.holes or None)
        except Exception:
            continue
        if poly.is_empty:
            continue
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly is None or poly.is_empty:
            continue
        geoms.append(poly)
    if not geoms:
        return []
    merged = unary_union(geoms)
    if merged.is_empty:
        return []
    if not merged.is_valid:
        merged = merged.buffer(0)
    rings: list[tuple[list[tuple[float, float]], list[list[tuple[float, float]]]]] = []
    for part in _shapely_polys(merged):
        exterior = _ring_xy_closed(part.exterior.coords)
        if len(exterior) < 3:
            continue
        holes = []
        for hole in part.interiors:
            ring = _ring_xy_closed(hole.coords)
            if len(ring) >= 3:
                holes.append(ring)
        rings.append((exterior, holes))
    return rings


def _flip_band_t(data: array) -> array:
    flipped = array("f", data)
    for i in range(2, len(flipped), 5):
        flipped[i] = 1.0 - flipped[i]
    return flipped


def _band_chunks_for_poly(
    exterior: list[tuple[float, float]],
    holes: list[list[tuple[float, float]]],
    width: float,
) -> list[array]:
    chunks: list[array] = []
    band = stroke_seaward_band(
        exterior, 0.05, closed=True, landward_m=width
    )
    if len(band) >= 15:
        chunks.append(band)
    for hole in holes:
        inner = stroke_seaward_band(hole, width, closed=True, landward_m=0.05)
        if len(inner) >= 15:
            chunks.append(_flip_band_t(inner))
    return chunks


def _field_sample(
    buf: array,
    size: tuple[int, int],
    frame: tuple[float, float, float, float],
    x: float,
    y: float,
) -> float:
    w, h = size
    if w < 2 or h < 2 or not buf:
        return 0.0
    minx, miny, maxx, maxy = frame
    fx = (x - minx) / max(maxx - minx, 1.0) * (w - 1)
    fy = (y - miny) / max(maxy - miny, 1.0) * (h - 1)
    x0 = int(max(0, min(w - 2, fx // 1)))
    y0 = int(max(0, min(h - 2, fy // 1)))
    tx = fx - x0
    ty = fy - y0
    i00 = y0 * w + x0
    a = buf[i00] * (1.0 - tx) + buf[i00 + 1] * tx
    b = buf[i00 + w] * (1.0 - tx) + buf[i00 + w + 1] * tx
    return float(a * (1.0 - ty) + b * ty)


def _house_miter_splat(
    ring: list[tuple[float, float]], extent: float, peak: float, data: array
) -> bool:
    """Miter-buffer of the footprint: t=0 on the wall, t=1 at offset extent."""
    if len(ring) >= 2 and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        return False
    band = stroke_seaward_band(ring, extent, closed=True, landward_m=0.0)
    if len(band) < 15:
        return False
    for i in range(0, len(band), 5):
        data.extend((band[i], band[i + 1], band[i + 2], peak))
    for x, y in triangulate(ring, None):
        data.extend((x, y, 0.0, peak))
    return True


def _dots_on_polyline(
    points: list[tuple[float, float]], step_m: float
) -> list[tuple[float, float]]:
    if len(points) < 2:
        return list(points)
    step = max(step_m, 4.0)
    out: list[tuple[float, float]] = [points[0]]
    remain = 0.0
    for i in range(len(points) - 1):
        ax, ay = points[i]
        bx, by = points[i + 1]
        dx = bx - ax
        dy = by - ay
        seg = (dx * dx + dy * dy) ** 0.5
        if seg < 1e-4:
            continue
        pos = remain
        while pos <= seg:
            t = pos / seg
            out.append((ax + dx * t, ay + dy * t))
            pos += step
        remain = pos - seg
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out


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


def _clamped_sdf_max_dim(ctx) -> int:
    max_dim = SDF_TEX_MAX_DIM
    try:
        info = ctx.info or {}
        hw = int(info.get("GL_MAX_TEXTURE_SIZE") or max_dim)
        max_dim = max(256, min(max_dim, hw))
    except Exception:
        pass
    return max_dim


def _field_cache_key(
    world: MapData,
    veg: VegParams,
    urban: UrbanParams,
    roads: RoadParams,
    piers: PierParams,
    field_dtype: str,
) -> str:
    layers = world.manifest.get("layers") or {}
    veg_layer = layers.get("vegetation") or {}
    pier_layer = layers.get("piers") or {}
    return "|".join(
        (
            str(world.manifest.get("content_version")),
            str(veg_layer.get("hash")),
            str(len(world.taiwan)),
            str(len(world.coast)),
            str(len(world.vegetation)),
            str(len(world.buildings)),
            str(len(world.roads)),
            str(len(world.airports)),
            str(SDF_TEX_MAX_DIM),
            str(int(VEG_DETAIL_CROWNS)),
            field_dtype,
            str(veg.band_width_m),
            str(urban.kernel),
            str(urban.sigma_m),
            str(urban.peak),
            str(urban.size_ref_m),
            str(urban.splat_sigmas),
            str(roads.kernel),
            str(roads.sigma_m),
            str(roads.peak),
            str(roads.width_ref_m),
            str(roads.splat_sigmas),
            str(roads.step_m),
            str(roads.gain),
            str(roads.influence),
            str(piers.stamp_value),
            str(pier_layer.get("rings")),
            str(pier_layer.get("pixels")),
            str(pier_layer.get("stamp_value")),
        )
    )


@dataclass
class StaticMesh:
    vao: object
    nverts: int
    features: int
    vbo: object = None


class GLMapRenderer:
    """GPU path: static VBOs per layer, a handful of draw calls per frame."""

    backend = "gl"

    def __init__(self, world: MapData, ctx, size: tuple[int, int]) -> None:
        import moderngl

        self.mgl = moderngl
        self.world = world
        self.ctx = ctx
        self.radar = False
        self.last_stats: dict[str, int] = {}
        self._size = (max(1, size[0]), max(1, size[1]))
        self._t0 = perf_counter()
        self._cpu_meshes: dict[int, array] = {}
        self.layers: dict[str, StaticMesh] = {}
        self.water = WaterParams()
        self.veg = VegParams()
        self.urban = UrbanParams()
        self.road_params = RoadParams()
        self.pier_params = PierParams()
        self.prog_map = ctx.program(
            vertex_shader=_shader("map.vert"),
            fragment_shader=_shader("map.frag"),
        )
        self.prog_land = ctx.program(
            vertex_shader=_shader("veg.vert"),
            fragment_shader=_shader("land.frag"),
        )
        self.prog_urban_splat = ctx.program(
            vertex_shader=_shader("urban_splat.vert"),
            fragment_shader=_shader("urban_splat.frag"),
        )
        self.prog_road_splat = ctx.program(
            vertex_shader=_shader("road_splat.vert"),
            fragment_shader=_shader("road_splat.frag"),
        )
        self.prog_post = ctx.program(
            vertex_shader=_shader("post.vert"),
            fragment_shader=_shader("post.frag"),
        )
        self.prog_field_add = ctx.program(
            vertex_shader=_shader("post.vert"),
            fragment_shader=_shader("field_add.frag"),
        )
        self.prog_overlay = ctx.program(
            vertex_shader=_shader("overlay.vert"),
            fragment_shader=_shader("overlay.frag"),
        )
        self.prog_sea = ctx.program(
            vertex_shader=_shader("sea.vert"),
            fragment_shader=_shader("sea.frag"),
        )
        self.prog_shore = ctx.program(
            vertex_shader=_shader("shore.vert"),
            fragment_shader=_shader("shore.frag"),
        )
        self.prog_veg = None
        self.prog_veg_grass = None
        if VEG_DETAIL_CROWNS:
            self.prog_veg = ctx.program(
                vertex_shader=_shader("veg.vert"),
                fragment_shader=_shader("veg.frag"),
            )
            self.prog_veg_grass = ctx.program(
                vertex_shader=_shader("veg.vert"),
                fragment_shader=_shader("veg_grass.frag"),
            )
        self.prog_veg_sdf = ctx.program(
            vertex_shader=_shader("veg_sdf.vert"),
            fragment_shader=_shader("veg_sdf.frag"),
        )
        self.prog_veg_sdf_fill = ctx.program(
            vertex_shader=_shader("veg.vert"),
            fragment_shader=_shader("veg_sdf_fill.frag"),
        )
        self._load_cpu_meshes()
        self._upload_static_layers()
        self._cpu_meshes.clear()
        self._sea_tex = None
        self._sea_frame = (-100_000.0, -100_000.0, 100_000.0, 100_000.0)
        self._upload_sea_field()
        self._shore_vao = None
        self._shore_nverts = 0
        self._upload_shore_band()
        self._veg_tex = None
        self._veg_mix_tex = None
        self._veg_frame = (-22_000.0, -32_000.0, 21_000.0, 35_000.0)
        self._veg_tex_size = (2, 2)
        self._land_tex = None
        self._land_frame = (-22_000.0, -32_000.0, 21_000.0, 35_000.0)
        self._land_sdf_vao = None
        self._land_sdf_nverts = 0
        self._veg_union_sdf_vao = None
        self._veg_union_sdf_nverts = 0
        self._forest_sdf_vao = None
        self._forest_sdf_nverts = 0
        self._grass_sdf_vao = None
        self._grass_sdf_nverts = 0
        self._urban_tex = None
        self._road_tex = None
        self._road_buf: array | None = None
        self._pier_tex = None
        self._pier_n = 0
        self._field_dtype = "f4"
        self._field_add_vbo = ctx.buffer(FULLSCREEN_TRI.tobytes())
        self._field_add_vao = ctx.vertex_array(
            self.prog_field_add, [(self._field_add_vbo, "2f", "in_pos")]
        )
        self._init_fields()
        self._post_vbo = ctx.buffer(FULLSCREEN_TRI.tobytes())
        self._post_vao = ctx.vertex_array(self.prog_post, [(self._post_vbo, "2f", "in_pos")])
        self._sea_vao = ctx.vertex_array(self.prog_sea, [(self._post_vbo, "2f", "in_pos")])
        self._overlay_vbo = ctx.buffer(reserve=96, dynamic=True)
        self._overlay_vao = ctx.vertex_array(
            self.prog_overlay, [(self._overlay_vbo, "2f 2f", "in_pos", "in_uv")]
        )
        self._fbo_tex = None
        self._fbo = None
        self._msaa_fbo = None
        self._msaa_rb = None
        self._msaa_samples = 0
        self._alloc_fbo(*self._size, log=True)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        if hasattr(moderngl, "MULTISAMPLE"):
            ctx.enable(moderngl.MULTISAMPLE)
        _set_uniform(self.prog_map, "u_opacity", 1.0)
        _set_uniform(self.prog_map, "u_tint", (1.0, 1.0, 1.0))

    def palette(self) -> dict[str, tuple[int, int, int]]:
        return palette_for(self.radar)

    def _load_cpu_meshes(self) -> None:
        t0 = perf_counter()
        key = _mesh_cache_key(self.world)
        blobs: list[bytes | None] | None = None
        if MESH_CACHE.is_file():
            try:
                payload = pickle.loads(MESH_CACHE.read_bytes())
                if payload.get("key") == key:
                    blobs = payload.get("blobs")
            except Exception:
                blobs = None
        expected = sum(len(group) for group in _poly_groups(self.world))
        if blobs is None or len(blobs) != expected:
            blobs = []
            for group in _poly_groups(self.world):
                for feat in group:
                    tris = triangulate(feat.exterior, feat.holes or None)
                    blobs.append(pack_xy(tris).tobytes() if tris else None)
            MESH_CACHE.parent.mkdir(parents=True, exist_ok=True)
            MESH_CACHE.write_bytes(pickle.dumps({"key": key, "blobs": blobs}, protocol=4))
        i = 0
        count = 0
        for group in _poly_groups(self.world):
            for feat in group:
                raw = blobs[i] if i < len(blobs) else None
                i += 1
                if raw:
                    mesh = array("f")
                    mesh.frombytes(raw)
                    self._cpu_meshes[id(feat)] = mesh
                    count += 1
        print(f"GL triangulate: {count} polygons in {perf_counter() - t0:.3f}s", flush=True)

    def _upload(self, data: array, features: int, prog=None) -> StaticMesh | None:
        if len(data) < 6 or features <= 0:
            return None
        vbo = self.ctx.buffer(data.tobytes())
        vao = self.ctx.vertex_array(prog or self.prog_map, [(vbo, "2f", "in_pos")])
        return StaticMesh(vao=vao, nverts=len(data) // 2, features=features, vbo=vbo)

    def _tris(self, feat) -> array | None:
        return self._cpu_meshes.get(id(feat))

    def _upload_static_layers(self) -> None:
        t0 = perf_counter()
        world = self.world

        def pack_polys(feats, predicate=None) -> tuple[array, int]:
            chunks: list[array] = []
            n = 0
            for feat in feats:
                if predicate is not None and not predicate(feat):
                    continue
                mesh = self._tris(feat)
                if mesh:
                    chunks.append(mesh)
                    n += 1
            return _concat(chunks), n

        def pack_lines(feats, width_fn, predicate=None) -> tuple[array, int]:
            chunks: list[array] = []
            n = 0
            for feat in feats:
                if predicate is not None and not predicate(feat):
                    continue
                stroke = stroke_polyline(feat.points, width_fn(feat), closed=False)
                if len(stroke) >= 6:
                    chunks.append(stroke)
                    n += 1
            return _concat(chunks), n

        taiwan, n_taiwan = pack_polys(world.taiwan)
        coast, n_coast = pack_polys(world.coast)
        forest, n_forest = pack_polys(
            world.vegetation, lambda f: f.class_name == "forest"
        )
        grass, n_grass = pack_polys(
            world.vegetation, lambda f: f.class_name != "forest"
        )
        buildings, n_buildings = pack_polys(world.buildings)
        airports, n_airports = pack_polys(world.airports)

        roads, n_roads = pack_lines(
            world.roads,
            lambda f: max(f.width_m, MIN_ROAD_WIDTH_M),
            lambda f: not f.bridge,
        )
        bridges, n_bridges = pack_lines(
            world.roads, lambda f: max(f.width_m, MIN_ROAD_WIDTH_M), lambda f: f.bridge
        )
        airport_lines, n_apt_lines = pack_lines(
            world.airport_lines, lambda f: max(f.width_m, 8.0)
        )

        outline_chunks: list[array] = []
        n_outline = 0
        for feat in world.coast:
            stroke = stroke_polyline(feat.exterior, RADAR_OUTLINE_M, closed=True)
            if len(stroke) >= 6:
                outline_chunks.append(stroke)
                n_outline += 1
        coast_outline = _concat(outline_chunks)

        forest_prog = self.prog_veg if VEG_DETAIL_CROWNS else self.prog_map
        grass_prog = self.prog_veg_grass if VEG_DETAIL_CROWNS else self.prog_map
        specs = {
            "taiwan": (taiwan, n_taiwan, self.prog_map),
            "coast": (coast, n_coast, self.prog_land),
            "forest": (forest, n_forest, forest_prog),
            "grass": (grass, n_grass, grass_prog),
            "buildings": (buildings, n_buildings, self.prog_map),
            "airports": (airports, n_airports, self.prog_map),
            "roads": (roads, n_roads, self.prog_map),
            "bridges": (bridges, n_bridges, self.prog_map),
            "airport_lines": (airport_lines, n_apt_lines, self.prog_map),
            "coast_outline": (coast_outline, n_outline, self.prog_map),
        }
        verts = 0
        draws = 0
        for name, (data, features, prog) in specs.items():
            mesh = self._upload(data, features, prog)
            if mesh is not None:
                self.layers[name] = mesh
                verts += mesh.nverts
                draws += 1
        print(
            f"GL static VBO: {draws} layers, {verts} verts in {perf_counter() - t0:.3f}s",
            flush=True,
        )

    def _sdf_fill_vao(self, name: str) -> tuple[object | None, int]:
        mesh = self.layers.get(name)
        if mesh is None or mesh.vbo is None or mesh.nverts < 3:
            return None, 0
        vao = self.ctx.vertex_array(
            self.prog_veg_sdf_fill, [(mesh.vbo, "2f", "in_pos")]
        )
        return vao, mesh.nverts

    def _upload_sea_field(self) -> None:
        data, size, frame = build_sea_distance(self.world)
        self._sea_frame = frame
        self._sea_tex = self.ctx.texture((size, size), 1, data)
        self._sea_tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
        self._sea_tex.repeat_x = False
        self._sea_tex.repeat_y = False

    def _upload_shore_band(self) -> None:
        width = max(self.water.mesh_width_m, 1.0)
        landward = max(self.water.band_landward_m, 0.0)
        chunks: list[array] = []
        for group in (self.world.taiwan, self.world.coast):
            for feat in group:
                band = stroke_seaward_band(
                    feat.exterior, width, closed=True, landward_m=landward
                )
                if len(band) >= 15:
                    chunks.append(band)
        data = _concat(chunks)
        if len(data) < 15:
            self._shore_vao = None
            self._shore_nverts = 0
            return
        vbo = self.ctx.buffer(data.tobytes())
        self._shore_vao = self.ctx.vertex_array(
            self.prog_shore, [(vbo, "2f 1f 2x4", "in_pos", "in_t")]
        )
        self._shore_nverts = len(data) // 5
        print(f"GL shore band: {self._shore_nverts} verts", flush=True)

    def _upload_veg_bands(self) -> None:
        width = max(self.veg.band_width_m, 8.0)
        forest_chunks: list[array] = []
        grass_chunks: list[array] = []
        n_forest = 0
        n_grass = 0
        for feat in self.world.vegetation:
            chunks = _band_chunks_for_poly(feat.exterior, feat.holes or [], width)
            if feat.class_name == "forest":
                if chunks:
                    n_forest += 1
                forest_chunks.extend(chunks)
            else:
                if chunks:
                    n_grass += 1
                grass_chunks.extend(chunks)
        union_chunks: list[array] = []
        n_union = 0
        for exterior, holes in _union_veg_rings(self.world.vegetation):
            part = _band_chunks_for_poly(exterior, holes, width)
            if part:
                n_union += 1
            union_chunks.extend(part)

        def upload(chunks: list[array]):
            data = _concat(chunks)
            if len(data) < 15:
                return None, 0
            vbo = self.ctx.buffer(data.tobytes())
            nverts = len(data) // 5
            vao = self.ctx.vertex_array(
                self.prog_veg_sdf, [(vbo, "2f 1f 2x4", "in_pos", "in_t")]
            )
            return vao, nverts

        self._forest_sdf_vao, self._forest_sdf_nverts = upload(forest_chunks)
        self._grass_sdf_vao, self._grass_sdf_nverts = upload(grass_chunks)
        self._veg_union_sdf_vao, self._veg_union_sdf_nverts = upload(union_chunks)
        print(
            f"GL veg bands: forest {self._forest_sdf_nverts} / {n_forest}  "
            f"grass {self._grass_sdf_nverts} / {n_grass}  "
            f"union {self._veg_union_sdf_nverts} / {n_union}",
            flush=True,
        )

    def _bake_sdf_rg(
        self,
        size: tuple[int, int],
        frame: tuple[float, float, float, float],
        fills: list[tuple[object | None, int, tuple[bool, bool, bool, bool]]],
        bands: list[tuple[object | None, int, tuple[bool, bool, bool, bool]]],
    ):
        tex = self.ctx.texture(size, 2)
        tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
        tex.repeat_x = False
        tex.repeat_y = False
        fbo = self.ctx.framebuffer(color_attachments=[tex])
        prev = self.ctx.fbo
        width = max(self.veg.band_width_m, 8.0)
        fbo.use()
        self.ctx.viewport = (0, 0, size[0], size[1])
        self.ctx.disable(self.mgl.DEPTH_TEST)
        self.ctx.disable(self.mgl.CULL_FACE)
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)

        def draw_channel(vao, nverts, mask) -> None:
            if vao is None or nverts < 3:
                return
            self.ctx.color_mask = mask
            vao.render(mode=self.mgl.TRIANGLES, vertices=nverts)

        self.ctx.disable(self.mgl.BLEND)
        _set_uniform(self.prog_veg_sdf_fill, "u_view", frame)
        for vao, nverts, mask in fills:
            draw_channel(vao, nverts, mask)

        used_min = False
        min_eq = getattr(self.mgl, "MIN", None)
        try:
            if min_eq is not None:
                self.ctx.blend_equation = min_eq
                self.ctx.enable(self.mgl.BLEND)
                used_min = True
            else:
                self.ctx.disable(self.mgl.BLEND)
        except Exception:
            self.ctx.disable(self.mgl.BLEND)
        _set_uniform(self.prog_veg_sdf, "u_view", frame)
        _set_uniform(self.prog_veg_sdf, "u_band_width", width)
        _set_uniform(self.prog_veg_sdf, "u_max", width)
        for vao, nverts, mask in bands:
            draw_channel(vao, nverts, mask)

        self.ctx.color_mask = True, True, True, True
        self.ctx.disable(self.mgl.BLEND)
        if used_min:
            self.ctx.blend_equation = self.mgl.FUNC_ADD
        self.ctx.blend_func = self.mgl.SRC_ALPHA, self.mgl.ONE_MINUS_SRC_ALPHA
        if prev is not None:
            prev.use()
        else:
            self.ctx.screen.use()
        fbo.release()
        return tex

    def _bake_veg_sdf(self) -> None:
        frame = _penghu_frame(self.world)
        size = _sdf_tex_size(frame, _clamped_sdf_max_dim(self.ctx))
        forest_fill, forest_fill_n = self._sdf_fill_vao("forest")
        grass_fill, grass_fill_n = self._sdf_fill_vao("grass")
        r_only = (True, False, False, False)
        g_only = (False, True, False, False)
        self._veg_tex = self._bake_sdf_rg(
            size,
            frame,
            [
                (forest_fill, forest_fill_n, r_only),
                (grass_fill, grass_fill_n, g_only),
            ],
            [
                (self._forest_sdf_vao, self._forest_sdf_nverts, r_only),
                (self._grass_sdf_vao, self._grass_sdf_nverts, g_only),
            ],
        )
        self._veg_mix_tex = self._bake_sdf_rg(
            size,
            frame,
            [
                (forest_fill, forest_fill_n, r_only),
                (grass_fill, grass_fill_n, r_only),
            ],
            [
                (self._veg_union_sdf_vao, self._veg_union_sdf_nverts, r_only),
            ],
        )
        self._veg_frame = frame
        self._veg_tex_size = size
        cell = (frame[2] - frame[0]) / max(size[0] - 1, 1)
        print(
            f"GL veg SDF {size[0]}x{size[1]} ({cell:.1f} m/px) + union mix",
            flush=True,
        )

    def _upload_land_bands(self) -> None:
        width = max(self.veg.band_width_m, 8.0)
        chunks: list[array] = []
        n_parts = 0
        for feat in self.world.coast:
            part = _band_chunks_for_poly(feat.exterior, feat.holes or [], width)
            if part:
                n_parts += 1
            chunks.extend(part)
        data = _concat(chunks)
        if len(data) < 15:
            self._land_sdf_vao = None
            self._land_sdf_nverts = 0
            return
        vbo = self.ctx.buffer(data.tobytes())
        self._land_sdf_nverts = len(data) // 5
        self._land_sdf_vao = self.ctx.vertex_array(
            self.prog_veg_sdf, [(vbo, "2f 1f 2x4", "in_pos", "in_t")]
        )
        print(
            f"GL land bands: {self._land_sdf_nverts} verts / {n_parts}",
            flush=True,
        )

    def _bake_land_sdf(self) -> None:
        frame = _penghu_frame(self.world)
        size = _sdf_tex_size(frame, _clamped_sdf_max_dim(self.ctx))
        coast_fill, coast_fill_n = self._sdf_fill_vao("coast")
        r_only = (True, False, False, False)
        self._land_tex = self._bake_sdf_rg(
            size,
            frame,
            [(coast_fill, coast_fill_n, r_only)],
            [(self._land_sdf_vao, self._land_sdf_nverts, r_only)],
        )
        self._land_frame = frame
        self._veg_tex_size = size
        cell = (frame[2] - frame[0]) / max(size[0] - 1, 1)
        print(
            f"GL land SDF {size[0]}x{size[1]} ({cell:.1f} m/px)",
            flush=True,
        )

    def _draw_land(
        self,
        view: tuple[float, float, float, float],
        pal: dict[str, tuple[int, int, int]],
    ) -> int:
        mesh = self.layers.get("coast")
        if mesh is None:
            return 0
        self.ctx.disable(self.mgl.BLEND)
        if self._land_tex is not None:
            self._land_tex.use(3)
        if self._urban_tex is not None:
            self._urban_tex.use(4)
        land = pal["land"]
        rock = pal.get("rock") or land
        concrete = pal.get("concrete") or (148, 144, 138)
        prog = self.prog_land
        _set_uniform(prog, "u_view", view)
        _set_uniform(prog, "u_land_frame", self._land_frame)
        _set_uniform(prog, "u_landf", 3)
        _set_uniform(prog, "u_urban", 4)
        _set_uniform(prog, "u_land", (land[0] / 255.0, land[1] / 255.0, land[2] / 255.0))
        _set_uniform(prog, "u_rock", (rock[0] / 255.0, rock[1] / 255.0, rock[2] / 255.0))
        _set_uniform(
            prog,
            "u_concrete",
            (concrete[0] / 255.0, concrete[1] / 255.0, concrete[2] / 255.0),
        )
        _set_uniform(prog, "u_radar", 1 if self.radar else 0)
        self.urban.bind(_set_uniform, prog)
        self.veg.bind(_set_uniform, prog)
        mesh.vao.render(mode=self.mgl.TRIANGLES, vertices=mesh.nverts)
        return mesh.features

    def _probe_field_dtype(self) -> str:
        prev = self.ctx.fbo
        tex = None
        fbo = None
        try:
            tex = self.ctx.texture((2, 2), 1, dtype="f2")
            fbo = self.ctx.framebuffer(color_attachments=[tex])
            fbo.use()
            self.ctx.clear(0.0, 0.0, 0.0, 1.0)
            return "f2"
        except Exception:
            return "f4"
        finally:
            if fbo is not None:
                fbo.release()
            if tex is not None:
                tex.release()
            if prev is not None:
                prev.use()
            else:
                try:
                    self.ctx.screen.use()
                except Exception:
                    pass

    def _make_float_tex(self, size: tuple[int, int]):
        tex = self.ctx.texture(size, 1, dtype=self._field_dtype)
        tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
        tex.repeat_x = False
        tex.repeat_y = False
        return tex

    def _begin_additive_splat(self, tex, size: tuple[int, int]):
        fbo = self.ctx.framebuffer(color_attachments=[tex])
        prev = self.ctx.fbo
        fbo.use()
        self.ctx.viewport = (0, 0, size[0], size[1])
        self.ctx.disable(self.mgl.DEPTH_TEST)
        self.ctx.disable(self.mgl.CULL_FACE)
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        self.ctx.enable(self.mgl.BLEND)
        self.ctx.blend_equation = self.mgl.FUNC_ADD
        self.ctx.blend_func = self.mgl.ONE, self.mgl.ONE
        return fbo, prev

    def _end_additive_splat(self, fbo, prev) -> None:
        self.ctx.disable(self.mgl.BLEND)
        self.ctx.blend_func = self.mgl.SRC_ALPHA, self.mgl.ONE_MINUS_SRC_ALPHA
        if prev is not None:
            prev.use()
        else:
            self.ctx.screen.use()
        fbo.release()

    def _init_fields(self) -> None:
        self._field_dtype = self._probe_field_dtype()
        print(f"GL field dtype: {self._field_dtype}", flush=True)
        if self._load_field_cache():
            return
        self._bake_fields()
        self._save_field_cache()

    def _bake_fields(self) -> None:
        if VEG_DETAIL_CROWNS:
            self._upload_veg_bands()
            self._bake_veg_sdf()
        self._upload_land_bands()
        self._bake_land_sdf()
        self._load_pier_field()
        self._bake_road_field()
        self._bake_urban_field()
        self._release_road_field()

    def _release_road_field(self) -> None:
        if self._road_tex is not None:
            self._road_tex.release()
            self._road_tex = None
        self._road_buf = None

    def _upload_rg8(self, size: tuple[int, int], pixels) -> object:
        tex = self.ctx.texture(size, 2, data=pixels)
        tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
        tex.repeat_x = False
        tex.repeat_y = False
        return tex

    def _read_rg8(self, tex) -> object:
        import numpy as np

        w, h = tex.size
        data = np.frombuffer(tex.read(), dtype=np.uint8)
        return np.ascontiguousarray(data.reshape(h, w, 2))

    def _read_urban_array(self, tex) -> object:
        import numpy as np

        w, h = tex.size
        np_dtype = np.float16 if self._field_dtype == "f2" else np.float32
        data = np.frombuffer(tex.read(), dtype=np_dtype)
        return np.ascontiguousarray(data.reshape(h, w))

    def _field_cache_path(self) -> Path | None:
        layers = self.world.manifest.get("layers") or {}
        spec = layers.get("gl_fields") or {}
        name = spec.get("file") or FIELD_CACHE_NAME
        map_dir = self.world.map_dir
        if map_dir is None:
            return None
        return Path(map_dir) / name

    def _load_field_cache(self) -> bool:
        import numpy as np

        path = self._field_cache_path()
        if path is None or not path.is_file():
            return False
        key = _field_cache_key(
            self.world,
            self.veg,
            self.urban,
            self.road_params,
            self.pier_params,
            self._field_dtype,
        )
        try:
            data = np.load(path)
            saved = np.asarray(data["key"]).reshape(-1)
            saved_key = bytes(saved.astype(np.uint8)).decode("utf-8")
            if saved_key != key:
                return False
            if "land" not in data or "frame" not in data:
                return False
            if VEG_DETAIL_CROWNS and ("veg" not in data or "veg_mix" not in data):
                return False
            frame = tuple(float(v) for v in data["frame"])
            width, height = (int(data["width"]), int(data["height"]))
            size = (width, height)
            land = np.ascontiguousarray(data["land"])
            veg = mix = urban = None
            if VEG_DETAIL_CROWNS:
                veg = np.ascontiguousarray(data["veg"])
                mix = np.ascontiguousarray(data["veg_mix"])
            if "urban" in data:
                urban = np.ascontiguousarray(data["urban"])
            self._land_tex = self._upload_rg8(size, land.tobytes())
            self._land_frame = frame
            self._veg_frame = frame
            self._veg_tex_size = size
            if veg is not None and mix is not None:
                self._veg_tex = self._upload_rg8(size, veg.tobytes())
                self._veg_mix_tex = self._upload_rg8(size, mix.tobytes())
            if urban is not None:
                if urban.dtype == np.float16 and self._field_dtype != "f2":
                    urban = np.ascontiguousarray(urban.astype(np.float32))
                    dtype = "f4"
                elif urban.dtype == np.float32 and self._field_dtype == "f2":
                    urban = np.ascontiguousarray(urban.astype(np.float16))
                    dtype = "f2"
                else:
                    dtype = "f2" if urban.dtype == np.float16 else "f4"
                tex = self.ctx.texture(size, 1, data=urban.tobytes(), dtype=dtype)
                tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
                tex.repeat_x = False
                tex.repeat_y = False
                self._urban_tex = tex
            print(
                f"GL fields cache hit {width}x{height}  crowns {VEG_DETAIL_CROWNS}",
                flush=True,
            )
            return True
        except Exception as exc:
            print(f"GL fields cache miss ({exc})", flush=True)
            return False

    def _save_field_cache(self) -> None:
        import numpy as np

        if self._land_tex is None:
            return
        path = self._field_cache_path()
        if path is None:
            return
        key = _field_cache_key(
            self.world,
            self.veg,
            self.urban,
            self.road_params,
            self.pier_params,
            self._field_dtype,
        )
        width, height = self._veg_tex_size
        payload = {
            "key": np.frombuffer(key.encode("utf-8"), dtype=np.uint8).copy(),
            "frame": np.asarray(self._land_frame, dtype=np.float64),
            "width": np.int32(width),
            "height": np.int32(height),
            "land": self._read_rg8(self._land_tex),
        }
        if VEG_DETAIL_CROWNS and self._veg_tex is not None and self._veg_mix_tex is not None:
            payload["veg"] = self._read_rg8(self._veg_tex)
            payload["veg_mix"] = self._read_rg8(self._veg_mix_tex)
        if self._urban_tex is not None:
            payload["urban"] = self._read_urban_array(self._urban_tex)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **payload)
        print(f"GL fields cache wrote {path.name}", flush=True)

    def _bake_road_field(self) -> None:
        frame = self._land_frame
        size = self._veg_tex_size
        rp = self.road_params
        sigma = max(rp.sigma_m, 1.0)
        half = sigma * max(rp.splat_sigmas, 1.0)
        ref = max(rp.width_ref_m, 1.0)
        data = array("f")
        n_pts = 0
        minx, miny, maxx, maxy = frame
        for feat in self.world.roads:
            width = max(float(feat.width_m), MIN_ROAD_WIDTH_M)
            peak = float(rp.peak) * (width / ref)
            if peak <= 0.0:
                continue
            for px, py in _dots_on_polyline(feat.points, rp.step_m):
                if (
                    px < minx - half
                    or px > maxx + half
                    or py < miny - half
                    or py > maxy + half
                ):
                    continue
                x0 = px - half
                y0 = py - half
                x1 = px + half
                y1 = py + half
                data.extend(
                    (
                        x0, y0, px, py, peak,
                        x1, y0, px, py, peak,
                        x1, y1, px, py, peak,
                        x0, y0, px, py, peak,
                        x1, y1, px, py, peak,
                        x0, y1, px, py, peak,
                    )
                )
                n_pts += 1
        tex = self._make_float_tex(size)
        fbo, prev = self._begin_additive_splat(tex, size)
        if n_pts > 0 and len(data) >= 15:
            _set_uniform(self.prog_road_splat, "u_view", frame)
            _set_uniform(self.prog_road_splat, "u_urban_sigma", sigma)
            _set_uniform(self.prog_road_splat, "u_urban_kernel", int(rp.kernel))
            vbo = self.ctx.buffer(data.tobytes())
            vao = self.ctx.vertex_array(
                self.prog_road_splat,
                [(vbo, "2f 2f 1f", "in_pos", "in_center", "in_peak")],
            )
            vao.render(mode=self.mgl.TRIANGLES, vertices=len(data) // 5)
            vao.release()
            vbo.release()
        self._end_additive_splat(fbo, prev)
        import numpy as np

        np_dtype = np.float16 if self._field_dtype == "f2" else np.float32
        values = np.frombuffer(tex.read(), dtype=np_dtype)
        expected = size[0] * size[1]
        buf = None
        if values.size != expected:
            print(
                f"GL road field: read {values.size} floats, expected {expected}",
                flush=True,
            )
        else:
            buf = array("f")
            buf.frombytes(np.ascontiguousarray(values.astype(np.float32)).tobytes())
        if self._road_tex is not None:
            self._road_tex.release()
        self._road_tex = tex
        self._road_buf = buf
        print(
            f"GL road field: {n_pts} samples  sigma {sigma:.0f} m  "
            f"kernel {rp.kernel}",
            flush=True,
        )

    def _pier_field_path(self) -> Path | None:
        layers = self.world.manifest.get("layers") or {}
        spec = layers.get("piers") or {}
        name = spec.get("file") or PIER_FIELD_NAME
        map_dir = self.world.map_dir
        if map_dir is None:
            return None
        path = Path(map_dir) / name
        return path if path.is_file() else None

    def _load_pier_field(self) -> None:
        if self._pier_tex is not None:
            self._pier_tex.release()
            self._pier_tex = None
        self._pier_n = 0
        path = self._pier_field_path()
        if path is None:
            print(
                "GL piers: no piers_field.npz — run python -m fall_of_penghu.pier_prep",
                flush=True,
            )
            return
        import numpy as np

        try:
            data = np.load(path)
            mask = np.ascontiguousarray(data["mask"])
            stamp = float(
                data["stamp_value"] if "stamp_value" in data else self.pier_params.stamp_value
            )
            n_rings = int(data["n_rings"]) if "n_rings" in data else 0
        except Exception as exc:
            print(f"GL piers: failed to load {path.name}: {exc}", flush=True)
            return
        field = np.ascontiguousarray(mask.astype(np.float32) * stamp)
        if self._field_dtype == "f2":
            field = np.ascontiguousarray(field.astype(np.float16))
        height, width = field.shape
        tex = self._make_float_tex((width, height))
        tex.write(field.tobytes())
        self._pier_tex = tex
        self._pier_n = n_rings
        print(
            f"GL piers: loaded {path.name}  {width}x{height}  rings {n_rings}",
            flush=True,
        )

    def _blit_pier_field(self) -> None:
        if self._pier_tex is None:
            return
        self._pier_tex.use(0)
        _set_uniform(self.prog_field_add, "u_src", 0)
        self._field_add_vao.render(mode=self.mgl.TRIANGLES, vertices=3)

    def _bake_urban_field(self) -> None:
        frame = self._land_frame
        size = self._veg_tex_size
        sigma = max(self.urban.sigma_m, 1.0)
        half = sigma * max(self.urban.splat_sigmas, 1.0)
        data = array("f")
        n_b = 0
        minx, miny, maxx, maxy = frame
        ref = max(self.urban.size_ref_m, 1.0)
        base_peak = float(self.urban.peak)
        influence = float(self.road_params.influence)
        road_buf = self._road_buf
        for feat in self.world.buildings:
            cx = 0.5 * (feat.bbox[0] + feat.bbox[2])
            cy = 0.5 * (feat.bbox[1] + feat.bbox[3])
            if cx < minx - half or cx > maxx + half or cy < miny - half or cy > maxy + half:
                continue
            bw = max(feat.bbox[2] - feat.bbox[0], 1.0)
            bh = max(feat.bbox[3] - feat.bbox[1], 1.0)
            house_size = 0.5 * (bw * bw + bh * bh)
            house_peak = base_peak * (house_size / ref)
            if influence != 0.0 and road_buf:
                road = _field_sample(road_buf, size, frame, cx, cy)
                density = max(road, 0.0) * max(self.road_params.gain, 0.0)
                house_peak *= 1.0 + influence * density
            if (
                feat.bbox[2] < minx - half
                or feat.bbox[0] > maxx + half
                or feat.bbox[3] < miny - half
                or feat.bbox[1] > maxy + half
            ):
                continue
            if _house_miter_splat(feat.exterior, half, house_peak, data):
                n_b += 1
        has_piers = self._pier_tex is not None
        if (n_b <= 0 or len(data) < 12) and not has_piers:
            if self._urban_tex is not None:
                self._urban_tex.release()
            self._urban_tex = None
            print("GL urban field: no buildings", flush=True)
            return
        tex = self._make_float_tex(size)
        fbo, prev = self._begin_additive_splat(tex, size)
        _set_uniform(self.prog_urban_splat, "u_view", frame)
        _set_uniform(self.prog_urban_splat, "u_urban_sigma", sigma)
        _set_uniform(self.prog_urban_splat, "u_urban_extent", half)
        _set_uniform(self.prog_urban_splat, "u_urban_kernel", int(self.urban.kernel))
        if n_b > 0 and len(data) >= 12:
            vbo = self.ctx.buffer(data.tobytes())
            vao = self.ctx.vertex_array(
                self.prog_urban_splat, [(vbo, "2f 1f 1f", "in_pos", "in_t", "in_peak")]
            )
            vao.render(mode=self.mgl.TRIANGLES, vertices=len(data) // 4)
            vao.release()
            vbo.release()
        self._blit_pier_field()
        self._end_additive_splat(fbo, prev)
        if self._pier_tex is not None:
            self._pier_tex.release()
            self._pier_tex = None
        if self._urban_tex is not None:
            self._urban_tex.release()
        self._urban_tex = tex
        print(
            f"GL urban field: {n_b} buildings  sigma {sigma:.0f} m  "
            f"roadInf {influence:.4f}  piers {self._pier_n}",
            flush=True,
        )

    def _bind_veg(
        self,
        prog,
        kind: int,
        view: tuple[float, float, float, float],
        view_w: float,
        pal: dict[str, tuple[int, int, int]],
    ) -> None:
        if self._veg_tex is not None:
            self._veg_tex.use(1)
        if self._veg_mix_tex is not None:
            self._veg_mix_tex.use(2)
        fill = pal["forest"] if kind == 1 else pal["grass"]
        soil = pal["grass"]
        canopy = pal["forest"]
        _set_uniform(prog, "u_vegf", 1)
        _set_uniform(prog, "u_veg_mix", 2)
        _set_uniform(prog, "u_view", view)
        _set_uniform(prog, "u_veg_frame", self._veg_frame)
        _set_uniform(prog, "u_view_width", view_w)
        _set_uniform(prog, "u_kind", kind)
        _set_uniform(prog, "u_radar", 1 if self.radar else 0)
        _set_uniform(prog, "u_debug", 0)
        _set_uniform(prog, "u_fill", (fill[0] / 255.0, fill[1] / 255.0, fill[2] / 255.0))
        _set_uniform(prog, "u_soil", (soil[0] / 255.0, soil[1] / 255.0, soil[2] / 255.0))
        _set_uniform(prog, "u_canopy", (canopy[0] / 255.0, canopy[1] / 255.0, canopy[2] / 255.0))
        if kind == 1:
            _set_uniform(prog, "u_tree_spacing", self.veg.forest_spacing_m)
            _set_uniform(prog, "u_tree_freq", self.veg.forest_freq)
        else:
            _set_uniform(prog, "u_tree_spacing", self.veg.grass_spacing_m)
            _set_uniform(prog, "u_tree_freq", self.veg.grass_freq)
        self.veg.bind(_set_uniform, prog)

    def _draw_veg(
        self,
        name: str,
        kind: int,
        view: tuple[float, float, float, float],
        view_w: float,
        pal: dict[str, tuple[int, int, int]],
    ) -> int:
        mesh = self.layers.get(name)
        if mesh is None:
            return 0
        if not VEG_DETAIL_CROWNS:
            color = pal["forest"] if kind == 1 else pal["grass"]
            return self._draw_mesh(name, color)
        self.ctx.disable(self.mgl.BLEND)
        prog = self.prog_veg if kind == 1 else self.prog_veg_grass
        self._bind_veg(prog, kind, view, view_w, pal)
        mesh.vao.render(mode=self.mgl.TRIANGLES, vertices=mesh.nverts)
        return mesh.features

    def _draw_shore(
        self, view: tuple[float, float, float, float], view_w: float
    ) -> None:
        if self.radar or self._shore_vao is None:
            return
        self.ctx.enable(self.mgl.BLEND)
        _set_uniform(self.prog_shore, "u_view", view)
        _set_uniform(self.prog_shore, "u_time", perf_counter() - self._t0)
        _set_uniform(self.prog_shore, "u_view_width", view_w)
        self.water.bind(_set_uniform, self.prog_shore)
        self._shore_vao.render(mode=self.mgl.TRIANGLES, vertices=self._shore_nverts)
        self.ctx.disable(self.mgl.BLEND)

    def _draw_sea(
        self,
        view: tuple[float, float, float, float],
        pal: dict[str, tuple[int, int, int]],
    ) -> None:
        if self.radar or self._sea_tex is None:
            r, g, b = pal["sea"]
            self.ctx.clear(r / 255.0, g / 255.0, b / 255.0, 1.0)
            return
        self._sea_tex.use(0)
        _set_uniform(self.prog_sea, "u_dist", 0)
        _set_uniform(self.prog_sea, "u_view", view)
        _set_uniform(self.prog_sea, "u_frame", self._sea_frame)
        _set_uniform(self.prog_sea, "u_max_dist", SEA_MAX_DIST_M)
        _set_uniform(self.prog_sea, "u_tex_size", float(SEA_TEX_SIZE))
        self.water.bind(_set_uniform, self.prog_sea)
        self._sea_vao.render(mode=self.mgl.TRIANGLES, vertices=3)

    def _draw_mesh(
        self, name: str, color: tuple[int, int, int], opacity: float = 1.0
    ) -> int:
        mesh = self.layers.get(name)
        if mesh is None or opacity <= 0.01:
            return 0
        if opacity < 0.999:
            self.ctx.enable(self.mgl.BLEND)
        else:
            self.ctx.disable(self.mgl.BLEND)
        r, g, b = color
        _set_uniform(self.prog_map, "u_color", (r / 255.0, g / 255.0, b / 255.0))
        _set_uniform(self.prog_map, "u_opacity", opacity)
        mesh.vao.render(mode=self.mgl.TRIANGLES, vertices=mesh.nverts)
        return mesh.features

    def _release_fbos(self) -> None:
        for obj in (self._msaa_fbo, self._msaa_rb, self._fbo, self._fbo_tex):
            if obj is not None:
                obj.release()
        self._msaa_fbo = None
        self._msaa_rb = None
        self._fbo = None
        self._fbo_tex = None

    def _alloc_fbo(self, width: int, height: int, *, log: bool = False) -> None:
        width = max(1, width)
        height = max(1, height)
        self._release_fbos()
        self._fbo_tex = self.ctx.texture((width, height), 4)
        self._fbo_tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
        self._fbo_tex.repeat_x = False
        self._fbo_tex.repeat_y = False
        self._fbo = self.ctx.framebuffer(color_attachments=[self._fbo_tex])
        self._msaa_samples = 0
        wanted = min(MSAA_SAMPLES, int(getattr(self.ctx, "max_samples", 0) or 0))
        if wanted >= 2:
            try:
                self._msaa_rb = self.ctx.renderbuffer((width, height), 4, samples=wanted)
                self._msaa_fbo = self.ctx.framebuffer(color_attachments=[self._msaa_rb])
                self._msaa_samples = wanted
            except Exception:
                if self._msaa_fbo is not None:
                    self._msaa_fbo.release()
                if self._msaa_rb is not None:
                    self._msaa_rb.release()
                self._msaa_fbo = None
                self._msaa_rb = None
                self._msaa_samples = 0
        self._size = (width, height)
        if log:
            print(f"GL MSAA: {self._msaa_samples}x  FXAA light", flush=True)

    def resize(self, width: int, height: int, surface=None) -> None:
        del surface
        self._alloc_fbo(width, height)
        self.ctx.viewport = (0, 0, max(1, width), max(1, height))

    def draw(self, camera: Camera, screen_w: int, screen_h: int) -> dict[str, int]:
        if (screen_w, screen_h) != self._size:
            self._alloc_fbo(screen_w, screen_h)
        pal = self.palette()
        view = camera.world_bounds(screen_w, screen_h)
        view_w = camera.view_width_m
        stats = {
            "taiwan": 0,
            "coast": 0,
            "vegetation": 0,
            "buildings": 0,
            "roads": 0,
            "airports": 0,
        }
        target = self._msaa_fbo or self._fbo
        target.use()
        self.ctx.viewport = (0, 0, screen_w, screen_h)
        self.ctx.disable(self.mgl.BLEND)
        self._draw_sea(view, pal)
        _set_uniform(self.prog_map, "u_view", view)
        _set_uniform(self.prog_map, "u_tint", (1.0, 1.0, 1.0))
        _set_uniform(self.prog_map, "u_opacity", 1.0)

        stats["taiwan"] = self._draw_mesh("taiwan", pal["taiwan"])
        stats["coast"] = self._draw_land(view, pal)
        stats["vegetation"] += self._draw_veg("forest", 1, view, view_w, pal)
        stats["vegetation"] += self._draw_veg("grass", 0, view, view_w, pal)
        self._draw_shore(view, view_w)

        road_a = layer_opacity(view_w, ROADS_FADE_FULL_M, ROADS_FADE_GONE_M)
        stats["roads"] += self._draw_mesh("roads", pal["road"], road_a)
        stats["roads"] += self._draw_mesh("bridges", pal["bridge"], road_a)

        apt_a = layer_opacity(view_w, AIRPORTS_FADE_FULL_M, AIRPORTS_FADE_GONE_M)
        stats["airports"] += self._draw_mesh("airports", pal["airport"], apt_a)
        stats["airports"] += self._draw_mesh("airport_lines", pal["airport"], apt_a)

        bld_a = layer_opacity(view_w, BUILDINGS_FADE_FULL_M, BUILDINGS_FADE_GONE_M)
        stats["buildings"] = self._draw_mesh("buildings", pal["building"], bld_a)

        if self.radar:
            self._draw_mesh("coast_outline", pal["hud"])
        self.ctx.disable(self.mgl.BLEND)

        if self._msaa_fbo is not None:
            try:
                self.ctx.copy_framebuffer(self._fbo, self._msaa_fbo)
            except Exception:
                self._msaa_fbo = None
                self._msaa_samples = 0

        self.ctx.screen.use()
        self.ctx.viewport = (0, 0, screen_w, screen_h)
        self._fbo_tex.use(0)
        _set_uniform(self.prog_post, "u_map", 0)
        _set_uniform(self.prog_post, "u_resolution", (float(screen_w), float(screen_h)))
        _set_uniform(self.prog_post, "u_time", perf_counter() - self._t0)
        _set_uniform(self.prog_post, "u_radar", 1 if self.radar else 0)
        self._post_vao.render(mode=self.mgl.TRIANGLES, vertices=3)
        self.last_stats = stats
        return stats

    def overlay(self, surface, dest: tuple[int, int] = (0, 0)) -> None:
        import pygame

        width, height = surface.get_size()
        if width <= 0 or height <= 0:
            return
        raw = pygame.image.tobytes(surface, "RGBA", False)
        tex = self.ctx.texture((width, height), 4, raw)
        tex.filter = (self.mgl.NEAREST, self.mgl.NEAREST)
        x, y = dest
        verts = array(
            "f",
            (
                x,
                y,
                0.0,
                0.0,
                x + width,
                y,
                1.0,
                0.0,
                x + width,
                y + height,
                1.0,
                1.0,
                x,
                y,
                0.0,
                0.0,
                x + width,
                y + height,
                1.0,
                1.0,
                x,
                y + height,
                0.0,
                1.0,
            ),
        )
        self._overlay_vbo.write(verts.tobytes())
        self.ctx.enable(self.mgl.BLEND)
        tex.use(0)
        _set_uniform(self.prog_overlay, "u_image", 0)
        _set_uniform(self.prog_overlay, "u_screen", (float(self._size[0]), float(self._size[1])))
        self._overlay_vao.render(mode=self.mgl.TRIANGLES, vertices=6)
        self.ctx.disable(self.mgl.BLEND)
        tex.release()

    def present(self) -> None:
        import pygame

        pygame.display.flip()
