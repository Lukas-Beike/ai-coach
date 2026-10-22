"""Garmin transport and record helpers for morning recovery reads."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.canonical.section_items import merge_records

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


def merge_garmin_records(incoming: Any, previous: Any) -> list[Any]:
    """Merge bounded-window results without discarding older snapshot records."""
    return merge_records(incoming, previous)
