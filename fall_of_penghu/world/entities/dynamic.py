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
            orient_radar=kind in ("drone", "scout", "intercept"),
        )
        self.speed_mps = speed_mps
        self.mobility = mobility
        self.route: Route | None = None
        self.ground: str | None = None
        self.ground_id: int | str | None = None
        self.doctrine = (
            "fire"
            if kind in ("aaw", "aa_pickup", "infantry", "tank", "artillery")
            else "hold"
        )
        self.weapon_ready_sim = 0.0
        self.clip = 0
        self.reserve = 0
        self.reloading = False
        self.last_hurt_sim = 0.0
        self.last_moved_sim = 0.0
        self.rest_ammo_acc = 0.0
        self.cargo_id: str | None = None
        self.strike_id: str | None = None
        self.armed = False
        self.engage_kinds: frozenset[str] | None = None
        self.engage_kinds_saved: frozenset[str] | None = None
        self.aim_xy: tuple[float, float] | None = None
        self.focus_ids: frozenset[str] = frozenset()
        self.magazine = 0
        self.stowed = False
        self.docked = False
        self.home_port_id: str | None = None
        self.xfer: str | None = None
        self.xfer_frac: float = 0.0
        self.task = ""

    @property
    def moving(self) -> bool:
        if self.kind == "intercept":
            return bool(self.active)
        return self.route is not None and self.route.remaining_length() > 1.0

    def update(self, dt_sim: float, speed_mps: float | None = None) -> None:
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
        speed = self.speed_mps if speed_mps is None else speed_mps
        self.route.s += max(speed, 0.0) * dt_sim
        if self.route.s >= self.route.length:
            end = self.route.points[-1]
            prev = self.route.points[-2]
            self.x, self.y = end
            self.heading = atan2(end[1] - prev[1], end[0] - prev[0])
            self.route = None
            return
        self.x, self.y, self.heading = self.route.pose_at(self.route.s)
