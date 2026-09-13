from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter

import pygame

AVG_FRAMES = 30
BUDGET_MS = 1000.0 / 60.0
PANEL_H = 40
TITLE_H = 24
PAD = 8
ROW_H = 16
WIDTH = 520
MAX_BODY = 22
HOT_MS = 16.7
WARM_MS = 8.0


@dataclass
class ProfNode:
    name: str
    total_ms: float = 0.0
    children: list[ProfNode] = field(default_factory=list)

    @property
    def self_ms(self) -> float:
        return max(0.0, self.total_ms - sum(c.total_ms for c in self.children))


class _Noop:
    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


_NOOP = _Noop()


class FrameProfiler:
    """Nested CPU timers for one game frame. Cheap when disabled."""

    def __init__(self) -> None:
        self.enabled = False
        self._root: ProfNode | None = None
        self._stack: list[ProfNode] = []
        self.last: ProfNode | None = None
        self._history: list[dict[str, float]] = []
        self.avg: dict[str, float] = {}
        self.panel = ProfPanel()
        self._frame_t0 = 0.0
        self._want_enabled: bool | None = None

    def toggle(self) -> None:
        # Defer so a scope already on the stack is not torn down mid-with.
        if self._want_enabled is None:
            self._want_enabled = not self.enabled
        else:
            self._want_enabled = not self._want_enabled

    def begin_frame(self) -> None:
        self._frame_t0 = perf_counter()
        if self._want_enabled is not None:
            self.enabled = self._want_enabled
            self._want_enabled = None
        if not self.enabled:
            self._root = None
            self._stack = []
            return
        self._root = ProfNode("frame")
        self._stack = [self._root]

    def remaining_ms(self) -> float:
        if self._frame_t0 <= 0.0:
            return BUDGET_MS
        return BUDGET_MS - (perf_counter() - self._frame_t0) * 1000.0

    def end_frame(self) -> None:
        if self._want_enabled is not None:
            self.enabled = self._want_enabled
            self._want_enabled = None
        if self._root is None:
            self._stack = []
            return
        self._root.total_ms = (perf_counter() - self._frame_t0) * 1000.0
        self.last = self._root
        flat = _flatten(self._root)
        self._history.append(flat)
        if len(self._history) > AVG_FRAMES:
            self._history.pop(0)
        acc: dict[str, float] = defaultdict(float)
        for row in self._history:
            for key, value in row.items():
                acc[key] += value
        n = float(len(self._history))
        self.avg = {key: value / n for key, value in acc.items()}
        self._root = None
        self._stack = []

    def scope(self, name: str):
        if not self.enabled or not self._stack:
            return _NOOP
        return _scope(self, name)


@contextmanager
def _scope(prof: FrameProfiler, name: str):
    node = ProfNode(name)
    if not prof._stack:
        yield
        return
    parent = prof._stack[-1]
    parent.children.append(node)
    prof._stack.append(node)
    t0 = perf_counter()
    try:
        yield
    finally:
        node.total_ms = (perf_counter() - t0) * 1000.0
        if prof._stack and prof._stack[-1] is node:
            prof._stack.pop()


def _flatten(node: ProfNode, prefix: str = "") -> dict[str, float]:
    path = f"{prefix}/{node.name}" if prefix else node.name
    out = {path: node.total_ms}
    for child in node.children:
        out.update(_flatten(child, path))
    return out


def _walk(
    node: ProfNode, depth: int = 0, prefix: str = ""
) -> list[tuple[int, str, str, float, float]]:
    path = f"{prefix}/{node.name}" if prefix else node.name
    rows = [(depth, node.name, path, node.total_ms, node.self_ms)]
    for child in node.children:
        rows.extend(_walk(child, depth + 1, path))
    return rows


def _sum_named(node: ProfNode | None, prefix: str) -> float:
    if node is None:
        return 0.0
    total = 0.0
    if node.name.startswith(prefix):
        total += node.total_ms
    for child in node.children:
        total += _sum_named(child, prefix)
    return total


class ProfPanel:
    """Draggable F11 overlay. Drawn only while the profiler is on."""

    def __init__(self) -> None:
        self.x = 12
        self.y = PANEL_H + 8
        self._placed = False
        self._scroll = 0
        self._drag = False
        self._drag_off = (0, 0)
        self._panel = pygame.Rect(0, 0, 1, 1)
        self._title = pygame.Rect(0, 0, 1, 1)
        self._font: pygame.font.Font | None = None
        self._tiny: pygame.font.Font | None = None

    def hits(self, x: int, y: int) -> bool:
        return bool(self._panel.collidepoint(x, y))

    def handle_event(
        self, event: pygame.event.Event, screen_w: int, screen_h: int
    ) -> bool:
        if not prof.enabled:
            return False
        self._layout(screen_w, screen_h, len(_rows(prof)))
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._title.collidepoint(event.pos):
                self._drag = True
                self._drag_off = (event.pos[0] - self.x, event.pos[1] - self.y)
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
            if not self._panel.collidepoint(mx, my):
                return False
            n = max(0, len(_rows(prof)) - MAX_BODY)
            self._scroll = min(max(0, self._scroll - event.y), n)
            return True
        return False

    def blit(self, renderer, screen_w: int, screen_h: int) -> None:
        if self._font is None:
            self._font = pygame.font.SysFont("consolas", 13)
            self._tiny = pygame.font.SysFont("consolas", 12)
        rows = _rows(prof)
        self._layout(screen_w, screen_h, len(rows))
        surf = pygame.Surface((self._panel.w, self._panel.h), pygame.SRCALPHA)
        surf.fill((8, 10, 12, 220))
        pygame.draw.rect(surf, (230, 228, 220, 80), surf.get_rect(), 1)
        last_ms = 0.0 if prof.last is None else prof.last.total_ms
        avg_ms = prof.avg.get("frame", last_ms)
        fps = 0.0 if last_ms <= 1e-6 else 1000.0 / last_ms
        path_ms = _sum_named(prof.last, "plan.")
        ink = (230, 228, 220)
        title = self._font.render("FRAME PROF  F11", True, ink)
        surf.blit(title, (PAD, (TITLE_H - title.get_height()) // 2))
        head = self._tiny.render(
            f"{last_ms:6.1f} ms  {fps:5.1f} fps  avg{AVG_FRAMES} {avg_ms:6.1f}  "
            f"budget {BUDGET_MS:.1f}  path {path_ms:5.1f}",
            True,
            ink,
        )
        surf.blit(head, (PAD, TITLE_H + 2))
        note = self._tiny.render(
            "CPU wall time. GPU work may land in map/present. Scroll wheel.",
            True,
            (180, 178, 170),
        )
        surf.blit(note, (PAD, TITLE_H + 16))
        visible = rows[self._scroll : self._scroll + MAX_BODY]
        y = TITLE_H + 34
        frame_ms = last_ms if last_ms > 1e-6 else 1.0
        for depth, name, total, self_ms, avg in visible:
            pct = 100.0 * total / frame_ms
            color = _row_color(total, ink)
            indent = "  " * depth
            extra = f"  self {self_ms:5.2f}" if self_ms + 0.05 < total else ""
            avg_s = f"  ~{avg:5.2f}" if avg > 0.0 else ""
            line = f"{total:7.2f} {pct:5.1f}%  {indent}{name}{extra}{avg_s}"
            label = self._tiny.render(line, True, color)
            surf.blit(label, (PAD, y))
            y += ROW_H
        renderer.overlay(surf, (self._panel.x, self._panel.y))

    def _layout(self, screen_w: int, screen_h: int, n_rows: int) -> None:
        if not self._placed:
            self.x = max(12, screen_w - WIDTH - 12)
            self.y = PANEL_H + 8
            self._placed = True
        body = min(MAX_BODY, max(n_rows, 1))
        height = TITLE_H + 34 + body * ROW_H + PAD
        self._panel = pygame.Rect(self.x, self.y, WIDTH, height)
        self._clamp(screen_w, screen_h)
        self._panel = pygame.Rect(self.x, self.y, WIDTH, height)
        self._title = pygame.Rect(self.x, self.y, WIDTH, TITLE_H)

    def _clamp(self, screen_w: int, screen_h: int) -> None:
        self.x = min(max(0, self.x), max(0, screen_w - WIDTH))
        self.y = min(max(PANEL_H, self.y), max(PANEL_H, screen_h - 80))


def _rows(
    profiler: FrameProfiler,
) -> list[tuple[int, str, float, float, float]]:
    if profiler.last is None:
        return []
    out: list[tuple[int, str, float, float, float]] = []
    for depth, name, path, total, self_ms in _walk(profiler.last):
        out.append((depth, name, total, self_ms, profiler.avg.get(path, 0.0)))
    return out


def _row_color(
    ms: float, ink: tuple[int, int, int]
) -> tuple[int, int, int]:
    if ms >= HOT_MS:
        return (235, 120, 90)
    if ms >= WARM_MS:
        return (230, 200, 90)
    return ink


prof = FrameProfiler()


def scope(name: str):
    return prof.scope(name)


def remaining_ms() -> float:
    return prof.remaining_ms()


# If the 16.7 ms frame is already spent, still use this much so a queue
# of cheap units (~0.2 ms) yields about five per frame, not one.
_OVER_BUDGET_SLICE_MS = 1.0


def slice_round_robin(items, cursor: int, work) -> int:
    """Round-robin `work(item)` from `cursor`. Always one unit.

    More while leftover 16.7 ms frame time remains. If the frame is
    already over budget, keep going for up to 1 ms. At most one full pass.
    """
    n = len(items)
    if n <= 0:
        return cursor
    i = cursor % n
    done = 0
    leftover = prof.remaining_ms()
    t0 = perf_counter()
    while done < n:
        if done >= 1:
            if leftover > 0.0:
                if prof.remaining_ms() <= 0.0:
                    break
            elif (perf_counter() - t0) * 1000.0 >= _OVER_BUDGET_SLICE_MS:
                break
        work(items[i])
        done += 1
        i = (i + 1) % n
    return i
