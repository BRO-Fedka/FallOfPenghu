"""Standalone pygame board: live palette vs a 30-second day."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pygame

from Test.tod import (
    DAY_SECONDS,
    GROUPS,
    PALETTE_KEYS,
    clock_label,
    palette_at,
    phase_label,
    tod_from_elapsed,
)

WINDOW = (1440, 900)
STRIP_SAMPLES = 256
SCRUB_PER_SEC = 0.35


def _font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in ("consolas", "cascadia mono", "segoe ui"):
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.SysFont("consolas", size, bold=bold)


def _luma(rgb: tuple[int, int, int]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _ink(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return (18, 18, 20) if _luma(rgb) > 140 else (240, 238, 230)


def _hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _build_strips() -> dict[str, pygame.Surface]:
    surfaces: dict[str, pygame.Surface] = {}
    for key in PALETTE_KEYS:
        surf = pygame.Surface((STRIP_SAMPLES, 1))
        for x in range(STRIP_SAMPLES):
            pal = palette_at(x / max(STRIP_SAMPLES - 1, 1))
            surf.set_at((x, 0), pal[key])
        surfaces[key] = surf
    return surfaces


def run() -> None:
    pygame.init()
    pygame.display.set_caption("Fall of Penghu — palette / time of day")
    screen = pygame.display.set_mode(WINDOW, pygame.RESIZABLE)
    clock = pygame.time.Clock()
    title_font = _font(22, bold=True)
    body_font = _font(16)
    small_font = _font(13)
    strips = _build_strips()

    elapsed = 0.0
    paused = False
    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        keys = pygame.key.get_pressed()
        if not paused:
            elapsed += dt
        if keys[pygame.K_LEFT]:
            elapsed -= SCRUB_PER_SEC * DAY_SECONDS * dt
        if keys[pygame.K_RIGHT]:
            elapsed += SCRUB_PER_SEC * DAY_SECONDS * dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key == pygame.K_HOME:
                    elapsed = 0.0

        tod = tod_from_elapsed(elapsed)
        pal = palette_at(tod)
        page = tuple(max(0, int(c * 0.42)) for c in pal["sea_deep"])
        ink = _ink(page)
        muted = tuple(int(page[i] * 0.55 + ink[i] * 0.45) for i in range(3))
        screen.fill(page)

        w, h = screen.get_size()
        header_h = 86
        strip_row_h = 16
        strip_block_h = 28 + len(PALETTE_KEYS) * strip_row_h
        pad = 20

        # Header
        pygame.draw.rect(screen, pal["sea"], (0, 0, w, header_h))
        header_ink = _ink(pal["sea"])
        title = title_font.render(
            f"{clock_label(tod)}    {phase_label(tod)}",
            True,
            header_ink,
        )
        meta = body_font.render(
            f"сутки {DAY_SECONDS:.0f} с    "
            f"{'пауза' if paused else 'идёт'}    "
            f"tod {tod:.3f}    "
            f"пробел пауза   ← → время   Home полночь   Esc выход",
            True,
            header_ink,
        )
        screen.blit(title, (pad, 14))
        screen.blit(meta, (pad, 48))

        bar_x, bar_y, bar_w, bar_h = pad, header_h - 10, w - pad * 2, 6
        pygame.draw.rect(screen, pal["sea_shallow"], (bar_x, bar_y, bar_w, bar_h), border_radius=3)
        pygame.draw.rect(
            screen,
            pal["hud"],
            (bar_x, bar_y, max(2, int(bar_w * tod)), bar_h),
            border_radius=3,
        )

        # Swatches
        swatch_top = header_h + 16
        swatch_bottom = h - strip_block_h - pad
        group_gap = 18
        inner_h = max(120, swatch_bottom - swatch_top)
        group_h = (inner_h - group_gap * (len(GROUPS) - 1)) / len(GROUPS)

        hover_key = None
        mouse = pygame.mouse.get_pos()

        y = swatch_top
        for group_name, keys_in_group in GROUPS:
            label = small_font.render(group_name, True, muted)
            screen.blit(label, (pad, y))
            n = len(keys_in_group)
            cell_w = (w - pad * 2) / n
            cell_h = group_h - 18
            for i, key in enumerate(keys_in_group):
                rx = pad + i * cell_w + 4
                ry = y + 18
                rw = cell_w - 8
                rh = cell_h
                rect = pygame.Rect(rx, ry, rw, rh)
                color = pal[key]
                pygame.draw.rect(screen, color, rect, border_radius=8)
                pygame.draw.rect(screen, tuple(min(255, c + 28) for c in color), rect, 1, border_radius=8)
                on_swatch = _ink(color)
                name = body_font.render(key, True, on_swatch)
                rgb = small_font.render(
                    f"{color[0]:3d} {color[1]:3d} {color[2]:3d}   {_hex(color)}",
                    True,
                    on_swatch,
                )
                screen.blit(name, (rx + 10, ry + 8))
                screen.blit(rgb, (rx + 10, ry + 30))
                if rect.collidepoint(mouse):
                    hover_key = key
            y += group_h + group_gap

        # 24h strips
        strip_top = h - strip_block_h
        pygame.draw.rect(screen, pal["sea"], (0, strip_top - 8, w, strip_block_h + 8))
        strip_ink = _ink(pal["sea"])
        caption = small_font.render("24 часа  (полоска = один материал, линия = сейчас)", True, strip_ink)
        screen.blit(caption, (pad, strip_top - 4))
        label_w = 118
        strip_x = pad + label_w
        strip_w = w - pad - strip_x
        for i, key in enumerate(PALETTE_KEYS):
            row_y = strip_top + 18 + i * strip_row_h
            name = small_font.render(key, True, strip_ink)
            screen.blit(name, (pad, row_y))
            dest = pygame.Rect(strip_x, row_y, strip_w, strip_row_h - 3)
            scaled = pygame.transform.smoothscale(strips[key], (dest.w, dest.h))
            screen.blit(scaled, dest)
        play_x = strip_x + int(strip_w * tod)
        pygame.draw.line(
            screen,
            pal["hud"],
            (play_x, strip_top + 16),
            (play_x, h - 10),
            2,
        )

        if hover_key is not None:
            rgb = pal[hover_key]
            tip = body_font.render(f"{hover_key}  {rgb}  {_hex(rgb)}", True, ink)
            box = tip.get_rect()
            box.topleft = (mouse[0] + 16, mouse[1] + 16)
            box.inflate_ip(16, 10)
            if box.right > w - 8:
                box.right = w - 8
            if box.bottom > h - 8:
                box.bottom = h - 8
            pygame.draw.rect(screen, pal["hud"], box, border_radius=6)
            screen.blit(tip, (box.x + 8, box.y + 5))

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    run()
