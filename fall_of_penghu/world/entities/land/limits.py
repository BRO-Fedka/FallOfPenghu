from __future__ import annotations


ASTAR_MAX_ITERS = 40_000
SEA_ASTAR_MAX_ITERS = 250_000
RASTER_ASTAR_MAX_ITERS = 80_000
UNWIND_MAX_ITERS = 8_000
HOPS_MAX_ITERS = 256
CHAIN_MAX_ITERS = 256
NEAREST_MAX_RINGS = 16
RASTER_MAX_CELLS = 80_000
RASTER_TARGET_CELLS = 40_000
RASTER_MIN_CELL_M = 16.0
RASTER_MAX_CELL_M = 80.0


class SearchLimitError(RuntimeError):
    """A route search ran past its iteration cap."""

    def __init__(self, where: str, iters: int, limit: int) -> None:
        super().__init__(f"{where} exceeded {limit} iterations ({iters})")
        self.where = where
        self.iters = iters
        self.limit = limit


def tick(where: str, iters: int, limit: int) -> int:
    nxt = iters + 1
    if nxt > limit:
        raise SearchLimitError(where, nxt, limit)
    return nxt


def unwind(
    prev: dict[int, int],
    goal: int,
    where: str,
) -> list[int]:
    path = [goal]
    seen = {goal}
    u = goal
    n = 0
    while u in prev:
        n = tick(f"{where}.unwind", n, UNWIND_MAX_ITERS)
        u = prev[u]
        if u in seen:
            raise SearchLimitError(f"{where}.cycle", n, n)
        seen.add(u)
        path.append(u)
    path.reverse()
    return path
