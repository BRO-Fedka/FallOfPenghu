"""Why the quiet-island squad is or is not dispatched."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fall_of_penghu.ai import ChinaDirector
from fall_of_penghu.ai.china_util import (
    capture_islands,
    china_by_island,
    island_has_foe,
)
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import FACTION_CHINA
from fall_of_penghu.world.world import World

DT_SIM = 10.0


def main() -> None:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    world = World.load(ROOT / "penghu_map_v1")
    china = ChinaDirector(world)
    steps = int(minutes * 60.0 / DT_SIM)
    for i in range(1, steps + 1):
        world.clock.advance(DT_SIM / world.clock.k)
        world.step()
        china.step(world)
        if i % 30:
            continue
        now = world.clock.simulation_time
        lookouts = world.perception.lookouts
        inhabited = sorted(lookouts.inhabited) if lookouts else []
        held = china_by_island(world)
        cap = capture_islands(world)
        print(f"--- sim {now:.0f}s inhabited={inhabited} capture={cap}")
        for iid in cap:
            print(
                f"    island {iid}: foe={island_has_foe(world, iid)} "
                f"held={len(held.get(iid, ()))} "
                f"inbound={sorted(world.transport.inbound_kinds(iid))}"
            )
        for obj in world.entities.items:
            if (
                isinstance(obj, DynamicObject)
                and obj.active
                and obj.faction == FACTION_CHINA
                and obj.kind in ("landing_ship", "ferry")
            ):
                print(
                    f"    {obj.id} task={obj.task or '-'} mag={getattr(obj, 'magazine', 0)} "
                    f"cargo={obj.cargo_id or '-'} xy={obj.x:.0f},{obj.y:.0f}"
                )
        print(flush=True)


if __name__ == "__main__":
    main()
