from __future__ import annotations

import sys
from pathlib import Path

import pygame

from fall_of_penghu.ai import ChinaDirector
from fall_of_penghu.camera import Camera
from fall_of_penghu.chat import ChatLog
from fall_of_penghu.input import Input
from fall_of_penghu.render import create_game_display
from fall_of_penghu.render.dynamic import DynamicRenderer
from fall_of_penghu.selection import Selection
from fall_of_penghu.debug_palette import DebugPalette
from fall_of_penghu.engage_palette import EngagePalette
from fall_of_penghu.range_palette import RangePalette
from fall_of_penghu.ui import Hud
from fall_of_penghu.vision_palette import VisionPalette
from fall_of_penghu.display_palette import DisplayPalette
from fall_of_penghu.profile import prof, scope
from fall_of_penghu.world import FACTION_PLAYER, World
from fall_of_penghu.world.events import ContactNotice

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
    palette = DebugPalette()
    palette.refresh(world.catalog)
    engage = EngagePalette()
    vision = VisionPalette()
    ranges = RangePalette()
    units = DisplayPalette()
    units.refresh(world.catalog)
    dynamic = DynamicRenderer()
    chat = ChatLog()
    china = ChinaDirector(world)
    china.step(world)
    world.perception.step(world)

    while not controls.quit:
        dt_wall = frame_clock.tick(600) / 1000.0
        screen_w, screen_h = pygame.display.get_window_size()
        mouse = pygame.mouse.get_pos()
        selection.visible_kinds = units.enabled
        prof.begin_frame()

        with scope("events"):
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    prof.toggle()
                    continue
                if prof.enabled and prof.panel.handle_event(event, screen_w, screen_h):
                    continue
                if camera.debug_mode and palette.handle_event(event, screen_w, screen_h):
                    continue
                if vision.handle_event(event, screen_w, screen_h):
                    continue
                if ranges.handle_event(event, screen_w, screen_h):
                    continue
                if units.handle_event(event, screen_w, screen_h):
                    continue
                if event.type == pygame.KEYDOWN and event.key == pygame.K_g:
                    ranges.toggle()
                    continue
                if engage.handle_event(
                    event,
                    selection,
                    world.entities,
                    world.catalog,
                    screen_w,
                    screen_h,
                ):
                    continue
                if hud.handle_event(
                    event,
                    world.clock,
                    camera,
                    chat=chat,
                    selection=selection,
                    entities=world.entities,
                    screen_w=screen_w,
                    screen_h=screen_h,
                ):
                    continue
                if event.type == pygame.MOUSEWHEEL and hud.hits_chrome(
                    *pygame.mouse.get_pos()[:2],
                    screen_w,
                    screen_h,
                    camera.debug_mode,
                    chat,
                    palette,
                    engage,
                    vision,
                    ranges,
                    units,
                    selection,
                    world.entities,
                    camera,
                ):
                    continue
                if (
                    event.type == pygame.MOUSEBUTTONDOWN
                    and event.button == 1
                    and hud.hits_chrome(
                        *pygame.mouse.get_pos()[:2],
                        screen_w,
                        screen_h,
                        camera.debug_mode,
                        chat,
                        palette,
                        engage,
                        vision,
                        ranges,
                        units,
                        selection,
                        world.entities,
                        camera,
                    )
                ):
                    continue
                if event.type == pygame.KEYDOWN and event.key == pygame.K_F12:
                    camera.debug_mode = not camera.debug_mode
                    if camera.debug_mode:
                        palette.refresh(world.catalog)
                    else:
                        palette.kind = None
                        world.clock.cap_to_player_speeds()
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
                    place_kind=palette.kind if camera.debug_mode else None,
                    place_faction=palette.faction if camera.debug_mode else None,
                )
        if controls.resize_to is not None:
            display.resize(*controls.resize_to)
            controls.resize_to = None
            screen_w, screen_h = pygame.display.get_window_size()

        with scope("hover"):
            controls.handle_held(camera, dt_wall, screen_w, screen_h)
            if not hud.hits_chrome(
                *mouse,
                screen_w,
                screen_h,
                camera.debug_mode,
                chat,
                palette,
                engage,
                vision,
                ranges,
                units,
                selection,
                world.entities,
                camera,
            ):
                selection.update_hover(
                    world.entities, camera, screen_w, screen_h, *mouse
                )
            else:
                selection.hover_id = None

        with scope("sim"):
            with scope("clock"):
                world.clock.advance(dt_wall)
            with scope("entities"):
                world.entities.step(world.clock.dt_sim)
            with scope("transport"):
                world.transport.step(world)
            with scope("control"):
                world.control.step(world)
            with scope("china"):
                china.step(world)
            with scope("perception"):
                world.perception.step(world)
            with scope("combat"):
                world.combat.step(world)
            for notice in world.drain_notices():
                if notice.faction != FACTION_PLAYER:
                    continue
                if notice.slow_time:
                    world.clock.set_speed(1.0)
                chat.push(notice)
        with scope("camera"):
            camera.step_fly_to(dt_wall, screen_w, screen_h)

        tod = world.clock.time_of_day
        with scope("map"):
            stats = renderer.draw(camera, screen_w, screen_h, tod)
        mouse_world = camera.screen_to_world(*mouse, screen_w, screen_h)
        with scope("dynamic"):
            dynamic.draw(
                renderer,
                camera,
                world.entities,
                selection,
                screen_w,
                screen_h,
                tod,
                perception=world.perception,
                now_sim=world.clock.simulation_time,
                vision_on=vision.enabled,
                range_on=ranges.enabled,
                show_kinds=units.enabled,
                mouse_world=mouse_world,
                heatmaps=china.intel.heat if camera.debug_mode else None,
            )
        hover = (
            world.entities.get(selection.hover_id)
            if selection.hover_id
            else None
        )
        heat_probe = None
        if camera.debug_mode:
            heat_probe = china.intel.sample(*mouse_world)
        with scope("hud"):
            hud.blit(
                renderer,
                camera=camera,
                clock=world.clock,
                fps=frame_clock.get_fps(),
                backend=display.gpu.backend,
                stats=stats,
                mouse_world=mouse_world,
                mouse_screen=mouse,
                hover=hover,
                selection=selection,
                entities=world.entities,
                selection_count=len(selection.selected),
                screen_w=screen_w,
                screen_h=screen_h,
                perception=world.perception,
                chat=chat,
                palette=palette,
                engage=engage,
                vision=vision,
                ranges=ranges,
                display=units,
                heat_probe=heat_probe,
            )
        prof.end_frame()
        if prof.enabled:
            prof.panel.blit(renderer, screen_w, screen_h)
        renderer.present()

    pygame.quit()


if __name__ == "__main__":
    run()
    sys.exit(0)
