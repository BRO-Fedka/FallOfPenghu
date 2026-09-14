from __future__ import annotations

import pygame

from fall_of_penghu.render.static.tod import palette_at

PANEL = (8, 10, 12)
RADIUS = 3


def ink_at(tod: float = 0.5) -> tuple[int, int, int]:
    return palette_at(tod)["hud"]


def fonts() -> tuple[pygame.font.Font, pygame.font.Font, pygame.font.Font]:
    return (
        pygame.font.SysFont("consolas", 22),
        pygame.font.SysFont("consolas", 16),
        pygame.font.SysFont("consolas", 14),
    )


def panel(size: tuple[int, int], alpha: int = 200) -> pygame.Surface:
    surf = pygame.Surface(size, pygame.SRCALPHA)
    surf.fill((*PANEL, alpha))
    return surf


def frame(surf: pygame.Surface, ink: tuple[int, int, int], alpha: int = 90) -> None:
    pygame.draw.rect(surf, (*ink, alpha), surf.get_rect(), 1)


def button(
    surf: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    font: pygame.font.Font,
    ink: tuple[int, int, int],
    *,
    selected: bool = False,
    disabled: bool = False,
    hover: bool = False,
) -> None:
    if disabled:
        fill_a, edge_a = 10, 40
    elif selected:
        fill_a, edge_a = 55, 200
    elif hover:
        fill_a, edge_a = 36, 140
    else:
        fill_a, edge_a = 18, 90
    pygame.draw.rect(surf, (*ink, fill_a), rect, border_radius=RADIUS)
    pygame.draw.rect(surf, (*ink, edge_a), rect, 1, border_radius=RADIUS)
    color = ink if not disabled else (ink[0] // 2, ink[1] // 2, ink[2] // 2)
    text = font.render(label, True, color)
    surf.blit(
        text,
        (
            rect.x + (rect.w - text.get_width()) // 2,
            rect.y + (rect.h - text.get_height()) // 2,
        ),
    )


def slider(
    surf: pygame.Surface,
    rect: pygame.Rect,
    value: float,
    ink: tuple[int, int, int],
    *,
    hover: bool = False,
) -> None:
    value = min(1.0, max(0.0, value))
    mid = rect.y + rect.h // 2
    track = pygame.Rect(rect.x, mid - 2, rect.w, 4)
    fill_w = max(0, int(round(rect.w * value)))
    pygame.draw.rect(surf, (*ink, 36), track, border_radius=2)
    if fill_w:
        pygame.draw.rect(
            surf, (*ink, 110 if hover else 80), (rect.x, mid - 2, fill_w, 4), border_radius=2
        )
    kx = rect.x + fill_w
    knob = pygame.Rect(kx - 6, mid - 8, 12, 16)
    pygame.draw.rect(surf, (*ink, 55 if hover else 40), knob, border_radius=RADIUS)
    pygame.draw.rect(surf, (*ink, 200 if hover else 140), knob, 1, border_radius=RADIUS)


def label(
    surf: pygame.Surface,
    text: str,
    font: pygame.font.Font,
    ink: tuple[int, int, int],
    pos: tuple[int, int],
) -> pygame.Surface:
    glyph = font.render(text, True, ink)
    surf.blit(glyph, pos)
    return glyph
