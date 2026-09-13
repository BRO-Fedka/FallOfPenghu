from __future__ import annotations

# Simulation seconds per wall second at 1x. Marked advanced in match settings.
DEFAULT_K = 4.0
# Calendar seconds per simulation second. 8 sim hours = 24 calendar hours.
CALENDAR_PER_SIM = 3.0
CALENDAR_DAY_S = 86_400.0
# Matches map TOD: civil day from 05:00 to the start of night at 18:15.
DAYLIGHT_START = 5.0 / 24.0
DAYLIGHT_END = 18.25 / 24.0

# F1… for each entry. F7 (32x) is debug-only.
SPEEDS = (0.0, 0.5, 1.0, 4.0, 16.0)
DEBUG_SPEED = 32.0
# Matches TOD keyframes: day from 05:00 through the start of dusk.
DAY_START = 5.0 / 24.0
DAY_END = 18.25 / 24.0

# Same TOD windows as render.static.tod.KEYFRAMES: 1 = full night, 0 = day.
_DARKNESS_KEYS: tuple[tuple[float, float], ...] = (
    (0.00, 1.0),
    (4 / 24, 1.0),
    (5 / 24, 0.0),
    (17.75 / 24, 0.0),
    (19 / 24, 1.0),
    (1.0, 1.0),
)


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

    @property
    def is_daylight(self) -> bool:
        t = self.time_of_day
        return DAYLIGHT_START <= t < DAYLIGHT_END

    @property
    def darkness(self) -> float:
        """0 at noon, 1 at night. Lerps through dawn and dusk."""
        return darkness_at(self.time_of_day)

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


def darkness_at(tod: float) -> float:
    t = tod % 1.0
    keys = _DARKNESS_KEYS
    for i in range(len(keys) - 1):
        t0, d0 = keys[i]
        t1, d1 = keys[i + 1]
        if t0 <= t < t1 or (i == len(keys) - 2 and t >= t0):
            if d0 == d1:
                return d0
            u = (t - t0) / max(t1 - t0, 1e-9)
            u = u * u * (3.0 - 2.0 * u)
            return d0 * (1.0 - u) + d1 * u
    return 1.0
