from __future__ import annotations

import pygame

from fall_of_penghu.render.dynamic.icons import IconStore
from fall_of_penghu.world.combat.doctrine import FIRE, HOLD, is_battery, is_shooter
from fall_of_penghu.world.entities import (
    Entities,
    FACTION_PLAYER,
    SetAim,
    SetDoctrine,
    SetEngageFilter,
    SetFocus,
)
from fall_of_penghu.world.entities.kinds import kind_label
from fall_of_penghu.world.perception import DetectionCatalog
from fall_of_penghu.selection import Selection

PANEL_H = 40
PAD = 6
TITLE_H = 24
ROW_H = 22
CHECK = 14
TWIST = 12
ICON = 16
BRANCHES = ("air", "land", "sea", "static")
BRANCH_LABEL = {"air": "Air", "land": "Land", "sea": "Sea", "static": "Static"}
BTN_W = 56
BTN_H = 22


class EngagePalette:
    """Movable target-filter tree. Writes through SetEngageFilter."""

    def __init__(self) -> None:
        self.x = -1
        self.y = PANEL_H + 12
        self._open: dict[str, bool] = {name: False for name in BRANCHES}
        self._icons = IconStore()
        self._font = pygame.font.SysFont("consolas", 13)
        self._panel = pygame.Rect(0, 0, 1, 1)
        self._title = pygame.Rect(0, 0, 1, 1)
        self._rows: list[tuple[pygame.Rect, str, str | None]] = []
        self._btns: list[tuple[pygame.Rect, str]] = []
        self._drag = False
        self._drag_off = (0, 0)
        self._width = 220

    def visible(self, selection: Selection | None, entities: Entities | None) -> bool:
        return bool(self._shooters(selection, entities))

    def hits(self, x: int, y: int, selection: Selection | None, entities: Entities | None) -> bool:
        if not self.visible(selection, entities):
            return False
        return bool(self._panel.collidepoint(x, y))

    def handle_event(
        self,
        event: pygame.event.Event,
        selection: Selection | None,
        entities: Entities | None,
        catalog: DetectionCatalog | None,
        screen_w: int,
        screen_h: int,
    ) -> bool:
        if catalog is None or not self.visible(selection, entities):
            return False
        shooters = self._shooters(selection, entities)
        self._layout(shooters, catalog, selection, screen_w, screen_h)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._title.collidepoint(event.pos):
                self._drag = True
                self._drag_off = (event.pos[0] - self.x, event.pos[1] - self.y)
                return True
            for rect, action in self._btns:
                if not rect.collidepoint(event.pos):
                    continue
                if action == "hold":
                    self._hold(shooters, entities, catalog)
                    return True
                if action == "fire":
                    self._fire(shooters, entities, catalog)
                    return True
                if action == "aim" and selection is not None:
                    self._aim(shooters, selection)
                    return True
                if action == "clr" and selection is not None:
                    self._clear_aim(shooters, entities, selection)
                    return True
                if action == "pick" and selection is not None:
                    shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
                    self._pick(shooters, entities, selection, clear=shift)
                    return True
            for rect, action, key in self._rows:
                if not rect.collidepoint(event.pos):
                    continue
                if action == "twist" and key is not None:
                    self._open[key] = not self._open.get(key, False)
                    return True
                if action == "branch" and key is not None:
                    self._toggle_branch(shooters, entities, catalog, key)
                    return True
                if action == "kind" and key is not None:
                    self._toggle_kind(shooters, entities, catalog, key)
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
        selection: Selection | None,
        entities: Entities | None,
        catalog: DetectionCatalog | None,
        screen_w: int,
        screen_h: int,
    ) -> None:
        if catalog is None or not self.visible(selection, entities):
            return
        shooters = self._shooters(selection, entities)
        self._layout(shooters, catalog, selection, screen_w, screen_h)
        surf = pygame.Surface((self._panel.w, self._panel.h), pygame.SRCALPHA)
        surf.fill((8, 10, 12, 200))
        pygame.draw.rect(surf, (*ink, 80), surf.get_rect(), 1)
        title = self._font.render("TARGETS", True, ink)
        surf.blit(title, (PAD, (TITLE_H - title.get_height()) // 2))
        mx, my = mouse
        tip: str | None = None
        for rect, action, key in self._rows:
            local = pygame.Rect(rect.x - self.x, rect.y - self.y, rect.w, rect.h)
            hover = local.collidepoint(mx - self.x, my - self.y)
            if hover:
                pygame.draw.rect(surf, (*ink, 28), local)
            if action == "twist" and key is not None:
                self._draw_twist(surf, local, ink, self._open.get(key, False))
            elif action == "branch" and key is not None:
                state = self._branch_state(shooters, catalog, key)
                self._draw_check(surf, local, ink, state)
                label = self._font.render(BRANCH_LABEL[key], True, ink)
                surf.blit(
                    label,
                    (local.right + 6, local.y + (ROW_H - label.get_height()) // 2),
                )
                if hover:
                    tip = BRANCH_LABEL[key]
            elif action == "kind" and key is not None:
                state = self._kind_state(shooters, catalog, key)
                self._draw_check(surf, local, ink, state)
                icon = self._icons.get(key, FACTION_PLAYER, False)
                ix = local.right + 6
                if icon is not None:
                    chip = pygame.transform.smoothscale(icon, (ICON, ICON))
                    surf.blit(
                        chip,
                        (ix, local.y + (ROW_H - ICON) // 2),
                    )
                    ix += ICON + 4
                label = self._font.render(kind_label(key), True, ink)
                surf.blit(
                    label,
                    (ix, local.y + (ROW_H - label.get_height()) // 2),
                )
                if hover:
                    tip = kind_label(key)
        for rect, action in self._btns:
            local = pygame.Rect(rect.x - self.x, rect.y - self.y, rect.w, rect.h)
            hover = local.collidepoint(mx - self.x, my - self.y)
            armed = False
            if action == "hold":
                guns = [obj for obj in shooters if is_battery(obj)]
                armed = bool(guns) and all(
                    getattr(obj, "doctrine", "") == HOLD for obj in guns
                )
            elif action == "fire":
                guns = [obj for obj in shooters if is_battery(obj)]
                armed = bool(guns) and all(
                    getattr(obj, "doctrine", "") == FIRE for obj in guns
                )
            elif action == "aim" and selection is not None:
                armed = bool(selection.artillery_aim) or any(
                    getattr(obj, "aim_xy", None) is not None
                    for obj in shooters
                    if obj.kind == "artillery"
                )
            elif action == "clr":
                armed = False
            elif action == "pick" and selection is not None:
                armed = bool(selection.pick_targets) or any(
                    bool(getattr(obj, "focus_ids", ())) for obj in shooters if is_battery(obj)
                )
            fill = (*ink, 55 if armed else 18)
            pygame.draw.rect(surf, fill, local, border_radius=3)
            pygame.draw.rect(
                surf, (*ink, 200 if armed else 90), local, 1, border_radius=3
            )
            if hover:
                pygame.draw.rect(surf, (*ink, 28), local)
            text = self._font.render(action.upper(), True, ink)
            surf.blit(
                text,
                (
                    local.x + (local.w - text.get_width()) // 2,
                    local.y + (local.h - text.get_height()) // 2,
                ),
            )
            if hover:
                if action == "aim":
                    tip = "AIM map point"
                elif action == "clr":
                    tip = "Clear map aim"
                elif action == "pick":
                    tip = "PICK units  Shift+PICK clear"
                else:
                    tip = action.upper()
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

    @staticmethod
    def _shooters(selection: Selection | None, entities: Entities | None):
        if selection is None or entities is None:
            return []
        out = []
        for oid in selection.selected:
            obj = entities.get(oid)
            if is_shooter(obj) and obj is not None and obj.faction == FACTION_PLAYER:
                out.append(obj)
        return out

    def _kinds_for_branch(self, shooters, catalog: DetectionCatalog, branch: str) -> list[str]:
        found: set[str] = set()
        for obj in shooters:
            for kind in catalog.engage_kinds_for(obj.kind):
                if catalog.target_branch(kind) == branch:
                    found.add(kind)
        return sorted(found)

    def _kind_on(self, obj, catalog: DetectionCatalog, kind: str) -> bool:
        allowed = catalog.engage_kinds_for(obj.kind)
        if kind not in allowed:
            return False
        selected = getattr(obj, "engage_kinds", None)
        if selected is None:
            return True
        return kind in selected

    def _kind_state(self, shooters, catalog: DetectionCatalog, kind: str) -> str:
        flags = [
            self._kind_on(obj, catalog, kind)
            for obj in shooters
            if kind in catalog.engage_kinds_for(obj.kind)
        ]
        if not flags:
            return "off"
        if all(flags):
            return "on"
        if not any(flags):
            return "off"
        return "mix"

    def _branch_state(self, shooters, catalog: DetectionCatalog, branch: str) -> str:
        kinds = self._kinds_for_branch(shooters, catalog, branch)
        flags = [self._kind_state(shooters, catalog, kind) for kind in kinds]
        if not flags:
            return "off"
        if all(item == "on" for item in flags):
            return "on"
        if all(item == "off" for item in flags):
            return "off"
        return "mix"

    def _set_kinds(self, obj, entities: Entities, catalog: DetectionCatalog, kinds: set[str]) -> None:
        allowed = catalog.engage_kinds_for(obj.kind)
        picked = tuple(sorted(k for k in kinds if k in allowed))
        payload = None if set(picked) == allowed else picked
        entities.dispatch(
            SetEngageFilter(object_id=obj.id, kinds=payload),
            as_faction=FACTION_PLAYER,
        )

    def _current_kinds(self, obj, catalog: DetectionCatalog) -> set[str]:
        selected = getattr(obj, "engage_kinds", None)
        if selected is None:
            return set(catalog.engage_kinds_for(obj.kind))
        return set(selected)

    def _toggle_kind(
        self, shooters, entities: Entities, catalog: DetectionCatalog, kind: str
    ) -> None:
        turn_on = self._kind_state(shooters, catalog, kind) != "on"
        for obj in shooters:
            if kind not in catalog.engage_kinds_for(obj.kind):
                continue
            current = self._current_kinds(obj, catalog)
            if turn_on:
                current.add(kind)
            else:
                current.discard(kind)
            self._set_kinds(obj, entities, catalog, current)

    def _toggle_branch(
        self, shooters, entities: Entities, catalog: DetectionCatalog, branch: str
    ) -> None:
        kinds = self._kinds_for_branch(shooters, catalog, branch)
        turn_on = self._branch_state(shooters, catalog, branch) != "on"
        for obj in shooters:
            allowed = catalog.engage_kinds_for(obj.kind)
            current = self._current_kinds(obj, catalog)
            for kind in kinds:
                if kind not in allowed:
                    continue
                if turn_on:
                    current.add(kind)
                else:
                    current.discard(kind)
            self._set_kinds(obj, entities, catalog, current)

    def _hold(self, shooters, entities: Entities, catalog: DetectionCatalog) -> None:
        for obj in shooters:
            if not is_battery(obj):
                continue
            if getattr(obj, "doctrine", "") != HOLD:
                obj.engage_kinds_saved = obj.engage_kinds
            self._set_kinds(obj, entities, catalog, set())
            entities.dispatch(
                SetDoctrine(object_id=obj.id, doctrine=HOLD),
                as_faction=FACTION_PLAYER,
            )

    def _fire(self, shooters, entities: Entities, catalog: DetectionCatalog) -> None:
        for obj in shooters:
            if not is_battery(obj):
                continue
            saved = getattr(obj, "engage_kinds_saved", None)
            if saved is None:
                payload = None
            else:
                payload = tuple(sorted(saved))
            entities.dispatch(
                SetEngageFilter(object_id=obj.id, kinds=payload),
                as_faction=FACTION_PLAYER,
            )
            entities.dispatch(
                SetDoctrine(object_id=obj.id, doctrine=FIRE),
                as_faction=FACTION_PLAYER,
            )

    def _aim(self, shooters, selection: Selection) -> None:
        guns = [obj for obj in shooters if obj.kind == "artillery"]
        if not guns:
            return
        selection.pick_targets = False
        selection.artillery_aim = not selection.artillery_aim

    def _clear_aim(self, shooters, entities: Entities, selection: Selection) -> None:
        selection.artillery_aim = False
        for obj in shooters:
            if obj.kind != "artillery":
                continue
            entities.dispatch(
                SetAim(object_id=obj.id, target=None),
                as_faction=FACTION_PLAYER,
            )

    def _pick(
        self, shooters, entities: Entities, selection: Selection, *, clear: bool
    ) -> None:
        guns = [obj for obj in shooters if is_battery(obj)]
        if not guns:
            return
        if clear:
            selection.pick_targets = False
            for obj in guns:
                entities.dispatch(
                    SetFocus(object_id=obj.id, ids=None),
                    as_faction=FACTION_PLAYER,
                )
            return
        selection.artillery_aim = False
        selection.pick_targets = not selection.pick_targets

    def _layout(
        self,
        shooters,
        catalog: DetectionCatalog,
        selection: Selection | None,
        screen_w: int,
        screen_h: int,
    ) -> None:
        _ = selection
        if self.x < 0:
            self.x = max(12, screen_w - self._width - 12)
        rows = 0
        shown: list[tuple[str, list[str]]] = []
        for branch in BRANCHES:
            kinds = self._kinds_for_branch(shooters, catalog, branch)
            if not kinds:
                continue
            shown.append((branch, kinds))
            rows += 1
            if self._open.get(branch):
                rows += len(kinds)
        guns = [obj for obj in shooters if is_battery(obj)]
        has_artillery = any(obj.kind == "artillery" for obj in shooters)
        btn_rows = 0
        if guns:
            btn_rows = 2 if has_artillery else 1
        extra = (PAD + btn_rows * (BTN_H + 4)) if btn_rows else 0
        height = TITLE_H + PAD + rows * ROW_H + extra + PAD
        self._panel = pygame.Rect(self.x, self.y, self._width, height)
        self._clamp(screen_w, screen_h)
        self._panel = pygame.Rect(self.x, self.y, self._width, height)
        self._title = pygame.Rect(self.x, self.y, self._width, TITLE_H)
        self._rows = []
        self._btns = []
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
        if btn_rows:
            y += PAD // 2
            x = self.x + PAD
            for action in ("hold", "fire"):
                self._btns.append((pygame.Rect(x, y, BTN_W, BTN_H), action))
                x += BTN_W + 6
            if has_artillery:
                y += BTN_H + 4
                x = self.x + PAD
                for action in ("aim", "clr", "pick"):
                    self._btns.append((pygame.Rect(x, y, BTN_W, BTN_H), action))
                    x += BTN_W + 6
            else:
                self._btns.append((pygame.Rect(x, y, BTN_W, BTN_H), "pick"))

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
