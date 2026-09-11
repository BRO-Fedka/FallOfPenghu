from __future__ import annotations

import pygame

from fall_of_penghu.camera import Camera
from fall_of_penghu.chat import LINE_H, MAX_LINES, ChatLog
from fall_of_penghu.render.dynamic.icons import CHIP, IconStore
from fall_of_penghu.render.static.tod import palette_at, phase_label
from fall_of_penghu.selection import Selection
from fall_of_penghu.world.clock import DEBUG_SPEED, SPEEDS, Clock
from fall_of_penghu.world.combat.doctrine import FIRE, HOLD, LABELS, doctrines_for, is_battery
from fall_of_penghu.world.entities import (
    Entities,
    FACTION_PLAYER,
    GameObject,
    SetDoctrine,
    WreckObject,
)
from fall_of_penghu.debug_palette import DebugPalette
from fall_of_penghu.engage_palette import EngagePalette
from fall_of_penghu.vision_palette import VisionPalette
from fall_of_penghu.world.entities.transport import PORT_CAP
from fall_of_penghu.world.perception import Perception, format_calendar_span

PANEL_H = 40
DEBUG_H = 44
BTN_W = 52
BTN_H = 26
BTN_GAP = 6
MODE_BTN_W = 28
DOC_BTN_W = 44
CLOCK_W = 148
MODE_GAP = 18
ENGAGE_BOX = 14
ENGAGE_HIT_W = 72
PORT_BTN_W = 86
PORT_BTN_H = 24
PORT_HINT = {
    "launch": "Click destination",
    "recall": "Click a ferry",
    "load": "Click a unit",
    "unload": "Click destination",
    "destroy": "Destroy this bridge",
}


class Hud:
    """Chrome overlay. Top bar is always on; debug text only in debug_mode."""

    def __init__(self) -> None:
        self.font = pygame.font.SysFont("consolas", 16)
        self.small = pygame.font.SysFont("consolas", 14)
        self._buttons: list[tuple[pygame.Rect, float]] = []
        self._mode_buttons: list[tuple[pygame.Rect, bool]] = []
        self._doctrine_buttons: list[tuple[pygame.Rect, str]] = []
        self._engage_box = pygame.Rect(0, 0, ENGAGE_BOX, ENGAGE_BOX)
        self._engage_hit = pygame.Rect(0, 0, ENGAGE_HIT_W, BTN_H)
        self._panel_h = PANEL_H
        self._icons = IconStore()
        self._port_buttons: list[tuple[pygame.Rect, str]] = []

    def hits_chrome(
        self,
        x: int,
        y: int,
        screen_w: int,
        screen_h: int,
        debug: bool,
        chat: ChatLog | None = None,
        palette: DebugPalette | None = None,
        engage: EngagePalette | None = None,
        vision: VisionPalette | None = None,
        selection: Selection | None = None,
        entities: Entities | None = None,
        camera: Camera | None = None,
    ) -> bool:
        if y < self._panel_h:
            return True
        inset = DEBUG_H if debug else 0
        if chat is not None and chat.hits(x, y, screen_w, screen_h, inset):
            return True
        if debug and palette is not None and palette.hits(x, y):
            return True
        if engage is not None and engage.hits(x, y, selection, entities):
            return True
        if vision is not None and vision.hits(x, y):
            return True
        self._layout_port_menu(selection, entities, camera, screen_w, screen_h)
        for rect, _cmd in self._port_buttons:
            if rect.collidepoint(x, y):
                return True
        return bool(debug and y >= screen_h - DEBUG_H)

    def _layout(self, debug: bool) -> None:
        speeds: tuple[float, ...] = SPEEDS + ((DEBUG_SPEED,) if debug else ())
        x = 12 + CLOCK_W
        y = (PANEL_H - BTN_H) // 2
        self._buttons = []
        for speed in speeds:
            self._buttons.append((pygame.Rect(x, y, BTN_W, BTN_H), speed))
            x += BTN_W + BTN_GAP
        x += MODE_GAP
        self._mode_label_x = x
        label_w = 36
        x += label_w + BTN_GAP
        self._mode_buttons = [
            (pygame.Rect(x, y, MODE_BTN_W, BTN_H), False),
            (pygame.Rect(x + MODE_BTN_W + BTN_GAP, y, MODE_BTN_W, BTN_H), True),
        ]
        x = self._mode_buttons[-1][0].right + MODE_GAP
        self._engage_hit = pygame.Rect(x, y, ENGAGE_HIT_W, BTN_H)
        self._engage_box = pygame.Rect(
            x,
            y + (BTN_H - ENGAGE_BOX) // 2,
            ENGAGE_BOX,
            ENGAGE_BOX,
        )

    def _layout_doctrine(
        self,
        selection: Selection | None,
        entities: Entities | None,
    ) -> None:
        self._doctrine_buttons = []
        if selection is None or entities is None:
            return
        batteries = self._selected_batteries(selection, entities)
        if not batteries:
            return
        x = self._engage_hit.right + MODE_GAP
        y = (PANEL_H - BTN_H) // 2
        kinds = {obj.kind for obj in batteries}
        for doctrine in doctrines_for(kinds):
            if doctrine in (FIRE, HOLD):
                continue
            self._doctrine_buttons.append((pygame.Rect(x, y, DOC_BTN_W, BTN_H), doctrine))
            x += DOC_BTN_W + BTN_GAP

    @staticmethod
    def _selected_port(
        selection: Selection | None, entities: Entities | None
    ) -> GameObject | None:
        if selection is None or entities is None or len(selection.selected) != 1:
            return None
        oid = next(iter(selection.selected))
        obj = entities.get(oid)
        if obj is None or obj.kind != "port" or not obj.active:
            return None
        if obj.faction != FACTION_PLAYER:
            return None
        return obj

    @staticmethod
    def _selected_ferry(
        selection: Selection | None, entities: Entities | None
    ) -> GameObject | None:
        if selection is None or entities is None or len(selection.selected) != 1:
            return None
        oid = next(iter(selection.selected))
        obj = entities.get(oid)
        if obj is None or obj.kind != "ferry" or not obj.active:
            return None
        if obj.faction != FACTION_PLAYER:
            return None
        return obj

    @staticmethod
    def _selected_bridge(
        selection: Selection | None, entities: Entities | None
    ) -> GameObject | None:
        if selection is None or entities is None or len(selection.selected) != 1:
            return None
        oid = next(iter(selection.selected))
        obj = entities.get(oid)
        if obj is None or obj.kind != "bridge" or not obj.active:
            return None
        return obj

    def _layout_port_menu(
        self,
        selection: Selection | None,
        entities: Entities | None,
        camera: Camera | None,
        screen_w: int,
        screen_h: int,
    ) -> None:
        self._port_buttons = []
        if camera is None:
            return
        port = self._selected_port(selection, entities)
        ferry = None if port is not None else self._selected_ferry(selection, entities)
        bridge = (
            None
            if port is not None or ferry is not None
            else self._selected_bridge(selection, entities)
        )
        obj = port if port is not None else ferry if ferry is not None else bridge
        if obj is None:
            return
        sx, sy = camera.world_to_screen(obj.x, obj.y, screen_w, screen_h)
        x = int(sx) + 18
        y = int(sy) - PORT_BTN_H
        if x + PORT_BTN_W > screen_w - 8:
            x = int(sx) - 18 - PORT_BTN_W
        if y < PANEL_H + 8:
            y = PANEL_H + 8
        if y + PORT_BTN_H * 2 + 4 > screen_h - 8:
            y = max(PANEL_H + 8, screen_h - 8 - PORT_BTN_H * 2 - 4)
        if port is not None:
            cmds = ("launch", "recall")
        elif ferry is not None:
            cmds = ("load", "unload")
        else:
            cmds = ("destroy",)
        self._port_buttons = [
            (pygame.Rect(x, y + i * (PORT_BTN_H + 4), PORT_BTN_W, PORT_BTN_H), cmd)
            for i, cmd in enumerate(cmds)
        ]

    @staticmethod
    def _selected_batteries(
        selection: Selection, entities: Entities
    ) -> list[GameObject]:
        out: list[GameObject] = []
        for oid in selection.selected:
            obj = entities.get(oid)
            if is_battery(obj) and obj.faction == FACTION_PLAYER:
                out.append(obj)
        return out

    def handle_event(
        self,
        event: pygame.event.Event,
        clock: Clock,
        camera: Camera,
        *,
        chat: ChatLog | None = None,
        selection: Selection | None = None,
        entities: Entities | None = None,
        screen_w: int = 1280,
        screen_h: int = 720,
    ) -> bool:
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False
        self._layout(camera.debug_mode)
        self._layout_doctrine(selection, entities)
        for rect, speed in self._buttons:
            if rect.collidepoint(event.pos):
                clock.set_speed(speed)
                return True
        for rect, radar in self._mode_buttons:
            if rect.collidepoint(event.pos):
                camera.radar_mode = radar
                return True
        if self._engage_hit.collidepoint(event.pos):
            camera.show_engagement = not camera.show_engagement
            return True
        if entities is not None and selection is not None:
            for rect, doctrine in self._doctrine_buttons:
                if rect.collidepoint(event.pos):
                    for obj in self._selected_batteries(selection, entities):
                        entities.dispatch(
                            SetDoctrine(object_id=obj.id, doctrine=doctrine),
                            as_faction=FACTION_PLAYER,
                        )
                    return True
        self._layout_port_menu(selection, entities, camera, screen_w, screen_h)
        if selection is not None:
            port = self._selected_port(selection, entities)
            ferry = self._selected_ferry(selection, entities)
            bridge = self._selected_bridge(selection, entities)
            owner = port if port is not None else ferry
            stock = int(getattr(port, "ferries", 0) or 0) if port is not None else 0
            cargo_on = bool(getattr(ferry, "cargo_id", None)) if ferry is not None else False
            for rect, cmd in self._port_buttons:
                if not rect.collidepoint(event.pos):
                    continue
                if cmd == "destroy":
                    if bridge is None or entities is None:
                        return True
                    entities.dispatch(
                        WreckObject(object_id=bridge.id),
                        as_faction=FACTION_PLAYER,
                    )
                    selection.clear()
                    return True
                if owner is None:
                    return True
                if cmd == "launch" and stock <= 0:
                    return True
                if cmd == "recall" and stock >= PORT_CAP:
                    if selection.port_cmd == "recall":
                        selection.port_cmd = None
                    return True
                if cmd == "load" and cargo_on:
                    return True
                if cmd == "unload" and not cargo_on:
                    return True
                if selection.port_cmd == cmd and selection.port_id == owner.id:
                    selection.port_cmd = None
                else:
                    selection.port_cmd = cmd
                    selection.port_id = owner.id
                return True
        if chat is not None:
            inset = DEBUG_H if camera.debug_mode else 0
            msg = chat.click_at(*event.pos, screen_w, screen_h, inset)
            if msg is not None:
                camera.fly_to(msg.x, msg.y)
                if selection is not None:
                    selection.selected = set(msg.object_ids)
                    selection.port_cmd = None
                    selection.port_id = None
                return True
        return False

    def blit(
        self,
        renderer,
        *,
        camera: Camera,
        clock: Clock,
        fps: float,
        backend: str,
        stats: dict[str, int],
        mouse_world: tuple[float, float],
        mouse_screen: tuple[int, int],
        hover: GameObject | None = None,
        selection: Selection | None = None,
        entities: Entities | None = None,
        selection_count: int = 0,
        screen_w: int,
        screen_h: int,
        perception: Perception | None = None,
        chat: ChatLog | None = None,
        palette: DebugPalette | None = None,
        engage: EngagePalette | None = None,
        vision: VisionPalette | None = None,
        heat_probe: tuple[float, float, float] | None = None,
        defeated: bool = False,
    ) -> None:
        debug = camera.debug_mode
        self._layout(debug)
        self._layout_doctrine(selection, entities)
        self._layout_port_menu(selection, entities, camera, screen_w, screen_h)
        pal = palette_at(clock.time_of_day)
        ink = pal["hud"]
        bar = pygame.Surface((screen_w, PANEL_H), pygame.SRCALPHA)
        bar.fill((8, 10, 12, 170))

        clock_surf = self.font.render(clock.clock_label(), True, ink)
        bar.blit(clock_surf, (12, (PANEL_H - clock_surf.get_height()) // 2))

        for rect, speed in self._buttons:
            selected = abs(clock.speed - speed) < 1e-6
            fill = (ink[0], ink[1], ink[2], 55 if selected else 18)
            pygame.draw.rect(bar, fill, rect, border_radius=3)
            pygame.draw.rect(bar, (*ink, 200 if selected else 90), rect, 1, border_radius=3)
            label = clock.speed_label(speed)
            text = self.small.render(label, True, ink)
            bar.blit(
                text,
                (
                    rect.x + (rect.w - text.get_width()) // 2,
                    rect.y + (rect.h - text.get_height()) // 2,
                ),
            )

        mode_label = self.small.render("MOD", True, ink)
        bar.blit(
            mode_label,
            (self._mode_label_x, (PANEL_H - mode_label.get_height()) // 2),
        )
        for rect, radar in self._mode_buttons:
            selected = camera.radar_mode == radar
            fill = (ink[0], ink[1], ink[2], 55 if selected else 18)
            pygame.draw.rect(bar, fill, rect, border_radius=3)
            pygame.draw.rect(bar, (*ink, 200 if selected else 90), rect, 1, border_radius=3)
            text = self.small.render("R" if radar else "N", True, ink)
            bar.blit(
                text,
                (
                    rect.x + (rect.w - text.get_width()) // 2,
                    rect.y + (rect.h - text.get_height()) // 2,
                ),
            )

        pygame.draw.rect(bar, (*ink, 90), self._engage_box, 1)
        if camera.show_engagement:
            inner = self._engage_box.inflate(-4, -4)
            pygame.draw.rect(bar, (*ink, 210), inner)
        rng = self.small.render("RNG  G", True, ink)
        bar.blit(
            rng,
            (
                self._engage_box.right + 6,
                (PANEL_H - rng.get_height()) // 2,
            ),
        )

        current_doctrine = None
        if selection is not None and entities is not None:
            found = {
                getattr(obj, "doctrine", None)
                for obj in self._selected_batteries(selection, entities)
            }
            if len(found) == 1:
                current_doctrine = found.pop()
        for rect, doctrine in self._doctrine_buttons:
            selected = doctrine == current_doctrine
            fill = (ink[0], ink[1], ink[2], 55 if selected else 18)
            pygame.draw.rect(bar, fill, rect, border_radius=3)
            pygame.draw.rect(bar, (*ink, 200 if selected else 90), rect, 1, border_radius=3)
            text = self.small.render(LABELS[doctrine], True, ink)
            bar.blit(
                text,
                (
                    rect.x + (rect.w - text.get_width()) // 2,
                    rect.y + (rect.h - text.get_height()) // 2,
                ),
            )

        if perception is not None:
            sat = perception.satellite_status(clock.calendar_time)
            if sat.active:
                sat_text = f"SAT ON  {format_calendar_span(sat.remain_calendar_s)}"
            else:
                sat_text = f"SAT  {format_calendar_span(sat.until_start_calendar_s)}"
            sat_surf = self.small.render(sat_text, True, ink)
            right = screen_w - sat_surf.get_width() - (88 if debug else 12)
            bar.blit(sat_surf, (right, (PANEL_H - sat_surf.get_height()) // 2))

        if debug:
            badge = self.small.render("DEBUG", True, ink)
            bar.blit(badge, (screen_w - badge.get_width() - 12, (PANEL_H - badge.get_height()) // 2))

        renderer.overlay(bar, (0, 0))

        if defeated:
            banner = self.font.render("DEFEAT — no player units remain on the islands", True, ink)
            box = pygame.Surface(
                (banner.get_width() + 24, banner.get_height() + 16), pygame.SRCALPHA
            )
            box.fill((8, 10, 12, 210))
            box.blit(banner, (12, 8))
            renderer.overlay(
                box,
                ((screen_w - box.get_width()) // 2, PANEL_H + 16),
            )

        if hover is not None:
            tip = hover.name
            doctrine = getattr(hover, "doctrine", None)
            if hover.kind in (
                "aaw",
                "aa_pickup",
                "infantry",
                "tank",
                "artillery",
            ) and doctrine:
                tip = f"{tip}  {LABELS.get(doctrine, doctrine)}"
            hp = getattr(hover, "hp", None)
            max_hp = getattr(hover, "max_hp", None)
            if hp is not None and max_hp is not None and float(max_hp) > 1.5:
                tip = f"{tip}  {int(hp)}/{int(max_hp)}"
            if hover.kind == "port":
                stock = int(getattr(hover, "ferries", 0) or 0)
                tip = f"{tip}  ferries {stock}/20"
            cargo = None
            if hover.kind == "ferry" and entities is not None:
                cargo_id = getattr(hover, "cargo_id", None)
                if cargo_id:
                    cargo = entities.get(cargo_id)
            if cargo is not None:
                tip = f"{tip}  {cargo.name}"
            if not hover.active:
                tip = f"{tip}  wrecked"
            if selection_count > 1:
                tip = f"{tip}  ({selection_count} selected)"
            text = self.small.render(tip, True, ink)
            cargo_icon = None
            if cargo is not None:
                cargo_icon = self._icons.get(cargo.kind, cargo.faction, False)
            icon_w = CHIP if cargo_icon is not None else 0
            gap = 6 if cargo_icon is not None else 0
            mx, my = mouse_screen
            pad = 6
            box_w = text.get_width() + pad * 2 + icon_w + gap
            box_h = max(text.get_height(), CHIP if cargo_icon is not None else 0) + pad * 2
            tx = min(max(12, mx + 14), screen_w - box_w - 12)
            ty = min(max(PANEL_H + 8, my + 14), screen_h - box_h - 16)
            box = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
            box.fill((8, 10, 12, 200))
            x = pad
            if cargo_icon is not None:
                box.blit(cargo_icon, (x, (box_h - CHIP) // 2))
                x += CHIP + gap
            box.blit(text, (x, (box_h - text.get_height()) // 2))
            renderer.overlay(box, (tx, ty))

        if debug:
            wx, wy = mouse_world
            hud = (
                f"{fps:5.1f} fps   "
                f"{backend}   "
                f"{phase_label(clock.time_of_day)}   "
                f"tod {clock.time_of_day:.3f}   "
                f"{clock.speed_label()}   "
                f"view {camera.view_width_m / 1000:6.2f} km   "
                f"{camera.meters_per_pixel(screen_w):7.2f} m/px   "
                f"cam {camera.x:.0f},{camera.y:.0f}   "
                f"cursor {wx:.0f},{wy:.0f} m   "
                f"{'RADAR' if camera.radar_mode else 'MAP'}   "
                f"draw c{stats['coast']} v{stats['vegetation']} "
                f"b{stats['buildings']} r{stats['roads']}"
            )
            if heat_probe is not None:
                hud += (
                    f"   heat T{heat_probe[0]:.2f} "
                    f"L{heat_probe[1]:.2f} AA{heat_probe[2]:.2f}"
                )
            hint = (
                "WASD pan  LMB select  Shift box  RMB move  "
                "Shift+RMB sea/air waypoints  Q/E zoom  "
                "Shift+Del delete  F12 debug  red=C snapshot  yellow=C imprint  "
                "heat R/G/B=threat/land/AA  Esc quit"
            )
            footer = pygame.Surface((screen_w, DEBUG_H), pygame.SRCALPHA)
            footer.fill((8, 10, 12, 170))
            footer.blit(self.small.render(hud, True, ink), (10, 4))
            footer.blit(self.small.render(hint, True, ink), (10, 22))
            renderer.overlay(footer, (0, screen_h - DEBUG_H))

        self._blit_port_menu(renderer, selection, entities, ink, screen_w, screen_h)
        if selection is not None and selection.artillery_aim:
            hint = self.small.render("Click map to aim  CLR to cancel", True, ink)
            box = pygame.Surface(
                (hint.get_width() + 12, hint.get_height() + 8), pygame.SRCALPHA
            )
            box.fill((8, 10, 12, 200))
            box.blit(hint, (6, 4))
            renderer.overlay(box, (12, PANEL_H + 8))
        elif selection is not None and selection.pick_targets:
            hint = self.small.render("Click or box enemy units  RMB done", True, ink)
            box = pygame.Surface(
                (hint.get_width() + 12, hint.get_height() + 8), pygame.SRCALPHA
            )
            box.fill((8, 10, 12, 200))
            box.blit(hint, (6, 4))
            renderer.overlay(box, (12, PANEL_H + 8))

        if chat is not None:
            inset = DEBUG_H if debug else 0
            self._blit_chat(renderer, chat, ink, screen_w, screen_h, inset)

        if debug and palette is not None:
            palette.blit(renderer, mouse_screen, ink, screen_w, screen_h)
        if engage is not None:
            engage.blit(
                renderer,
                mouse_screen,
                ink,
                selection,
                entities,
                None if perception is None else perception.catalog,
                screen_w,
                screen_h,
            )
        if vision is not None:
            vision.blit(renderer, mouse_screen, ink, screen_w, screen_h)

    def _blit_port_menu(
        self,
        renderer,
        selection: Selection | None,
        entities: Entities | None,
        ink: tuple[int, int, int],
        screen_w: int,
        screen_h: int,
    ) -> None:
        if not self._port_buttons:
            return
        port = self._selected_port(selection, entities)
        ferry = self._selected_ferry(selection, entities)
        stock = int(getattr(port, "ferries", 0) or 0) if port is not None else 0
        cargo_on = bool(getattr(ferry, "cargo_id", None)) if ferry is not None else False
        labels = {
            "launch": "Launch",
            "recall": "Recall",
            "load": "Load",
            "unload": "Unload",
            "destroy": "Destroy",
        }
        for rect, cmd in self._port_buttons:
            armed = selection is not None and selection.port_cmd == cmd
            disabled = (
                (cmd == "launch" and stock <= 0)
                or (cmd == "recall" and stock >= PORT_CAP)
                or (cmd == "load" and cargo_on)
                or (cmd == "unload" and not cargo_on)
            )
            fill_a = 18
            if armed:
                fill_a = 70
            elif disabled:
                fill_a = 10
            surf = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            surf.fill((ink[0], ink[1], ink[2], fill_a))
            pygame.draw.rect(
                surf, (*ink, 210 if armed else 70 if disabled else 140), surf.get_rect(), 1
            )
            text = self.small.render(labels[cmd], True, ink)
            if disabled:
                text.set_alpha(90)
            surf.blit(
                text,
                (
                    (rect.w - text.get_width()) // 2,
                    (rect.h - text.get_height()) // 2,
                ),
            )
            renderer.overlay(surf, (rect.x, rect.y))
        if selection is None or selection.port_cmd is None:
            return
        hint = PORT_HINT.get(selection.port_cmd)
        if not hint:
            return
        text = self.small.render(hint, True, ink)
        last = self._port_buttons[-1][0]
        hx = last.x
        hy = last.bottom + 6
        if hx + text.get_width() + 12 > screen_w:
            hx = screen_w - text.get_width() - 16
        if hy + text.get_height() + 8 > screen_h:
            hy = self._port_buttons[0][0].y - text.get_height() - 8
        box = pygame.Surface(
            (text.get_width() + 12, text.get_height() + 8), pygame.SRCALPHA
        )
        box.fill((8, 10, 12, 200))
        box.blit(text, (6, 4))
        renderer.overlay(box, (hx, hy))

    def _blit_chat(
        self,
        renderer,
        chat: ChatLog,
        ink: tuple[int, int, int],
        screen_w: int,
        screen_h: int,
        bottom_inset: int = 0,
    ) -> None:
        panel = chat.panel_rect(screen_w, screen_h, bottom_inset)
        surf = pygame.Surface((panel.w, panel.h), pygame.SRCALPHA)
        surf.fill((8, 10, 12, 180))
        pygame.draw.rect(surf, (*ink, 70), surf.get_rect(), 1)
        title = self.small.render("CONTACTS", True, ink)
        surf.blit(title, (10, 6))
        chat._rects = []
        lines = chat.messages[-MAX_LINES:]
        y = 28
        for msg in reversed(lines):
            row = pygame.Rect(6, y, panel.w - 12, LINE_H - 2)
            pygame.draw.rect(surf, (ink[0], ink[1], ink[2], 22), row)
            text = self.small.render(msg.text, True, ink)
            surf.blit(text, (row.x + 6, row.y + (row.h - text.get_height()) // 2))
            chat._rects.append(
                (pygame.Rect(panel.x + row.x, panel.y + row.y, row.w, row.h), msg)
            )
            y += LINE_H
        renderer.overlay(surf, (panel.x, panel.y))
