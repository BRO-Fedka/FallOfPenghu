from __future__ import annotations

import pygame

from fall_of_penghu.shell.i18n import t
from fall_of_penghu.shell.theme import ui_font

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

BOOT_SLIDES = (
    ("Built with", "python"),
    ("Powered by", "pygame"),
    ("Made by", "BRO_Fedka"),
    ("", "FALL OF PENGHU"),
)

FADE_IN = 0.4
HOLD_IMAGE = 4.0
HOLD_TEXT = 2.0
FADE_OUT = 0.4
INITIAL_DELAY = 0.5
SKIP_SPEED = 2.0
TYPE_CPS = 28.0

def briefing_lines(*, ago: str | None = None) -> list[str]:
    war = t("brief.war")
    first = t("brief.ago_wrap", ago=ago, war=war) if ago else war
    return [first, t("brief.command"), t("brief.fall"), t("brief.begin")]


class ImageIntro:
    """Boot credits. Same fade/hold/skip as the Demo intro; no typewriter."""

    def __init__(self) -> None:
        self.slides = BOOT_SLIDES
        self.current = 0
        self.timer = -INITIAL_DELAY
        self.speed = 1.0
        self.finished = False
        self._small = pygame.font.SysFont("consolas", 22)
        self._large = pygame.font.SysFont("consolas", 42)
        self._title = pygame.font.SysFont("consolas", 56)
        self._bg: pygame.Surface | None = None

    def reset(self) -> None:
        self.current = 0
        self.timer = -INITIAL_DELAY
        self.speed = 1.0
        self.finished = False

    def skip(self) -> None:
        if self.finished:
            return
        fade_in_end = FADE_IN
        hold_end = fade_in_end + HOLD_IMAGE
        if self.timer < 0:
            self.timer = 0.0
            return
        if self.timer < hold_end:
            self.timer = hold_end
        self.speed = SKIP_SPEED

    def update(self, dt: float) -> None:
        if self.finished:
            return
        self.timer += dt * self.speed
        fade_in_end = FADE_IN
        hold_end = fade_in_end + HOLD_IMAGE
        fade_out_end = hold_end + FADE_OUT
        if self.timer < fade_out_end:
            return
        self.speed = 1.0
        self.current += 1
        if self.current >= len(self.slides):
            self.finished = True
            return
        self.timer = 0.0

    def draw(self, target, screen_w: int, screen_h: int) -> None:
        _fill_black(target, screen_w, screen_h, self)
        if self.finished or self.timer < 0:
            return
        alpha = _alpha(self.timer, FADE_IN, HOLD_IMAGE, FADE_OUT)
        if alpha <= 0.0:
            return
        caption, name = self.slides[self.current]
        name_font = self._title if not caption else self._large
        frame = _render_credit(
            self._small, name_font, caption, name, screen_w, screen_h
        )
        target.overlay(_with_alpha(frame, alpha), (0, 0))


class TypeIntro:
    """New-world / continue reel. White typewriter on black; last slide waits."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = list(lines)
        self.current = 0
        self.timer = -INITIAL_DELAY
        self.speed = 1.0
        self.finished = False
        self._font = ui_font(22)
        self._bg: pygame.Surface | None = None

    def reset(self, lines: list[str] | None = None) -> None:
        if lines is not None:
            self.lines = list(lines)
        self.current = 0
        self.timer = -INITIAL_DELAY
        self.speed = 1.0
        self.finished = False

    @property
    def last(self) -> bool:
        return self.current >= len(self.lines) - 1

    def skip(self) -> None:
        if self.finished:
            return
        type_s = self._type_s()
        fade_in_end = FADE_IN
        typed_end = fade_in_end + type_s
        hold_end = typed_end + (0.0 if self.last else HOLD_TEXT)
        if self.timer < 0:
            self.timer = 0.0
            return
        if self.last:
            if self.timer < typed_end:
                self.timer = typed_end
            else:
                self.finished = True
            return
        if self.timer < hold_end:
            self.timer = hold_end
        self.speed = SKIP_SPEED

    def update(self, dt: float) -> None:
        if self.finished:
            return
        if self.last:
            type_s = self._type_s()
            typed_end = FADE_IN + type_s
            if self.timer < typed_end:
                self.timer += dt * self.speed
            return
        self.timer += dt * self.speed
        type_s = self._type_s()
        fade_out_end = FADE_IN + type_s + HOLD_TEXT + FADE_OUT
        if self.timer < fade_out_end:
            return
        self.speed = 1.0
        self.current += 1
        self.timer = 0.0

    def draw(self, target, screen_w: int, screen_h: int) -> None:
        _fill_black(target, screen_w, screen_h, self)
        if self.timer < 0:
            return
        text = self.lines[min(self.current, len(self.lines) - 1)]
        wrapped = _wrap(self._font, text, int(screen_w * 0.7))
        full = "\n".join(wrapped)
        type_s = self._type_s()
        fade_in_end = FADE_IN
        typed_end = fade_in_end + type_s
        hold_end = typed_end + (0.0 if self.last else HOLD_TEXT)
        if self.finished:
            alpha = 1.0
            shown = full
            caret = (pygame.time.get_ticks() // 400) % 2 == 0
        elif self.timer < fade_in_end:
            alpha = max(0.0, min(1.0, self.timer / FADE_IN))
            shown = ""
            caret = True
        elif self.last or self.timer < hold_end:
            alpha = 1.0
            n = len(full) if type_s <= 0.0 else int(
                (self.timer - fade_in_end) / type_s * len(full)
            )
            shown = full[: max(0, min(len(full), n))]
            caret = len(shown) < len(full) or (
                self.last and (pygame.time.get_ticks() // 400) % 2 == 0
            )
        else:
            k = (self.timer - hold_end) / FADE_OUT
            alpha = max(0.0, min(1.0, 1.0 - k))
            shown = full
            caret = False
        if alpha <= 0.0:
            return
        block = _render_type(self._font, shown, caret, screen_w, screen_h)
        target.overlay(_with_alpha(block, alpha), (0, 0))

    def _type_s(self) -> float:
        return max(0.15, len(self.lines[self.current]) / TYPE_CPS)


def _alpha(timer: float, fade_in: float, hold: float, fade_out: float) -> float:
    fade_in_end = fade_in
    hold_end = fade_in_end + hold
    fade_out_end = hold_end + fade_out
    if timer < fade_in_end:
        return max(0.0, min(1.0, timer / fade_in))
    if timer < hold_end:
        return 1.0
    if timer < fade_out_end:
        return max(0.0, min(1.0, 1.0 - (timer - hold_end) / fade_out))
    return 0.0


def _with_alpha(surf: pygame.Surface, alpha: float) -> pygame.Surface:
    """Bake fade into pixels. Overlay uploads RGBA; set_alpha() never reaches GL."""
    if alpha >= 1.0:
        return surf
    out = surf.convert_alpha()
    veil = pygame.Surface(out.get_size(), pygame.SRCALPHA)
    veil.fill((255, 255, 255, max(0, min(255, int(round(255.0 * alpha))))))
    out.blit(veil, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return out


def _render_credit(
    caption_font: pygame.font.Font,
    name_font: pygame.font.Font,
    caption: str,
    name: str,
    screen_w: int,
    screen_h: int,
) -> pygame.Surface:
    surf = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    name_g = name_font.render(name, True, WHITE)
    if caption:
        cap_g = caption_font.render(caption, True, WHITE)
        gap = 14
        height = cap_g.get_height() + gap + name_g.get_height()
        y = (screen_h - height) // 2
        surf.blit(cap_g, ((screen_w - cap_g.get_width()) // 2, y))
        y += cap_g.get_height() + gap
        surf.blit(name_g, ((screen_w - name_g.get_width()) // 2, y))
        return surf
    surf.blit(
        name_g,
        ((screen_w - name_g.get_width()) // 2, (screen_h - name_g.get_height()) // 2),
    )
    return surf


def _fill_black(target, screen_w: int, screen_h: int, owner) -> None:
    bg = getattr(owner, "_bg", None)
    if bg is None or bg.get_size() != (screen_w, screen_h):
        bg = pygame.Surface((screen_w, screen_h))
        bg.fill(BLACK)
        owner._bg = bg
    target.overlay(bg, (0, 0))


def _wrap(font: pygame.font.Font, text: str, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        if para == "":
            lines.append("")
            continue
        cur = ""
        for word in para.split(" "):
            trial = word if not cur else f"{cur} {word}"
            if font.size(trial)[0] <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines


def _render_type(
    font: pygame.font.Font,
    shown: str,
    caret: bool,
    screen_w: int,
    screen_h: int,
) -> pygame.Surface:
    surf = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    rows = shown.split("\n") if shown else [""]
    if caret:
        if rows:
            rows[-1] = rows[-1] + "▌"
        else:
            rows = ["▌"]
    glyphs = [font.render(row if row else " ", True, WHITE) for row in rows]
    gap = 10
    height = sum(g.get_height() for g in glyphs) + gap * max(0, len(glyphs) - 1)
    y = (screen_h - height) // 2
    for glyph in glyphs:
        x = (screen_w - glyph.get_width()) // 2
        surf.blit(glyph, (x, y))
        y += glyph.get_height() + gap
    return surf
