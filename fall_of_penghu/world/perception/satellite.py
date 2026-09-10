from __future__ import annotations

from dataclasses import dataclass

from fall_of_penghu.world.clock import CALENDAR_DAY_S, darkness_at

# Matches clock darkness keys: full night 19:00–04:00.
_NIGHT_START = 19.0 / 24.0
_NIGHT_END = 4.0 / 24.0


@dataclass(frozen=True)
class SatelliteStatus:
    active: bool
    remain_calendar_s: float
    until_start_calendar_s: float


class SatelliteWindows:
    """Repeating calendar windows, or the whole civil day when always_day."""

    def __init__(
        self,
        *,
        period_s: float,
        duration_s: float,
        offset_s: float = 0.0,
        always_day: bool = False,
    ) -> None:
        self.period_s = max(float(period_s), 1.0)
        self.duration_s = min(max(float(duration_s), 0.0), self.period_s)
        self.offset_s = float(offset_s)
        self.always_day = bool(always_day)

    def status(self, calendar_time: float) -> SatelliteStatus:
        if self.always_day:
            return _daylight_status(calendar_time)
        t = (calendar_time - self.offset_s) % self.period_s
        if t < self.duration_s:
            return SatelliteStatus(True, self.duration_s - t, 0.0)
        return SatelliteStatus(False, 0.0, self.period_s - t)


def _daylight_status(calendar_time: float) -> SatelliteStatus:
    tod = (calendar_time / CALENDAR_DAY_S) % 1.0
    if darkness_at(tod) >= 1.0 - 1e-9:
        return SatelliteStatus(False, 0.0, _until_tod(tod, _NIGHT_END))
    return SatelliteStatus(True, _until_tod(tod, _NIGHT_START), 0.0)


def _until_tod(tod: float, target: float) -> float:
    delta = (target - tod) % 1.0
    return delta * CALENDAR_DAY_S


def format_calendar_span(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes:02d}:{secs:02d}"
