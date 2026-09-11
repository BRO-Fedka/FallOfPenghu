"""Headless match probe: forest coverage, detection latency, losses, landings.

Run: python tools/probe_night.py [sim_minutes] [--station]
`--station` parks the first carrier on its stand-off so drones skip the 100 km
transit; use it when measuring behaviour over the islands rather than approach.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fall_of_penghu.ai import ChinaDirector
from fall_of_penghu.ai.china_util import standoff_xy
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA, FACTION_PLAYER
from fall_of_penghu.world.entities.kinds import SHOT_KINDS, is_static_kind
from fall_of_penghu.world.world import World

DT_SIM = 10.0
WATCH_KINDS = ("aaw", "aa_pickup", "artillery", "infantry", "tank", "truck")


def player_units(world: World) -> list[DynamicObject]:
    return [
        obj
        for obj in world.entities.items
        if isinstance(obj, DynamicObject)
        and obj.active
        and obj.faction == FACTION_PLAYER
        and obj.kind in WATCH_KINDS
        and not is_static_kind(obj.kind)
        and obj.kind not in SHOT_KINDS
    ]


def china_kinds(world: World) -> dict[str, int]:
    out: dict[str, int] = {}
    for obj in world.entities.items:
        if isinstance(obj, DynamicObject) and obj.active and obj.faction == FACTION_CHINA:
            out[obj.kind] = out.get(obj.kind, 0) + 1
    return out


def main() -> None:
    minutes = 30.0
    station = False
    for arg in sys.argv[1:]:
        if arg == "--station":
            station = True
        else:
            minutes = float(arg)
    world = World.load(ROOT / "penghu_map_v1")
    china = ChinaDirector(world)
    if station:
        for obj in world.entities.items:
            if isinstance(obj, DynamicObject) and obj.kind == "drone_carrier":
                obj.x, obj.y = standoff_xy(world)
                obj.route = None
                obj.task = "station"
                break
    watched = {obj.id: obj.kind for obj in player_units(world)}
    first_seen: dict[str, float] = {}
    steps = int(minutes * 60.0 / DT_SIM)
    report_every = max(1, steps // 6)
    for i in range(1, steps + 1):
        world.clock.advance(DT_SIM / world.clock.k)
        world.step()
        china.step(world)
        now = world.clock.simulation_time
        for obj in world.perception.visible_objects(FACTION_CHINA):
            if obj.id in watched and obj.id not in first_seen:
                first_seen[obj.id] = now
        if i % report_every == 0 or i == steps:
            report(world, china, watched, first_seen, now)


def report(world, china, watched, first_seen, now) -> None:
    stats = china.intel.forest.stats(now)
    per = stats["per_island"]
    gaps = sorted(
        ((iid, seen, total) for iid, (seen, total) in per.items() if seen < total),
        key=lambda row: row[2] - row[1],
        reverse=True,
    )
    print(
        f"=== sim {now:.0f}s  lane={stats['lane_m']:.0f}m  "
        f"tod={world.clock.time_of_day:.2f} dark={world.clock.darkness:.2f}"
    )
    print(
        f"forest ever {stats['ever']}/{stats['lanes']} "
        f"({stats['ever_frac'] * 100.0:.0f}%)  fresh {stats['seen']} "
        f"({stats['frac'] * 100.0:.0f}%)  islands with gaps: {len(gaps)}"
    )
    for iid, seen, total in gaps[:6]:
        print(f"  island {iid:3d} {seen:3d}/{total:3d}")
    missed = [oid for oid in watched if oid not in first_seen]
    print(f"detected {len(first_seen)}/{len(watched)} player units")
    for oid in sorted(first_seen, key=first_seen.get)[:4]:
        print(f"  {oid:22s} {watched[oid]:10s} at {first_seen[oid]:.0f}s")
    for oid in sorted(missed)[:6]:
        print(f"  MISSED {oid:22s} {watched[oid]}")
    counts = china_kinds(world)
    print(
        "china "
        + " ".join(f"{k}={v}" for k, v in sorted(counts.items()) if k != "intercept")
    )
    tasks: dict[str, int] = {}
    for obj in world.entities.items:
        if isinstance(obj, DynamicObject) and obj.active and obj.kind == "scout":
            tasks[obj.task or "-"] = tasks.get(obj.task or "-", 0) + 1
    print("scout tasks " + " ".join(f"{k}={v}" for k, v in sorted(tasks.items())))
    lanes = [pt for pts in china.intel.forest.lanes.values() for pt in pts]
    todo = china.intel.forest.pending(now=now)
    reach = _scout_reach(world)
    blocked = sum(sum(1 for b in row if b) for row in china.intel.forest.air_blocked.values())
    debt = sum(
        len(china.intel.forest.ground_debt(iid, now))
        for iid in china.intel.forest.lanes
    )
    print(
        f"scout forest sight {reach:.0f}m  pending {len(todo)}  "
        f"under AA {blocked}/{len(lanes)}  ground debt {debt}"
    )
    for obj in sorted(
        (
            o
            for o in world.entities.items
            if isinstance(o, DynamicObject)
            and o.active
            and o.kind == "scout"
            and o.faction == FACTION_CHINA
        ),
        key=lambda o: o.id,
    ):
        d_lane = min((_d(obj, pt) for pt in lanes), default=-1.0)
        d_todo = min((_d(obj, pt) for pt in todo), default=-1.0)
        rem = obj.route.remaining_length() if obj.route is not None else -1.0
        pts = len(obj.route.points) if obj.route is not None else 0
        print(
            f"  {obj.id} {obj.task:7s} xy={obj.x:.0f},{obj.y:.0f} "
            f"lane={d_lane:.0f} todo={d_todo:.0f} rem={rem:.0f} pts={pts}"
        )
    print(flush=True)


def _d(obj, pt) -> float:
    return ((obj.x - pt[0]) ** 2 + (obj.y - pt[1]) ** 2) ** 0.5


def _scout_reach(world: World) -> float:
    catalog = world.catalog
    reach = catalog.emitter_range_m("visual_advanced", "scout") or 0.0
    reach *= catalog.darkness_scale("visual_advanced", world.clock.darkness)
    return reach * catalog.cover_factor("visual_advanced", "forest")


if __name__ == "__main__":
    main()
