from __future__ import annotations

import pygame

from fall_of_penghu.render.dynamic.icons import CHIP, IconStore
from fall_of_penghu.shell.settings import (
    AA_LABELS,
    AA_MODES,
    RENDERER_LABELS,
    RENDERERS,
    Settings,
)
from fall_of_penghu.shell.saves import list_slots
from fall_of_penghu.shell.theme import button, fonts, frame, ink_at, label, panel, slider
from fall_of_penghu.world.entities.game_object import FACTION_CHINA
from fall_of_penghu.world.victory import kill_total, ordered_kills

BTN_W = 220
WARN = (196, 72, 64)
BTN_H = 32
CLOSE_W = 28
MENU_VEIL_A = 64


class ModalScrim:
    """Veil and an X just outside the form. The dimmed area eats mouse events."""

    def __init__(self) -> None:
        self._font = fonts()[1]
        self._close = pygame.Rect(0, 0, CLOSE_W, CLOSE_W)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False
        return self._close.collidepoint(event.pos)

    def blocks(self, event: pygame.event.Event, form: pygame.Rect) -> bool:
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
        elif event.type == pygame.MOUSEBUTTONDOWN:
            pos = event.pos
        else:
            return False
        if form.collidepoint(pos) or self._close.collidepoint(pos):
            return False
        return True

    def draw_veil(self, target, screen_w: int, screen_h: int) -> None:
        veil = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
        veil.fill((0, 0, 0, MENU_VEIL_A))
        target.overlay(veil, (0, 0))

    def draw_close(
        self,
        target,
        form: pygame.Rect,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        tod: float = 0.5,
    ) -> None:
        ink = ink_at(tod)
        self._close = pygame.Rect(form.right + 8, form.top, CLOSE_W, CLOSE_W)
        if self._close.right > screen_w - 8:
            self._close.x = form.right - CLOSE_W
            self._close.y = form.top - CLOSE_W - 8
        if self._close.top < 8:
            self._close.y = form.top + 8
        chip = panel((CLOSE_W, CLOSE_W), 220)
        frame(chip, ink, 80)
        button(
            chip,
            chip.get_rect(),
            "X",
            self._font,
            ink,
            hover=self._close.collidepoint(mouse),
        )
        target.overlay(chip, (self._close.x, self._close.y))


class MenuSheet:
    """Title column on the shell window."""

    def __init__(self) -> None:
        self._title, self._font, self._small = fonts()
        self._rects: dict[str, pygame.Rect] = {}

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        for key, rect in self._rects.items():
            if rect.collidepoint(event.pos):
                return key
        return None

    def draw(
        self,
        target,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        *,
        can_continue: bool,
        tod: float = 0.5,
    ) -> None:
        ink = ink_at(tod)
        x = 48
        y = screen_h // 2 - 160
        sheet = panel((320, 360), 200)
        frame(sheet, ink, 70)
        label(sheet, "FALL OF PENGHU", self._title, ink, (16, 16))
        sub = self._small.render("There will be no help", True, ink)
        sheet.blit(sub, (16, 46))
        keys = (
            ("continue", "Continue", not can_continue),
            ("new", "New Game", False),
            ("load", "Load game", False),
            ("settings", "Settings", False),
            ("help", "Field manual", False),
            ("quit", "Quit", False),
        )
        self._rects = {}
        by = 80
        for key, caption, dead in keys:
            local = pygame.Rect(16, by, BTN_W, BTN_H)
            self._rects[key] = local.move(x, y)
            button(
                sheet,
                local,
                caption,
                self._font,
                ink,
                disabled=dead,
                hover=not dead and self._rects[key].collidepoint(mouse),
            )
            by += 40
        target.overlay(sheet, (x, y))


class PauseSheet:
    def __init__(self) -> None:
        self._title, self._font, self._small = fonts()
        self._rects: dict[str, pygame.Rect] = {}

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        for key, rect in self._rects.items():
            if rect.collidepoint(event.pos):
                return key
        return None

    def draw(
        self,
        target,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        tod: float = 0.5,
    ) -> None:
        ink = ink_at(tod)
        veil = panel((screen_w, screen_h), 140)
        target.overlay(veil, (0, 0))
        w, h = 280, 280
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        sheet = panel((w, h), 220)
        frame(sheet, ink, 80)
        label(sheet, "PAUSED", self._title, ink, (16, 14))
        keys = (
            ("resume", "Resume", False),
            ("save", "Save", False),
            ("settings", "Settings", False),
            ("help", "Field manual", False),
            ("menu", "To menu", False),
        )
        self._rects = {}
        by = 56
        for key, caption, dead in keys:
            local = pygame.Rect(16, by, w - 32, BTN_H)
            self._rects[key] = local.move(x, y)
            button(
                sheet,
                local,
                caption,
                self._font,
                ink,
                disabled=dead,
                hover=not dead and self._rects[key].collidepoint(mouse),
            )
            by += 40
        target.overlay(sheet, (x, y))


class SurrenderSheet:
    """Capitulation card after China takes the last island."""

    def __init__(self) -> None:
        self._title, self._font, self._small = fonts()
        self._icons = IconStore()
        self._rects: dict[str, pygame.Rect] = {}

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        for key, rect in self._rects.items():
            if rect.collidepoint(event.pos):
                return key
        return None

    def draw(
        self,
        target,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        *,
        held: str,
        kills: dict[str, int] | None,
        tod: float = 0.5,
    ) -> None:
        ink = ink_at(tod)
        veil = panel((screen_w, screen_h), 150)
        target.overlay(veil, (0, 0))
        w = min(460, max(360, screen_w - 48))
        inner = w - 32
        chips = self._kill_chips(kills, ink)
        kill_h = self._wrap_h(chips, inner)
        rank_y = 160 + kill_h + 16
        by = rank_y + 64
        h = min(screen_h - 32, by + 80 + 16)
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        sheet = panel((w, h), 230)
        frame(sheet, ink, 80)
        label(sheet, "SURRENDER", self._title, ink, (16, 14))
        sub = self._font.render("The archipelago is lost.", True, ink)
        sheet.blit(sub, (16, 48))
        held_l = self._small.render("Held for", True, ink)
        held_v = self._font.render(held, True, ink)
        sheet.blit(held_l, (16, 88))
        sheet.blit(held_v, (16, 106))
        total = kill_total(kills)
        kill_l = self._small.render(
            "Destroyed" if total == 0 else f"Destroyed  ·  {total}",
            True,
            ink,
        )
        sheet.blit(kill_l, (16, 140))
        self._blit_kills(sheet, chips, 16, 160, inner)
        rank_l = self._small.render("Global rank", True, ink)
        rank_v = self._font.render("—", True, ink)
        rank_note = self._small.render("leaderboard coming later", True, ink)
        sheet.blit(rank_l, (16, rank_y))
        sheet.blit(rank_v, (16, rank_y + 18))
        sheet.blit(rank_note, (16, rank_y + 40))
        keys = (
            ("observe", "Observe the world"),
            ("quit", "To menu"),
        )
        self._rects = {}
        for key, caption in keys:
            local = pygame.Rect(16, by, w - 32, BTN_H)
            self._rects[key] = local.move(x, y)
            button(
                sheet,
                local,
                caption,
                self._font,
                ink,
                hover=self._rects[key].collidepoint(mouse),
            )
            by += 40
        target.overlay(sheet, (x, y))

    def _kill_chips(
        self,
        kills: dict[str, int] | None,
        ink: tuple[int, int, int],
    ) -> list[tuple[pygame.Surface | None, pygame.Surface, int]]:
        rows = ordered_kills(kills)
        if not rows:
            none = self._font.render("none", True, ink)
            return [(None, none, none.get_width())]
        out: list[tuple[pygame.Surface | None, pygame.Surface, int]] = []
        for kind, n in rows:
            icon = self._icons.get(kind, FACTION_CHINA, False)
            count = self._font.render(str(n), True, ink)
            width = (CHIP + 4 if icon is not None else 0) + count.get_width() + 14
            out.append((icon, count, width))
        return out

    def _wrap_h(
        self,
        chips: list[tuple[pygame.Surface | None, pygame.Surface, int]],
        inner: int,
    ) -> int:
        x = 0
        rows = 1
        for _icon, _count, width in chips:
            if x and x + width > inner:
                x = 0
                rows += 1
            x += width
        return rows * 28

    def _blit_kills(
        self,
        sheet: pygame.Surface,
        chips: list[tuple[pygame.Surface | None, pygame.Surface, int]],
        left: int,
        top: int,
        inner: int,
    ) -> int:
        x = left
        y = top
        for icon, count, width in chips:
            if x > left and x + width > left + inner:
                x = left
                y += 28
            if icon is not None:
                sheet.blit(icon, (x, y + (28 - CHIP) // 2))
                x += CHIP + 4
            sheet.blit(count, (x, y + (28 - count.get_height()) // 2))
            x += count.get_width() + 14
        return y + 28


class SettingsSheet:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self._applied_renderer = cfg.renderer
        self._title, self._font, self._small = fonts()
        self._hits: list[tuple[pygame.Rect, str, object]] = []
        self._sliders: dict[str, pygame.Rect] = {}
        self._drag: str | None = None

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._drag is not None:
                self._drag = None
                return True
            return False
        if event.type == pygame.MOUSEMOTION and self._drag is not None:
            self._set_vol(self._drag, event.pos[0])
            return True
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False
        for field, rect in self._sliders.items():
            if rect.collidepoint(event.pos):
                self._drag = field
                self._set_vol(field, event.pos[0])
                return True
        for rect, kind, payload in self._hits:
            if not rect.collidepoint(event.pos):
                continue
            if kind == "fullscreen":
                self.cfg.fullscreen = not self.cfg.fullscreen
                return True
            if kind == "simple_shaders":
                self.cfg.simple_shaders = not self.cfg.simple_shaders
                return True
            if kind == "renderer":
                self.cfg.renderer = str(payload)
                return True
            if kind == "aa":
                self.cfg.antialias = str(payload)
                return True
            if kind == "clock":
                self.cfg.clock_12h = bool(payload)
                return True
            return True
        return False

    def draw(
        self,
        target,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        tod: float = 0.5,
    ) -> None:
        ink = ink_at(tod)
        w, h = self._form_size(screen_w, screen_h)
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        sheet = panel((w, h), 220)
        frame(sheet, ink, 80)
        label(sheet, "SETTINGS", self._title, ink, (16, 14))
        note = self._small.render("Esc back", True, ink)
        sheet.blit(note, (16, 46))
        self._hits = []
        self._sliders = {}
        row = 80
        row = self._check(
            sheet, x, y, mouse, ink, row, "fullscreen", "Fullscreen", self.cfg.fullscreen
        )
        label(sheet, "Clock", self._font, ink, (16, row + 4))
        cx = 160
        for twelve, caption in ((False, "24-hour"), (True, "12-hour")):
            rect = pygame.Rect(cx, row, 100, 28)
            self._hits.append((rect.move(x, y), "clock", twelve))
            button(
                sheet,
                rect,
                caption,
                self._small,
                ink,
                selected=self.cfg.clock_12h == twelve,
                hover=rect.move(x, y).collidepoint(mouse),
            )
            cx += 108
        row += 44
        label(sheet, "Renderer", self._font, ink, (16, row + 4))
        rx = 160
        for name in RENDERERS:
            rect = pygame.Rect(rx, row, 88, 28)
            self._hits.append((rect.move(x, y), "renderer", name))
            button(
                sheet,
                rect,
                RENDERER_LABELS[name],
                self._small,
                ink,
                selected=self.cfg.renderer == name,
                hover=rect.move(x, y).collidepoint(mouse),
            )
            rx += 96
        row += 44
        if self.cfg.renderer != self._applied_renderer:
            warn = self._small.render(
                "Restart the game to apply the renderer change.", True, WARN
            )
            sheet.blit(warn, (16, row))
            row += 28
        if self.cfg.renderer == "gl":
            label(sheet, "Graphics", self._font, ink, (16, row + 4))
            row += 32
            row = self._check(
                sheet,
                x,
                y,
                mouse,
                ink,
                row,
                "simple_shaders",
                "Simplified shaders",
                self.cfg.simple_shaders,
            )
            label(sheet, "Anti-alias", self._font, ink, (16, row + 4))
            ax = 140
            for name in AA_MODES:
                rect = pygame.Rect(ax, row, 72, 28)
                self._hits.append((rect.move(x, y), "aa", name))
                button(
                    sheet,
                    rect,
                    AA_LABELS[name],
                    self._small,
                    ink,
                    selected=self.cfg.antialias == name,
                    hover=rect.move(x, y).collidepoint(mouse),
                )
                ax += 80
            row += 44
        for field, caption in (
            ("master", "Master"),
            ("music", "Music"),
            ("sfx", "Effects"),
        ):
            row = self._vol(sheet, x, y, mouse, ink, w, row, field, caption)
        target.overlay(sheet, (x, y))

    def form_rect(self, screen_w: int, screen_h: int) -> pygame.Rect:
        w, h = self._form_size(screen_w, screen_h)
        return pygame.Rect((screen_w - w) // 2, (screen_h - h) // 2, w, h)

    def _form_size(self, screen_w: int, screen_h: int) -> tuple[int, int]:
        h = 392
        if self.cfg.renderer == "gl":
            h += 116
        if self.cfg.renderer != self._applied_renderer:
            h += 28
        return min(600, screen_w - 48), min(h, screen_h - 48)

    def _set_vol(self, field: str, x: int) -> None:
        rect = self._sliders.get(field)
        if rect is None or rect.w <= 0:
            return
        value = (x - rect.x) / rect.w
        setattr(self.cfg, field, min(1.0, max(0.0, value)))

    def _check(
        self,
        sheet: pygame.Surface,
        ox: int,
        oy: int,
        mouse: tuple[int, int],
        ink: tuple[int, int, int],
        row: int,
        key: str,
        caption: str,
        on: bool,
    ) -> int:
        rect = pygame.Rect(16, row, 280, 28)
        self._hits.append((rect.move(ox, oy), key, None))
        button(
            sheet,
            rect,
            f"{caption}  {'ON' if on else 'OFF'}",
            self._small,
            ink,
            selected=on,
            hover=rect.move(ox, oy).collidepoint(mouse),
        )
        return row + 40

    def _vol(
        self,
        sheet: pygame.Surface,
        ox: int,
        oy: int,
        mouse: tuple[int, int],
        ink: tuple[int, int, int],
        width: int,
        row: int,
        field: str,
        caption: str,
    ) -> int:
        label(sheet, caption, self._font, ink, (16, row + 4))
        track = pygame.Rect(140, row + 4, width - 220, 24)
        screen = track.move(ox, oy)
        self._sliders[field] = screen
        current = float(getattr(self.cfg, field))
        slider(sheet, track, current, ink, hover=screen.collidepoint(mouse))
        pct = self._small.render(f"{int(round(current * 100))}", True, ink)
        sheet.blit(pct, (track.right + 10, row + 6))
        return row + 40


class LoadSheet:
    def __init__(self) -> None:
        self._title, self._font, self._small = fonts()
        self._box = pygame.Rect(0, 0, 1, 1)
        self._hits: list[tuple[pygame.Rect, str]] = []

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        for rect, slot_id in self._hits:
            if rect.collidepoint(event.pos):
                return slot_id
        return None

    def draw(
        self,
        target,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        tod: float = 0.5,
    ) -> None:
        ink = ink_at(tod)
        w, h = min(520, screen_w - 48), min(420, screen_h - 48)
        self._box = pygame.Rect((screen_w - w) // 2, (screen_h - h) // 2, w, h)
        sheet = panel((w, h), 220)
        frame(sheet, ink, 80)
        label(sheet, "LOAD THEATER", self._title, ink, (16, 14))
        slots = list_slots()
        self._hits = []
        if not slots:
            empty = self._font.render("No saved worlds yet.", True, ink)
            sheet.blit(empty, (16, 80))
            hint = self._small.render(
                "Save from pause, or leave a match to the menu.", True, ink
            )
            sheet.blit(hint, (16, 112))
        else:
            note = self._small.render("Esc back", True, ink)
            sheet.blit(note, (16, 46))
            y = 72
            for slot in slots[:8]:
                local = pygame.Rect(16, y, w - 32, BTN_H)
                self._hits.append((local.move(self._box.x, self._box.y), slot.id))
                button(
                    sheet,
                    local,
                    slot.label,
                    self._small,
                    ink,
                    hover=local.move(self._box.x, self._box.y).collidepoint(mouse),
                )
                y += 40
        target.overlay(sheet, (self._box.x, self._box.y))

    def form_rect(self, screen_w: int, screen_h: int) -> pygame.Rect:
        w, h = min(520, screen_w - 48), min(420, screen_h - 48)
        return pygame.Rect((screen_w - w) // 2, (screen_h - h) // 2, w, h)


class SplashStub:
    """Placeholder card. Art comes later."""

    def __init__(self, title: str, line: str) -> None:
        self.title = title
        self.line = line
        self._title, self._font, self._small = fonts()

    def draw(
        self, target, screen_w: int, screen_h: int, tod: float = 0.5
    ) -> None:
        ink = ink_at(tod)
        w, h = min(560, screen_w - 48), 160
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        sheet = panel((w, h), 210)
        frame(sheet, ink, 80)
        label(sheet, self.title, self._title, ink, (20, 24))
        sub = self._font.render(self.line, True, ink)
        sheet.blit(sub, (20, 72))
        skip = self._small.render("splash stub  ·  click or key to skip", True, ink)
        sheet.blit(skip, (20, 112))
        target.overlay(sheet, (x, y))
