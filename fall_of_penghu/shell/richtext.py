"""Inline icons in help copy. Tokens: /W /space /lmb /drone /drone_c /sat /pause. /n new line. // a slash."""

from __future__ import annotations

import re
from pathlib import Path

import pygame

from fall_of_penghu.render.dynamic.icons import KIND_FOLDERS, IconStore, listed_kinds
from fall_of_penghu.paths import resource_root
from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER

ROOT = resource_root()
KEYS_DIR = ROOT / "assets" / "icons" / "keys"
HUD_DIR = ROOT / "assets" / "icons" / "hud"

INLINE = 20
GAP = 3
_TOKEN = re.compile(r"//|/nl|/n|/([A-Za-z0-9_]+)|.")

_ALIASES = {
    "escape": "esc",
    "return": "enter",
    "ret": "enter",
    "bksp": "backspace",
    "back": "backspace",
    "del": "delete",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "page_down": "pagedown",
    "page_up": "pageup",
    "control": "ctrl",
    "up": "arrow_up",
    "down": "arrow_down",
    "left": "arrow_left",
    "right": "arrow_right",
    "arrowup": "arrow_up",
    "arrowdown": "arrow_down",
    "arrowleft": "arrow_left",
    "arrowright": "arrow_right",
    "lmb": "mouse_left",
    "rmb": "mouse_right",
    "mmb": "mouse_middle",
    "mouseleft": "mouse_left",
    "mouseright": "mouse_right",
    "mousemiddle": "mouse_middle",
    "leftclick": "mouse_left",
    "rightclick": "mouse_right",
    "wheel": "mouse_scroll_up",
    "scroll": "scroll",
    "scrollup": "mouse_scroll_up",
    "scrolldown": "mouse_scroll_down",
    "plus": "equals",
    "kp_plus": "equals",
    "kp_minus": "minus",
    "sat": "satellite_green",
    "sat_green": "satellite_green",
    "sat_on": "satellite_green",
    "sat_red": "satellite_red",
    "sat_off": "satellite_red",
}


class InlineIcons:
    """Keyboard / mouse PNGs plus game chips, all ~20px tall."""

    def __init__(self) -> None:
        self._store = IconStore()
        self._keys: dict[str, Path] = {}
        self._hud: dict[str, Path] = {}
        self._kinds: set[str] = set(KIND_FOLDERS) | set(listed_kinds())
        self._cache: dict[str, pygame.Surface | None] = {}
        self._index_keys()
        self._index_hud()

    def _index_keys(self) -> None:
        if not KEYS_DIR.is_dir():
            return
        for path in KEYS_DIR.rglob("*.png"):
            stem = path.stem.lower()
            if stem.startswith("key_"):
                stem = stem[4:]
            self._keys[stem] = path
            self._keys[stem.replace("-", "_")] = path

    def _index_hud(self) -> None:
        if not HUD_DIR.is_dir():
            return
        for path in HUD_DIR.glob("*.png"):
            self._hud[path.stem.lower()] = path

    def surface(self, token: str) -> pygame.Surface | None:
        name = token.lower()
        name = _ALIASES.get(name, name)
        if name in self._cache:
            return self._cache[name]
        kind = name
        faction = FACTION_PLAYER
        if kind.endswith("_c") and kind[:-2] in self._kinds:
            kind = kind[:-2]
            faction = FACTION_CHINA
        if kind in self._kinds:
            chip = self._store.get(kind, faction, False)
            baked = _fit(chip) if chip is not None else None
            self._cache[name] = baked
            return baked
        path = self._hud.get(name) or self._keys.get(name)
        if path is None:
            self._cache[name] = None
            return None
        try:
            raw = pygame.image.load(str(path)).convert_alpha()
        except pygame.error:
            self._cache[name] = None
            return None
        baked = _fit(raw)
        self._cache[name] = baked
        return baked


def blit_rich(
    dest: pygame.Surface,
    text: str,
    font: pygame.font.Font,
    ink: tuple[int, int, int],
    x: int,
    y: int,
    max_w: int,
    icons: InlineIcons,
) -> int:
    """Draw wrapping text with /tokens. Returns height used."""
    chunks = _chunks(text, font, ink, icons)
    if not chunks:
        return font.get_height()
    line_h = max(font.get_height(), INLINE)
    cx, cy = x, y
    used = line_h
    for kind, payload in chunks:
        w = payload.get_width()
        if kind == "text" and w == 0:
            continue
        if kind != "nl" and cx > x and cx + w > x + max_w:
            cx = x
            cy += line_h + 2
            used = cy - y + line_h
        if kind == "nl":
            cx = x
            cy += line_h + 2
            used = cy - y + line_h
            continue
        oy = cy + (line_h - payload.get_height()) // 2
        dest.blit(payload, (cx, oy))
        cx += w + (0 if kind == "text" else GAP)
        used = max(used, cy - y + line_h)
    return used


def _fit(src: pygame.Surface) -> pygame.Surface:
    h = INLINE
    w = max(1, int(round(src.get_width() * h / max(1, src.get_height()))))
    w = min(max(w, 16), 56)
    return pygame.transform.smoothscale(src, (w, h))


def _chunks(
    text: str,
    font: pygame.font.Font,
    ink: tuple[int, int, int],
    icons: InlineIcons,
) -> list[tuple[str, pygame.Surface]]:
    out: list[tuple[str, pygame.Surface]] = []
    buf: list[str] = []

    def flush() -> None:
        if not buf:
            return
        raw = "".join(buf)
        buf.clear()
        for i, word in enumerate(_split_keep(raw)):
            if word == "\n":
                out.append(("nl", pygame.Surface((0, 0))))
            elif word:
                out.append(("text", font.render(word, True, ink)))

    for m in _TOKEN.finditer(text):
        tok = m.group(1)
        whole = m.group(0)
        if whole == "//":
            buf.append("/")
            continue
        if whole in ("/n", "/nl"):
            flush()
            out.append(("nl", pygame.Surface((0, 0))))
            continue
        if tok is not None:
            icon = icons.surface(tok)
            if icon is not None:
                flush()
                out.append(("icon", icon))
                continue
            buf.append(whole)
            continue
        if whole == "\n":
            flush()
            out.append(("nl", pygame.Surface((0, 0))))
            continue
        buf.append(whole)
    flush()
    return out


def _split_keep(text: str) -> list[str]:
    """Keep spaces attached to the following word so wrap stays on word bounds."""
    parts: list[str] = []
    cur = ""
    for ch in text:
        if ch == "\n":
            if cur:
                parts.append(cur)
                cur = ""
            parts.append("\n")
        elif ch == " " and cur:
            parts.append(cur)
            cur = " "
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return parts
