from __future__ import annotations

from array import array

import pygame

from fall_of_penghu.render.static.backends.gl_backend import _set_uniform, _shader
from fall_of_penghu.shell.theme import PANEL


class GLShell:
    """Clear + HUD overlay on an existing ModernGL context. No map data."""

    backend = "gl"

    def __init__(self, ctx, size: tuple[int, int]) -> None:
        import moderngl

        self.mgl = moderngl
        self.ctx = ctx
        self._size = (max(1, size[0]), max(1, size[1]))
        self.prog_overlay = ctx.program(
            vertex_shader=_shader("overlay.vert"),
            fragment_shader=_shader("overlay.frag"),
        )
        self._overlay_vbo = ctx.buffer(reserve=96, dynamic=True)
        self._overlay_vao = ctx.vertex_array(
            self.prog_overlay, [(self._overlay_vbo, "2f 2f", "in_pos", "in_uv")]
        )
        self._overlay_tex_cache: dict[tuple[int, int], object] = {}
        self._layer_tex: dict[str, list] = {}
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

    def begin(self) -> None:
        r, g, b = PANEL
        self.ctx.screen.use()
        self.ctx.viewport = (0, 0, self._size[0], self._size[1])
        self.ctx.clear(r / 255.0, g / 255.0, b / 255.0, 1.0)

    def overlay(self, surface: pygame.Surface, dest: tuple[int, int] = (0, 0)) -> None:
        width, height = surface.get_size()
        if width <= 0 or height <= 0:
            return
        raw = pygame.image.tobytes(surface, "RGBA", False)
        tex = self._overlay_texture(width, height, raw)
        self._draw_overlay(tex, dest, width, height, 1.0)

    def overlay_layer(
        self,
        name: str,
        surface: pygame.Surface,
        dest: tuple[float, float] = (0.0, 0.0),
        *,
        revision: int = 0,
        alpha: float = 1.0,
        linear: bool = False,
    ) -> None:
        if alpha <= 0.01:
            return
        width, height = surface.get_size()
        if width <= 0 or height <= 0:
            return
        slot = self._layer_tex.get(name)
        if slot is None or slot[1] != (width, height):
            if slot is not None:
                slot[0].release()
            tex = self.ctx.texture((width, height), 3)
            tex.repeat_x = False
            tex.repeat_y = False
            slot = [tex, (width, height), -1]
            self._layer_tex[name] = slot
        tex = slot[0]
        tex.filter = (
            (self.mgl.LINEAR, self.mgl.LINEAR)
            if linear
            else (self.mgl.NEAREST, self.mgl.NEAREST)
        )
        if slot[2] != revision:
            tex.write(pygame.image.tobytes(surface, "RGB", False))
            slot[2] = revision
        self._draw_overlay(tex, dest, width, height, alpha)

    def present(self) -> None:
        pygame.display.flip()

    def resize(self, width: int, height: int, surface=None) -> None:
        del surface
        self._size = (max(1, width), max(1, height))
        self.ctx.viewport = (0, 0, self._size[0], self._size[1])

    def _overlay_texture(self, width: int, height: int, raw: bytes):
        key = (width, height)
        tex = self._overlay_tex_cache.get(key)
        if tex is None:
            while len(self._overlay_tex_cache) >= 8:
                _, old = self._overlay_tex_cache.popitem()
                old.release()
            tex = self.ctx.texture((width, height), 4)
            tex.filter = (self.mgl.NEAREST, self.mgl.NEAREST)
            self._overlay_tex_cache[key] = tex
        tex.write(raw)
        return tex

    def _draw_overlay(
        self,
        tex,
        dest: tuple[float, float],
        width: int,
        height: int,
        alpha: float,
    ) -> None:
        x, y = dest
        verts = array(
            "f",
            (
                x, y, 0.0, 0.0,
                x + width, y, 1.0, 0.0,
                x + width, y + height, 1.0, 1.0,
                x, y, 0.0, 0.0,
                x + width, y + height, 1.0, 1.0,
                x, y + height, 0.0, 1.0,
            ),
        )
        nbytes = 6 * 16
        if nbytes > self._overlay_vbo.size:
            self._overlay_vbo.release()
            self._overlay_vbo = self.ctx.buffer(reserve=nbytes, dynamic=True)
            self._overlay_vao = self.ctx.vertex_array(
                self.prog_overlay, [(self._overlay_vbo, "2f 2f", "in_pos", "in_uv")]
            )
        self._overlay_vbo.write(verts.tobytes())
        self.ctx.enable(self.mgl.BLEND)
        tex.use(0)
        _set_uniform(self.prog_overlay, "u_image", 0)
        _set_uniform(self.prog_overlay, "u_alpha", float(max(0.0, min(1.0, alpha))))
        _set_uniform(
            self.prog_overlay,
            "u_screen",
            (float(self._size[0]), float(self._size[1])),
        )
        self._overlay_vao.render(mode=self.mgl.TRIANGLES, vertices=6)
        self.ctx.disable(self.mgl.BLEND)
