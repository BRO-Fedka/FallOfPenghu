from __future__ import annotations

from dataclasses import dataclass

import pygame

from fall_of_penghu.render.dynamic.icons import CHIP, IconStore
from fall_of_penghu.shell.settings import Settings
from fall_of_penghu.shell.theme import button, fonts, frame, panel
from fall_of_penghu.world.clock import CALENDAR_DAY_S
from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER
from fall_of_penghu.world.events import ContactNotice
from fall_of_penghu.world.notices import AMMO, CONTACT, LIFT, LOSSES, SPOTTED, color_for

CHAT_W = 340
CHAT_MARGIN = 12
LINE_H = 26
TOOL_H = 26
DOCK_LINES = 5
FREE_LINES = 12
HISTORY = 80
SLIDE_S = 0.28
BTN_W = 40
MAX_ICONS = 3

_ICON_FACTION = {
    CONTACT: FACTION_CHINA,
    LOSSES: FACTION_PLAYER,
    SPOTTED: FACTION_PLAYER,
    AMMO: FACTION_PLAYER,
    LIFT: FACTION_PLAYER,
}


@dataclass
class ChatMessage:
    text: str
    object_ids: tuple[str, ...]
    x: float
    y: float
    category: str = CONTACT
    calendar_time: float = 0.0
    color: tuple[int, int, int] = (86, 196, 214)
    sat_down: bool = False
    born: float = 0.0
    icon_kinds: tuple[str, ...] = ()


class ChatLog:
    """Contact journal. Docked bottom-right, or a free window."""

    def __init__(self) -> None:
        self.messages: list[ChatMessage] = []
        self._rects: list[tuple[pygame.Rect, ChatMessage]] = []
        self._font = fonts()[2]
        self._icons = IconStore()
        self.scroll = 0
        self._drag: tuple[int, int] | None = None
        self._hits: dict[str, pygame.Rect] = {}

    def push(self, notice: ContactNotice, wall_now: float) -> None:
        self.messages.insert(
            0,
            ChatMessage(
                text=notice.text,
                object_ids=notice.object_ids,
                x=notice.x,
                y=notice.y,
                category=notice.category,
                calendar_time=notice.calendar_time,
                color=color_for(notice.category, sat_down=notice.sat_down),
                sat_down=notice.sat_down,
                born=wall_now,
                icon_kinds=notice.icon_kinds,
            ),
        )
        if len(self.messages) > HISTORY:
            self.messages = self.messages[:HISTORY]
        self.scroll = 0

    def panel_rect(self, screen_w: int, screen_h: int, bottom_inset: int = 0):
        cfg = self._cfg
        h = self._height(cfg.chat_docked if cfg is not None else True)
        if cfg is not None and not cfg.chat_docked:
            w = CHAT_W
            x = CHAT_MARGIN if cfg.chat_x is None else int(cfg.chat_x)
            y = CHAT_MARGIN if cfg.chat_y is None else int(cfg.chat_y)
            x = max(8, min(x, screen_w - w - 8))
            y = max(8, min(y, screen_h - h - 8))
            return pygame.Rect(x, y, w, h)
        return pygame.Rect(
            screen_w - CHAT_W - CHAT_MARGIN,
            screen_h - h - CHAT_MARGIN - bottom_inset,
            CHAT_W,
            h,
        )

    def hits(
        self,
        x: int,
        y: int,
        screen_w: int,
        screen_h: int,
        bottom_inset: int = 0,
    ) -> bool:
        return self.panel_rect(screen_w, screen_h, bottom_inset).collidepoint(x, y)

    def click_at(
        self,
        x: int,
        y: int,
        screen_w: int,
        screen_h: int,
        bottom_inset: int = 0,
    ) -> ChatMessage | None:
        for rect, msg in self._rects:
            if rect.collidepoint(x, y):
                return msg
        return None

    def handle_event(
        self,
        event: pygame.event.Event,
        cfg: Settings,
        screen_w: int,
        screen_h: int,
        bottom_inset: int = 0,
    ) -> str | ChatMessage | None:
        self._cfg = cfg
        panel = self.panel_rect(screen_w, screen_h, bottom_inset)
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._drag is not None:
                self._drag = None
                return "chat_prefs"
            return None
        if event.type == pygame.MOUSEMOTION and self._drag is not None:
            cfg.chat_x = event.pos[0] - self._drag[0]
            cfg.chat_y = event.pos[1] - self._drag[1]
            return "chat_drag"
        if event.type == pygame.MOUSEWHEEL and panel.collidepoint(pygame.mouse.get_pos()):
            if cfg.chat_docked:
                return "chat_wheel"
            shown = self._visible(cfg.chat_docked)
            max_scroll = max(0, len(self.messages) - shown)
            if event.y < 0:
                self.scroll = min(max_scroll, self.scroll + 1)
            elif event.y > 0:
                self.scroll = max(0, self.scroll - 1)
            return "chat_wheel"
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        if not panel.collidepoint(event.pos):
            return None
        for key, rect in self._hits.items():
            if not rect.collidepoint(event.pos):
                continue
            if key == "format":
                cfg.chat_docked = not cfg.chat_docked
                if not cfg.chat_docked:
                    cfg.chat_x = panel.x
                    cfg.chat_y = max(8, panel.y - 40)
                self.scroll = 0
                return "chat_prefs"
            if key == "settings":
                return "chat_settings"
        msg = self.click_at(*event.pos, screen_w, screen_h, bottom_inset)
        if msg is not None:
            return msg
        if not cfg.chat_docked:
            bar = pygame.Rect(panel.x, panel.y, panel.w, TOOL_H)
            if bar.collidepoint(event.pos):
                self._drag = (event.pos[0] - panel.x, event.pos[1] - panel.y)
                return "chat_drag"
        return "chat_hit"

    def draw(
        self,
        renderer,
        cfg: Settings,
        ink: tuple[int, int, int],
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        *,
        bottom_inset: int = 0,
        wall_now: float = 0.0,
    ) -> None:
        self._cfg = cfg
        box = self.panel_rect(screen_w, screen_h, bottom_inset)
        surf = panel((box.w, box.h), 180)
        frame(surf, ink, 70)
        title = self._font.render("CONTACTS", True, ink)
        surf.blit(title, (8, (TOOL_H - title.get_height()) // 2))
        self._hits = {}
        bx = box.w - 8 - BTN_W
        set_local = pygame.Rect(bx, 2, BTN_W, TOOL_H - 4)
        self._hits["settings"] = set_local.move(box.x, box.y)
        button(
            surf,
            set_local,
            "SET",
            self._font,
            ink,
            hover=self._hits["settings"].collidepoint(mouse),
        )
        bx -= BTN_W + 4
        fmt_local = pygame.Rect(bx, 2, BTN_W, TOOL_H - 4)
        self._hits["format"] = fmt_local.move(box.x, box.y)
        button(
            surf,
            fmt_local,
            "WIN" if cfg.chat_docked else "DOCK",
            self._font,
            ink,
            selected=not cfg.chat_docked,
            hover=self._hits["format"].collidepoint(mouse),
        )
        shown = self._visible(cfg.chat_docked)
        start = 0 if cfg.chat_docked else self.scroll
        lines = self.messages[start : start + shown]
        self._rects = []
        clip = pygame.Rect(0, TOOL_H, box.w, box.h - TOOL_H)
        surf.set_clip(clip)
        y = TOOL_H + 2
        for msg in lines:
            row = pygame.Rect(4, y, box.w - 8, LINE_H - 2)
            slide = _slide(msg.born, wall_now)
            ox = int(slide * (box.w + 12))
            pygame.draw.rect(surf, (*msg.color, 18), row.move(ox, 0))
            chips, extra = self._chips(msg)
            stamp = _stamp(msg.calendar_time, cfg.clock_12h)
            time_g = self._font.render(stamp, True, ink)
            text_g = self._font.render(msg.text, True, msg.color)
            ty = row.y + (row.h - time_g.get_height()) // 2
            icon_w = 0
            if extra:
                plus = self._font.render("+", True, msg.color)
                icon_w += plus.get_width() + 4
            icon_w += len(chips) * (CHIP + 2)
            surf.blit(time_g, (row.x + 4 + ox, ty))
            text_x = row.x + 8 + time_g.get_width() + ox
            text_right = row.x + row.w - 4 + ox - icon_w
            old_clip = surf.get_clip()
            surf.set_clip(pygame.Rect(text_x, row.y, max(0, text_right - text_x), row.h))
            surf.blit(text_g, (text_x, ty))
            surf.set_clip(old_clip)
            ix = row.x + row.w - 4 + ox
            if extra:
                plus = self._font.render("+", True, msg.color)
                ix -= plus.get_width()
                surf.blit(plus, (ix, ty))
                ix -= 4
            for chip in reversed(chips):
                ix -= CHIP
                surf.blit(chip, (ix, row.y + (row.h - CHIP) // 2))
                ix -= 2
            self._rects.append(
                (pygame.Rect(box.x + row.x, box.y + row.y, row.w, row.h), msg)
            )
            y += LINE_H
        surf.set_clip(None)
        renderer.overlay(surf, (box.x, box.y))

    def _chips(self, msg: ChatMessage) -> tuple[list[pygame.Surface], bool]:
        faction = _ICON_FACTION.get(msg.category)
        if faction is None or not msg.icon_kinds:
            return [], False
        unique = list(dict.fromkeys(msg.icon_kinds))
        extra = len(unique) > MAX_ICONS
        if extra:
            unique = unique[:2]
        chips: list[pygame.Surface] = []
        for kind in unique:
            chip = self._icons.get(kind, faction, False)
            if chip is not None:
                chips.append(chip)
        return chips, extra

    def _visible(self, docked: bool) -> int:
        return DOCK_LINES if docked else FREE_LINES

    def _height(self, docked: bool) -> int:
        return TOOL_H + 6 + self._visible(docked) * LINE_H

    @property
    def _cfg(self) -> Settings | None:
        return getattr(self, "_cfg_ref", None)

    @_cfg.setter
    def _cfg(self, value: Settings | None) -> None:
        self._cfg_ref = value


def _slide(born: float, now: float) -> float:
    if born <= 0.0:
        return 0.0
    age = now - born
    if age >= SLIDE_S:
        return 0.0
    t = max(0.0, min(1.0, age / SLIDE_S))
    t = t * t * (3.0 - 2.0 * t)
    return 1.0 - t


def _stamp(calendar_time: float, clock_12h: bool) -> str:
    tod = (calendar_time / CALENDAR_DAY_S) % 1.0
    secs = int(tod * 24.0 * 3600.0) % (24 * 3600)
    hours, minutes = secs // 3600, (secs % 3600) // 60
    if not clock_12h:
        return f"{hours:02d}:{minutes:02d}"
    suffix = "a" if hours < 12 else "p"
    h12 = hours % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{minutes:02d}{suffix}"
