from __future__ import annotations

from dataclasses import dataclass, field

from fall_of_penghu.camera import Camera
from fall_of_penghu.mapdata import LineFeature, MapData, PolyFeature
from fall_of_penghu.render.geom import overlaps, pad_view

NORMAL = {
    "sea": (30, 180, 195),
    "sea_shallow": (90, 215, 215),
    "sea_deep": (20, 145, 175),
    "taiwan": (168, 160, 136),
    "land": (196, 184, 152),
    "forest": (74, 108, 70),
    "grass": (138, 146, 90),
    "building": (90, 86, 78),
    "road": (48, 46, 44),
    "bridge": (132, 96, 72),
    "airport": (108, 110, 116),
    "hud": (230, 228, 220),
}

RADAR = {
    "sea": (4, 10, 12),
    "taiwan": (20, 70, 68),
    "land": (18, 56, 54),
    "forest": (12, 64, 52),
    "grass": (16, 72, 58),
    "building": (70, 210, 190),
    "road": (40, 160, 150),
    "bridge": (220, 200, 90),
    "airport": (180, 220, 210),
    "hud": (160, 230, 220),
}

BUILDINGS_FADE_FULL_M = 3_200.0
BUILDINGS_FADE_GONE_M = 5_500.0
ROADS_FADE_FULL_M = 28_000.0
ROADS_FADE_GONE_M = 52_000.0
AIRPORTS_FADE_FULL_M = 60_000.0
AIRPORTS_FADE_GONE_M = 95_000.0


def palette_for(radar: bool) -> dict[str, tuple[int, int, int]]:
    return RADAR if radar else NORMAL


def layer_opacity(view_w: float, full_below: float, gone_above: float) -> float:
    """1 when zoomed in past full_below, 0 when zoomed out past gone_above."""
    if view_w <= full_below:
        return 1.0
    if view_w >= gone_above:
        return 0.0
    t = (view_w - full_below) / max(gone_above - full_below, 1.0)
    t = t * t * (3.0 - 2.0 * t)
    return 1.0 - t


@dataclass
class PolyCmd:
    feat: PolyFeature
    color: tuple[int, int, int]
    layer: str
    outline: bool = False
    clip: bool = False


@dataclass
class LineCmd:
    feat: LineFeature
    color: tuple[int, int, int]
    layer: str
    width_px: int


@dataclass
class Frame:
    sea: tuple[int, int, int]
    view: tuple[float, float, float, float]
    clip_rect: tuple[float, float, float, float]
    mpp: float
    polys: list[PolyCmd] = field(default_factory=list)
    lines: list[LineCmd] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def _needs_clip(
    feat: PolyFeature, view: tuple[float, float, float, float]
) -> bool:
    bx0, by0, bx1, by1 = feat.bbox
    return (bx1 - bx0) > (view[2] - view[0]) * 1.15 or (by1 - by0) > (
        view[3] - view[1]
    ) * 1.15


def build_frame(
    world: MapData,
    camera: Camera,
    screen_w: int,
    screen_h: int,
    radar: bool,
) -> Frame:
    pal = palette_for(radar)
    view = camera.world_bounds(screen_w, screen_h)
    view_w = camera.view_width_m
    mpp = camera.meters_per_pixel(screen_w)
    frame = Frame(
        sea=pal["sea"],
        view=view,
        clip_rect=pad_view(view, max(80.0, mpp * 4.0)),
        mpp=mpp,
        stats={
            "taiwan": 0,
            "coast": 0,
            "vegetation": 0,
            "buildings": 0,
            "roads": 0,
            "airports": 0,
        },
    )

    def add_poly(
        feat: PolyFeature,
        color: tuple[int, int, int],
        layer: str,
        *,
        outline: bool = False,
        count: bool = True,
    ) -> None:
        frame.polys.append(
            PolyCmd(
                feat=feat,
                color=color,
                layer=layer,
                outline=outline,
                clip=_needs_clip(feat, view),
            )
        )
        if count:
            frame.stats[layer] += 1

    def add_line(
        feat: LineFeature,
        color: tuple[int, int, int],
        layer: str,
        width_px: int,
    ) -> None:
        frame.lines.append(
            LineCmd(feat=feat, color=color, layer=layer, width_px=width_px)
        )
        frame.stats[layer] += 1

    for feat in world.taiwan:
        if not overlaps(feat.bbox, view):
            continue
        add_poly(feat, pal["taiwan"], "taiwan")

    coast_ids = world.coast_grid.query(*view) if world.coast_grid else range(len(world.coast))
    for idx in coast_ids:
        feat = world.coast[idx]
        if not overlaps(feat.bbox, view):
            continue
        add_poly(feat, pal["land"], "coast")

    veg_ids = world.veg_grid.query(*view) if world.veg_grid else []
    for idx in veg_ids:
        feat = world.vegetation[idx]
        if not overlaps(feat.bbox, view):
            continue
        color = pal["forest"] if feat.class_name == "forest" else pal["grass"]
        add_poly(feat, color, "vegetation")

    if view_w <= ROADS_FADE_GONE_M:
        road_ids = world.road_grid.query(*view) if world.road_grid else []
        for idx in road_ids:
            feat = world.roads[idx]
            if not overlaps(feat.bbox, view):
                continue
            width_px = 2 if feat.bridge else max(1, min(6, int(feat.width_m / mpp + 0.25)))
            color = pal["bridge"] if feat.bridge else pal["road"]
            add_line(feat, color, "roads", width_px)

    if view_w <= BUILDINGS_FADE_GONE_M:
        b_ids = world.building_grid.query(*view) if world.building_grid else []
        for idx in b_ids:
            feat = world.buildings[idx]
            if not overlaps(feat.bbox, view):
                continue
            add_poly(feat, pal["building"], "buildings")

    if view_w <= AIRPORTS_FADE_GONE_M:
        for feat in world.airports:
            if not overlaps(feat.bbox, view):
                continue
            add_poly(feat, pal["airport"], "airports")
        for feat in world.airport_lines:
            if not overlaps(feat.bbox, view):
                continue
            add_line(feat, pal["airport"], "airports", 2)

    if radar:
        radar_ids = world.coast_grid.query(*view) if world.coast_grid else []
        for idx in radar_ids:
            feat = world.coast[idx]
            if overlaps(feat.bbox, view):
                add_poly(feat, pal["hud"], "coast", outline=True, count=False)

    return frame
