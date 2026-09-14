from __future__ import annotations

from pathlib import Path

import pygame

from fall_of_penghu.ai import ChinaDirector
from fall_of_penghu.camera import Camera
from fall_of_penghu.chat import ChatLog
from fall_of_penghu.debug_palette import DebugPalette
from fall_of_penghu.display_palette import DisplayPalette
from fall_of_penghu.engage_palette import EngagePalette
from fall_of_penghu.input import Input
from fall_of_penghu.profile import prof, scope
from fall_of_penghu.range_palette import RangePalette
from fall_of_penghu.render.display import GameDisplay
from fall_of_penghu.render.dynamic import DynamicRenderer
from fall_of_penghu.selection import Selection
from fall_of_penghu.shell.settings import Settings
from fall_of_penghu.shell.snapshot import apply_camera, apply_chat, apply_china, apply_world
from fall_of_penghu.ui import Hud
from fall_of_penghu.vision_palette import VisionPalette
from fall_of_penghu.world import FACTION_PLAYER, World
from fall_of_penghu.world.combat.health import wreck
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind

ROOT = Path(__file__).resolve().parents[2]
MAP_DIR = ROOT / "penghu_map_v1"


def _penghu_start(world: World) -> tuple[float, float, float]:
    bbox = world.map.manifest.get("bbox_penghu") or [-8000, -8000, 8000, 8000]
    cx = (bbox[0] + bbox[2]) * 0.5
    cy = (bbox[1] + bbox[3]) * 0.5
    return cx, cy, 28_000.0


class Match:
    """Live theater. Overlays are drawn by the host, not by the HUD."""

    def __init__(
        self,
        cfg: Settings,
        display: GameDisplay,
        snapshot: dict | None = None,
        world: World | None = None,
    ) -> None:
        if world is None:
            print("Loading map…", flush=True)
            world = World.load(MAP_DIR)
            if snapshot is not None:
                print("Restoring slot…", flush=True)
                apply_world(world, snapshot)
        self.world = world
        print(
            f"Loaded coast={len(world.map.coast)} veg={len(world.map.vegetation)} "
            f"buildings={len(world.map.buildings)} roads={len(world.map.roads)} "
            f"objects={len(world.entities.items)}",
            flush=True,
        )
        display.bind_map(
            world.map,
            simple_shaders=cfg.simple_shaders,
            antialias=cfg.antialias,
        )
        self.cfg = cfg
        self.display = display
        cx, cy, view_w = _penghu_start(world)
        self.camera = Camera(center_x=cx, center_y=cy, view_width_m=view_w)
        frame_min = world.map.manifest.get("frame_min_xy") or [-100000.0, -100000.0]
        frame_max = world.map.manifest.get("frame_max_xy") or [100000.0, 100000.0]
        self.camera.set_frame(frame_min[0], frame_min[1], frame_max[0], frame_max[1])
        if snapshot is not None:
            apply_camera(self.camera, snapshot.get("camera") or {})
            cx, cy, view_w = self.camera.x, self.camera.y, self.camera.view_width_m
        self.controls = Input(cx, cy, view_w)
        self.selection = Selection()
        self.hud = Hud()
        self.palette = DebugPalette()
        self.palette.refresh(world.catalog)
        self.engage = EngagePalette()
        self.vision = VisionPalette()
        self.ranges = RangePalette()
        self.units = DisplayPalette()
        self.units.refresh(world.catalog)
        self.dynamic = DynamicRenderer()
        self.chat = ChatLog()
        self.china = ChinaDirector(world, bootstrap=snapshot is None)
        if snapshot is not None:
            apply_china(self.china, snapshot.get("china") or {})
            apply_chat(self.chat, snapshot.get("chat") or [])
        else:
            self.china.step(world)
        world.perception.step(world)
        self.observing = world.defeat is not None
        self._stats = {
            "coast": 0,
            "vegetation": 0,
            "buildings": 0,
            "roads": 0,
        }

    @property
    def tod(self) -> float:
        return self.world.clock.time_of_day

    def close(self) -> None:
        self.display.release_map()
        self.world = None

    def hold(self) -> None:
        self.world.clock.set_speed(0.0)

    def release(self) -> None:
        self.world.clock.set_speed(self.world.clock._resume_speed)

    def handle_event(
        self,
        event: pygame.event.Event,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        *,
        blocked: bool,
    ) -> str | None:
        if event.type == pygame.QUIT:
            self.controls.quit = True
            return "quit"
        if event.type == pygame.VIDEORESIZE:
            self.display.resize(event.w, event.h)
            return None
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            prof.toggle()
            return None
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F1:
            return "help"
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "pause"
        if blocked:
            return None
        if prof.enabled and prof.panel.handle_event(event, screen_w, screen_h):
            return None
        camera = self.camera
        world = self.world
        if camera.debug_mode and self.palette.handle_event(event, screen_w, screen_h):
            if self.palette.kill_ground:
                self.palette.kill_ground = False
                n = _wreck_player_ground(world)
                print(f"debug: wrecked {n} player ground unit(s)", flush=True)
            return None
        if self.vision.handle_event(event, screen_w, screen_h):
            return None
        if self.ranges.handle_event(event, screen_w, screen_h):
            return None
        if self.units.handle_event(event, screen_w, screen_h):
            return None
        if event.type == pygame.KEYDOWN and event.key == pygame.K_g:
            self.ranges.toggle()
            return None
        if self.engage.handle_event(
            event,
            self.selection,
            world.entities,
            world.catalog,
            screen_w,
            screen_h,
        ):
            return None
        hud = self.hud.handle_event(
            event,
            world.clock,
            camera,
            chat=self.chat,
            selection=self.selection,
            entities=world.entities,
            screen_w=screen_w,
            screen_h=screen_h,
            clock_12h=self.cfg.clock_12h,
        )
        if hud == "pause":
            return "pause"
        if hud == "help":
            return "help"
        if hud:
            return None
        if event.type == pygame.MOUSEWHEEL and self._chrome(screen_w, screen_h, *mouse):
            return None
        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self._chrome(screen_w, screen_h, *mouse)
        ):
            return None
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F12:
            camera.debug_mode = not camera.debug_mode
            if camera.debug_mode:
                self.palette.refresh(world.catalog)
            else:
                self.palette.kind = None
                world.clock.cap_to_player_speeds()
            return None
        self.controls.handle_event(
            event,
            camera,
            world.clock,
            world.entities,
            self.selection,
            screen_w,
            screen_h,
            mouse,
            place_kind=self.palette.kind if camera.debug_mode else None,
            place_faction=self.palette.faction if camera.debug_mode else None,
        )
        if self.controls.quit:
            return "quit"
        return None

    def step(
        self,
        dt_wall: float,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        *,
        blocked: bool = False,
    ) -> None:
        self.selection.visible_kinds = self.units.enabled
        if self.controls.resize_to is not None:
            self.display.resize(*self.controls.resize_to)
            self.controls.resize_to = None
        if blocked:
            self.world.clock.advance(dt_wall)
            return
        with scope("hover"):
            self.controls.handle_held(self.camera, dt_wall, screen_w, screen_h)
            if not self._chrome(screen_w, screen_h, *mouse):
                self.selection.update_hover(
                    self.world.entities, self.camera, screen_w, screen_h, *mouse
                )
            else:
                self.selection.hover_id = None
        world = self.world
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
                self.china.step(world)
            with scope("perception"):
                world.perception.step(world)
            with scope("combat"):
                world.combat.step(world)
            for notice in world.drain_notices():
                if notice.faction != FACTION_PLAYER:
                    continue
                if notice.slow_time:
                    world.clock.set_speed(1.0)
                self.chat.push(notice)
        with scope("camera"):
            self.camera.step_fly_to(dt_wall, screen_w, screen_h)

    def draw(self, fps: float, screen_w: int, screen_h: int, mouse: tuple[int, int]) -> None:
        renderer = self.display.renderer
        camera = self.camera
        world = self.world
        tod = world.clock.time_of_day
        with scope("map"):
            self._stats = renderer.draw(camera, screen_w, screen_h, tod)
        mouse_world = camera.screen_to_world(*mouse, screen_w, screen_h)
        with scope("dynamic"):
            self.dynamic.draw(
                renderer,
                camera,
                world.entities,
                self.selection,
                screen_w,
                screen_h,
                tod,
                perception=world.perception,
                now_sim=world.clock.simulation_time,
                vision_on=self.vision.enabled,
                range_on=self.ranges.enabled,
                show_kinds=self.units.enabled,
                mouse_world=mouse_world,
                heatmaps=self.china.intel.heat if camera.debug_mode else None,
            )
        hover = (
            world.entities.get(self.selection.hover_id)
            if self.selection.hover_id
            else None
        )
        heat_probe = None
        if camera.debug_mode:
            heat_probe = self.china.intel.sample(*mouse_world)
        with scope("hud"):
            self.hud.blit(
                renderer,
                camera=camera,
                clock=world.clock,
                fps=fps,
                backend=self.display.gpu.backend,
                stats=self._stats,
                mouse_world=mouse_world,
                mouse_screen=mouse,
                hover=hover,
                selection=self.selection,
                entities=world.entities,
                selection_count=len(self.selection.selected),
                screen_w=screen_w,
                screen_h=screen_h,
                perception=world.perception,
                chat=self.chat,
                palette=self.palette,
                engage=self.engage,
                vision=self.vision,
                ranges=self.ranges,
                display=self.units,
                heat_probe=heat_probe,
                defeated=world.defeat is not None and self.observing,
                clock_12h=self.cfg.clock_12h,
            )
        if prof.enabled:
            prof.panel.blit(renderer, screen_w, screen_h)

    def present(self) -> None:
        self.display.renderer.present()

    def overlay(self, surface: pygame.Surface, dest: tuple[int, int] = (0, 0)) -> None:
        self.display.renderer.overlay(surface, dest)

    def _chrome(self, screen_w: int, screen_h: int, x: int, y: int) -> bool:
        return self.hud.hits_chrome(
            x,
            y,
            screen_w,
            screen_h,
            self.camera.debug_mode,
            self.chat,
            self.palette,
            self.engage,
            self.vision,
            self.ranges,
            self.units,
            self.selection,
            self.world.entities,
            self.camera,
        )


def _wreck_player_ground(world: World) -> int:
    n = 0
    for obj in list(world.entities.items):
        if not isinstance(obj, DynamicObject) or not obj.active:
            continue
        if obj.faction != FACTION_PLAYER or obj.mobility != "land":
            continue
        if obj.kind in SHOT_KINDS or is_static_kind(obj.kind):
            continue
        wreck(obj, world)
        n += 1
    return n
