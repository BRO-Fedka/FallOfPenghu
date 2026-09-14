from __future__ import annotations

import json
from pathlib import Path

import pygame

from fall_of_penghu.shell.richtext import InlineIcons, blit_rich
from fall_of_penghu.shell.theme import button, fonts, frame, ink_at, label, panel

ROOT = Path(__file__).resolve().parents[2]
HELP_JSON = Path(__file__).resolve().parents[1] / "data" / "help.json"
SHOT_DIR = ROOT / "assets" / "help"
TAB_W = 120
SHOT_H = 168
SHOT_GAP = 10


class HelpBook:
    """Tabbed field manual. Screenshots optional; missing files show a slot."""

    def __init__(self) -> None:
        self.tabs = _load_tabs()
        self.index = 0
        self._tab_rects: list[tuple[pygame.Rect, int]] = []
        self._scroll = 0
        self._title, self._font, self._small = fonts()
        self._shots: dict[str, pygame.Surface] = {}
        self._icons = InlineIcons()

    def open(self, tab_id: str | None = None) -> None:
        if tab_id:
            for i, tab in enumerate(self.tabs):
                if tab["id"] == tab_id:
                    self.index = i
                    break
        self._scroll = 0

    def handle_event(self, event: pygame.event.Event, screen_w: int, screen_h: int) -> bool:
        box = _frame(screen_w, screen_h)
        if event.type == pygame.MOUSEWHEEL:
            if box.collidepoint(pygame.mouse.get_pos()):
                self._scroll = max(0, self._scroll - event.y * 36)
                return True
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, idx in self._tab_rects:
                if rect.collidepoint(event.pos):
                    self.index = idx
                    self._scroll = 0
                    return True
            return box.collidepoint(event.pos)
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
        box = _frame(screen_w, screen_h)
        surf = panel((box.w, box.h), 220)
        frame(surf, ink, 80)
        label(surf, "FIELD MANUAL", self._title, ink, (16, 12))
        hint = self._small.render("Tabs  ·  Esc back  ·  F1", True, ink)
        surf.blit(hint, (box.w - hint.get_width() - 16, 18))

        self._tab_rects = []
        y = 52
        for i, tab in enumerate(self.tabs):
            rect = pygame.Rect(12, y, TAB_W, 28)
            self._tab_rects.append((rect.move(box.x, box.y), i))
            button(
                surf,
                rect,
                str(tab["title"]),
                self._small,
                ink,
                selected=i == self.index,
                hover=rect.move(box.x, box.y).collidepoint(mouse),
            )
            y += 34

        body = pygame.Rect(TAB_W + 28, 52, box.w - TAB_W - 44, box.h - 68)
        pygame.draw.rect(surf, (*ink, 16), body)
        pygame.draw.rect(surf, (*ink, 50), body, 1)
        clip = surf.subsurface(body)
        self._draw_tab(clip, self.tabs[self.index], ink)
        target.overlay(surf, (box.x, box.y))

    def form_rect(self, screen_w: int, screen_h: int) -> pygame.Rect:
        return _frame(screen_w, screen_h)

    def _draw_tab(
        self, clip: pygame.Surface, tab: dict, ink: tuple[int, int, int]
    ) -> None:
        y = 10 - self._scroll
        pad = 12
        max_w = max(40, clip.get_width() - pad * 2)
        y += blit_rich(
            clip,
            str(tab.get("lead") or ""),
            self._font,
            ink,
            pad,
            y,
            max_w,
            self._icons,
        )
        y += 12
        shots = list(tab.get("shots") or [])
        col_w = (clip.get_width() - 36) // 2
        for i in range(0, len(shots), 2):
            row_h = 0
            for col, shot in enumerate(shots[i : i + 2]):
                x = 12 + col * (col_w + 12)
                h = self._blit_shot(clip, shot, ink, x, y, col_w)
                row_h = max(row_h, h)
            y += row_h + SHOT_GAP
        for note in tab.get("notes") or []:
            h = blit_rich(
                clip,
                f"·  {note}",
                self._small,
                ink,
                pad,
                y,
                max_w,
                self._icons,
            )
            y += h + 4
        overflow = max(0, y + self._scroll - clip.get_height() + 8)
        if overflow < self._scroll:
            self._scroll = overflow

    def _blit_shot(
        self,
        clip: pygame.Surface,
        shot: dict,
        ink: tuple[int, int, int],
        x: int,
        y: int,
        width: int,
    ) -> int:
        name = str(shot.get("file") or "")
        pic = self._image(name, width, SHOT_H, ink)
        clip.blit(pic, (x, y))
        cap_h = blit_rich(
            clip,
            str(shot.get("caption") or ""),
            self._small,
            ink,
            x,
            y + SHOT_H + 4,
            width,
            self._icons,
        )
        return SHOT_H + 8 + cap_h

    def _image(
        self, name: str, w: int, h: int, ink: tuple[int, int, int]
    ) -> pygame.Surface:
        key = f"{name}:{w}x{h}"
        cached = self._shots.get(key)
        if cached is not None:
            return cached
        raw = None
        path = SHOT_DIR / name
        if name and path.is_file():
            try:
                loaded = pygame.image.load(str(path))
                src = pygame.Surface(loaded.get_size(), pygame.SRCALPHA, 32)
                src.blit(loaded, (0, 0))
                raw = pygame.transform.smoothscale(src, (w, h))
            except (pygame.error, ValueError):
                raw = None
        if raw is None:
            raw = panel((w, h), 160)
            pygame.draw.rect(raw, (*ink, 70), raw.get_rect(), 1)
            mark = self._small.render(name or "shot", True, ink)
            raw.blit(
                mark,
                ((w - mark.get_width()) // 2, (h - mark.get_height()) // 2),
            )
        self._shots[key] = raw
        return raw


def _frame(screen_w: int, screen_h: int) -> pygame.Rect:
    w = min(1040, screen_w - 48)
    h = min(620, screen_h - 48)
    return pygame.Rect((screen_w - w) // 2, (screen_h - h) // 2, w, h)


def _load_tabs() -> list[dict]:
    try:
        data = json.loads(HELP_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [
            {
                "id": "map",
                "title": "MAP",
                "lead": "Help file missing.",
                "shots": [],
                "notes": [],
            }
        ]
    tabs = data.get("tabs") or []
    return [tab for tab in tabs if isinstance(tab, dict)]
