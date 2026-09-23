"""Pure projections for public Intervals.icu sync state."""

import json
from datetime import date, timedelta
from typing import Any


def calendar_window(
    snapshot: Any,
    *,
    today: date,
    history_days: int,
    future_days: int,
) -> dict[str, str]:
    provider_sync = (
        snapshot.get("provider_sync", {}) if isinstance(snapshot, dict) else {}
    )
    window = (
        provider_sync.get("calendar_window")
        if isinstance(provider_sync, dict)
        else None
    )
    if isinstance(window, dict):
        return window
    return {
        "start": (today - timedelta(days=history_days)).isoformat(),
        "end": (today + timedelta(days=future_days)).isoformat(),
    }


def connection_state(
    configured: bool,
    running: bool,
    error: str | None,
    last_sync_at: str | None,
    last_library_sync_at: str | None,
) -> str:
    if not configured:
        return "not_configured"
    if running:
        return "syncing"
    if error:
        return "error"
    if last_sync_at or last_library_sync_at:
        return "connected"
    return "configured"


def decode_pagination(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def public_state(
    *,
    configured: bool,
    running: bool,
    status: str | None,
    last_sync_at: str | None,
    last_sync_error: str | None,
    last_library_sync_at: str | None,
    last_library_sync_error: str | None,
    pagination_value: Any,
    snapshot: Any,
    library_sync_state: dict[str, Any],
    today: date,
    history_days: int,
    future_days: int,
) -> dict[str, Any]:
    error = last_sync_error or last_library_sync_error
    return {
        "configured": configured,
        "state": connection_state(
            configured, running, error, last_sync_at, last_library_sync_at
        ),
        "running": running,
        "status": status,
        "last_sync_at": last_sync_at,
        "last_error": error,
        "pagination": decode_pagination(pagination_value),
        "calendar_window": calendar_window(
            snapshot,
            today=today,
            history_days=history_days,
            future_days=future_days,
        ),
        "library_sync": {
            "last_sync_at": last_library_sync_at,
            "last_error": last_library_sync_error,
            "state": library_sync_state,
        },
    }
