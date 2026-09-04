from __future__ import annotations

import sys
from pathlib import Path

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.input import Input
from fall_of_penghu.render import create_game_display
from fall_of_penghu.render.dynamic import DynamicRenderer
from fall_of_penghu.selection import Selection
from fall_of_penghu.ui import Hud
from fall_of_penghu.world import World

ROOT = Path(__file__).resolve().parent.parent
MAP_DIR = ROOT / "penghu_map_v1"


def _penghu_start(world: World) -> tuple[float, float, float]:
    bbox = world.map.manifest.get("bbox_penghu") or [-8000, -8000, 8000, 8000]
    cx = (bbox[0] + bbox[2]) * 0.5
    cy = (bbox[1] + bbox[3]) * 0.5
    return cx, cy, 28_000.0


def run() -> None:
    pygame.init()
    pygame.display.set_caption("Fall of Penghu")
    frame_clock = pygame.time.Clock()

    print("Loading map…", flush=True)
    world = World.load(MAP_DIR)
    print(
        f"Loaded coast={len(world.map.coast)} veg={len(world.map.vegetation)} "
        f"buildings={len(world.map.buildings)} roads={len(world.map.roads)} "
        f"objects={len(world.entities.items)}",
        flush=True,
    )

    display = create_game_display(world.map, (1280, 720))
    renderer = display.renderer
    cx, cy, view_w = _penghu_start(world)
    camera = Camera(center_x=cx, center_y=cy, view_width_m=view_w)
    frame_min = world.map.manifest.get("frame_min_xy") or [-100000.0, -100000.0]
    frame_max = world.map.manifest.get("frame_max_xy") or [100000.0, 100000.0]
    camera.set_frame(frame_min[0], frame_min[1], frame_max[0], frame_max[1])

    controls = Input(cx, cy, view_w)
    selection = Selection()
    hud = Hud()
    dynamic = DynamicRenderer()

    while not controls.quit:
        dt_wall = frame_clock.tick(6000) / 1000.0
        screen_w, screen_h = pygame.display.get_window_size()
        mouse = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if hud.handle_event(event, world.clock, camera):
                continue
            if event.type == pygame.MOUSEWHEEL and hud.hits_chrome(
                *pygame.mouse.get_pos()[:2], screen_h, camera.debug_mode
            ):
                continue
            if (
                event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
                and hud.hits_chrome(
                    *pygame.mouse.get_pos()[:2], screen_h, camera.debug_mode
                )
            ):
                continue
            controls.handle_event(
                event,
                camera,
                world.clock,
                world.entities,
                selection,
                screen_w,
                screen_h,
                mouse,
            )
        if controls.resize_to is not None:
            display.resize(*controls.resize_to)
            controls.resize_to = None
            screen_w, screen_h = pygame.display.get_window_size()

        controls.handle_held(camera, dt_wall, screen_w, screen_h)
        if not hud.hits_chrome(*mouse, screen_h, camera.debug_mode):
            selection.update_hover(
                world.entities, camera, screen_w, screen_h, *mouse
            )
        else:
            selection.hover_id = None

        world.clock.advance(dt_wall)
        world.entities.step(world.clock.dt_sim)
        camera.step_fly_to(dt_wall, screen_w, screen_h)

        tod = world.clock.time_of_day
        stats = renderer.draw(camera, screen_w, screen_h, tod)
        dynamic.draw(
            renderer, camera, world.entities, selection, screen_w, screen_h, tod
        )
        hover = (
            world.entities.get(selection.hover_id)
            if selection.hover_id
            else None
        )
        hud.blit(
            renderer,
            camera=camera,
            clock=world.clock,
            fps=frame_clock.get_fps(),
            backend=display.gpu.backend,
            stats=stats,
            mouse_world=camera.screen_to_world(*mouse, screen_w, screen_h),
            mouse_screen=mouse,
            hover=hover,
            selection_count=len(selection.selected),
            screen_w=screen_w,
            screen_h=screen_h,
        )
        renderer.present()

    pygame.quit()


if __name__ == "__main__":
    run()
    sys.exit(0)
