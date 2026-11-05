"""Map stored provider sleep rows to canonical sleep periods.

The intervals are the ones sleep timing variability reads (see
``backend.canonical.sleep_bounds``): every object of the row with a start and an
end field, the same instants counted once. A Garmin daily sleep record, or its
``dailySleepDTO``, is Garmin's main sleep of the day, so its interval is NIGHT
whatever the clock time; every other interval is UNKNOWN. Periods are never
classified by hour or length, and naps are not mapped.

Each period is dated by the provider's own day: Garmin's ``calendarDate`` of the
daily sleep record (the element or its ``dailySleepDTO``), or the Intervals.icu
wellness day, so sleep lands on the
same day as that day's wellness values and the activities recorded there. A
period keeps the ingest zone as its timezone only when the zone gives the same
wake date. Without a usable provider day within a day of the end's UTC date, the
local date of its end in the ingest zone applies. Its reported duration is the provider's sleep time from the same object, when that
is a plausible number of seconds.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, tzinfo
from typing import Any, Final
from zoneinfo import ZoneInfo

from backend.canonical.decimal_text import comma_decimal_float
from backend.canonical.domain_records import MAX_REPORTED_SLEEP_S, SleepPeriod
from backend.canonical.local_time import local_date
from backend.canonical.records import Provenance
from backend.canonical.sleep_bounds import SleepInterval, bounds_method, sleep_intervals
from backend.canonical.vocabulary import (
    ProviderId,
    RecordingOrigin,
    SleepKind,
    SourceKind,
)
from backend.providers.garmin_fields import GARMIN_SLEEP_DURATION_ALIASES

GARMIN_MAIN_SLEEP_KEY: Final = "dailySleepDTO"
GARMIN_CALENDAR_DATE_KEY: Final = "calendarDate"
_DAY_LENGTH: Final = 10  # "YYYY-MM-DD"
INTERVALS_SLEEP_DURATION_ALIASES: Final = ("sleepSecs",)
_LABELS: Final = {
    ProviderId.GARMIN: "Garmin Connect",
    ProviderId.INTERVALS: "Intervals.icu",
}


def _zone_name(zone: tzinfo) -> str | None:
    return zone.key if isinstance(zone, ZoneInfo) else None


def _reported_seconds(
    record: Mapping[str, Any], aliases: tuple[str, ...]
) -> float | None:
    for alias in aliases:
        if record.get(alias) in (None, ""):
            continue
        try:
            seconds = comma_decimal_float(record[alias])
        except TypeError, ValueError:
            return None
        if 0.0 <= seconds <= MAX_REPORTED_SLEEP_S:
            return seconds
        return None
    return None


def _provider_day(
    payload: object, main: object, provider: ProviderId, source_record_id: str
) -> date | None:
    """Return the day the provider files the sleep under, or None."""
    text: object = source_record_id
    if provider is ProviderId.GARMIN:
        # The daily sleep record is the element itself or its ``dailySleepDTO``.
        record = main if isinstance(main, Mapping) else payload
        text = (
            record.get(GARMIN_CALENDAR_DATE_KEY)
            if isinstance(record, Mapping)
            else None
        )
    if not isinstance(text, str) or len(text) != _DAY_LENGTH:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _wake_date(end: datetime, zone: tzinfo, provider_day: date | None) -> date:
    # Every UTC offset is under a day, so a lived wake day is within a day of the
    # UTC date; a provider day further away is not this period's.
    if provider_day is not None and abs((provider_day - end.date()).days) <= 1:
        return provider_day
    return local_date(end, zone)


def _distinct(intervals: list[SleepInterval]) -> list[SleepInterval]:
    """Keep one interval per instant pair (the last one, as sleep timing variability),
    then one per start, the first, because a provider period is keyed by its start."""
    by_bounds: dict[tuple[datetime, datetime], SleepInterval] = {}
    for interval in intervals:
        by_bounds[(interval.start, interval.end)] = interval
    by_start: dict[datetime, SleepInterval] = {}
    for interval in by_bounds.values():
        by_start.setdefault(interval.start, interval)
    return list(by_start.values())


def map_sleep_periods(
    payload: object,
    *,
    provider: ProviderId,
    source_record_id: str,
    retrieved_at: datetime,
    zone: tzinfo,
) -> tuple[SleepPeriod, ...]:
    """Return the sleep periods of one stored row of ``provider``.

    For Garmin, ``payload`` is a sleep section element; for Intervals.icu, a
    wellness row. An unusable row yields no period.
    """
    garmin = provider is ProviderId.GARMIN
    main = payload.get(GARMIN_MAIN_SLEEP_KEY) if isinstance(payload, Mapping) else None
    durations = (
        GARMIN_SLEEP_DURATION_ALIASES if garmin else INTERVALS_SLEEP_DURATION_ALIASES
    )
    provenance = Provenance(
        provider=provider,
        source_kind=SourceKind.DEVICE_MEASURED
        if garmin
        else SourceKind.PROVIDER_REPORTED,
        source_record_id=source_record_id,
        recorded_by=RecordingOrigin.GARMIN if garmin else RecordingOrigin.UNKNOWN,
        retrieved_at=retrieved_at,
        label=_LABELS[provider],
    )
    zone_name = _zone_name(zone)
    provider_day = _provider_day(payload, main, provider, source_record_id)
    periods: list[SleepPeriod] = []
    for interval in _distinct(list(sleep_intervals(payload))):
        is_main = garmin and (interval.depth == 0 or interval.record is main)
        try:
            wake_date = _wake_date(interval.end, zone, provider_day)
            in_zone = wake_date == local_date(interval.end, zone)
        except OverflowError:
            continue
        periods.append(
            SleepPeriod(
                start=interval.start,
                end=interval.end,
                wake_date=wake_date,
                kind=SleepKind.NIGHT if is_main else SleepKind.UNKNOWN,
                timezone=zone_name if in_zone else None,
                reported_duration_s=_reported_seconds(interval.record, durations),
                bounds_method=bounds_method(interval.start_field, interval.end_field),
                provenance=provenance,
            )
        )
    return tuple(periods)
