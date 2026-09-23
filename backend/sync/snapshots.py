"""Provider snapshot merges and connection-taking persistence operations."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend.activities.duplicates import deduplicate_api_records


def merge_performance_snapshot(
    current: dict[str, Any] | None, performance: dict[str, Any]
) -> dict[str, Any]:
    """Apply performance-owned fields to the latest complete provider snapshot."""
    merged = dict(current or {})
    merged["synced_at"] = performance["synced_at"]
    merged["athlete"] = performance.get("athlete", {})
    merged["recent_wellness"] = deduplicate_api_records(
        list(performance.get("recent_wellness") or [])
        + list(merged.get("recent_wellness") or [])
    )
    raw = dict(merged.get("raw_provider_data") or {})
    incoming_raw = performance.get("raw_provider_data") or {}
    if "athlete" in incoming_raw:
        raw["athlete"] = incoming_raw["athlete"]
    raw["wellness"] = deduplicate_api_records(
        list(incoming_raw.get("wellness") or []) + list(raw.get("wellness") or [])
    )
    merged["raw_provider_data"] = raw
    provider_sync = dict(merged.get("provider_sync") or {})
    pagination = dict(provider_sync.get("pagination") or {})
    incoming_pagination = (performance.get("provider_sync") or {}).get(
        "pagination"
    ) or {}
    if "performance_wellness" in incoming_pagination:
        pagination["performance_wellness"] = incoming_pagination["performance_wellness"]
    provider_sync["pagination"] = pagination
    merged["provider_sync"] = provider_sync
    return merged


def merge_historical_snapshot(
    current: dict[str, Any] | None, historical: dict[str, Any]
) -> dict[str, Any]:
    """Merge historical provider collections without replacing the current read model."""
    if not isinstance(current, dict):
        return historical
    merged = dict(current)
    current_raw = (
        current.get("raw_provider_data")
        if isinstance(current.get("raw_provider_data"), dict)
        else {}
    )
    historical_raw = (
        historical.get("raw_provider_data")
        if isinstance(historical.get("raw_provider_data"), dict)
        else {}
    )
    merged["raw_provider_data"] = {
        "athlete": current_raw.get("athlete") or historical_raw.get("athlete") or {},
        "activities": deduplicate_api_records(
            (current_raw.get("activities") or [])
            + (historical_raw.get("activities") or [])
        ),
        "wellness": deduplicate_api_records(
            (current_raw.get("wellness") or []) + (historical_raw.get("wellness") or [])
        ),
        "upcoming_calendar": current_raw.get("upcoming_calendar") or [],
    }
    merged["historical_sync"] = {
        "synced_at": historical.get("synced_at"),
        "window": historical.get("provider_sync", {}).get("calendar_window", {})
        if isinstance(historical.get("provider_sync"), dict)
        else {},
    }
    return merged


def latest_snapshot(db: Any, repository: Any) -> dict[str, Any] | None:
    payload = repository.latest_payload(db)
    return json.loads(payload) if payload else None


def save_snapshot(
    db: Any,
    snapshot: dict[str, Any],
    repository: Any,
    *,
    update_full_sync: bool,
    activity_days: int | None,
    set_value: Callable[[str, str, Any], None],
) -> None:
    repository.save(db, snapshot, snapshot["synced_at"])
    if update_full_sync:
        set_value("last_sync_at", snapshot["synced_at"], db)
        set_value("last_sync_error", "", db)
        if activity_days is not None:
            set_value("last_sync_activity_days", str(activity_days), db)
    else:
        set_value("last_performance_refresh_at", snapshot["synced_at"], db)
