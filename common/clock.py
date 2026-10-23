"""Time helpers. Everything in the house runs on Perth time (no daylight saving).

`Clock.now()` is the one place code asks "what time is it?", so the simulator and
the tests can pretend it is 22:30 without touching the system clock.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

PERTH = ZoneInfo("Australia/Perth")


class Clock:
    """Real time, in Perth."""

    def now(self) -> datetime:
        return datetime.now(PERTH)


class SimClock(Clock):
    """A clock you can move. Time keeps ticking from wherever you set it."""

    def __init__(self) -> None:
        self._offset = timedelta(0)

    def now(self) -> datetime:
        return datetime.now(PERTH) + self._offset

    def set_time_of_day(self, hhmm: str) -> None:
        """Pretend it is HH:MM today (Perth). '22:30' -> 10:30 pm today."""
        target_t = parse_hhmm(hhmm)
        real = datetime.now(PERTH)
        target = real.replace(hour=target_t.hour, minute=target_t.minute, second=0, microsecond=0)
        self._offset = target - real

    def set(self, when: datetime) -> None:
        """Pretend it is exactly `when` (must be timezone-aware)."""
        self._offset = when - datetime.now(PERTH)

    def advance(self, **kwargs) -> None:
        """Jump forward, e.g. advance(hours=2)."""
        self._offset += timedelta(**kwargs)

    def reset(self) -> None:
        self._offset = timedelta(0)


def parse_hhmm(text: str) -> time:
    hours, minutes = text.strip().split(":")
    return time(int(hours), int(minutes))


def in_window(now: datetime, start: str, end: str) -> bool:
    """True if now's time-of-day is inside [start, end). Handles windows that
    wrap past midnight, e.g. quiet hours 21:00 -> 07:00."""
    t = now.astimezone(PERTH).time()
    s, e = parse_hhmm(start), parse_hhmm(end)
    if s <= e:
        return s <= t < e
    return t >= s or t < e


def day_key(now: datetime, day_starts_at: str = "04:00") -> date:
    """Which 'conversation day' a moment belongs to.

    The robot's day starts at 04:00 Perth by default, not midnight, so a chat
    at 23:50 that runs on to 00:20 stays in one conversation and one diary page.
    """
    local = now.astimezone(PERTH)
    start = parse_hhmm(day_starts_at)
    shifted = local - timedelta(hours=start.hour, minutes=start.minute)
    return shifted.date()


def friendly_time(now: datetime) -> str:
    """'Thursday 23 October, 7:40 pm' — rounded down to 5 minutes."""
    local = now.astimezone(PERTH)
    minute = local.minute - local.minute % 5
    hour12 = local.hour % 12 or 12
    ampm = "am" if local.hour < 12 else "pm"
    return f"{local:%A} {local.day} {local:%B}, {hour12}:{minute:02d} {ampm}"
