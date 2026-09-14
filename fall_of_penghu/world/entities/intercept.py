from __future__ import annotations

from collections import deque
from math import atan2, hypot

from fall_of_penghu.world.combat.health import apply_damage
from fall_of_penghu.world.entities.dynamic import DynamicObject
from fall_of_penghu.world.entities.game_object import GameObject

TRAIL_STEP_M = 16.0
TRAIL_MAX = 6


class Intercept(DynamicObject):
    """Homing shot. Same registry rules as other dynamics; not player-commanded."""

    def __init__(
        self,
        *,
        id: str,
        faction: str,
        x: float,
        y: float,
        heading: float,
        speed_mps: float,
        shooter_id: str,
        target_id: str,
        kill_m: float,
        born_sim: float,
        life_sim_s: float,
        damage: float = 100.0,
    ) -> None:
        super().__init__(
            id=id,
            faction=faction,
            kind="intercept",
            name="Intercept",
            x=x,
            y=y,
            heading=heading,
            speed_mps=speed_mps,
            mobility="air",
        )
        self.shooter_id = shooter_id
        self.target_id = target_id
        self.kill_m = kill_m
        self.born_sim = born_sim
        self.life_sim_s = life_sim_s
        self.damage = damage
        self.trail: deque[tuple[float, float]] = deque(maxlen=TRAIL_MAX)
        self.trail.append((x, y))

    def update(self, dt_sim: float, speed_mps: float | None = None) -> None:
        return

    def steer(
        self,
        target: GameObject | None,
        now_sim: float,
        dt_sim: float,
    ) -> None:
        if not self.active:
            return
        if now_sim - self.born_sim >= self.life_sim_s:
            self.active = False
            return
        if target is None or not target.active:
            self.active = False
            return
        if dt_sim <= 0.0:
            return
        dx = target.x - self.x
        dy = target.y - self.y
        dist = hypot(dx, dy)
        if dist <= self.kill_m:
            self._hit(target)
            return
        self.heading = atan2(dy, dx)
        step = self.speed_mps * dt_sim
        if step >= dist:
            self.x, self.y = target.x, target.y
            self._hit(target)
            return
        self.x += dx / dist * step
        self.y += dy / dist * step
        self._record_trail()

    def _record_trail(self) -> None:
        pos = (self.x, self.y)
        if not self.trail:
            self.trail.append(pos)
            return
        lx, ly = self.trail[-1]
        if hypot(self.x - lx, self.y - ly) >= TRAIL_STEP_M:
            self.trail.append(pos)

    def _hit(self, target: GameObject) -> None:
        from fall_of_penghu.shell.audio import play

        play("explosion")
        apply_damage(target, self.damage)
        self.active = False
