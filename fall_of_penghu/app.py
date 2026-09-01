from __future__ import annotations

import sys
from pathlib import Path

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.mapdata import load_map
from fall_of_penghu.render import create_game_display

ROOT = Path(__file__).resolve().parent.parent
MAP_DIR = ROOT / "penghu_map_v1"

PAN_PIXELS_PER_SEC = 680.0
ZOOM_IN = 1 / 1.12
ZOOM_OUT = 1.12


def _penghu_start(world) -> tuple[float, float, float]:
    bbox = world.manifest.get("bbox_penghu") or [-8000, -8000, 8000, 8000]
    cx = (bbox[0] + bbox[2]) * 0.5
    cy = (bbox[1] + bbox[3]) * 0.5
    return cx, cy, 28_000.0


def run() -> None:
    pygame.init()
    pygame.display.set_caption("Fall of Penghu")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 16)

    print("Loading map…", flush=True)
    world = load_map(MAP_DIR)
    print(
        f"Loaded coast={len(world.coast)} veg={len(world.vegetation)} "
        f"buildings={len(world.buildings)} roads={len(world.roads)}",
        flush=True,
    )

    display = create_game_display(world, (1280, 720))
    renderer = display.renderer
    cx, cy, view_w = _penghu_start(world)
    camera = Camera(center_x=cx, center_y=cy, view_width_m=view_w)
    frame_min = world.manifest.get("frame_min_xy") or [-100000.0, -100000.0]
    frame_max = world.manifest.get("frame_max_xy") or [100000.0, 100000.0]
    camera.set_frame(frame_min[0], frame_min[1], frame_max[0], frame_max[1])

    dragging = False
    running = True
    while running:
        dt = clock.tick(6000) / 1000.0
        screen_w, screen_h = pygame.display.get_window_size()
        mouse = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                display.resize(event.w, event.h)
                screen_w, screen_h = pygame.display.get_window_size()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_r:
                    renderer.radar = not renderer.radar
                elif event.key == pygame.K_HOME:
                    camera.move_to(cx, cy, view_w)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 2:
                    dragging = True
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 2:
                    dragging = False
            elif event.type == pygame.MOUSEMOTION:
                if dragging:
                    camera.pan_pixels(event.rel[0], event.rel[1], screen_w)
            elif event.type == pygame.MOUSEWHEEL:
                factor = ZOOM_IN if event.y > 0 else ZOOM_OUT
                camera.zoom_at_screen(factor, *mouse, screen_w, screen_h)

        keys = pygame.key.get_pressed()
        move = PAN_PIXELS_PER_SEC * dt * camera.meters_per_pixel(screen_w)
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            camera.pan_world(0.0, move)
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            camera.pan_world(0.0, -move)
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            camera.pan_world(-move, 0.0)
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            camera.pan_world(move, 0.0)

        camera.follow(dt, screen_w, screen_h)

        stats = renderer.draw(camera, screen_w, screen_h)
        wx, wy = camera.screen_to_world(*mouse, screen_w, screen_h)
        pal = renderer.palette()
        hud = (
            f"{clock.get_fps():5.1f} fps   "
            f"{display.gpu.backend}   "
            f"view {camera.view_width_m/1000:6.2f} km   "
            f"{camera.meters_per_pixel(screen_w):7.2f} m/px   "
            f"cam {camera.x:.0f},{camera.y:.0f}   "
            f"cursor {wx:.0f},{wy:.0f} m   "
            f"{'RADAR' if renderer.radar else 'MAP'}   "
            f"draw c{stats['coast']} v{stats['vegetation']} "
            f"b{stats['buildings']} r{stats['roads']}"
        )
        text = font.render(hud, True, pal["hud"])
        hint = font.render(
            "WASD pan  MMB drag  wheel zoom  R radar  Home reset  Esc quit",
            True,
            pal["hud"],
        )
        renderer.overlay(text, (10, 8))
        renderer.overlay(hint, (10, 28))
        renderer.present()

    pygame.quit()


if __name__ == "__main__":
    run()
    sys.exit(0)
