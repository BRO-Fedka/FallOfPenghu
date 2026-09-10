from __future__ import annotations

import pygame

from fall_of_penghu.camera import KEYBOARD_TICK_S, Camera
from fall_of_penghu.selection import DRAG_PX, Selection, pick_at
from fall_of_penghu.world.clock import DEBUG_SPEED, SPEEDS, Clock
from fall_of_penghu.world.combat.doctrine import is_battery
from fall_of_penghu.world.entities import (
    DynamicObject,
    Entities,
    FACTION_PLAYER,
    SetAim,
    SetFocus,
    SetRoute,
)
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind

PAN_SPEED_PX = 5.0
ZOOM_DELTA_DIVISOR = 600.0
WHEEL_SCALE = 100.0
WHEEL_DEADZONE = 2.0
ZOOM_KEY_DELTA = 10.0
MAX_KEY_TICKS = 32.0

SPEED_KEYS = {
    pygame.K_F1: SPEEDS[0],
    pygame.K_F2: SPEEDS[1],
    pygame.K_F3: SPEEDS[2],
    pygame.K_F4: SPEEDS[3],
    pygame.K_F5: SPEEDS[4],
    pygame.K_F6: SPEEDS[5],
}

ZOOM_IN_KEYS = (pygame.K_e, pygame.K_EQUALS, pygame.K_KP_PLUS)
ZOOM_OUT_KEYS = (pygame.K_q, pygame.K_MINUS, pygame.K_KP_MINUS)


def _key_ticks(dt_wall: float) -> float:
    return min(max(dt_wall, 0.0) / KEYBOARD_TICK_S, MAX_KEY_TICKS)


def _zoom_factor(delta: float) -> float:
    return 1.0 + delta / ZOOM_DELTA_DIVISOR


class Input:
    """Map, clock, and entity commands. Does not draw."""

    def __init__(self, home_x: float, home_y: float, home_view_m: float) -> None:
        self.quit = False
        self.home_x = home_x
        self.home_y = home_y
        self.home_view_m = home_view_m
        self.resize_to: tuple[int, int] | None = None
        self._lmb_down = False
        self._press_xy: tuple[int, int] = (0, 0)
        self._press_obj_id: str | None = None
        self._panning = False
        self._box_select = False

    def handle_event(
        self,
        event: pygame.event.Event,
        camera: Camera,
        clock: Clock,
        entities: Entities,
        selection: Selection,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        place_kind: str | None = None,
        place_faction: str | None = None,
    ) -> None:
        if event.type == pygame.QUIT:
            self.quit = True
        elif event.type == pygame.VIDEORESIZE:
            self.resize_to = (event.w, event.h)
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.quit = True
            elif event.key == pygame.K_r:
                camera.radar_mode = not camera.radar_mode
            elif event.key == pygame.K_g:
                camera.show_engagement = not camera.show_engagement
            elif event.key == pygame.K_SPACE:
                clock.toggle_pause()
            elif event.key in SPEED_KEYS:
                clock.set_speed(SPEED_KEYS[event.key])
            elif event.key == pygame.K_F7:
                if camera.debug_mode:
                    clock.set_speed(DEBUG_SPEED)
            elif event.key == pygame.K_F12:
                camera.debug_mode = not camera.debug_mode
                if not camera.debug_mode:
                    clock.cap_to_player_speeds()
            elif event.key in (pygame.K_HOME, pygame.K_c):
                camera.fly_to(self.home_x, self.home_y, self.home_view_m)
            elif (
                camera.debug_mode
                and event.key in (pygame.K_DELETE, pygame.K_KP_PERIOD)
                and bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            ):
                removed = entities.forget_objects(selection.selected)
                for oid in removed:
                    selection.selected.discard(oid)
                    if selection.hover_id == oid:
                        selection.hover_id = None
                if removed:
                    print(
                        f"debug: removed {len(removed)} object(s) from sites.json",
                        flush=True,
                    )
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                self._on_lmb_down(
                    event,
                    camera,
                    entities,
                    selection,
                    screen_w,
                    screen_h,
                    place_kind,
                    place_faction,
                )
            elif event.button == 3:
                self._on_rmb(event, camera, entities, selection, screen_w, screen_h)
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self._on_lmb_up(
                    event,
                    camera,
                    entities,
                    selection,
                    screen_w,
                    screen_h,
                    place_kind,
                    place_faction,
                )
        elif event.type == pygame.MOUSEMOTION:
            if self._lmb_down:
                self._on_lmb_drag(event, camera, selection, screen_w, screen_h)
        elif event.type == pygame.MOUSEWHEEL:
            delta = -event.y * WHEEL_SCALE
            if abs(delta) < WHEEL_DEADZONE:
                return
            camera.zoom_at_screen(
                _zoom_factor(delta), *mouse, screen_w, screen_h
            )

    def _on_lmb_down(
        self,
        event: pygame.event.Event,
        camera: Camera,
        entities: Entities,
        selection: Selection,
        screen_w: int,
        screen_h: int,
        place_kind: str | None,
        place_faction: str | None = None,
    ) -> None:
        self._lmb_down = True
        self._press_xy = event.pos
        self._panning = False
        self._box_select = False
        self._press_obj_id = None
        if selection.artillery_aim:
            wx, wy = camera.screen_to_world(*event.pos, screen_w, screen_h)
            for oid in list(selection.selected):
                obj = entities.get(oid)
                if obj is None or obj.kind != "artillery":
                    continue
                if obj.faction != FACTION_PLAYER:
                    continue
                entities.dispatch(
                    SetAim(object_id=oid, target=(wx, wy)),
                    as_faction=FACTION_PLAYER,
                )
            selection.artillery_aim = False
            self._lmb_down = False
            return
        if selection.pick_targets:
            self._box_select = True
            selection.box = (*event.pos, *event.pos)
            return
        if place_kind:
            return
        if selection.port_cmd:
            return
        hit = pick_at(
            entities,
            camera,
            screen_w,
            screen_h,
            *event.pos,
            own_only=not camera.debug_mode,
            source=list(entities.items) if camera.debug_mode else None,
            include_intercept=camera.debug_mode,
        )
        self._press_obj_id = hit.id if hit else None
        mods = pygame.key.get_mods()
        shift = bool(mods & pygame.KMOD_SHIFT)
        if shift and hit is None:
            self._box_select = True
            selection.box = (*event.pos, *event.pos)
        elif hit is None:
            self._panning = True

    def _on_lmb_drag(
        self,
        event: pygame.event.Event,
        camera: Camera,
        selection: Selection,
        screen_w: int,
        screen_h: int,
    ) -> None:
        if self._box_select:
            x0, y0 = self._press_xy
            selection.box = (x0, y0, event.pos[0], event.pos[1])
            return
        dx = event.pos[0] - self._press_xy[0]
        dy = event.pos[1] - self._press_xy[1]
        if not self._panning and (abs(dx) > DRAG_PX or abs(dy) > DRAG_PX):
            if self._press_obj_id is None:
                self._panning = True
                selection.box = None
                self._box_select = False
        if self._panning:
            camera.pan_pixels(event.rel[0], event.rel[1], screen_w, screen_h)

    def _on_lmb_up(
        self,
        event: pygame.event.Event,
        camera: Camera,
        entities: Entities,
        selection: Selection,
        screen_w: int,
        screen_h: int,
        place_kind: str | None,
        place_faction: str | None = None,
    ) -> None:
        if not self._lmb_down:
            return
        mods = pygame.key.get_mods()
        shift = bool(mods & pygame.KMOD_SHIFT)
        dx = event.pos[0] - self._press_xy[0]
        dy = event.pos[1] - self._press_xy[1]
        moved = abs(dx) > DRAG_PX or abs(dy) > DRAG_PX

        if place_kind and not moved and not self._box_select:
            wx, wy = camera.screen_to_world(*event.pos, screen_w, screen_h)
            spawned = entities.spawn_debug(
                place_kind, wx, wy, faction=place_faction or FACTION_PLAYER
            )
            if spawned is not None:
                print(
                    f"debug: placed {spawned.faction} {spawned.kind} {spawned.id}",
                    flush=True,
                )
            self._lmb_down = False
            self._panning = False
            self._box_select = False
            self._press_obj_id = None
            selection.box = None
            return

        if selection.pick_targets:
            if self._box_select and moved:
                box = selection.box or (*self._press_xy, *event.pos)
                ids = selection.foes_in_box(
                    entities, camera, screen_w, screen_h, *box
                )
                _merge_focus(entities, selection, ids)
            elif not moved:
                hit = pick_at(
                    entities,
                    camera,
                    screen_w,
                    screen_h,
                    *event.pos,
                    own_only=False,
                    source=list(entities.snapshot(FACTION_PLAYER)),
                )
                if (
                    hit is not None
                    and hit.faction != FACTION_PLAYER
                    and hit.kind not in SHOT_KINDS
                    and not is_static_kind(hit.kind)
                    and hit.active
                    and not getattr(hit, "stowed", False)
                ):
                    _toggle_focus(entities, selection, hit.id)
            self._lmb_down = False
            self._panning = False
            self._box_select = False
            self._press_obj_id = None
            selection.box = None
            return

        if self._box_select and moved:
            selection.apply_box(
                entities,
                camera,
                screen_w,
                screen_h,
                *selection.box or (*self._press_xy, *event.pos),
                additive=shift,
                debug=camera.debug_mode,
            )
        elif not moved:
            if selection.port_cmd:
                self._finish_port_cmd(
                    event, camera, entities, selection, screen_w, screen_h
                )
            elif self._press_obj_id:
                if shift:
                    selection.toggle(self._press_obj_id)
                else:
                    selection.replace(self._press_obj_id)
            elif not shift:
                selection.clear()

        self._lmb_down = False
        self._panning = False
        self._box_select = False
        self._press_obj_id = None
        selection.box = None

    def _on_rmb(
        self,
        event: pygame.event.Event,
        camera: Camera,
        entities: Entities,
        selection: Selection,
        screen_w: int,
        screen_h: int,
    ) -> None:
        if selection.port_cmd:
            selection.port_cmd = None
            return
        if selection.artillery_aim:
            selection.artillery_aim = False
            return
        if selection.pick_targets:
            selection.pick_targets = False
            return
        if not selection.selected:
            return
        wx, wy = camera.screen_to_world(*event.pos, screen_w, screen_h)
        target = (wx, wy)
        for oid in list(selection.selected):
            obj = entities.get(oid)
            if not isinstance(obj, DynamicObject) or not obj.active:
                continue
            if obj.faction != FACTION_PLAYER or obj.kind in ("intercept", "tracer", "shell"):
                continue
            entities.dispatch(
                SetRoute(object_id=oid, mode="auto", target=target),
                as_faction=FACTION_PLAYER,
            )

    def _finish_port_cmd(
        self,
        event: pygame.event.Event,
        camera: Camera,
        entities: Entities,
        selection: Selection,
        screen_w: int,
        screen_h: int,
    ) -> None:
        port_id = selection.port_id
        if not port_id:
            selection.port_cmd = None
            return
        if selection.port_cmd == "launch":
            wx, wy = camera.screen_to_world(*event.pos, screen_w, screen_h)
            entities.launch_ferry(port_id, (wx, wy))
            selection.port_cmd = None
            return
        if selection.port_cmd == "recall":
            hit = pick_at(
                entities,
                camera,
                screen_w,
                screen_h,
                *event.pos,
                own_only=not camera.debug_mode,
                source=list(entities.items) if camera.debug_mode else None,
            )
            if hit is None or hit.kind != "ferry" or hit.faction != FACTION_PLAYER:
                return
            entities.recall_ferry(port_id, hit.id)
            selection.port_cmd = None
            return
        if selection.port_cmd == "load":
            hit = pick_at(
                entities,
                camera,
                screen_w,
                screen_h,
                *event.pos,
                own_only=not camera.debug_mode,
                source=list(entities.items) if camera.debug_mode else None,
            )
            if hit is None or hit.id == port_id:
                return
            if not isinstance(hit, DynamicObject) or hit.mobility != "land":
                return
            if hit.faction != FACTION_PLAYER or not hit.active:
                return
            entities.load_ferry(port_id, hit.id)
            selection.port_cmd = None
            return
        if selection.port_cmd == "unload":
            hit = pick_at(
                entities,
                camera,
                screen_w,
                screen_h,
                *event.pos,
                own_only=not camera.debug_mode,
                source=list(entities.items) if camera.debug_mode else None,
            )
            wx, wy = camera.screen_to_world(*event.pos, screen_w, screen_h)
            dest_port_id = None
            if (
                hit is not None
                and hit.kind == "port"
                and hit.active
                and hit.faction == FACTION_PLAYER
            ):
                dest_port_id = hit.id
                wx, wy = hit.x, hit.y
            entities.unload_ferry(port_id, (wx, wy), dest_port_id=dest_port_id)
            selection.port_cmd = None

    def handle_held(
        self, camera: Camera, dt_wall: float, screen_w: int, screen_h: int
    ) -> None:
        keys = pygame.key.get_pressed()
        ticks = _key_ticks(dt_wall)
        step = PAN_SPEED_PX * ticks
        dx = 0.0
        dy = 0.0
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dy += step
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dy -= step
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            dx += step
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            dx -= step
        if dx or dy:
            camera.pan_pixels(dx, dy, screen_w, screen_h)

        zoom_in = any(keys[k] for k in ZOOM_IN_KEYS)
        zoom_out = any(keys[k] for k in ZOOM_OUT_KEYS)
        if zoom_in == zoom_out:
            return
        signed = -ZOOM_KEY_DELTA if zoom_in else ZOOM_KEY_DELTA
        factor = _zoom_factor(signed) ** ticks
        camera.zoom_at_screen(
            factor, screen_w * 0.5, screen_h * 0.5, screen_w, screen_h
        )


def _focus_guns(entities: Entities, selection: Selection) -> list:
    out = []
    for oid in selection.selected:
        obj = entities.get(oid)
        if is_battery(obj) and obj is not None and obj.faction == FACTION_PLAYER:
            out.append(obj)
    return out


def _merge_focus(entities: Entities, selection: Selection, ids: set[str]) -> None:
    if not ids:
        return
    for obj in _focus_guns(entities, selection):
        current = set(getattr(obj, "focus_ids", ()) or ())
        current |= ids
        entities.dispatch(
            SetFocus(object_id=obj.id, ids=tuple(sorted(current))),
            as_faction=FACTION_PLAYER,
        )


def _toggle_focus(entities: Entities, selection: Selection, target_id: str) -> None:
    for obj in _focus_guns(entities, selection):
        current = set(getattr(obj, "focus_ids", ()) or ())
        if target_id in current:
            current.discard(target_id)
        else:
            current.add(target_id)
        entities.dispatch(
            SetFocus(object_id=obj.id, ids=tuple(sorted(current))),
            as_faction=FACTION_PLAYER,
        )
