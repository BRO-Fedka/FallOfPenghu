from __future__ import annotations

import pygame

from fall_of_penghu.range import RANGE_DEFAULT_ON, RANGE_RINGS
from fall_of_penghu.shell.i18n import t
from fall_of_penghu.shell.theme import ui_font
from fall_of_penghu.world.entities.kinds import kind_label

PANEL_H = 40
PAD = 6
TITLE_H = 24
HINT_H = 16
ROW_H = 22
CHECK = 14


class RangePalette:
    """Movable checkboxes for engagement range rings."""

    def __init__(self) -> None:
        self.x = 12
        self.y = PANEL_H + 12
        self.enabled: set[str] = set(RANGE_DEFAULT_ON)
        self._saved: set[str] = set(RANGE_DEFAULT_ON)
        self._font = ui_font(13)
        self._panel = pygame.Rect(0, 0, 1, 1)
        self._title = pygame.Rect(0, 0, 1, 1)
        self._rows: list[tuple[pygame.Rect, str]] = []
        self._drag = False
        self._drag_off = (0, 0)
        self._width = 200

    def hits(self, x: int, y: int) -> bool:
        return bool(self._panel.collidepoint(x, y))

    def toggle(self) -> None:
        if self.enabled:
            self._saved = set(self.enabled)
            self.enabled.clear()
        else:
            self.enabled = set(self._saved)

    def handle_event(
        self, event: pygame.event.Event, screen_w: int, screen_h: int
    ) -> bool:
        self._layout(screen_w, screen_h)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._title.collidepoint(event.pos):
                self._drag = True
                self._drag_off = (event.pos[0] - self.x, event.pos[1] - self.y)
                return True
            for rect, kind in self._rows:
                if rect.collidepoint(event.pos):
                    if kind in self.enabled:
                        self.enabled.discard(kind)
                    else:
                        self.enabled.add(kind)
                    return True
            return self._panel.collidepoint(*event.pos)
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._drag:
                self._drag = False
                return True
            return False
        if event.type == pygame.MOUSEMOTION and self._drag:
            self.x = event.pos[0] - self._drag_off[0]
            self.y = event.pos[1] - self._drag_off[1]
            self._clamp(screen_w, screen_h)
            return True
        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()[:2]
            return self._panel.collidepoint(mx, my)
        return False

    def blit(
        self,
        renderer,
        mouse: tuple[int, int],
        ink: tuple[int, int, int],
        screen_w: int,
        screen_h: int,
    ) -> None:
        self._layout(screen_w, screen_h)
        surf = pygame.Surface((self._panel.w, self._panel.h), pygame.SRCALPHA)
        surf.fill((8, 10, 12, 200))
        pygame.draw.rect(surf, (*ink, 80), surf.get_rect(), 1)
        title = self._font.render(t("panel.range"), True, ink)
        surf.blit(title, (PAD, (TITLE_H - title.get_height()) // 2))
        key = self._font.render("G", True, ink)
        surf.blit(
            key,
            (self._width - PAD - key.get_width(), (TITLE_H - key.get_height()) // 2),
        )
        hint = self._font.render(t("panel.range_hint"), True, ink)
        hint.set_alpha(170)
        surf.blit(hint, (PAD, TITLE_H + (HINT_H - hint.get_height()) // 2))
        for rect, kind in self._rows:
            local = pygame.Rect(rect.x - self.x, rect.y - self.y, CHECK, CHECK)
            on = kind in self.enabled
            color = next(item[1] for item in RANGE_RINGS if item[0] == kind)
            label = kind_label(kind)
            pygame.draw.rect(surf, (*color[:3], 200), local, 1)
            if on:
                inner = local.inflate(-4, -4)
                pygame.draw.line(
                    surf,
                    (*color[:3], 230),
                    (inner.x, inner.centery),
                    (inner.centerx - 1, inner.bottom - 1),
                    2,
                )
                pygame.draw.line(
                    surf,
                    (*color[:3], 230),
                    (inner.centerx - 1, inner.bottom - 1),
                    (inner.right - 1, inner.y),
                    2,
                )
            text = self._font.render(label, True, color[:3])
            surf.blit(
                text,
                (local.right + 6, local.y + (CHECK - text.get_height()) // 2),
            )
        renderer.overlay(surf, (self._panel.x, self._panel.y))

    def _layout(self, screen_w: int, screen_h: int) -> None:
        height = TITLE_H + HINT_H + PAD + len(RANGE_RINGS) * ROW_H + PAD
        self._panel = pygame.Rect(self.x, self.y, self._width, height)
        self._clamp(screen_w, screen_h)
        self._panel = pygame.Rect(self.x, self.y, self._width, height)
        self._title = pygame.Rect(self.x, self.y, self._width, TITLE_H)
        self._rows = []
        y = self.y + TITLE_H + HINT_H + PAD
        for kind, _color, _label in RANGE_RINGS:
            box = pygame.Rect(
                self.x + PAD, y + (ROW_H - CHECK) // 2, self._width - PAD * 2, ROW_H
            )
            self._rows.append((box, kind))
            y += ROW_H

    def _clamp(self, screen_w: int, screen_h: int) -> None:
        self.x = min(max(0, self.x), max(0, screen_w - self._panel.w))
        self.y = min(max(PANEL_H, self.y), max(PANEL_H, screen_h - self._panel.h))
