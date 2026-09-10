from __future__ import annotations

from math import atan2, hypot

from fall_of_penghu.world.entities.dynamic import DynamicObject


class Tracer(DynamicObject):
    """Ballistic gun streak. Flies to a lead point; hit was rolled at fire."""

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
        aim_x: float,
        aim_y: float,
        will_hit: bool,
        damage: float,
        born_sim: float,
        life_sim_s: float,
        kind: str = "tracer",
        blast_m: float = 0.0,
        from_x: float | None = None,
        from_y: float | None = None,
        mark_x: float | None = None,
        mark_y: float | None = None,
        scatter_m: float = 0.0,
    ) -> None:
        super().__init__(
            id=id,
            faction=faction,
            kind=kind,
            name="Shell" if kind == "shell" else "Tracer",
            x=x,
            y=y,
            heading=heading,
            speed_mps=speed_mps,
            mobility="air",
        )
        self.orient_radar = False
        self.shooter_id = shooter_id
        self.target_id = target_id
        self.aim_x = aim_x
        self.aim_y = aim_y
        self.will_hit = will_hit
        self.damage = damage
        self.born_sim = born_sim
        self.life_sim_s = life_sim_s
        self.blast_m = float(blast_m)
        self.from_x = float(x if from_x is None else from_x)
        self.from_y = float(y if from_y is None else from_y)
        self.mark_x = float(aim_x if mark_x is None else mark_x)
        self.mark_y = float(aim_y if mark_y is None else mark_y)
        self.scatter_m = float(scatter_m)

    def update(self, dt_sim: float, speed_mps: float | None = None) -> None:
        return

    def fly(self, now_sim: float, dt_sim: float) -> bool:
        """Advance toward the aim point. True when the shot should resolve."""
        if not self.active:
            return False
        if now_sim - self.born_sim >= self.life_sim_s:
            self.active = False
            return False
        if dt_sim <= 0.0:
            return False
        dx = self.aim_x - self.x
        dy = self.aim_y - self.y
        dist = hypot(dx, dy)
        step = self.speed_mps * dt_sim
        if dist <= 1.0 or step >= dist:
            self.x, self.y = self.aim_x, self.aim_y
            self.active = False
            return True
        self.heading = atan2(dy, dx)
        self.x += dx / dist * step
        self.y += dy / dist * step
        return False
