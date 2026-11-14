"""Observation days of a fetched Garmin payload's sections.

The sync stamps each section's freshness with the newest day these find, before
the payload is stored.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.providers import garmin_performance_fields as garmin_perf_fields

_OBSERVATION_DATE_FIELDS = garmin_perf_fields.OBSERVATION_DATE_FIELDS


def _garmin_record_date(value: Any) -> str | None:
    """Return a validated ISO date from a Garmin date or timestamp value."""
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value <= 100_000_000_000:
            return None
        try:
            return datetime.fromtimestamp(float(value) / 1000, UTC).date().isoformat()
        except OverflowError, OSError, ValueError:
            return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        return date.fromisoformat(iso_date_prefix(text)).isoformat()
    except AttributeError, TypeError, ValueError:
        return None


def garmin_record_observation_date(record: dict[str, Any]) -> str | None:
    """Return the first valid observation date represented by one record."""
    if not isinstance(record, dict):
        return None
    for field in _OBSERVATION_DATE_FIELDS:
        value = record.get(field)
        if value not in (None, ""):
            return _garmin_record_date(value)
    return None


def _garmin_nested_records(record: dict[str, Any]) -> list[Any]:
    return [item for item in record.values() if isinstance(item, (dict, list))]


def garmin_source_observed_at(value: Any) -> str | None:
    """Return the newest valid observation date in nested Garmin data."""
    dates: list[str] = []
    pending = [value]
    visited: set[int] = set()
    while pending:
        record = pending.pop()
        if isinstance(record, dict):
            marker = id(record)
            if marker in visited:
                continue
            visited.add(marker)
            observed_at = garmin_record_observation_date(record)
            if observed_at:
                dates.append(observed_at)
            pending.extend(_garmin_nested_records(record))
        elif isinstance(record, list):
            marker = id(record)
            if marker in visited:
                continue
            visited.add(marker)
            pending.extend(record)
    return max(dates, default=None)


def garmin_sleep_observed_at(value: Any) -> str | None:
    """Return the newest primary ``calendarDate`` of the sleep records.

    Nested timestamps such as the wake time can fall on the next day, which
    would make the night look observed in the future, so only the record's own
    ``calendarDate`` counts. Records without one fall back to the nested search.
    """
    records = value if isinstance(value, list) else [value]
    dates = [
        observed_at
        for record in records
        if (observed_at := _sleep_calendar_date(record))
    ]
    return max(dates, default=None) or garmin_source_observed_at(value)


def _sleep_calendar_date(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    nested = record.get("dailySleepDTO")
    nested = nested if isinstance(nested, dict) else {}
    return _garmin_record_date(
        record.get(garmin_perf_fields.CALENDAR_DATE)
        or nested.get(garmin_perf_fields.CALENDAR_DATE)
    )
