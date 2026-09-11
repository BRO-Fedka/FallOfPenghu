from __future__ import annotations

from dataclasses import dataclass
from math import exp, hypot
from typing import TYPE_CHECKING

from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER, GameObject
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind
from fall_of_penghu.world.entities.land.geom import point_in_poly
from fall_of_penghu.world.entities.land.islands import IslandIndex
from fall_of_penghu.world.perception.imprint import ContactImprint

if TYPE_CHECKING:
    from fall_of_penghu.world.world import World


@dataclass
class Ember:
    source_id: str
    kind: str
    x: float
    y: float
    last_sim: float


@dataclass
class IslandGrid:
    island: int
    origin: tuple[float, float]
    cell_m: float
    w: int
    h: int
    land: list[bool]
    coastal: list[bool]
    threat: list[float]
    landing: list[float]
    aa: list[float]
    n_land: int = 0

    def index(self, x: float, y: float) -> int | None:
        gx = int((x - self.origin[0]) / self.cell_m)
        gy = int((y - self.origin[1]) / self.cell_m)
        if gx < 0 or gy < 0 or gx >= self.w or gy >= self.h:
            return None
        i = gy * self.w + gx
        if not self.land[i]:
            return None
        return i

    def center(self, i: int) -> tuple[float, float]:
        gx = i % self.w
        gy = i // self.w
        c = self.cell_m
        ox, oy = self.origin
        return (ox + (gx + 0.5) * c, oy + (gy + 0.5) * c)


@dataclass
class BeachPick:
    island: int
    x: float
    y: float
    landing: float
    cost: float
    n_land: int
    inhabited: bool


class IslandHeatmaps:
    """Per-island 500 m land grids. Intel picture only. Not saved."""

    def __init__(self) -> None:
        self.grids: dict[int, IslandGrid] = {}
        self.embers: dict[str, Ember] = {}
        self.inhabited: frozenset[int] = frozenset()

    def bake(self, world: World) -> None:
        planner = world.entities.planner
        if planner is None:
            return
        islands = planner.land.islands
        cell = max(50.0, world.catalog.heat_cell_m)
        lookouts = world.perception.lookouts
        self.inhabited = lookouts.inhabited if lookouts is not None else frozenset()
        self.grids = {}
        for iid in islands.ids():
            grid = _bake_island(islands, iid, cell)
            if grid is not None and grid.n_land > 0:
                self.grids[iid] = grid

    def refresh(self, world: World) -> None:
        catalog = world.catalog
        now = world.clock.simulation_time
        self._sync_embers(world, now)
        for grid in self.grids.values():
            n = len(grid.land)
            grid.threat = [0.0] * n
            grid.landing = [0.0] * n
            grid.aa = [0.0] * n
        half = max(catalog.heat_half_life_sim_s, 1.0)
        for ember in self.embers.values():
            age = max(0.0, now - ember.last_sim)
            decay = 0.5 ** (age / half)
            if decay < 0.02:
                continue
            weight, sigma = catalog.splat(ember.kind)
            land_w = catalog.landing_weight(ember.kind)
            self._splat(ember.x, ember.y, weight * decay, sigma, "threat")
            self._splat(ember.x, ember.y, land_w * decay, sigma, "landing")
        self._paint_aa(world)

    def sample(self, x: float, y: float) -> tuple[float, float, float] | None:
        grid, i = self._at(x, y)
        if grid is None or i is None:
            return None
        return (grid.threat[i], grid.landing[i], grid.aa[i])

    def pick_landing(self, world: World) -> BeachPick | None:
        catalog = world.catalog
        cold_w = catalog.landing_cold_weight
        far_w = catalog.landing_far_weight
        hot_lim = catalog.landing_hot_threshold
        best: BeachPick | None = None
        for iid, grid in self.grids.items():
            pick = _best_coastal(grid, cold_w, far_w)
            if pick is None:
                continue
            inhabited = iid in self.inhabited
            held = iid in world.perception.china_held
            pull = (3.2 if inhabited and not held else 2.0 if inhabited else 1.0)
            scored = BeachPick(
                island=iid,
                x=pick[0],
                y=pick[1],
                landing=pick[2],
                cost=pick[3]
                / (1.0 + 0.15 * pull * _area_bonus(grid.n_land)),
                n_land=grid.n_land,
                inhabited=inhabited,
            )
            if best is None or scored.cost < best.cost:
                best = scored
        if best is None or best.landing >= hot_lim:
            return None
        return best

    def iter_view(
        self, minx: float, miny: float, maxx: float, maxy: float
    ):
        for grid in self.grids.values():
            c = grid.cell_m
            ox, oy = grid.origin
            for i, land in enumerate(grid.land):
                if not land:
                    continue
                gx = i % grid.w
                gy = i // grid.w
                x0 = ox + gx * c
                y0 = oy + gy * c
                x1 = x0 + c
                y1 = y0 + c
                if x1 < minx or x0 > maxx or y1 < miny or y0 > maxy:
                    continue
                t = grid.threat[i]
                land_h = grid.landing[i]
                aa = grid.aa[i]
                if t < 0.04 and land_h < 0.04 and aa < 0.04:
                    continue
                yield (x0, y0, x1, y1, t, land_h, aa)

    def _at(self, x: float, y: float) -> tuple[IslandGrid | None, int | None]:
        for grid in self.grids.values():
            i = grid.index(x, y)
            if i is not None:
                return grid, i
        return None, None

    def _sync_embers(self, world: World, now: float) -> None:
        live: dict[str, GameObject] = {}
        for obj in world.perception.visible_objects(FACTION_CHINA):
            if obj.faction != FACTION_PLAYER or not obj.active:
                continue
            if is_static_kind(obj.kind) or obj.kind in SHOT_KINDS:
                continue
            if getattr(obj, "stowed", False):
                continue
            live[obj.id] = obj
        seen_imprint: dict[str, ContactImprint] = {}
        for mark in world.perception.imprints(FACTION_CHINA):
            if mark.faction != FACTION_PLAYER:
                continue
            if is_static_kind(mark.kind) or mark.kind in SHOT_KINDS:
                continue
            if not mark.active:
                self.embers.pop(mark.source_id, None)
                continue
            seen_imprint[mark.source_id] = mark
        for sid in list(self.embers):
            obj = world.entities.get(sid)
            if obj is not None and not obj.active:
                self.embers.pop(sid, None)
        for obj in live.values():
            self.embers[obj.id] = Ember(obj.id, obj.kind, obj.x, obj.y, now)
        for sid, mark in seen_imprint.items():
            if sid in live:
                continue
            obj = world.entities.get(sid)
            if obj is not None and not obj.active:
                self.embers.pop(sid, None)
                continue
            self.embers[sid] = Ember(sid, mark.kind, mark.x, mark.y, mark.born_sim)

    def _splat(
        self, x: float, y: float, weight: float, sigma: float, layer: str
    ) -> None:
        if weight <= 0.0 or sigma <= 0.0:
            return
        radius = 3.0 * sigma
        two_s2 = 2.0 * sigma * sigma
        for grid in self.grids.values():
            c = grid.cell_m
            ox, oy = grid.origin
            gx0 = max(0, int((x - radius - ox) / c))
            gy0 = max(0, int((y - radius - oy) / c))
            gx1 = min(grid.w, int((x + radius - ox) / c) + 1)
            gy1 = min(grid.h, int((y + radius - oy) / c) + 1)
            dest = grid.threat if layer == "threat" else grid.landing
            for gy in range(gy0, gy1):
                row = gy * grid.w
                for gx in range(gx0, gx1):
                    i = row + gx
                    if not grid.land[i]:
                        continue
                    cx, cy = grid.center(i)
                    d2 = (cx - x) * (cx - x) + (cy - y) * (cy - y)
                    dest[i] += weight * exp(-d2 / two_s2)

    def _paint_aa(self, world: World) -> None:
        catalog = world.catalog
        factor = catalog.radar_aa_factor
        contacts: list[GameObject | ContactImprint] = []
        for obj in world.perception.visible_objects(FACTION_CHINA):
            if obj.faction != FACTION_PLAYER or not obj.active:
                continue
            contacts.append(obj)
        for mark in world.perception.imprints(FACTION_CHINA):
            if mark.faction != FACTION_PLAYER or not mark.active:
                continue
            contacts.append(mark)
        seen: set[str] = set()
        for src in contacts:
            sid = getattr(src, "id", None) or getattr(src, "source_id", "")
            if sid in seen:
                continue
            seen.add(str(sid))
            kind = src.kind
            if kind in ("aaw", "aa_pickup"):
                reach = catalog.engagement_m(kind) or 0.0
                if reach > 0.0:
                    self._disk(src.x, src.y, reach, 1.0)
            radar = catalog.emitter_range_m("radar", kind)
            if radar is not None and radar > 0.0 and factor > 0.0:
                self._disk(src.x, src.y, radar, factor)

    def _disk(self, x: float, y: float, radius: float, weight: float) -> None:
        if radius <= 0.0 or weight <= 0.0:
            return
        r2 = radius * radius
        for grid in self.grids.values():
            c = grid.cell_m
            ox, oy = grid.origin
            gx0 = max(0, int((x - radius - ox) / c))
            gy0 = max(0, int((y - radius - oy) / c))
            gx1 = min(grid.w, int((x + radius - ox) / c) + 1)
            gy1 = min(grid.h, int((y + radius - oy) / c) + 1)
            for gy in range(gy0, gy1):
                row = gy * grid.w
                for gx in range(gx0, gx1):
                    i = row + gx
                    if not grid.land[i]:
                        continue
                    cx, cy = grid.center(i)
                    d2 = (cx - x) * (cx - x) + (cy - y) * (cy - y)
                    if d2 <= r2:
                        grid.aa[i] += weight


def _area_bonus(n_land: int) -> float:
    return min(4.0, max(0.4, n_land / 20.0))


def _bake_island(islands: IslandIndex, iid: int, cell: float) -> IslandGrid | None:
    feats = islands.features(iid)
    if not feats:
        return None
    minx, miny, maxx, maxy = islands.bbox(iid)
    pad = cell
    origin = (minx - pad, miny - pad)
    w = max(1, int((maxx - minx + 2 * pad) / cell) + 1)
    h = max(1, int((maxy - miny + 2 * pad) / cell) + 1)
    n = w * h
    land = [False] * n
    mix = [False] * n
    n_land = 0
    for gy in range(h):
        y0 = origin[1] + gy * cell
        y1 = y0 + cell
        row = gy * w
        for gx in range(w):
            x0 = origin[0] + gx * cell
            x1 = x0 + cell
            hits = _cell_hits(feats, x0, y0, x1, y1)
            if hits <= 0:
                continue
            land[row + gx] = True
            mix[row + gx] = hits < 5
            n_land += 1
    if n_land <= 0:
        return None
    coastal = [False] * n
    for gy in range(h):
        row = gy * w
        for gx in range(w):
            i = row + gx
            if not land[i]:
                continue
            if mix[i]:
                coastal[i] = True
                continue
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = gx + dx, gy + dy
                if nx < 0 or ny < 0 or nx >= w or ny >= h:
                    coastal[i] = True
                    break
                if not land[ny * w + nx]:
                    coastal[i] = True
                    break
    return IslandGrid(
        island=iid,
        origin=origin,
        cell_m=cell,
        w=w,
        h=h,
        land=land,
        coastal=coastal,
        threat=[0.0] * n,
        landing=[0.0] * n,
        aa=[0.0] * n,
        n_land=n_land,
    )


def _cell_hits(feats, x0: float, y0: float, x1: float, y1: float) -> int:
    pts = (
        (x0, y0),
        (x1, y0),
        (x0, y1),
        (x1, y1),
        ((x0 + x1) * 0.5, (y0 + y1) * 0.5),
    )
    n = 0
    for x, y in pts:
        for feat in feats:
            if point_in_poly(x, y, feat):
                n += 1
                break
    return n


def _best_coastal(
    grid: IslandGrid, cold_w: float, far_w: float
) -> tuple[float, float, float, float] | None:
    cells = [i for i, ok in enumerate(grid.coastal) if ok and grid.land[i]]
    if not cells:
        return None
    heats = [grid.landing[i] for i in cells]
    peak = max(heats) if heats else 0.0
    hot_cut = max(1.0, 0.25 * peak) if peak > 0.0 else 1e9
    hot_xy = [grid.center(i) for i in cells if grid.landing[i] >= hot_cut]
    max_d = 1.0
    dists: list[float] = []
    for i in cells:
        cx, cy = grid.center(i)
        if not hot_xy:
            dists.append(1.0)
            continue
        d = min(hypot(cx - hx, cy - hy) for hx, hy in hot_xy)
        dists.append(d)
        if d > max_d:
            max_d = d
    best_i = cells[0]
    best_cost = 1e30
    inv_peak = 1.0 / max(peak, 1e-6)
    for i, d in zip(cells, dists):
        cx, cy = grid.center(i)
        heat = grid.landing[i]
        heat_n = heat * inv_peak if peak > 0.0 else 0.0
        dist_n = d / max_d
        west = (cx - grid.origin[0]) / max(grid.w * grid.cell_m, 1.0)
        cost = cold_w * heat_n + far_w * (1.0 - dist_n) + 0.12 * west
        if cost < best_cost:
            best_cost = cost
            best_i = i
    cx, cy = grid.center(best_i)
    return (cx, cy, grid.landing[best_i], best_cost)
