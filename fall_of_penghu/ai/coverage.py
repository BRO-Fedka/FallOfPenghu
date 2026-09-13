from __future__ import annotations

from math import ceil, hypot
from typing import TYPE_CHECKING

from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA

if TYPE_CHECKING:
    from fall_of_penghu.ai.heatmap import IslandHeatmaps
    from fall_of_penghu.world.world import World

STALE_S = 2_400.0
MARK_EVERY_S = 2.0
BUCKET_M = 500.0
PROBE_N = 3
LANE_OVERLAP = 0.70
AIR_EYES = {"scout": "visual_advanced", "drone": "visual_primitive"}
GROUND_EYES = {
    "infantry": "visual_primitive",
    "tank": "visual_primitive",
    "artillery": "visual_primitive",
    "truck": "visual_primitive",
    "aa_pickup": "visual_primitive",
}


class ForestCoverage:
    """Ledger of forest lanes and who has actually looked at them.

    Canopy cuts a scout's sight to about 210 m and an infantry squad's to about
    125 m, so a forest is only searched if someone passes within that distance of
    every lane. Air and ground share one ledger: pockets a drone cannot enter
    stay pending until landed troops walk them.
    """

    def __init__(self) -> None:
        self.lanes: dict[int, tuple[tuple[float, float], ...]] = {}
        self.seen: dict[int, list[float]] = {}
        self.ever: dict[int, list[bool]] = {}
        self.air_blocked: dict[int, list[bool]] = {}
        self.lane_m = 250.0
        self._buckets: dict[tuple[int, int], list[tuple[int, int]]] = {}
        self._mark_sim = -1e9

    def bake(self, world: World, heat: IslandHeatmaps) -> None:
        cover = world.perception.cover
        self.lanes = {}
        self.seen = {}
        self.ever = {}
        self.air_blocked = {}
        self._buckets = {}
        self._mark_sim = -1e9
        if cover is None:
            return
        cell = max(50.0, world.catalog.heat_cell_m)
        self.lane_m = _lane_m(world, cell)
        step = max(80.0, self.lane_m)
        cols = max(1, int(ceil(cell / step)))
        for grid in heat.grids.values():
            pts: list[tuple[float, float]] = []
            for i, land in enumerate(grid.land):
                if not land or not _touches_forest(cover, grid.center(i), cell):
                    continue
                cx, cy = grid.center(i)
                for gx in range(cols):
                    for gy in range(cols):
                        x = cx - cell / 2.0 + cell * (gx + 0.5) / cols
                        y = cy - cell / 2.0 + cell * (gy + 0.5) / cols
                        if cover.at(x, y, "ground") == "forest":
                            pts.append((x, y))
            if not pts:
                continue
            lanes = tuple(_snake(pts, step))
            self.lanes[grid.island] = lanes
            self.seen[grid.island] = [0.0] * len(lanes)
            self.ever[grid.island] = [False] * len(lanes)
            self.air_blocked[grid.island] = [False] * len(lanes)
        self._index()

    def snakes(self) -> list[tuple[int, tuple[tuple[float, float], ...]]]:
        return [(iid, self.lanes[iid]) for iid in sorted(self.lanes)]

    def mark(self, world: World) -> None:
        now = world.clock.simulation_time
        if now - self._mark_sim < MARK_EVERY_S or not self.lanes:
            return
        self._mark_sim = now
        catalog = world.catalog
        darkness = world.clock.darkness
        reach: dict[str, float] = {}
        for obj in world.entities.items:
            if not isinstance(obj, DynamicObject) or not obj.active or obj.stowed:
                continue
            if obj.faction != FACTION_CHINA:
                continue
            channel = AIR_EYES.get(obj.kind) or GROUND_EYES.get(obj.kind)
            if channel is None:
                continue
            r = reach.get(obj.kind)
            if r is None:
                r = _forest_reach(catalog, channel, obj.kind, darkness)
                reach[obj.kind] = r
            if r <= 0.0:
                continue
            self._touch(obj.x, obj.y, r, now)

    def pending(
        self, island: int | None = None, *, now: float | None = None
    ) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for iid in (self.lanes if island is None else [island]):
            lanes = self.lanes.get(iid)
            seen = self.seen.get(iid)
            if not lanes or seen is None:
                continue
            for i, pt in enumerate(lanes):
                if _stale(seen[i], now):
                    out.append(pt)
        return out

    def is_pending(self, pt: tuple[float, float], now: float | None = None) -> bool:
        hit = self._at(pt)
        if hit is None:
            return False
        iid, i = hit
        return _stale(self.seen[iid][i], now)

    def block_air(self, pts: list[tuple[float, float]]) -> None:
        """Lanes a drone must not enter. Ground inherits them as its first job."""
        for pt in pts:
            hit = self._at(pt)
            if hit is not None:
                self.air_blocked[hit[0]][hit[1]] = True

    def ground_debt(self, island: int, now: float | None = None) -> list[tuple[float, float]]:
        lanes = self.lanes.get(island) or ()
        seen = self.seen.get(island) or []
        blocked = self.air_blocked.get(island) or []
        debt = [
            pt
            for i, pt in enumerate(lanes)
            if _stale(seen[i], now) and i < len(blocked) and blocked[i]
        ]
        return debt

    def stats(self, now: float | None = None) -> dict[str, object]:
        per_island: dict[int, tuple[int, int]] = {}
        total = 0
        done = 0
        for iid, lanes in self.lanes.items():
            seen = self.seen.get(iid) or []
            hit = sum(1 for i in range(len(lanes)) if not _stale(seen[i], now))
            per_island[iid] = (hit, len(lanes))
            total += len(lanes)
            done += hit
        ever = sum(sum(1 for flag in row if flag) for row in self.ever.values())
        return {
            "lanes": total,
            "seen": done,
            "ever": ever,
            "frac": (done / total) if total else 0.0,
            "ever_frac": (ever / total) if total else 0.0,
            "per_island": per_island,
            "lane_m": self.lane_m,
        }

    def _index(self) -> None:
        self._buckets = {}
        for iid, lanes in self.lanes.items():
            for i, (x, y) in enumerate(lanes):
                self._buckets.setdefault(_key(x, y), []).append((iid, i))

    def _touch(self, x: float, y: float, r: float, now: float) -> None:
        span = int(ceil(r / BUCKET_M))
        kx, ky = _key(x, y)
        for gx in range(kx - span, kx + span + 1):
            for gy in range(ky - span, ky + span + 1):
                for iid, i in self._buckets.get((gx, gy), ()):
                    px, py = self.lanes[iid][i]
                    if hypot(px - x, py - y) <= r:
                        self.seen[iid][i] = now
                        self.ever[iid][i] = True

    def _at(self, pt: tuple[float, float]) -> tuple[int, int] | None:
        kx, ky = _key(pt[0], pt[1])
        best = None
        best_d = 60.0
        for gx in range(kx - 1, kx + 2):
            for gy in range(ky - 1, ky + 2):
                for iid, i in self._buckets.get((gx, gy), ()):
                    px, py = self.lanes[iid][i]
                    d = hypot(px - pt[0], py - pt[1])
                    if d < best_d:
                        best = (iid, i)
                        best_d = d
        return best


def _stale(seen: float, now: float | None) -> bool:
    if seen <= 0.0:
        return True
    return now is not None and now - seen > STALE_S


def _key(x: float, y: float) -> tuple[int, int]:
    return (int(x // BUCKET_M), int(y // BUCKET_M))


def _forest_reach(catalog, channel: str, kind: str, darkness: float) -> float:
    reach = catalog.emitter_range_m(channel, kind) or 0.0
    reach *= catalog.darkness_scale(channel, darkness)
    reach *= catalog.cover_factor(channel, "forest")
    return max(0.0, reach)


def _lane_m(world: World, cell: float) -> float:
    """Spacing a scout can actually see through canopy, with overlap."""
    reach = _forest_reach(world.catalog, "visual_advanced", "scout", 0.0)
    if reach <= 0.0:
        return min(cell, 160.0)
    return max(80.0, reach * LANE_OVERLAP)


def _touches_forest(cover, center: tuple[float, float], cell: float) -> bool:
    """A 500 m cell is rarely all forest; probe it so tree lines are not skipped."""
    cx, cy = center
    for i in range(PROBE_N):
        for j in range(PROBE_N):
            x = cx - cell / 2.0 + cell * (i + 0.5) / PROBE_N
            y = cy - cell / 2.0 + cell * (j + 0.5) / PROBE_N
            if cover.at(x, y, "ground") == "forest":
                return True
    return False


def _snake(
    cells: list[tuple[float, float]], row_m: float
) -> list[tuple[float, float]]:
    rows: dict[int, list[tuple[float, float]]] = {}
    for x, y in cells:
        rows.setdefault(int(round(y / row_m)), []).append((x, y))
    path: list[tuple[float, float]] = []
    for i, gy in enumerate(sorted(rows)):
        row = sorted(rows[gy], key=lambda p: p[0])
        if i % 2:
            row.reverse()
        path.extend(row)
    return path
