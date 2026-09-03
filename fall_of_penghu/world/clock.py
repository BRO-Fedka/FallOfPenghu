from __future__ import annotations

# Simulation seconds per wall second at 1x. Marked advanced in match settings.
DEFAULT_K = 4.0
# Calendar seconds per simulation second. 8 sim hours = 24 calendar hours.
CALENDAR_PER_SIM = 3.0
CALENDAR_DAY_S = 86_400.0

# F1–F6. F7 (32x) is debug-only.
SPEEDS = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)
DEBUG_SPEED = 32.0


class Clock:
    """Match clocks. Units never scale time themselves; they read dt_sim."""

    def __init__(self, *, k: float = DEFAULT_K) -> None:
        self.k = float(k)
        self.speed = 1.0
        self._resume_speed = 1.0
        self.paused = False
        self.wall_time = 0.0
        self.simulation_time = 0.0
        # Open at noon so the first frame matches the authored day look.
        self.calendar_time = 0.5 * CALENDAR_DAY_S
        self.dt_wall = 0.0
        self.dt_sim = 0.0
        self.dt_calendar = 0.0

    def advance(self, wall_dt: float) -> None:
        self.dt_wall = max(float(wall_dt), 0.0)
        self.wall_time += self.dt_wall
        factor = 0.0 if self.paused or self.speed == 0.0 else self.speed
        # 1x → k sim seconds per wall second (default k=4: four times real).
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
        if self.speed == 0.0:
            self.set_speed(self._resume_speed)
        else:
            self.set_speed(0.0)

    def set_speed(self, speed: float) -> None:
        self.speed = max(float(speed), 0.0)
        self.paused = self.speed == 0.0
        if self.speed > 0.0:
            self._resume_speed = self.speed

    def cap_to_player_speeds(self) -> None:
        if self.speed > SPEEDS[-1]:
            self.set_speed(SPEEDS[-1])

    def clock_label(self) -> str:
        secs = int(self.time_of_day * 24.0 * 3600.0) % (24 * 3600)
        hours = secs // 3600
        minutes = (secs % 3600) // 60
        seconds = secs % 60
        return f"D{self.calendar_day + 1} {hours:02d}:{minutes:02d}:{seconds:02d}"

    def speed_label(self, speed: float | None = None) -> str:
        value = self.speed if speed is None else speed
        if value == int(value):
            return f"{int(value)}x"
        return f"{value:g}x"
