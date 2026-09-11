"""Force one approach axis and watch ships arrive, land, and unload.

Run: python tools/trace_axis.py north [sim_minutes]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fall_of_penghu.ai import air_ops, naval_ops
from fall_of_penghu.ai import ChinaDirector
from fall_of_penghu.ai.china_util import axis_order
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA
from fall_of_penghu.world.world import World

DT_SIM = 10.0


def main() -> None:
    axis = sys.argv[1] if len(sys.argv) > 1 else "north"
    minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 150.0
    air_ops.approach_axis = lambda world, wave: axis
    naval_ops.approach_axis = lambda world, wave: axis
    world = World.load(ROOT / "penghu_map_v1")
    print(f"axis={axis} legal={axis_order(world)}")
    china = ChinaDirector(world)
    steps = int(minutes * 60.0 / DT_SIM)
    for i in range(1, steps + 1):
        world.clock.advance(DT_SIM / world.clock.k)
        world.step()
        china.step(world)
        if i % 60:
            continue
        now = world.clock.simulation_time
        hulls = [
            obj
            for obj in world.entities.items
            if isinstance(obj, DynamicObject)
            and obj.active
            and obj.faction == FACTION_CHINA
            and obj.kind in ("landing_ship", "drone_carrier", "ferry")
        ]
        ashore = sum(
            1
            for obj in world.entities.items
            if isinstance(obj, DynamicObject)
            and obj.active
            and obj.faction == FACTION_CHINA
            and obj.mobility == "land"
            and not obj.stowed
        )
        print(f"--- {now:.0f}s ashore={ashore}")
        for obj in sorted(hulls, key=lambda o: o.id):
            rem = obj.route.remaining_length() if obj.route is not None else -1.0
            print(
                f"    {obj.id:14s} {obj.kind:13s} task={obj.task or '-':10s} "
                f"xy={obj.x:.0f},{obj.y:.0f} rem={rem:.0f}"
            )
        print(flush=True)
    for line in china.log.lines()[-14:]:
        print(line)


if __name__ == "__main__":
    main()
