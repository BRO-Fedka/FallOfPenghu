from __future__ import annotations

import pygame

from fall_of_penghu.render.dynamic.icons import IconStore
from fall_of_penghu.world.entities.game_object import FACTION_PLAYER
from fall_of_penghu.world.entities.kinds import kind_label
from fall_of_penghu.world.perception import DetectionCatalog

PANEL_H = 40
PAD = 6
TITLE_H = 24
ROW_H = 22
CHECK = 14
TWIST = 12
ICON = 16
BRANCHES = ("air", "land", "sea", "static")
BRANCH_LABEL = {"air": "Air", "land": "Land", "sea": "Sea", "static": "Static"}


class DisplayPalette:
    """Movable tree of kinds shown on the map."""

    def __init__(self) -> None:
        self.x = 224
        self.y = PANEL_H + 12
        self.enabled: set[str] = set()
        self._kinds: dict[str, list[str]] = {name: [] for name in BRANCHES}
        self._open: dict[str, bool] = {name: False for name in BRANCHES}
        self._icons = IconStore()
        self._font = pygame.font.SysFont("consolas", 13)
        self._panel = pygame.Rect(0, 0, 1, 1)
        self._title = pygame.Rect(0, 0, 1, 1)
        self._rows: list[tuple[pygame.Rect, str, str | None]] = []
        self._drag = False
        self._drag_off = (0, 0)
        self._width = 220

    def refresh(self, catalog: DetectionCatalog) -> None:
        grouped: dict[str, list[str]] = {name: [] for name in BRANCHES}
        for kind in catalog.target_kinds():
            grouped.setdefault(catalog.target_branch(kind), []).append(kind)
        for branch in BRANCHES:
            grouped[branch] = sorted(grouped.get(branch, ()))
        self._kinds = grouped
        self.enabled = {kind for kinds in grouped.values() for kind in kinds}

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
            for rect, action, key in self._rows:
                if not rect.collidepoint(event.pos):
                    continue
                if action == "twist" and key is not None:
                    self._open[key] = not self._open.get(key, False)
                    return True
                if action == "branch" and key is not None:
                    self._toggle_branch(key)
                    return True
                if action == "kind" and key is not None:
                    if key in self.enabled:
                        self.enabled.discard(key)
                    else:
                        self.enabled.add(key)
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
        title = self._font.render("UNITS", True, ink)
        surf.blit(title, (PAD, (TITLE_H - title.get_height()) // 2))
        mx, my = mouse
        for rect, action, key in self._rows:
            local = pygame.Rect(rect.x - self.x, rect.y - self.y, rect.w, rect.h)
            hover = local.collidepoint(mx - self.x, my - self.y)
            if hover:
                pygame.draw.rect(surf, (*ink, 28), local)
            if action == "twist" and key is not None:
                self._draw_twist(surf, local, ink, self._open.get(key, False))
            elif action == "branch" and key is not None:
                self._draw_check(surf, local, ink, self._branch_state(key))
                label = self._font.render(BRANCH_LABEL[key], True, ink)
                surf.blit(
                    label,
                    (local.right + 6, local.y + (ROW_H - label.get_height()) // 2),
                )
            elif action == "kind" and key is not None:
                state = "on" if key in self.enabled else "off"
                self._draw_check(surf, local, ink, state)
                icon = self._icons.get(key, FACTION_PLAYER, False)
                ix = local.right + 6
                if icon is not None:
                    chip = pygame.transform.smoothscale(icon, (ICON, ICON))
                    surf.blit(chip, (ix, local.y + (ROW_H - ICON) // 2))
                    ix += ICON + 4
                label = self._font.render(kind_label(key), True, ink)
                surf.blit(
                    label,
                    (ix, local.y + (ROW_H - label.get_height()) // 2),
                )
        renderer.overlay(surf, (self._panel.x, self._panel.y))

    def _toggle_branch(self, branch: str) -> None:
        kinds = self._kinds.get(branch) or []
        if not kinds:
            return
        if self._branch_state(branch) == "on":
            self.enabled.difference_update(kinds)
        else:
            self.enabled.update(kinds)

    def _branch_state(self, branch: str) -> str:
        kinds = self._kinds.get(branch) or []
        if not kinds:
            return "off"
        flags = [kind in self.enabled for kind in kinds]
        if all(flags):
            return "on"
        if not any(flags):
            return "off"
        return "mix"

    def _layout(self, screen_w: int, screen_h: int) -> None:
        rows = 0
        shown: list[tuple[str, list[str]]] = []
        for branch in BRANCHES:
            kinds = self._kinds.get(branch) or []
            if not kinds:
                continue
            shown.append((branch, kinds))
            rows += 1
            if self._open.get(branch):
                rows += len(kinds)
        height = TITLE_H + PAD + rows * ROW_H + PAD
        self._panel = pygame.Rect(self.x, self.y, self._width, height)
        self._clamp(screen_w, screen_h)
        self._panel = pygame.Rect(self.x, self.y, self._width, height)
        self._title = pygame.Rect(self.x, self.y, self._width, TITLE_H)
        self._rows = []
        y = self.y + TITLE_H + PAD
        for branch, kinds in shown:
            twist = pygame.Rect(self.x + PAD, y + (ROW_H - TWIST) // 2, TWIST, TWIST)
            check = pygame.Rect(
                twist.right + 4, y + (ROW_H - CHECK) // 2, CHECK, CHECK
            )
            self._rows.append((twist, "twist", branch))
            self._rows.append((check, "branch", branch))
            y += ROW_H
            if not self._open.get(branch):
                continue
            for kind in kinds:
                box = pygame.Rect(
                    self.x + PAD + TWIST + 16,
                    y + (ROW_H - CHECK) // 2,
                    CHECK,
                    CHECK,
                )
                self._rows.append((box, "kind", kind))
                y += ROW_H

    def _clamp(self, screen_w: int, screen_h: int) -> None:
        self.x = min(max(0, self.x), max(0, screen_w - self._panel.w))
        self.y = min(max(PANEL_H, self.y), max(PANEL_H, screen_h - self._panel.h))

    @staticmethod
    def _draw_twist(surf: pygame.Surface, local: pygame.Rect, ink, open_: bool) -> None:
        cx, cy = local.center
        if open_:
            pts = [(cx - 4, cy - 2), (cx + 4, cy - 2), (cx, cy + 4)]
        else:
            pts = [(cx - 2, cy - 4), (cx + 4, cy), (cx - 2, cy + 4)]
        pygame.draw.polygon(surf, (*ink, 200), pts)

    @staticmethod
    def _draw_check(surf: pygame.Surface, local: pygame.Rect, ink, state: str) -> None:
        pygame.draw.rect(surf, (*ink, 200), local, 1)
        inner = local.inflate(-4, -4)
        if state == "on":
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
        elif state == "mix":
            pygame.draw.rect(surf, (*ink, 200), inner.inflate(0, -inner.h // 3))
