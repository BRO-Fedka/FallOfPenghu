from __future__ import annotations

from fall_of_penghu.world.entities.land.geom import point_in_poly
from fall_of_penghu.world.map import MapData, PolyFeature

# Clicks on OSM islets that are one gameplay island. Resolved at load.
MERGE_SEEDS: tuple[tuple[tuple[float, float], ...], ...] = (
    ((2938.0, 20456.0), (2500.0, 19741.0)),
)
SEED_SNAP_M = 80.0


class IslandIndex:
    """Penghu coast only. Taiwan is not an island. Some OSM islets share an id."""

    def __init__(self, world: MapData) -> None:
        self._world = world
        self._alias, self._members = _alias_map(world)

    def feature(self, index: int) -> PolyFeature:
        return self._world.coast[index]

    def features(self, index: int) -> list[PolyFeature]:
        return [self._world.coast[i] for i in self.members(index)]

    def members(self, index: int) -> tuple[int, ...]:
        return self._members.get(index, (index,))

    def canonical(self, index: int) -> int:
        return self._alias.get(index, index)

    def at(self, x: float, y: float) -> int | None:
        hit = _raw_at(self._world, x, y)
        if hit is None:
            return None
        return self.canonical(hit)

    def nearest(self, x: float, y: float, max_m: float) -> int | None:
        hit = self.at(x, y)
        if hit is not None:
            return hit
        raw = _raw_nearest(self._world, x, y, max_m)
        if raw is None:
            return None
        return self.canonical(raw)

    def nearest_shore(
        self, x: float, y: float, max_m: float
    ) -> tuple[int, tuple[float, float]] | None:
        hit = self.at(x, y)
        if hit is not None:
            return hit, (x, y)
        found = _raw_nearest_point(self._world, x, y, max_m)
        if found is None:
            return None
        raw, pt = found
        return self.canonical(raw), pt

    def coast_point(
        self,
        x: float,
        y: float,
        *,
        island: int | None = None,
        max_m: float = 8000.0,
    ) -> tuple[int, tuple[float, float]] | None:
        """Nearest coastline vertex. Works from inland and from water."""
        if island is not None:
            ids = self.members(island)
        elif self._world.coast_grid is not None:
            ids = self._world.coast_grid.query(
                x - max_m, y - max_m, x + max_m, y + max_m
            )
        else:
            ids = range(len(self._world.coast))
        best_i: int | None = None
        best_pt = (x, y)
        best_d = max_m * max_m
        for i in ids:
            feat = self._world.coast[i]
            step = max(1, len(feat.exterior) // 64)
            for px, py in feat.exterior[::step]:
                d = (px - x) * (px - x) + (py - y) * (py - y)
                if d < best_d:
                    best_d = d
                    best_i = i
                    best_pt = (px, py)
        if best_i is None:
            return None
        return self.canonical(best_i), best_pt

    def coast_samples(self, island: int) -> list[tuple[float, float]]:
        """Coastline vertices for a gameplay island, thinned."""
        out: list[tuple[float, float]] = []
        for i in self.members(island):
            feat = self._world.coast[i]
            step = max(1, len(feat.exterior) // 48)
            out.extend(feat.exterior[::step])
        return out


def _raw_at(world: MapData, x: float, y: float) -> int | None:
    if world.coast_grid is not None:
        for i in world.coast_grid.query(x, y, x, y):
            if point_in_poly(x, y, world.coast[i]):
                return i
        return None
    for i, feat in enumerate(world.coast):
        if point_in_poly(x, y, feat):
            return i
    return None


def _raw_nearest(world: MapData, x: float, y: float, max_m: float) -> int | None:
    hit = _raw_at(world, x, y)
    if hit is not None:
        return hit
    pad = max_m
    if world.coast_grid is not None:
        ids = world.coast_grid.query(x - pad, y - pad, x + pad, y + pad)
    else:
        ids = range(len(world.coast))
    best_i: int | None = None
    best_d = max_m * max_m
    for i in ids:
        feat = world.coast[i]
        step = max(1, len(feat.exterior) // 48)
        for px, py in feat.exterior[::step]:
            d = (px - x) * (px - x) + (py - y) * (py - y)
            if d < best_d:
                best_d = d
                best_i = i
    return best_i


def _raw_nearest_point(
    world: MapData, x: float, y: float, max_m: float
) -> tuple[int, tuple[float, float]] | None:
    pad = max_m
    if world.coast_grid is not None:
        ids = world.coast_grid.query(x - pad, y - pad, x + pad, y + pad)
    else:
        ids = range(len(world.coast))
    best_i: int | None = None
    best_pt = (x, y)
    best_d = max_m * max_m
    for i in ids:
        feat = world.coast[i]
        step = max(1, len(feat.exterior) // 48)
        for px, py in feat.exterior[::step]:
            d = (px - x) * (px - x) + (py - y) * (py - y)
            if d < best_d:
                best_d = d
                best_i = i
                best_pt = (px, py)
    if best_i is None:
        return None
    return best_i, best_pt


def _alias_map(world: MapData) -> tuple[dict[int, int], dict[int, tuple[int, ...]]]:
    parent: dict[int, int] = {}

    def find(i: int) -> int:
        while parent.get(i, i) != i:
            parent[i] = parent.get(parent[i], parent[i])
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rb < ra:
            ra, rb = rb, ra
        parent[rb] = ra
        parent.setdefault(ra, ra)

    for group in MERGE_SEEDS:
        ids: list[int] = []
        for x, y in group:
            i = _raw_at(world, x, y) or _raw_nearest(world, x, y, SEED_SNAP_M)
            if i is not None:
                ids.append(i)
        for a, b in zip(ids, ids[1:]):
            union(a, b)
    alias = {i: find(i) for i in parent}
    members: dict[int, list[int]] = {}
    for raw, canon in alias.items():
        members.setdefault(canon, []).append(raw)
    packed = {k: tuple(sorted(set(v))) for k, v in members.items()}
    return alias, packed
