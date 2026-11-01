"""Garmin transport and record helpers for morning recovery reads."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.canonical.section_items import merge_records
from backend.providers import garmin_performance_fields as garmin_perf_fields
from backend.providers.garmin_fields import first_present as _first_present

ExternalCall = Callable[[str, str, Callable[[], Any], dict[str, Any] | None], Any]


def fetch_morning_body_battery(
    client: Any,
    checkin_date: date,
    *,
    tokenstore: str,
    email_configured: bool,
    tokenstore_exists: bool,
    profile_timezone: str,
    fallback_zone: tzinfo | None,
    external_call: ExternalCall,
    sleep_bounds: Callable[[Any], tuple[Any, Any]],
) -> tuple[Any, list[Any]]:
    """Fetch the sleep record and matching Body Battery window."""
    mfa_status, _ = external_call(
        "garmin",
        "login",
        lambda: client.login(tokenstore),
        {
            "email_configured": email_configured,
            "tokenstore_exists": tokenstore_exists,
        },
    )
    if mfa_status:
        return {}, []
    sleep_payload = external_call(
        "garmin",
        "morning_sleep",
        lambda: client.get_sleep_data(checkin_date.isoformat()),
        {"date": checkin_date.isoformat()},
    )
    sleep_start, _ = sleep_bounds(sleep_payload)
    if sleep_start is None:
        return sleep_payload, []
    try:
        local_zone = ZoneInfo(profile_timezone)
    except ZoneInfoNotFoundError, ValueError:
        local_zone = fallback_zone or UTC
    range_start = sleep_start.astimezone(local_zone).date()
    records = external_call(
        "garmin",
        "body_battery",
        lambda: client.get_body_battery(
            range_start.isoformat(), checkin_date.isoformat()
        ),
        {
            "window_start": range_start.isoformat(),
            "window_end": checkin_date.isoformat(),
            "purpose": "morning_recovery",
        },
    )
    return sleep_payload, records if isinstance(records, list) else []


def morning_sleep_element(
    checkin_date: date, sleep_payload: Any
) -> dict[str, Any] | None:
    """Return the fetched night as a ``sleep`` section element, keyed by its date.

    The element holds the ``dailySleepDTO`` of the morning sleep read under the
    check-in date, the identity the daily sleep read gives the same night.
    """
    dto = (
        sleep_payload.get("dailySleepDTO") if isinstance(sleep_payload, dict) else None
    )
    if not isinstance(dto, dict) or not dto:
        return None
    return {"calendarDate": checkin_date.isoformat(), "dailySleepDTO": dto}


def merge_garmin_records(incoming: Any, previous: Any) -> list[Any]:
    """Merge bounded-window results without discarding older snapshot records."""
    return merge_records(incoming, previous)


def latest_garmin_record(value: Any) -> dict[str, Any]:
    """Return one dated Garmin record without exposing the complete range payload."""
    if not isinstance(value, (dict, list)):
        return {}
    records: list[dict[str, Any]] = []
    pending: list[Any] = [value]
    visited = 0
    while pending and visited < 2000:
        current = pending.pop()
        visited += 1
        if isinstance(current, dict):
            if _first_present(current, garmin_perf_fields.RECORD_IDENTITY_KEYS):
                records.append(current)
            pending.extend(
                item for item in current.values() if isinstance(item, (dict, list))
            )
        elif isinstance(current, list):
            pending.extend(
                item for item in current[:500] if isinstance(item, (dict, list))
            )
    if records:
        return max(
            records,
            key=lambda item: (
                1
                if _first_present(item, garmin_perf_fields.RECORD_TIMESTAMP_KEYS)
                else 0,
                str(
                    _first_present(item, garmin_perf_fields.RECORD_IDENTITY_KEYS) or ""
                ),
            ),
            default={},
        )
    return value if isinstance(value, dict) else {}
