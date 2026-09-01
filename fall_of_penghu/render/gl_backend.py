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
from fall_of_penghu.render.veg import VegParams
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
        self.debug_veg = False
        self.last_stats: dict[str, int] = {}
        self._size = (max(1, size[0]), max(1, size[1]))
        self._t0 = perf_counter()
        self._post_frag_override: str | None = None
        self._cpu_meshes: dict[int, array] = {}
        self.layers: dict[str, StaticMesh] = {}
        self.water = WaterParams()
        self.veg = VegParams()
        self.prog_map = ctx.program(
            vertex_shader=_shader("map.vert"),
            fragment_shader=_shader("map.frag"),
        )
        self.prog_post = ctx.program(
            vertex_shader=_shader("post.vert"),
            fragment_shader=_shader("post.frag"),
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
        self._veg_union_sdf_vao = None
        self._veg_union_sdf_nverts = 0
        self._forest_sdf_vao = None
        self._forest_sdf_nverts = 0
        self._grass_sdf_vao = None
        self._grass_sdf_nverts = 0
        self._upload_veg_bands()
        self._bake_veg_sdf()
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

        specs = {
            "taiwan": (taiwan, n_taiwan, self.prog_map),
            "coast": (coast, n_coast, self.prog_map),
            "forest": (forest, n_forest, self.prog_veg),
            "grass": (grass, n_grass, self.prog_veg_grass),
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
        max_dim = 8192
        try:
            info = self.ctx.info or {}
            hw = int(info.get("GL_MAX_TEXTURE_SIZE") or max_dim)
            max_dim = max(256, min(max_dim, hw))
        except Exception:
            pass
        size = _sdf_tex_size(frame, max_dim)
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

    def _bind_veg(
        self,
        prog,
        kind: int,
        view: tuple[float, float, float, float],
        view_w: float,
        pal: dict[str, tuple[int, int, int]],
    ) -> None:
        if self._sea_tex is not None:
            self._sea_tex.use(0)
        if self._veg_tex is not None:
            self._veg_tex.use(1)
        if self._veg_mix_tex is not None:
            self._veg_mix_tex.use(2)
        fill = pal["forest"] if kind == 1 else pal["grass"]
        soil = pal["grass"]
        canopy = pal["forest"]
        land = pal["land"]
        _set_uniform(prog, "u_sea", 0)
        _set_uniform(prog, "u_vegf", 1)
        _set_uniform(prog, "u_veg_mix", 2)
        _set_uniform(prog, "u_view", view)
        _set_uniform(prog, "u_sea_frame", self._sea_frame)
        _set_uniform(prog, "u_sea_max", SEA_MAX_DIST_M)
        _set_uniform(prog, "u_sea_tex", float(SEA_TEX_SIZE))
        _set_uniform(prog, "u_veg_frame", self._veg_frame)
        _set_uniform(prog, "u_veg_tex", (float(self._veg_tex_size[0]), float(self._veg_tex_size[1])))
        _set_uniform(prog, "u_veg_max", float(self.veg.band_width_m))
        _set_uniform(prog, "u_view_width", view_w)
        _set_uniform(prog, "u_kind", kind)
        _set_uniform(prog, "u_radar", 1 if self.radar else 0)
        _set_uniform(prog, "u_debug", 1 if self.debug_veg else 0)
        _set_uniform(prog, "u_fill", (fill[0] / 255.0, fill[1] / 255.0, fill[2] / 255.0))
        _set_uniform(prog, "u_soil", (soil[0] / 255.0, soil[1] / 255.0, soil[2] / 255.0))
        _set_uniform(prog, "u_canopy", (canopy[0] / 255.0, canopy[1] / 255.0, canopy[2] / 255.0))
        _set_uniform(prog, "u_land", (land[0] / 255.0, land[1] / 255.0, land[2] / 255.0))
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
        view_w: float,
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
        _set_uniform(self.prog_sea, "u_time", perf_counter() - self._t0)
        _set_uniform(self.prog_sea, "u_view_width", view_w)
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

    def set_post_shader(self, fragment_src: str | None) -> None:
        self._post_frag_override = fragment_src
        new_prog = self.ctx.program(
            vertex_shader=_shader("post.vert"),
            fragment_shader=fragment_src or _shader("post.frag"),
        )
        new_vao = self.ctx.vertex_array(new_prog, [(self._post_vbo, "2f", "in_pos")])
        old_prog = self.prog_post
        old_vao = self._post_vao
        self.prog_post = new_prog
        self._post_vao = new_vao
        old_vao.release()
        old_prog.release()

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
        self._draw_sea(view, view_w, pal)
        _set_uniform(self.prog_map, "u_view", view)
        _set_uniform(self.prog_map, "u_tint", (1.0, 1.0, 1.0))
        _set_uniform(self.prog_map, "u_opacity", 1.0)

        stats["taiwan"] = self._draw_mesh("taiwan", pal["taiwan"])
        stats["coast"] = self._draw_mesh("coast", pal["land"])
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
