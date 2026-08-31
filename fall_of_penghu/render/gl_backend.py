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


@dataclass
class StaticMesh:
    vao: object
    nverts: int
    features: int


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
        self._post_frag_override: str | None = None
        self._cpu_meshes: dict[int, array] = {}
        self.layers: dict[str, StaticMesh] = {}
        self.water = WaterParams()
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
        self._load_cpu_meshes()
        self._upload_static_layers()
        self._cpu_meshes.clear()
        self._sea_tex = None
        self._sea_frame = (-100_000.0, -100_000.0, 100_000.0, 100_000.0)
        self._upload_sea_field()
        self._shore_vao = None
        self._shore_nverts = 0
        self._upload_shore_band()
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
                    tris = triangulate(feat.exterior)
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

    def _upload(self, data: array, features: int) -> StaticMesh | None:
        if len(data) < 6 or features <= 0:
            return None
        vbo = self.ctx.buffer(data.tobytes())
        vao = self.ctx.vertex_array(self.prog_map, [(vbo, "2f", "in_pos")])
        return StaticMesh(vao=vao, nverts=len(data) // 2, features=features)

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
            "taiwan": (taiwan, n_taiwan),
            "coast": (coast, n_coast),
            "forest": (forest, n_forest),
            "grass": (grass, n_grass),
            "buildings": (buildings, n_buildings),
            "airports": (airports, n_airports),
            "roads": (roads, n_roads),
            "bridges": (bridges, n_bridges),
            "airport_lines": (airport_lines, n_apt_lines),
            "coast_outline": (coast_outline, n_outline),
        }
        verts = 0
        draws = 0
        for name, (data, features) in specs.items():
            mesh = self._upload(data, features)
            if mesh is not None:
                self.layers[name] = mesh
                verts += mesh.nverts
                draws += 1
        print(
            f"GL static VBO: {draws} layers, {verts} verts in {perf_counter() - t0:.3f}s",
            flush=True,
        )

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
        stats["vegetation"] += self._draw_mesh("forest", pal["forest"])
        stats["vegetation"] += self._draw_mesh("grass", pal["grass"])
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
