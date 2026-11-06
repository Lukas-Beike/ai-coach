"""Read one bounded window of Garmin wellness history for the one-off backfill.

The window yields the sections the regular sync stores, so the existing mappers
read them alike:

* ``sleep``: one full night element per night (``{"calendarDate", "dailySleepDTO"}``,
  the shape of ``wrap_daily_sleep``), so SpO2, respiration and sleeping heart rate
  come with duration and score. The range read names the nights; a night whose
  range row lacks the night values is read alone through ``get_sleep_data`` (the
  SDK range returns only sleep statistics). Both transports serve both calls.
* ``hrv``: the HRV range's last-night summaries.
* ``daily_stats``: the daily summaries, read in ranges of at most 31 days.
* ``resting_hr``: one ``{"calendarDate", "restingHeartRate"}`` row per summary day
  with a resting value, so the history needs no read per day.
* ``weight``: the raw weigh-in range response.

A failed source is recorded in ``errors`` and marked incomplete; the others stay.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, timedelta
from functools import partial
from typing import Any, Final

from backend.canonical.section_items import record_day
from backend.providers.descriptors import GARMIN_ID
from backend.providers.garmin import (
    ExternalCall,
    Redact,
    normalize_range_records,
    preserve_weight_response,
)
from backend.providers.garmin_personal import wrap_daily_sleep

DAILY_SUMMARY_RANGE_DAYS: Final = 31
# The sleep element fields that carry the night values (Garmin health mapper 18).
SLEEP_NIGHT_FIELDS: Final = (
    "averageSpO2Value",
    "lowestSpO2Value",
    "averageRespirationValue",
    "avgHeartRate",
)
WELLNESS_HISTORY_SOURCES: Final = ("sleep", "hrv", "daily_stats", "weight")
# Weight range keys that list readings; the SDK and Personal API share them.
_WEIGHT_READING_KEYS: Final = ("dailyWeightSummaries", "dateWeightList", "weighIns")


def has_night_values(element: object) -> bool:
    """Return whether a stored or fetched sleep element carries a night value."""
    if not isinstance(element, Mapping):
        return False
    nested = element.get("dailySleepDTO")
    for record in (element, nested if isinstance(nested, Mapping) else {}):
        for name in SLEEP_NIGHT_FIELDS:
            value = record.get(name)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value > 0
            ):
                return True
    return False


def collect_wellness_history(
    client: Any,
    start: date,
    end: date,
    *,
    external_call: ExternalCall,
    redact: Redact,
) -> dict[str, Any]:
    """Return the wellness sections of ``start``..``end`` (inclusive days)."""
    readers: dict[str, Callable[[Any, date, date, ExternalCall], list[Any]]] = {
        "sleep": _sleep_nights,
        "hrv": _hrv_summaries,
        "daily_stats": _daily_summaries,
        "weight": _weigh_ins,
    }
    payload: dict[str, Any] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "errors": [],
    }
    pagination: dict[str, dict[str, Any]] = {}
    for source, read in readers.items():
        try:
            records = read(client, start, end, external_call)
        except Exception as exc:  # noqa: BLE001 - SDK errors vary; keep the other sources.
            pagination[source] = {"complete": False, "records": 0}
            payload["errors"].append(
                {"source": source, "message": redact(str(exc))[:500]}
            )
            continue
        payload[source] = records
        pagination[source] = {"complete": True, "records": len(records)}
    if pagination["daily_stats"]["complete"]:
        payload["resting_hr"] = _resting_rows(payload["daily_stats"])
    payload["provider_sync"] = {"pagination": pagination}
    return payload


def _in_window(record: object, start: date, end: date) -> bool:
    day = record_day(record)
    return day is not None and start.isoformat() <= day <= end.isoformat()


def _sleep_nights(
    client: Any, start: date, end: date, external_call: ExternalCall
) -> list[Any]:
    value = external_call(
        GARMIN_ID,
        "sleep",
        lambda: client.get_sleep_daily(start.isoformat(), end.isoformat()),
        {"window_start": start.isoformat(), "window_end": end.isoformat()},
    )
    rows = [] if value is None else normalize_range_records("sleep", value)
    nights: list[Any] = []
    for row in rows:
        if not _in_window(row, start, end):
            continue
        if has_night_values(row):
            nights.append(row)
            continue
        day = str(record_day(row))
        full = external_call(
            GARMIN_ID,
            "sleep_night",
            partial(client.get_sleep_data, day),
            {"date": day},
        )
        dto = full.get("dailySleepDTO") if isinstance(full, Mapping) else None
        element = wrap_daily_sleep(dict(dto)) if isinstance(dto, Mapping) else None
        nights.append(element if element is not None else row)
    return nights


def _hrv_summaries(
    client: Any, start: date, end: date, external_call: ExternalCall
) -> list[Any]:
    value = external_call(
        GARMIN_ID,
        "hrv",
        lambda: client.get_hrv_data_range(start.isoformat(), end.isoformat()),
        {"window_start": start.isoformat(), "window_end": end.isoformat()},
    )
    if value is None:
        return []
    return [
        row
        for row in normalize_range_records("hrv", value)
        if _in_window(row, start, end)
    ]


def _daily_summaries(
    client: Any, start: date, end: date, external_call: ExternalCall
) -> list[Any]:
    rows: list[Any] = []
    first = start
    while first <= end:
        last = min(first + timedelta(days=DAILY_SUMMARY_RANGE_DAYS - 1), end)
        value = external_call(
            GARMIN_ID,
            "daily_stats",
            partial(client.get_daily_summaries, first.isoformat(), last.isoformat()),
            {"window_start": first.isoformat(), "window_end": last.isoformat()},
        )
        data = value.get("data") if isinstance(value, Mapping) else value
        if data is not None:
            rows.extend(
                row
                for row in normalize_range_records("daily_stats", data)
                if _in_window(row, start, end)
            )
        first = last + timedelta(days=1)
    return rows


def _weigh_ins(
    client: Any, start: date, end: date, external_call: ExternalCall
) -> list[Any]:
    value = external_call(
        GARMIN_ID,
        "weight",
        lambda: client.get_weigh_ins(start.isoformat(), end.isoformat()),
        {"window_start": start.isoformat(), "window_end": end.isoformat()},
    )
    if value is None or (
        isinstance(value, Mapping)
        and not any(value.get(key) for key in _WEIGHT_READING_KEYS)
    ):
        # A range without weigh-ins is no record: an empty envelope is not stored.
        return []
    return preserve_weight_response(value)


def _resting_value(row: Mapping[str, Any]) -> float | None:
    heart_rate = row.get("heartRate")
    for value in (
        row.get("restingHeartRate"),
        heart_rate.get("restingValue") if isinstance(heart_rate, Mapping) else None,
    ):
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0
        ):
            return float(value)
    return None


def _resting_rows(summaries: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in summaries:
        if not isinstance(row, Mapping):
            continue
        day = record_day(row)
        value = _resting_value(row)
        if day is not None and value is not None:
            rows.append({"calendarDate": day, "restingHeartRate": value})
    return rows
