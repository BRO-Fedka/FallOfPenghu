from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContactImprint:
    """Frozen last-seen mark. Not a GameObject and not commandable."""

    id: str
    source_id: str
    faction: str
    kind: str
    name: str
    x: float
    y: float
    heading: float
    born_sim: float
    fade_sim_s: float
    moving: bool = False
    trail: tuple[tuple[float, float], ...] = ()
    orient_radar: bool = False
    active: bool = True
    permanent: bool = False

    def age(self, now_sim: float) -> float:
        return max(0.0, now_sim - self.born_sim)

    def dead(self, now_sim: float) -> bool:
        if self.permanent:
            return False
        return self.age(now_sim) >= self.fade_sim_s

    def map_alpha(self, now_sim: float) -> float:
        if self.permanent:
            return 1.0
        life = max(self.fade_sim_s, 1e-6)
        return max(0.0, 1.0 - self.age(now_sim) / life)

    def radar_on(self, now_sim: float) -> bool:
        if self.permanent:
            return True
        age = self.age(now_sim)
        if age >= self.fade_sim_s:
            return False
        u = age / max(self.fade_sim_s, 1e-6)
        period = 0.35 + 1.45 * u
        duty = 0.78 * (1.0 - u) + 0.1
        return (age % period) < (period * duty)
