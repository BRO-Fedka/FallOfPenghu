from __future__ import annotations

from collections import defaultdict


class UniformGrid:
    """Axis-aligned hash grid in world meters."""

    def __init__(self, cell_m: float) -> None:
        self.cell_m = cell_m
        self._cells: dict[tuple[int, int], list[int]] = defaultdict(list)

    def insert(self, index: int, minx: float, miny: float, maxx: float, maxy: float) -> None:
        c = self.cell_m
        x0 = int(minx // c)
        y0 = int(miny // c)
        x1 = int(maxx // c)
        y1 = int(maxy // c)
        cells = self._cells
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                cells[gx, gy].append(index)

    def query(self, minx: float, miny: float, maxx: float, maxy: float) -> list[int]:
        c = self.cell_m
        x0 = int(minx // c)
        y0 = int(miny // c)
        x1 = int(maxx // c)
        y1 = int(maxy // c)
        seen: set[int] = set()
        out: list[int] = []
        cells = self._cells
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                bucket = cells.get((gx, gy))
                if not bucket:
                    continue
                for idx in bucket:
                    if idx not in seen:
                        seen.add(idx)
                        out.append(idx)
        return out
