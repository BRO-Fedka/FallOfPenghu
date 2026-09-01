from __future__ import annotations

from fall_of_penghu.mapdata import MapData

VEG_PAD_M = 500.0


def _penghu_frame(world: MapData) -> tuple[float, float, float, float]:
    bbox = world.manifest.get("bbox_penghu") or [-22_000.0, -32_000.0, 21_000.0, 35_000.0]
    return (
        float(bbox[0]) - VEG_PAD_M,
        float(bbox[1]) - VEG_PAD_M,
        float(bbox[2]) + VEG_PAD_M,
        float(bbox[3]) + VEG_PAD_M,
    )
