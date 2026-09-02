from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.mapdata import MapData
from fall_of_penghu.render.gpu import GpuInfo, assess_gl, software_info
from fall_of_penghu.render.scene import NORMAL, RADAR, palette_for
from fall_of_penghu.render.dynamic import DynamicRenderer
from fall_of_penghu.render.software import SoftwareMapRenderer

__all__ = [
    "NORMAL",
    "RADAR",
    "DynamicRenderer",
    "GameDisplay",
    "GpuInfo",
    "MapRenderer",
    "SoftwareMapRenderer",
    "create_game_display",
    "palette_for",
]

SOFT_WINDOW_FLAGS = pygame.RESIZABLE
GL_WINDOW_FLAGS = pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE


class MapRenderer(Protocol):
    radar: bool
    backend: str

    def palette(self) -> dict[str, tuple[int, int, int]]: ...

    def resize(self, width: int, height: int, surface: pygame.Surface | None = None) -> None: ...

    def draw(self, camera: Camera, screen_w: int, screen_h: int) -> dict[str, int]: ...

    def overlay(self, surface: pygame.Surface, dest: tuple[int, int] = (0, 0)) -> None: ...

    def present(self) -> None: ...


@dataclass
class GameDisplay:
    surface: pygame.Surface
    flags: int
    renderer: MapRenderer
    gpu: GpuInfo

    def resize(self, width: int, height: int) -> None:
        width = max(1, width)
        height = max(1, height)
        if self.flags & pygame.OPENGL:
            # Recreating the window would drop the GL context. pygame already resized it.
            self.renderer.resize(width, height, self.surface)
            return
        self.surface = pygame.display.set_mode((width, height), self.flags)
        self.renderer.resize(
            self.surface.get_width(), self.surface.get_height(), self.surface
        )


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


def _software_display(world: MapData, size: tuple[int, int], reason: str) -> GameDisplay:
    surface = pygame.display.set_mode(size, SOFT_WINDOW_FLAGS)
    renderer = SoftwareMapRenderer(world, surface)
    info = software_info(reason)
    print(f"Map renderer: {info.label}", flush=True)
    return GameDisplay(surface, SOFT_WINDOW_FLAGS, renderer, info)


def _try_gl(world: MapData, size: tuple[int, int]) -> GameDisplay | None:
    try:
        import moderngl
    except ImportError as exc:
        print(f"ModernGL missing ({exc}); using software renderer.", flush=True)
        return None
    last_exc: Exception | None = None
    for window_aa in (True, False):
        try:
            _set_gl_attributes(window_aa=window_aa)
            surface = pygame.display.set_mode(size, GL_WINDOW_FLAGS)
            ctx = moderngl.create_context(require=330)
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
            from fall_of_penghu.render.gl_backend import GLMapRenderer

            renderer = GLMapRenderer(world, ctx, size)
            print(f"Map renderer: {gpu.label}", flush=True)
            return GameDisplay(surface, GL_WINDOW_FLAGS, renderer, gpu)
        except Exception as exc:
            last_exc = exc
            try:
                _reset_display()
            except Exception:
                pass
    print(f"OpenGL init failed ({last_exc}); using software renderer.", flush=True)
    return None


def create_game_display(
    world: MapData,
    size: tuple[int, int] = (1280, 720),
    *,
    force: str | None = None,
) -> GameDisplay:
    """Open a window and pick GL or software from GPU capability / FOP_RENDERER."""
    choice = (force or os.environ.get("FOP_RENDERER") or "").strip().lower()
    if choice in ("software", "cpu", "2d"):
        return _software_display(world, size, "forced")
    created = _try_gl(world, size)
    if created is not None:
        return created
    reason = "forced GL failed" if choice in ("gl", "opengl", "gpu") else "OpenGL unavailable or GPU below bar"
    return _software_display(world, size, reason)
