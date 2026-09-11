"""Trace one scout's sweep decisions: plan length, route, progress."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fall_of_penghu.ai import ChinaDirector
from fall_of_penghu.ai.china_util import standoff_xy
from fall_of_penghu.ai.intel import _aa_rings, _safe_verts, _slot_of
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA
from fall_of_penghu.world.world import World

DT_SIM = 10.0


def main() -> None:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    world = World.load(ROOT / "penghu_map_v1")
    china = ChinaDirector(world)
    for obj in world.entities.items:
        if isinstance(obj, DynamicObject) and obj.kind == "drone_carrier":
            obj.x, obj.y = standoff_xy(world)
            obj.route = None
            obj.task = "station"
            break
    intel = china.intel
    steps = int(minutes * 60.0 / DT_SIM)
    for i in range(1, steps + 1):
        world.clock.advance(DT_SIM / world.clock.k)
        world.step()
        china.step(world)
        if i % 6:
            continue
        now = world.clock.simulation_time
        scout = next(
            (
                o
                for o in world.entities.items
                if isinstance(o, DynamicObject)
                and o.active
                and o.kind == "scout"
                and o.faction == FACTION_CHINA
                and getattr(o, "role", "") == "search"
            ),
            None,
        )
        if scout is None:
            print(f"{now:7.0f} no search scout", flush=True)
            continue
        rings = _aa_rings(world, intel._kills, now)
        slot = max(0, _slot_of(scout))
        k = int(getattr(scout, "sweep_k", 0) or 0)
        plans = intel._sweep_plans(scout, slot, 8, rings, k)
        plan = plans[0] if plans else ()
        verts = ()
        for cand in plans:
            verts = _safe_verts(world, scout, cand, rings, intel)
            if verts:
                plan = cand
                break
        rem = scout.route.remaining_length() if scout.route is not None else -1.0
        d0 = (
            ((scout.x - plan[0][0]) ** 2 + (scout.y - plan[0][1]) ** 2) ** 0.5
            if plan
            else -1.0
        )
        print(
            f"{now:7.0f} {scout.id} task={scout.task:7s} k={k} "
            f"xy={scout.x:.0f},{scout.y:.0f} plan={len(plan)} d0={d0:.0f} "
            f"verts={len(verts)} rem={rem:.0f} rings={len(rings)}",
            flush=True,
        )


if __name__ == "__main__":
    main()
