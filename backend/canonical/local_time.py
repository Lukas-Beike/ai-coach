"""Local wall-clock rules for provider datetimes.

Providers send timestamps either with an offset or as naive wall-clock text in
the athlete's zone. Naive wall times are localised as follows:

* an ambiguous time (autumn overlap) takes its first occurrence, the
  summer-time offset (fold=0);
* a non-existent time (spring gap) moves forward to the instant it names under
  the offset in force before the transition, so 02:30 on a spring-forward day
  becomes 03:30 with the summer-time offset.

A UTC round trip implements both rules, so no separate gap or overlap detection
is needed.

Aware inputs keep the instant and offset they were sent with. They are not
converted to the athlete's zone at parse time; use ``local_date`` to read the
calendar date in a zone.

An activity can carry its own UTC offset, the one in force where and when it was
recorded. ``wall_time`` then reads its wall clock and calendar date in that
offset, so travel does not move it to another day; without one the athlete zone
applies.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_PROVIDER_DATETIME_LENGTH: Final = 64
_DATE_PART_LENGTH: Final = 10  # "YYYY-MM-DD"
_DATE_TIME_SEPARATORS: Final = ("T", " ")
# Every UTC offset in use lies within +-14 hours and on a quarter hour.
MAX_UTC_OFFSET_MINUTES: Final = 14 * 60
UTC_OFFSET_STEP_MINUTES: Final = 15


def localize_wall_time(value: datetime, zone: tzinfo) -> datetime:
    """Return aware ``value`` unchanged, or read a naive wall time in ``zone``.

    The ``fold`` attribute of a naive input is ignored, so an ambiguous time
    always resolves to its first occurrence. Edge-of-range values can raise
    OverflowError during conversion, as datetime arithmetic does.
    """
    if value.utcoffset() is not None:
        return value
    wall = value.replace(tzinfo=zone, fold=0)
    return wall.astimezone(UTC).astimezone(zone)


def parse_provider_datetime(text: object, zone: tzinfo) -> datetime | None:
    """Parse provider ISO text into an aware datetime, or return None.

    Accepts ``T`` or one space between date and time, and a trailing ``Z`` or
    an explicit offset. Date-only text is rejected because a provider timestamp
    must name a time. Naive text is localised with ``localize_wall_time``.
    Malformed, empty, non-text or unrepresentable input returns None and never
    raises. An instant that cannot be expressed in ``zone`` (near the edge of
    datetime's range) is unrepresentable, so it returns None too; that keeps
    every returned value usable by ``local_date`` with the same zone.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if len(stripped) <= _DATE_PART_LENGTH or (
        len(stripped) > MAX_PROVIDER_DATETIME_LENGTH
    ):
        return None
    if stripped[_DATE_PART_LENGTH] not in _DATE_TIME_SEPARATORS:
        return None
    try:
        parsed = localize_wall_time(datetime.fromisoformat(stripped), zone)
        parsed.astimezone(zone)  # Rejects instants outside datetime's range.
    except OverflowError, ValueError:
        return None
    return parsed


def local_date(value: datetime, zone: tzinfo) -> date:
    """Return the calendar date of an aware datetime as seen in ``zone``.

    Naive input is a programming error rather than provider input, so it raises
    ValueError. Values at the edge of datetime's range can raise OverflowError
    during conversion; ``parse_provider_datetime`` filters those out.
    """
    if value.utcoffset() is None:
        raise ValueError("local_date requires a timezone-aware datetime")
    return value.astimezone(zone).date()


def valid_offset_minutes(value: object) -> bool:
    """Return whether ``value`` is a UTC offset in minutes, as activities carry it."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and abs(value) <= MAX_UTC_OFFSET_MINUTES
        and value % UTC_OFFSET_STEP_MINUTES == 0
    )


def _rounded_offset(seconds: float) -> int | None:
    step = UTC_OFFSET_STEP_MINUTES * 60
    minutes = round(seconds / step) * UTC_OFFSET_STEP_MINUTES
    return minutes if abs(minutes) <= MAX_UTC_OFFSET_MINUTES else None


def wall_clock_offset_minutes(local_text: object, instant: datetime) -> int | None:
    """Return the UTC offset that local wall-clock text shows for ``instant``.

    ``local_text`` is the provider's local start of the same moment, such as
    Garmin's ``startTimeLocal``. Naive text gives the difference to the UTC
    instant, rounded to a quarter hour; aware text gives its own offset. Text
    that does not parse, or an offset beyond +-14 hours, returns None.
    """
    parsed = parse_provider_datetime(local_text, UTC)
    if parsed is None or instant.utcoffset() is None:
        return None
    if isinstance(local_text, str) and _names_offset(local_text):
        offset = parsed.utcoffset()
        return None if offset is None else _rounded_offset(offset.total_seconds())
    utc_wall = instant.astimezone(UTC).replace(tzinfo=None)
    return _rounded_offset((parsed.replace(tzinfo=None) - utc_wall).total_seconds())


def _names_offset(text: str) -> bool:
    time_part = text.strip()[_DATE_PART_LENGTH + 1 :]
    return time_part.endswith(("Z", "z")) or "+" in time_part or "-" in time_part


def zone_offset_minutes(name: object, instant: datetime) -> int | None:
    """Return the UTC offset of IANA zone ``name`` at ``instant``, or None.

    A name that is not a known IANA zone, or a naive instant, returns None.
    """
    if not isinstance(name, str) or not name.strip() or instant.utcoffset() is None:
        return None
    try:
        offset = instant.astimezone(ZoneInfo(name.strip())).utcoffset()
    except ValueError, OverflowError, ZoneInfoNotFoundError:
        return None
    return None if offset is None else _rounded_offset(offset.total_seconds())


def wall_time(instant: datetime, zone: tzinfo, offset_minutes: int | None) -> datetime:
    """Return ``instant`` on the wall clock of its own offset, else of ``zone``.

    The result is aware; its ``date()`` is the day the activity was lived.
    """
    if offset_minutes is None:
        return instant.astimezone(zone)
    return instant.astimezone(timezone(timedelta(minutes=offset_minutes)))
