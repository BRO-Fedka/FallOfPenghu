"""Menu background: drifting crop of the baked strait poster, fading looks."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pygame

from fall_of_penghu.paths import resource_root

ROOT = resource_root()
THEATER_DIR = ROOT / "assets" / "menu_theater"
MANIFEST = THEATER_DIR / "manifest.json"

FADE_S = 5.8
HOLD_S = 14.0
INTRO_BLACK_S = 0.8
DRIFT_PX_S = 5.5
TURN_RAD_S = 0.12
EDGE_PX = 220.0
JUMP_CHANCE = 0.5
JUMP_MIN_PX = 720.0
CYCLE = ("radar", "day", "radar", "night")
VARIANTS = ("day", "night", "radar")
_HOLD_JUMP_AT = max(0.0, HOLD_S * 0.5 - FADE_S * 0.5)
_INTRO_JUMP_AT = FADE_S + _HOLD_JUMP_AT


def _smooth(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _steer(heading: float, want: float, dt: float) -> float:
    err = (want - heading + math.pi) % math.tau - math.pi
    return heading + err * min(1.0, dt * 1.6)


def _read_layout() -> tuple[int, int, int, int, int, int]:
    tw, th, pw, ph = 1920, 1080, 5760, 3240
    if MANIFEST.is_file():
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        tile = data.get("tile") or [tw, th]
        pixels = data.get("pixels") or [pw, ph]
        tw, th = int(tile[0]), int(tile[1])
        pw, ph = int(pixels[0]), int(pixels[1])
    return tw, th, pw, ph, pw // tw, ph // th


def _tile_path(name: str, col: int, row: int) -> Path:
    return THEATER_DIR / "tiles" / name / f"c{col}_r{row}.png"


def slice_posters(
    tw: int, th: int, cols: int, rows: int, names: tuple[str, ...] = VARIANTS
) -> None:
    """Cut full posters into tiles. Skips a variant whose tiles are already there."""
    for name in names:
        missing = [
            (col, row)
            for row in range(rows)
            for col in range(cols)
            if not _tile_path(name, col, row).is_file()
        ]
        if not missing:
            continue
        poster = THEATER_DIR / f"{name}.png"
        if not poster.is_file():
            raise FileNotFoundError(poster)
        img = pygame.image.load(str(poster))
        out_dir = THEATER_DIR / "tiles" / name
        out_dir.mkdir(parents=True, exist_ok=True)
        iw, ih = img.get_size()
        for row in range(rows):
            for col in range(cols):
                path = _tile_path(name, col, row)
                if path.is_file():
                    continue
                x, y = col * tw, row * th
                cell = img.subsurface((x, y, min(tw, iw - x), min(th, ih - y)))
                pygame.image.save(cell, str(path))
        print(f"Menu theater sliced {name} into {cols}x{rows} tiles", flush=True)


class _TiledShot:
    """One look, kept as HD tiles. Viewport is a reused screen-sized blit."""

    def __init__(
        self,
        tiles: list[list[pygame.Surface]],
        tw: int,
        th: int,
    ) -> None:
        self.tiles = tiles
        self.tw = tw
        self.th = th
        self.cols = len(tiles[0])
        self.rows = len(tiles)
        self.w = self.cols * tw
        self.h = self.rows * th
        self._pads: list[pygame.Surface | None] = [None, None]
        self._keys: list[tuple[int, int, int, int] | None] = [None, None]
        self._revs = [0, 0]

    def sample(
        self, fx: float, fy: float, vw: int, vh: int, slot: int = 0
    ) -> tuple[pygame.Surface, float, float, int]:
        pad_w, pad_h = vw + 1, vh + 1
        if pad_w > self.w or pad_h > self.h:
            fx = max(0.0, min(float(self.w - vw), fx))
            fy = max(0.0, min(float(self.h - vh), fy))
            ix, iy = int(round(fx)), int(round(fy))
            pad = self._ensure_pad(vw, vh, slot)
            key = (ix, iy, vw, vh)
            if self._keys[slot] != key:
                self._blit_tiles(pad, ix, iy, vw, vh)
                self._keys[slot] = key
                self._revs[slot] += 1
            return pad, 0.0, 0.0, self._revs[slot]
        fx = max(0.0, min(float(self.w - pad_w), fx))
        fy = max(0.0, min(float(self.h - pad_h), fy))
        ix, iy = int(math.floor(fx)), int(math.floor(fy))
        ox, oy = fx - ix, fy - iy
        pad = self._ensure_pad(pad_w, pad_h, slot)
        key = (ix, iy, pad_w, pad_h)
        if self._keys[slot] != key:
            self._blit_tiles(pad, ix, iy, pad_w, pad_h)
            self._keys[slot] = key
            self._revs[slot] += 1
        return pad, ox, oy, self._revs[slot]

    def _ensure_pad(self, w: int, h: int, slot: int) -> pygame.Surface:
        pad = self._pads[slot]
        if pad is None or pad.get_size() != (w, h):
            pad = pygame.Surface((w, h))
            self._pads[slot] = pad
            self._keys[slot] = None
        return pad

    def _blit_tiles(self, dest: pygame.Surface, ix: int, iy: int, vw: int, vh: int) -> None:
        c0 = max(0, ix // self.tw)
        r0 = max(0, iy // self.th)
        c1 = min(self.cols - 1, (ix + vw - 1) // self.tw)
        r1 = min(self.rows - 1, (iy + vh - 1) // self.th)
        for row in range(r0, r1 + 1):
            for col in range(c0, c1 + 1):
                dest.blit(
                    self.tiles[row][col],
                    (col * self.tw - ix, row * self.th - iy),
                )


class MenuTheater:
    """Black, then radar, then day over radar, then radar > day > radar > night."""

    def __init__(self) -> None:
        self._shots: dict[str, _TiledShot] = {}
        self._ok = False
        self._size = (5760, 3240)
        self.cx = 0.0
        self.cy = 0.0
        self._head = 0.0
        self._phase = "intro_black"
        self._t = 0.0
        self._cycle_i = 0
        self._from = "radar"
        self._to = "radar"
        self.weights = {"radar": 0.0, "day": 0.0, "night": 0.0}
        self._jump_at: float | None = None
        self._incoming = False
        self._jump_t = 0.0
        self._in_cx = 0.0
        self._in_cy = 0.0
        self._in_head = 0.0
        self._load()
        self.reset()

    def _load(self) -> None:
        tw, th, pw, ph, cols, rows = _read_layout()
        try:
            slice_posters(tw, th, cols, rows)
        except (FileNotFoundError, pygame.error) as exc:
            print(f"Menu theater slice failed: {exc}", flush=True)
            return
        shots: dict[str, _TiledShot] = {}
        for name in VARIANTS:
            grid: list[list[pygame.Surface]] = []
            try:
                for row in range(rows):
                    line: list[pygame.Surface] = []
                    for col in range(cols):
                        path = _tile_path(name, col, row)
                        line.append(pygame.image.load(str(path)).convert())
                    grid.append(line)
            except (FileNotFoundError, pygame.error) as exc:
                print(f"Menu theater failed {name}: {exc}", flush=True)
                return
            shots[name] = _TiledShot(grid, tw, th)
        self._shots = shots
        self._size = (pw, ph)
        self._ok = True

    def reset(self) -> None:
        self._phase = "intro_black"
        self._t = 0.0
        self._cycle_i = 0
        self.weights = {"radar": 0.0, "day": 0.0, "night": 0.0}
        minx, maxx, miny, maxy = self._frame()
        self.cx = random.uniform(minx, maxx)
        self.cy = random.uniform(miny, maxy)
        self._head = random.uniform(0.0, math.tau)
        self._clear_jump()

    def update(self, dt: float) -> None:
        if not self._ok:
            return
        dt = max(0.0, dt)
        self._t += dt
        self._advance()
        self._weights()
        self.cx, self.cy, self._head = self._nudge(self.cx, self.cy, self._head, dt)
        if self._jump_at is not None and not self._incoming and self._t >= self._jump_at:
            self._begin_jump()
        if self._incoming:
            self._jump_t += dt
            self._in_cx, self._in_cy, self._in_head = self._nudge(
                self._in_cx, self._in_cy, self._in_head, dt
            )
            if self._jump_t >= FADE_S:
                self.cx, self.cy, self._head = self._in_cx, self._in_cy, self._in_head
                self._clear_jump()

    def tod(self) -> float:
        if self.weights["night"] >= 0.55:
            return 0.0
        if self.weights["day"] >= 0.55:
            return 0.5
        return 0.0

    def draw(self, target, screen_w: int, screen_h: int) -> None:
        if not self._ok:
            return
        for name, alpha in self._stack():
            self._blit_look(
                target, name, alpha, self.cx, self.cy, 0, screen_w, screen_h
            )
        if self._incoming:
            look = self._look()
            inward = _smooth(self._jump_t / FADE_S)
            self._blit_look(
                target,
                look,
                inward,
                self._in_cx,
                self._in_cy,
                1,
                screen_w,
                screen_h,
            )

    def _advance(self) -> None:
        if self._phase == "intro_black":
            if self._t >= INTRO_BLACK_S:
                self._phase = "intro_radar"
                self._t = 0.0
                self._arm_jump(_INTRO_JUMP_AT)
            return
        if self._phase == "intro_radar":
            if self._t >= FADE_S + HOLD_S:
                self._phase = "intro_day"
                self._t = 0.0
                self._arm_jump(_INTRO_JUMP_AT)
            return
        if self._phase == "intro_day":
            if self._t >= FADE_S + HOLD_S:
                if self._incoming:
                    self.cx, self.cy, self._head = (
                        self._in_cx,
                        self._in_cy,
                        self._in_head,
                    )
                self._from = "day"
                self._to = "radar"
                self._cycle_i = 0
                self._phase = "fade"
                self._t = 0.0
                self._clear_jump()
            return
        if self._phase == "hold":
            if self._t >= HOLD_S:
                if self._incoming:
                    self.cx, self.cy, self._head = (
                        self._in_cx,
                        self._in_cy,
                        self._in_head,
                    )
                self._from = CYCLE[self._cycle_i]
                self._cycle_i = (self._cycle_i + 1) % len(CYCLE)
                self._to = CYCLE[self._cycle_i]
                self._phase = "fade"
                self._t = 0.0
                self._clear_jump()
            return
        if self._phase == "fade" and self._t >= FADE_S:
            self._phase = "hold"
            self._t = 0.0
            self._arm_jump(_HOLD_JUMP_AT)

    def _weights(self) -> None:
        w = {"radar": 0.0, "day": 0.0, "night": 0.0}
        if self._phase == "intro_black":
            self.weights = w
            return
        if self._phase == "intro_radar":
            w["radar"] = _smooth(self._t / FADE_S) if self._t < FADE_S else 1.0
            self.weights = w
            return
        if self._phase == "intro_day":
            w["radar"] = 1.0
            w["day"] = _smooth(self._t / FADE_S) if self._t < FADE_S else 1.0
            self.weights = w
            return
        if self._phase == "hold":
            w[CYCLE[self._cycle_i]] = 1.0
            self.weights = w
            return
        u = _smooth(self._t / FADE_S)
        w[self._from] = 1.0 - u
        w[self._to] = u
        self.weights = w

    def _stack(self) -> list[tuple[str, float]]:
        w = self.weights
        if self._phase == "intro_day":
            order = ("radar", "day")
        elif self._phase == "fade":
            order = (self._from, self._to)
        else:
            order = VARIANTS
        seen: set[str] = set()
        stack: list[tuple[str, float]] = []
        for name in order:
            if name in seen:
                continue
            seen.add(name)
            alpha = w.get(name, 0.0)
            if alpha > 0.01:
                stack.append((name, alpha))
        return stack

    def _look(self) -> str:
        if self._phase == "intro_radar":
            return "radar"
        if self._phase == "intro_day":
            return "day"
        if self._phase == "hold":
            return CYCLE[self._cycle_i]
        return self._to

    def _frame(self) -> tuple[float, float, float, float]:
        iw, ih = self._size
        vw = min(iw, max(1, pygame.display.get_window_size()[0]))
        vh = min(ih, max(1, pygame.display.get_window_size()[1]))
        return vw * 0.5, iw - vw * 0.5, vh * 0.5, ih - vh * 0.5

    def _clear_jump(self) -> None:
        self._jump_at = None
        self._incoming = False
        self._jump_t = 0.0

    def _arm_jump(self, start_t: float) -> None:
        self._clear_jump()
        if self._look() == "radar":
            return
        if random.random() < JUMP_CHANCE:
            self._jump_at = start_t

    def _begin_jump(self) -> None:
        minx, maxx, miny, maxy = self._frame()
        cx, cy = self.cx, self.cy
        for _ in range(16):
            nx = random.uniform(minx, maxx)
            ny = random.uniform(miny, maxy)
            if math.hypot(nx - self.cx, ny - self.cy) >= JUMP_MIN_PX:
                cx, cy = nx, ny
                break
        else:
            cx = minx + (maxx - minx) * (0.2 if self.cx > (minx + maxx) * 0.5 else 0.8)
            cy = miny + (maxy - miny) * (0.2 if self.cy > (miny + maxy) * 0.5 else 0.8)
        self._in_cx = cx
        self._in_cy = cy
        self._in_head = random.uniform(0.0, math.tau)
        self._incoming = True
        self._jump_t = 0.0

    def _nudge(
        self, cx: float, cy: float, head: float, dt: float
    ) -> tuple[float, float, float]:
        minx, maxx, miny, maxy = self._frame()
        head += random.gauss(0.0, TURN_RAD_S) * dt
        if cx < minx + EDGE_PX:
            head = _steer(head, 0.0, dt)
        elif cx > maxx - EDGE_PX:
            head = _steer(head, math.pi, dt)
        if cy < miny + EDGE_PX:
            head = _steer(head, math.pi * 0.5, dt)
        elif cy > maxy - EDGE_PX:
            head = _steer(head, math.pi * 1.5, dt)
        cx += math.cos(head) * DRIFT_PX_S * dt
        cy += math.sin(head) * DRIFT_PX_S * dt
        return max(minx, min(maxx, cx)), max(miny, min(maxy, cy)), head

    def _blit_look(
        self,
        target,
        name: str,
        alpha: float,
        cx: float,
        cy: float,
        slot: int,
        screen_w: int,
        screen_h: int,
    ) -> None:
        if alpha <= 0.01:
            return
        shot = self._shots.get(name)
        if shot is None:
            return
        vw = min(shot.w, max(1, screen_w))
        vh = min(shot.h, max(1, screen_h))
        pad, ox, oy, rev = shot.sample(cx - vw * 0.5, cy - vh * 0.5, vw, vh, slot)
        layer = getattr(target, "overlay_layer", None)
        if layer is None:
            target.overlay(pad, (int(-ox), int(-oy)))
            return
        layer(
            f"theater-{name}-{slot}",
            pad,
            (-ox, -oy),
            revision=rev,
            alpha=alpha,
            linear=True,
        )
