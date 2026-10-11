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
"""

from __future__ import annotations

from datetime import UTC, date, datetime, tzinfo
from typing import Final

MAX_PROVIDER_DATETIME_LENGTH: Final = 64
_DATE_PART_LENGTH: Final = 10  # "YYYY-MM-DD"
_DATE_TIME_SEPARATORS: Final = ("T", " ")


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
