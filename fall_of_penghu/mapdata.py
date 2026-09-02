"""Compatibility alias. Map geometry lives in fall_of_penghu.world.map."""

from fall_of_penghu.world.map import (
    LineFeature,
    MapData,
    PolyFeature,
    load_map,
)

__all__ = ["LineFeature", "MapData", "PolyFeature", "load_map"]
