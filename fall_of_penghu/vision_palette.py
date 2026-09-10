from __future__ import annotations

import pygame

from fall_of_penghu.vision import VISION_DEFAULT_ON, VISION_RINGS

PANEL_H = 40
PAD = 6
TITLE_H = 24
ROW_H = 22
CHECK = 14


class VisionPalette:
    """Movable checkboxes for visual range rings."""

    def __init__(self) -> None:
        self.x = 12
        self.y = PANEL_H + 220
        self.enabled: set[str] = set(VISION_DEFAULT_ON)
        self._font = pygame.font.SysFont("consolas", 13)
        self._panel = pygame.Rect(0, 0, 1, 1)
        self._title = pygame.Rect(0, 0, 1, 1)
        self._rows: list[tuple[pygame.Rect, str]] = []
        self._drag = False
        self._drag_off = (0, 0)
        self._width = 200

    def hits(self, x: int, y: int) -> bool:
        return bool(self._panel.collidepoint(x, y))

    def handle_event(
        self, event: pygame.event.Event, screen_w: int, screen_h: int
    ) -> bool:
        self._layout(screen_w, screen_h)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._title.collidepoint(event.pos):
                self._drag = True
                self._drag_off = (event.pos[0] - self.x, event.pos[1] - self.y)
                return True
            for rect, ring_id in self._rows:
                if rect.collidepoint(event.pos):
                    if ring_id in self.enabled:
                        self.enabled.discard(ring_id)
                    else:
                        self.enabled.add(ring_id)
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
        title = self._font.render("VISION", True, ink)
        surf.blit(title, (PAD, (TITLE_H - title.get_height()) // 2))
        for rect, ring_id in self._rows:
            local = pygame.Rect(rect.x - self.x, rect.y - self.y, CHECK, CHECK)
            on = ring_id in self.enabled
            pygame.draw.rect(surf, (*ink, 200), local, 1)
            if on:
                inner = local.inflate(-4, -4)
                pygame.draw.line(
                    surf,
                    (*ink, 230),
                    (inner.x, inner.centery),
                    (inner.centerx - 1, inner.bottom - 1),
                    2,
                )
                pygame.draw.line(
                    surf,
                    (*ink, 230),
                    (inner.centerx - 1, inner.bottom - 1),
                    (inner.right - 1, inner.y),
                    2,
                )
            label = next(item[4] for item in VISION_RINGS if item[0] == ring_id)
            text = self._font.render(label, True, ink)
            surf.blit(
                text,
                (local.right + 6, local.y + (CHECK - text.get_height()) // 2),
            )
        renderer.overlay(surf, (self._panel.x, self._panel.y))

    def _layout(self, screen_w: int, screen_h: int) -> None:
        height = TITLE_H + PAD + len(VISION_RINGS) * ROW_H + PAD
        self._panel = pygame.Rect(self.x, self.y, self._width, height)
        self._clamp(screen_w, screen_h)
        self._panel = pygame.Rect(self.x, self.y, self._width, height)
        self._title = pygame.Rect(self.x, self.y, self._width, TITLE_H)
        self._rows = []
        y = self.y + TITLE_H + PAD
        for ring_id, _ch, _cover, _color, _label in VISION_RINGS:
            box = pygame.Rect(
                self.x + PAD, y + (ROW_H - CHECK) // 2, self._width - PAD * 2, ROW_H
            )
            self._rows.append((box, ring_id))
            y += ROW_H

    def _clamp(self, screen_w: int, screen_h: int) -> None:
        self.x = min(max(0, self.x), max(0, screen_w - self._panel.w))
        self.y = min(max(PANEL_H, self.y), max(PANEL_H, screen_h - self._panel.h))
