from __future__ import annotations

import pygame

from fall_of_penghu.render.dynamic.icons import IconStore, listed_kinds
from fall_of_penghu.world.entities.kinds import kind_label
from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER
from fall_of_penghu.world.perception import DetectionCatalog

COLS = 4
CELL = 32
PAD = 6
TITLE_H = 24
FACTION_W = 22
PANEL_H = 40
PLACE_FACTIONS = (FACTION_PLAYER, FACTION_CHINA)


class DebugPalette:
    """Movable debug tray of placeable kinds. Does not mutate the world."""

    def __init__(self) -> None:
        self.x = 12
        self.y = PANEL_H + 12
        self.kind: str | None = None
        self.faction = FACTION_PLAYER
        self._icons = IconStore()
        self._kinds: list[str] = []
        self._cells: list[tuple[pygame.Rect, str]] = []
        self._faction_btns: list[tuple[pygame.Rect, str]] = []
        self._title = pygame.Rect(0, 0, 1, 1)
        self._panel = pygame.Rect(0, 0, 1, 1)
        self._drag = False
        self._drag_off = (0, 0)
        self._font = pygame.font.SysFont("consolas", 13)

    def refresh(self, catalog: DetectionCatalog | None = None) -> None:
        extra = catalog.listed_kinds() if catalog is not None else ()
        self._kinds = listed_kinds(*extra)
        self._layout()

    def hits(self, x: int, y: int) -> bool:
        return bool(self._panel.collidepoint(x, y))

    def handle_event(
        self, event: pygame.event.Event, screen_w: int, screen_h: int
    ) -> bool:
        self._layout()
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, faction in self._faction_btns:
                if rect.collidepoint(event.pos):
                    self.faction = faction
                    return True
            if self._title.collidepoint(event.pos):
                self._drag = True
                self._drag_off = (event.pos[0] - self.x, event.pos[1] - self.y)
                return True
            for rect, kind in self._cells:
                if rect.collidepoint(event.pos):
                    self.kind = None if self.kind == kind else kind
                    return True
            return self.hits(*event.pos)
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._drag:
                self._drag = False
                return True
            return False
        if event.type == pygame.MOUSEMOTION and self._drag:
            self.x = event.pos[0] - self._drag_off[0]
            self.y = event.pos[1] - self._drag_off[1]
            self._clamp(screen_w, screen_h)
            self._layout()
            return True
        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()[:2]
            return self.hits(mx, my)
        return False

    def blit(
        self,
        renderer,
        mouse: tuple[int, int],
        ink: tuple[int, int, int],
        screen_w: int,
        screen_h: int,
    ) -> None:
        self._layout()
        self._clamp(screen_w, screen_h)
        self._layout()
        surf = pygame.Surface((self._panel.w, self._panel.h), pygame.SRCALPHA)
        surf.fill((8, 10, 12, 200))
        pygame.draw.rect(surf, (*ink, 80), surf.get_rect(), 1)
        title = self._font.render("PLACE", True, ink)
        surf.blit(title, (PAD, (TITLE_H - title.get_height()) // 2))
        mx, my = mouse
        tip: str | None = None
        for rect, faction in self._faction_btns:
            local = pygame.Rect(rect.x - self.x, rect.y - self.y, rect.w, rect.h)
            selected = faction == self.faction
            fill = (ink[0], ink[1], ink[2], 70 if selected else 22)
            pygame.draw.rect(surf, fill, local, border_radius=3)
            pygame.draw.rect(
                surf, (*ink, 220 if selected else 90), local, 1, border_radius=3
            )
            label = self._font.render(faction, True, ink)
            surf.blit(
                label,
                (
                    local.x + (local.w - label.get_width()) // 2,
                    local.y + (local.h - label.get_height()) // 2,
                ),
            )
            if local.collidepoint(mx - self.x, my - self.y):
                tip = "Player" if faction == FACTION_PLAYER else "China"
        for rect, kind in self._cells:
            local = pygame.Rect(rect.x - self.x, rect.y - self.y, rect.w, rect.h)
            selected = kind == self.kind
            fill = (ink[0], ink[1], ink[2], 60 if selected else 22)
            pygame.draw.rect(surf, fill, local, border_radius=3)
            pygame.draw.rect(
                surf, (*ink, 210 if selected else 90), local, 1, border_radius=3
            )
            icon = self._icons.get(kind, self.faction, False)
            if icon is not None:
                dest = icon.get_rect(center=local.center)
                surf.blit(icon, dest)
            if local.collidepoint(mx - self.x, my - self.y):
                tip = kind_label(kind)
        renderer.overlay(surf, (self._panel.x, self._panel.y))
        if tip:
            text = self._font.render(tip, True, ink)
            pad = 5
            box = pygame.Surface(
                (text.get_width() + pad * 2, text.get_height() + pad * 2),
                pygame.SRCALPHA,
            )
            box.fill((8, 10, 12, 220))
            box.blit(text, (pad, pad))
            tx = min(max(8, mx + 14), screen_w - box.get_width() - 8)
            ty = min(max(PANEL_H + 8, my + 16), screen_h - box.get_height() - 8)
            renderer.overlay(box, (tx, ty))

    def _layout(self) -> None:
        n = max(len(self._kinds), 1)
        rows = (n + COLS - 1) // COLS
        width = PAD * 2 + COLS * CELL + (COLS - 1) * PAD
        height = TITLE_H + PAD + rows * CELL + (rows - 1) * PAD + PAD
        self._panel = pygame.Rect(self.x, self.y, width, height)
        self._title = pygame.Rect(self.x, self.y, width, TITLE_H)
        self._faction_btns = []
        fx = self.x + width - PAD - FACTION_W
        for faction in reversed(PLACE_FACTIONS):
            self._faction_btns.append(
                (pygame.Rect(fx, self.y + (TITLE_H - 18) // 2, FACTION_W, 18), faction)
            )
            fx -= FACTION_W + 4
        title_cut = FACTION_W * 2 + PAD * 2 + 8
        self._title = pygame.Rect(self.x, self.y, max(40, width - title_cut), TITLE_H)
        self._cells = []
        for i, kind in enumerate(self._kinds):
            col = i % COLS
            row = i // COLS
            rx = self.x + PAD + col * (CELL + PAD)
            ry = self.y + TITLE_H + PAD + row * (CELL + PAD)
            self._cells.append((pygame.Rect(rx, ry, CELL, CELL), kind))

    def _clamp(self, screen_w: int, screen_h: int) -> None:
        self.x = min(max(0, self.x), max(0, screen_w - self._panel.w))
        self.y = min(max(PANEL_H, self.y), max(PANEL_H, screen_h - self._panel.h))
