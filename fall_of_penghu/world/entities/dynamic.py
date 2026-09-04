from __future__ import annotations

from math import atan2

from fall_of_penghu.world.entities.game_object import GameObject
from fall_of_penghu.world.entities.route import Route


class DynamicObject(GameObject):
    """Moves along a Route in simulation time. Does not plan."""

    def __init__(
        self,
        *,
        id: str,
        faction: str,
        kind: str,
        name: str,
        x: float,
        y: float,
        heading: float = 0.0,
        active: bool = True,
        speed_mps: float,
        mobility: str,
    ) -> None:
        super().__init__(
            id=id,
            faction=faction,
            kind=kind,
            name=name,
            x=x,
            y=y,
            heading=heading,
            active=active,
            orient_icon=True,
        )
        self.speed_mps = speed_mps
        self.mobility = mobility
        self.route: Route | None = None

    def update(self, dt_sim: float) -> None:
        if not self.active or self.route is None:
            return
        if self.route.remaining_length() <= 1.0:
            end = self.route.points[-1]
            if len(self.route.points) >= 2:
                prev = self.route.points[-2]
                self.heading = atan2(end[1] - prev[1], end[0] - prev[0])
            self.x, self.y = end
            self.route = None
            return
        if dt_sim <= 0.0:
            return
        self.route.s += self.speed_mps * dt_sim
        if self.route.s >= self.route.length:
            end = self.route.points[-1]
            prev = self.route.points[-2]
            self.x, self.y = end
            self.heading = atan2(end[1] - prev[1], end[0] - prev[0])
            self.route = None
            return
        self.x, self.y, self.heading = self.route.pose_at(self.route.s)
