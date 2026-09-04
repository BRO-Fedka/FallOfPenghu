from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, hypot


@dataclass
class Route:
    """Polyline in meters. Progress `s` is arc length from the first vertex."""

    points: list[tuple[float, float]]
    s: float = 0.0
    length: float = field(init=False)

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("route needs at least two points")
        self.length = 0.0
        prev = self.points[0]
        for pt in self.points[1:]:
            self.length += hypot(pt[0] - prev[0], pt[1] - prev[1])
            prev = pt

    def remaining_length(self) -> float:
        return max(0.0, self.length - self.s)

    def remaining_points(self, x: float, y: float) -> list[tuple[float, float]]:
        """Polyline from the unit's current pose to the end."""
        if self.s >= self.length - 1e-6:
            return []
        out: list[tuple[float, float]] = [(x, y)]
        traveled = 0.0
        prev = self.points[0]
        for pt in self.points[1:]:
            seg = hypot(pt[0] - prev[0], pt[1] - prev[1])
            if traveled + seg > self.s + 1e-6:
                if pt != out[-1]:
                    out.append(pt)
            traveled += seg
            prev = pt
        return out if len(out) >= 2 else []

    def pose_at(self, s: float) -> tuple[float, float, float]:
        if s <= 0.0:
            a, b = self.points[0], self.points[1]
            return a[0], a[1], atan2(b[1] - a[1], b[0] - a[0])
        remain = min(s, self.length)
        prev = self.points[0]
        for pt in self.points[1:]:
            seg = hypot(pt[0] - prev[0], pt[1] - prev[1])
            if remain <= seg or seg <= 1e-9:
                t = 0.0 if seg <= 1e-9 else remain / seg
                x = prev[0] + (pt[0] - prev[0]) * t
                y = prev[1] + (pt[1] - prev[1]) * t
                return x, y, atan2(pt[1] - prev[1], pt[0] - prev[0])
            remain -= seg
            prev = pt
        a, b = self.points[-2], self.points[-1]
        return b[0], b[1], atan2(b[1] - a[1], b[0] - a[0])
