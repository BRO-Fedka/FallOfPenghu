from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.mapdata import MapData
from fall_of_penghu.render.static.backends.gpu import GpuInfo, assess_gl, software_info
from fall_of_penghu.render.static.backends.software import SoftwareMapRenderer
from fall_of_penghu.shell.theme import PANEL

SOFT_WINDOW_FLAGS = pygame.RESIZABLE
GL_WINDOW_FLAGS = pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE


class MapRenderer(Protocol):
    radar: bool
    backend: str

    def palette(self) -> dict[str, tuple[int, int, int]]: ...

    def resize(self, width: int, height: int, surface: pygame.Surface | None = None) -> None: ...

    def draw(self, camera: Camera, screen_w: int, screen_h: int, tod: float = 0.5) -> dict[str, int]: ...

    def overlay(self, surface: pygame.Surface, dest: tuple[int, int] = (0, 0)) -> None: ...

    def overlay_sprites(
        self, strip: pygame.Surface, dests: list[tuple[int, int]], cell: int
    ) -> None: ...

    def overlay_lines(
        self,
        points: list[tuple[float, float]],
        color: tuple[int, int, int] | tuple[int, int, int, int],
        width: int = 2,
    ) -> None: ...

    def overlay_aalines(
        self,
        polylines: list[list[tuple[float, float]]],
        color: tuple[int, int, int] | tuple[int, int, int, int],
    ) -> None: ...

    def overlay_rings(
        self,
        rings: list[tuple[float, float, float]],
        color: tuple[int, int, int] | tuple[int, int, int, int],
        camera: Camera,
        screen_w: int,
        screen_h: int,
    ) -> None: ...

    def present(self) -> None: ...


class SoftwareShell:
    backend = "software"

    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface

    def begin(self) -> None:
        self.surface.fill(PANEL)

    def overlay(self, surface: pygame.Surface, dest: tuple[int, int] = (0, 0)) -> None:
        self.surface.blit(surface, dest)

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
        del name, revision, linear
        if alpha <= 0.01:
            return
        if alpha < 0.999:
            faded = surface.copy()
            faded.set_alpha(max(0, min(255, int(round(255.0 * alpha)))))
            surface = faded
        self.surface.blit(surface, (int(dest[0]), int(dest[1])))

    def present(self) -> None:
        pygame.display.flip()

    def resize(self, width: int, height: int, surface: pygame.Surface | None = None) -> None:
        del width, height
        if surface is not None:
            self.surface = surface


@dataclass
class GameDisplay:
    """One window for the process. Map GPU data is bound and released around a match."""

    surface: pygame.Surface
    flags: int
    gpu: GpuInfo
    ctx: object = None
    shell: object = None
    map_renderer: MapRenderer | None = None

    @property
    def renderer(self) -> object:
        return self.map_renderer if self.map_renderer is not None else self.shell

    def begin(self) -> None:
        self.shell.begin()

    def overlay(self, surface: pygame.Surface, dest: tuple[int, int] = (0, 0)) -> None:
        self.renderer.overlay(surface, dest)

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
        fn = getattr(self.renderer, "overlay_layer", None)
        if fn is not None:
            fn(
                name,
                surface,
                dest,
                revision=revision,
                alpha=alpha,
                linear=linear,
            )
            return
        if alpha <= 0.01:
            return
        if alpha < 0.999:
            faded = surface.copy()
            faded.set_alpha(max(0, min(255, int(round(255.0 * alpha)))))
            surface = faded
        self.overlay(surface, (int(dest[0]), int(dest[1])))

    def present(self) -> None:
        self.renderer.present()

    def bind_map(
        self,
        world: MapData,
        *,
        simple_shaders: bool = False,
        antialias: str = "msaa4",
    ) -> None:
        self.release_map()
        size = pygame.display.get_window_size()
        if self.ctx is not None:
            from fall_of_penghu.render.static.backends.gl_backend import GLMapRenderer

            self.map_renderer = GLMapRenderer(
                world,
                self.ctx,
                size,
                simple_shaders=simple_shaders,
                antialias=antialias,
            )
            print(f"Map renderer: {self.gpu.label}", flush=True)
            return
        self.map_renderer = SoftwareMapRenderer(world, self.surface)
        print(f"Map renderer: {self.gpu.label}", flush=True)

    def release_map(self) -> None:
        if self.map_renderer is None:
            return
        closer = getattr(self.map_renderer, "release", None)
        if closer is not None:
            closer()
        self.map_renderer = None
        if self.ctx is not None:
            try:
                self.ctx.gc()
            except Exception:
                pass

    def resize(self, width: int, height: int) -> None:
        width = max(1, width)
        height = max(1, height)
        if self.flags & pygame.OPENGL:
            self.shell.resize(width, height, self.surface)
            if self.map_renderer is not None:
                self.map_renderer.resize(width, height, self.surface)
            return
        self.surface = pygame.display.set_mode((width, height), self.flags)
        self.shell.resize(width, height, self.surface)
        if self.map_renderer is not None:
            self.map_renderer.resize(
                self.surface.get_width(), self.surface.get_height(), self.surface
            )

    def set_fullscreen(self, on: bool) -> None:
        is_full = bool(self.flags & pygame.FULLSCREEN)
        if on == is_full:
            return
        try:
            pygame.display.toggle_fullscreen()
        except pygame.error:
            return
        if on:
            self.flags |= pygame.FULLSCREEN
        else:
            self.flags &= ~pygame.FULLSCREEN
        w, h = pygame.display.get_window_size()
        self.resize(w, h)


def _set_gl_attributes(*, window_aa: bool) -> None:
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
    pygame.display.gl_set_attribute(
        pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE
    )
    pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
    pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 1 if window_aa else 0)
    pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLESAMPLES, 4 if window_aa else 0)


def _reset_display() -> None:
    pygame.display.quit()
    pygame.display.init()


def reset_video() -> None:
    _reset_display()


def _mode_flags(base: int, *, fullscreen: bool) -> int:
    return base | (pygame.FULLSCREEN if fullscreen else 0)


def _software_open(
    size: tuple[int, int], reason: str, *, fullscreen: bool
) -> GameDisplay:
    flags = _mode_flags(SOFT_WINDOW_FLAGS, fullscreen=fullscreen)
    surface = pygame.display.set_mode(size, flags)
    info = software_info(reason)
    print(f"Window: {info.label}", flush=True)
    return GameDisplay(
        surface=surface,
        flags=flags,
        gpu=info,
        shell=SoftwareShell(surface),
    )


def _try_gl_open(size: tuple[int, int], *, fullscreen: bool) -> GameDisplay | None:
    try:
        import moderngl
    except ImportError as exc:
        print(f"ModernGL missing ({exc}); using software renderer.", flush=True)
        return None
    last_exc: Exception | None = None
    for window_aa in (True, False):
        try:
            _set_gl_attributes(window_aa=window_aa)
            flags = _mode_flags(GL_WINDOW_FLAGS, fullscreen=fullscreen)
            surface = pygame.display.set_mode(size, flags)
            ctx = moderngl.create_context(require=330)
            if hasattr(ctx, "gc_mode"):
                ctx.gc_mode = "auto"
            info_dict = getattr(ctx, "info", {}) or {}
            version = str(info_dict.get("GL_VERSION") or "")
            renderer_name = str(info_dict.get("GL_RENDERER") or "")
            vendor = str(info_dict.get("GL_VENDOR") or "")
            try:
                max_tex = int(info_dict.get("GL_MAX_TEXTURE_SIZE") or 0)
            except (TypeError, ValueError):
                max_tex = 0
            gpu = assess_gl(
                version=version,
                renderer=renderer_name,
                vendor=vendor,
                max_texture=max_tex,
            )
            if not gpu.usable:
                print(f"OpenGL present but skipped: {gpu.reason}", flush=True)
                _reset_display()
                return None
            from fall_of_penghu.render.static.backends.gl_shell import GLShell

            print(f"Window: {gpu.label}", flush=True)
            return GameDisplay(
                surface=surface,
                flags=flags,
                gpu=gpu,
                ctx=ctx,
                shell=GLShell(ctx, size),
            )
        except Exception as exc:
            last_exc = exc
            try:
                _reset_display()
            except Exception:
                pass
    print(f"OpenGL init failed ({last_exc}); using software renderer.", flush=True)
    return None


def open_display(
    size: tuple[int, int] = (1280, 720),
    *,
    force: str | None = None,
    fullscreen: bool = False,
) -> GameDisplay:
    """Open the process window once. Map data is bound later."""
    choice = (force or os.environ.get("FOP_RENDERER") or "").strip().lower()
    if choice in ("software", "cpu", "2d"):
        return _software_open(size, "forced", fullscreen=fullscreen)
    created = _try_gl_open(size, fullscreen=fullscreen)
    if created is not None:
        return created
    reason = (
        "forced GL failed"
        if choice in ("gl", "opengl", "gpu")
        else "OpenGL unavailable or GPU below bar"
    )
    return _software_open(size, reason, fullscreen=fullscreen)


def create_game_display(
    world: MapData,
    size: tuple[int, int] = (1280, 720),
    *,
    force: str | None = None,
    fullscreen: bool = False,
) -> GameDisplay:
    """Tools: open a window and bind the map immediately."""
    display = open_display(size, force=force, fullscreen=fullscreen)
    display.bind_map(world)
    return display
