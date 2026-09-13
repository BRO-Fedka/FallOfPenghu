from __future__ import annotations

from fall_of_penghu.spatial import UniformGrid
from fall_of_penghu.world.entities.land.geom import dist_seg, point_in_poly
from fall_of_penghu.world.map import MapData

CELL_M = 500.0
ROAD_ON_M = 18.0


class CoverIndex:
    """Forest / grass / open and road at a point, via a 500 m cell map.

    Each cell lists vegetation and road ids whose bbox overlaps it. Built
    once when the map loads. Air and sea skip vegetation.
    """

    def __init__(self, world: MapData, baked=None) -> None:
        self._map = world
        if baked is not None:
            from fall_of_penghu.world.map_bake import restore_grid

            cells = baked.payload["cover"]
            self._forest = restore_grid(cells["forest"], CELL_M)
            self._grass = restore_grid(cells["grass"], CELL_M)
            self._roads = restore_grid(cells["roads"], CELL_M)
            return
        self._forest = UniformGrid(CELL_M)
        self._grass = UniformGrid(CELL_M)
        self._roads = UniformGrid(CELL_M)
        for i, feat in enumerate(world.vegetation):
            grid = self._forest if feat.class_name == "forest" else self._grass
            grid.insert(i, *feat.bbox)
        pad = ROAD_ON_M
        for i, road in enumerate(world.roads):
            minx, miny, maxx, maxy = road.bbox
            self._roads.insert(
                i, minx - pad, miny - pad, maxx + pad, maxy + pad
            )

    def at(self, x: float, y: float, role: str) -> str:
        if role != "ground":
            return "open"
        veg = self._map.vegetation
        for i in self._forest.at(x, y):
            if point_in_poly(x, y, veg[i]):
                return "forest"
        for i in self._grass.at(x, y):
            if point_in_poly(x, y, veg[i]):
                return "grass"
        return "open"

    def on_road(self, x: float, y: float) -> bool:
        roads = self._map.roads
        lim = ROAD_ON_M
        for i in self._roads.at(x, y):
            pts = roads[i].points
            for a, b in zip(pts, pts[1:]):
                if dist_seg(x, y, a[0], a[1], b[0], b[1]) <= lim:
                    return True
        return False
