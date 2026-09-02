from __future__ import annotations

# Simulation seconds per wall second at 1x. Marked advanced in match settings.
DEFAULT_K = 4.0
# Calendar seconds per simulation second. 8 sim hours = 24 calendar hours.
CALENDAR_PER_SIM = 3.0
CALENDAR_DAY_S = 86_400.0

SPEEDS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0)


class Clock:
    """Match clocks. Units never scale time themselves; they read dt_sim."""

    def __init__(self, *, k: float = DEFAULT_K) -> None:
        self.k = float(k)
        self.speed = 1.0
        self.paused = False
        self.wall_time = 0.0
        self.simulation_time = 0.0
        self.calendar_time = 0.0
        self.dt_wall = 0.0
        self.dt_sim = 0.0
        self.dt_calendar = 0.0

    def advance(self, wall_dt: float) -> None:
        self.dt_wall = max(float(wall_dt), 0.0)
        self.wall_time += self.dt_wall
        factor = 0.0 if self.paused else self.speed
        self.dt_sim = self.dt_wall * self.k * factor
        self.simulation_time += self.dt_sim
        self.dt_calendar = self.dt_sim * CALENDAR_PER_SIM
        self.calendar_time += self.dt_calendar

    @property
    def time_of_day(self) -> float:
        """Fraction of a calendar day, 0..1, midnight at 0."""
        return (self.calendar_time / CALENDAR_DAY_S) % 1.0

    @property
    def calendar_day(self) -> int:
        return int(self.calendar_time // CALENDAR_DAY_S)

    def toggle_pause(self) -> None:
        self.paused = not self.paused

    def set_speed(self, speed: float) -> None:
        self.speed = float(speed)
        if self.speed > 0.0:
            self.paused = False

    def clock_label(self) -> str:
        minutes = int(self.time_of_day * 24.0 * 60.0) % (24 * 60)
        return f"D{self.calendar_day + 1} {minutes // 60:02d}:{minutes % 60:02d}"

    def speed_label(self) -> str:
        if self.paused:
            return "PAUSE"
        value = self.speed
        if value == int(value):
            return f"{int(value)}x"
        return f"{value:g}x"
