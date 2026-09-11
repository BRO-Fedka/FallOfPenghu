from __future__ import annotations

from fall_of_penghu.ai.air_ops import AirOps
from fall_of_penghu.ai.ground_ops import GroundOps
from fall_of_penghu.ai.intel import IntelOps
from fall_of_penghu.ai.log import DecisionLog
from fall_of_penghu.ai.naval_ops import NavalOps
from fall_of_penghu.world.world import World


class ChinaDirector:
    """PLA arrives from the sea. Layers: intel, air, naval, ground."""

    def __init__(self, world: World) -> None:
        self.log = DecisionLog()
        self.intel = IntelOps(self.log)
        self.air = AirOps(self.log, world.seed)
        self.naval = NavalOps(self.log)
        self.ground = GroundOps(self.log)
        self.intel.bake(world)
        self.air.ensure_carrier(world)

    def step(self, world: World) -> None:
        self.intel.step(world)
        self.air.step(world, self.intel)
        self.naval.step(world, self.intel)
        self.ground.step(world, self.intel)
