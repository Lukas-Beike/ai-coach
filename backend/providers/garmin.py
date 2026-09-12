"""Dependency-light Garmin collection adapter.

The application owns authentication, persistence, locking, and redaction.
This module only coordinates calls on an already authenticated Garmin client
and returns a bounded, provider-labelled collection result.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


ExternalCall = Callable[[str, str, Callable[[], Any], dict[str, Any] | None], Any]
Redact = Callable[[str], str]
WarningLogger = Callable[[str, str, BaseException], None]
StatusCallback = Callable[[str], None]
CapabilityAllowed = Callable[[str], bool]
CapabilityFailure = Callable[[str, BaseException], None]
CapabilitySuccess = Callable[[str], None]


@dataclass(frozen=True)
class GarminCollectionOptions:
    include_recovery: bool = True
    include_current_metrics: bool = True


def normalize_range_records(source: str, value: Any) -> list[dict[str, Any]]:
    """Normalize the current SDK range contracts, rejecting unknown response shapes."""
    if source == "hrv" and isinstance(value, dict) and "hrvSummaries" in value:
        value = value["hrvSummaries"]
    if not isinstance(value, list) or any(not isinstance(record, dict) for record in value):
        raise ValueError(f"Invalid Garmin {source} range response")
    return value


def _add_error(payload: dict[str, Any], source: str, exc: BaseException, redact: Redact,
               warn: WarningLogger | None) -> None:
    message = redact(str(exc))[:500]
    payload["errors"].append({"source": source, "message": message})
    if warn:
        warn(source, message, exc)


def _fetch_range(payload: dict[str, Any], pagination: dict[str, dict[str, Any]], key: str, fetch: Any,
                 window_start: date, window_end: date, windows_count: int, external_call: ExternalCall,
                 redact: Redact, warn: WarningLogger | None, capability_allowed: CapabilityAllowed | None,
                 capability_failure: CapabilityFailure | None, capability_success: CapabilitySuccess | None) -> None:
    stats = pagination.setdefault(key, {"windows": windows_count, "records": 0, "complete": True})
    if capability_allowed is not None and not capability_allowed(key):
        stats.update({"complete": False, "paused": True, "error": "capability_paused"})
        return
    try:
        value = external_call(
            "garmin", key, lambda: fetch(window_start.isoformat(), window_end.isoformat()),
            {"window_start": window_start.isoformat(), "window_end": window_end.isoformat()},
        )
        records = normalize_range_records(key, value)
        payload.setdefault(key, []).extend(records)
        stats["records"] = int(stats["records"]) + len(records)
        stats.setdefault("completed_windows", []).append({"start": window_start.isoformat(), "end": window_end.isoformat()})
        if capability_success:
            capability_success(key)
    except Exception as exc:
        stats["complete"] = False
        stats["error"] = redact(str(exc))[:500]
        if capability_failure:
            capability_failure(key, exc)
        _add_error(payload, key, exc, redact, warn)


def _collect_ranges(client: Any, windows: list[tuple[date, date]], payload: dict[str, Any],
                    pagination: dict[str, dict[str, Any]], include_recovery: bool, status: StatusCallback | None,
                    external_call: ExternalCall, redact: Redact, warn: WarningLogger | None,
                    capability_allowed: CapabilityAllowed | None, capability_failure: CapabilityFailure | None,
                    capability_success: CapabilitySuccess | None) -> None:
    for index, (window_start, window_end) in enumerate(windows, 1):
        if status:
            status(f"Garmin: Zeitraum {index}/{len(windows)} wird synchronisiert…")
        requests = [("activities", client.get_activities_by_date)]
        if include_recovery:
            requests[0:0] = [("sleep", client.get_sleep_daily), ("hrv", client.get_hrv_data_range)]
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="garmin-range") as executor:
            futures = [executor.submit(
                _fetch_range, payload, pagination, key, fetch, window_start, window_end, len(windows),
                external_call, redact, warn, capability_allowed, capability_failure, capability_success
            ) for key, fetch in requests]
            for future in futures:
                future.result()


def _collect_daily_stats(client: Any, windows: list[tuple[date, date]], payload: dict[str, Any],
                         pagination: dict[str, dict[str, Any]], external_call: ExternalCall, redact: Redact,
                         warn: WarningLogger | None) -> None:
    fetch = getattr(client, "get_user_summary", None)
    if not callable(fetch):
        return
    stats = pagination.setdefault("daily_stats", {"windows": len(windows), "records": 0, "complete": True})
    for window_start, window_end in windows:
        current = window_start
        while current <= window_end:
            try:
                value = external_call("garmin", "daily_stats", lambda current=current: fetch(current.isoformat()), {"date": current.isoformat()})
                records = value if isinstance(value, list) else [value]
                if any(not isinstance(record, dict) for record in records):
                    raise ValueError("Invalid Garmin daily_stats response")
                for record in records:
                    if not any(key in record for key in ("calendarDate", "summaryDate", "date")):
                        record = {"calendarDate": current.isoformat(), **record}
                    payload.setdefault("daily_stats", []).append(record)
                    stats["records"] = int(stats["records"]) + 1
            except Exception as exc:
                stats["complete"] = False
                stats["error"] = redact(str(exc))[:500]
                _add_error(payload, "daily_stats", exc, redact, warn)
            current += timedelta(days=1)


def _collect_resting_hr(client: Any, windows: list[tuple[date, date]], payload: dict[str, Any],
                        pagination: dict[str, dict[str, Any]], external_call: ExternalCall, redact: Redact,
                        warn: WarningLogger | None) -> None:
    fetch = getattr(client, "get_heart_rates", None)
    if not callable(fetch):
        return
    stats = pagination.setdefault("resting_hr", {"windows": len(windows), "records": 0, "complete": True})
    for window_start, window_end in windows:
        current = window_start
        while current <= window_end:
            try:
                value = external_call("garmin", "resting_hr", lambda current=current: fetch(current.isoformat()), {"date": current.isoformat()})
                if not isinstance(value, dict):
                    raise ValueError("Invalid Garmin resting_hr response")
                if not any(key in value for key in ("calendarDate", "date", "summaryDate")):
                    value = {"calendarDate": current.isoformat(), **value}
                payload.setdefault("resting_hr", []).append(value)
                stats["records"] = int(stats["records"]) + 1
            except Exception as exc:
                stats["complete"] = False
                stats["error"] = redact(str(exc))[:500]
                _add_error(payload, "resting_hr", exc, redact, warn)
            current += timedelta(days=1)


def _collect_current_metrics(client: Any, today: date, payload: dict[str, Any], external_call: ExternalCall,
                             redact: Redact, warn: WarningLogger | None) -> None:
    fetch = getattr(client, "get_heart_rate_zones", None)
    if callable(fetch):
        _collect_optional_metric(payload, "heart_rate_zones", fetch, None, external_call, redact, warn)
    max_metrics_start = today - timedelta(days=89)
    max_metrics_range = getattr(client, "get_max_metrics_range", None)
    metrics = (
        ("readiness", lambda: client.get_training_readiness(today.isoformat()), {"date": today.isoformat()}),
        ("race_predictions", client.get_race_predictions, None),
        ("max_metrics", lambda: client.get_max_metrics_range(max_metrics_start.isoformat(), today.isoformat()),
         {"window_start": max_metrics_start.isoformat(), "window_end": today.isoformat(), "range_supported": callable(max_metrics_range)}),
    )
    for key, metric_fetch, details in metrics:
        _collect_optional_metric(payload, key, metric_fetch, details, external_call, redact, warn)
    fetch = getattr(client, "get_cycling_ftp", None)
    if callable(fetch):
        _collect_optional_metric(payload, "cycling_ftp", fetch, None, external_call, redact, warn)
    fetch = getattr(client, "get_lactate_threshold", None)
    if callable(fetch):
        _collect_optional_metric(payload, "running_threshold", lambda: fetch(latest=True), {"latest": True}, external_call, redact, warn)
    fetch = getattr(client, "get_weigh_ins", None)
    if callable(fetch):
        weight_start = today - timedelta(days=89)
        _collect_optional_metric(payload, "weight", lambda: fetch(weight_start.isoformat(), today.isoformat()),
                                 {"window_start": weight_start.isoformat(), "window_end": today.isoformat()},
                                 external_call, redact, warn)


def _collect_optional_metric(payload: dict[str, Any], key: str, fetch: Any, details: Any,
                             external_call: ExternalCall, redact: Redact, warn: WarningLogger | None) -> None:
    try:
        payload[key] = external_call("garmin", key, fetch, details)
    except Exception as exc:
        _add_error(payload, key, exc, redact, warn)


def _validate_current_metrics(payload: dict[str, Any], redact: Redact, warn: WarningLogger | None) -> None:
    keys = ("heart_rate_zones", "readiness", "race_predictions", "max_metrics", "cycling_ftp",
            "running_threshold", "weight")
    for key in keys:
        if key in payload and not isinstance(payload[key], (dict, list)):
            payload.pop(key)
            _add_error(payload, key, ValueError(f"Invalid Garmin {key} response"), redact, warn)


def collect_garmin_data(
    client: Any,
    windows: Iterable[tuple[date, date]],
    *,
    start: date,
    today: date,
    synced_at: str,
    external_call: ExternalCall,
    redact: Redact,
    warn: WarningLogger | None = None,
    status: StatusCallback | None = None,
    capability_allowed: CapabilityAllowed | None = None,
    capability_failure: CapabilityFailure | None = None,
    capability_success: CapabilitySuccess | None = None,
    options: GarminCollectionOptions | None = None,
) -> dict[str, Any]:
    """Collect bounded Garmin data through injected application boundaries."""
    windows = list(windows)
    collection_options = options or GarminCollectionOptions()
    payload: dict[str, Any] = {"synced_at": synced_at, "start": start.isoformat(), "end": today.isoformat(), "errors": []}
    pagination: dict[str, dict[str, Any]] = {}
    _collect_ranges(client, windows, payload, pagination, collection_options.include_recovery, status, external_call,
                    redact, warn, capability_allowed, capability_failure, capability_success)
    if collection_options.include_recovery:
        _collect_daily_stats(client, windows, payload, pagination, external_call, redact, warn)
        _collect_resting_hr(client, windows, payload, pagination, external_call, redact, warn)
    if collection_options.include_current_metrics:
        _collect_current_metrics(client, today, payload, external_call, redact, warn)
    payload["provider_sync"] = {"pagination": pagination}
    _validate_current_metrics(payload, redact, warn)
    return payload

