"""Dependency-light Garmin collection adapter.

The application owns authentication, persistence, locking, and redaction.
This module only coordinates calls on an already authenticated Garmin client
and returns a bounded, provider-labelled collection result.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Any


ExternalCall = Callable[[str, str, Callable[[], Any], dict[str, Any] | None], Any]
Redact = Callable[[str], str]
WarningLogger = Callable[[str, str, BaseException], None]
StatusCallback = Callable[[str], None]


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
) -> dict[str, Any]:
    """Collect Garmin ranges through injected application boundaries.

    No credentials, database connections, locks, or application globals are
    owned here. Individual source failures are retained only as redacted
    bounded messages so callers can persist the result safely.
    """
    windows = list(windows)
    payload: dict[str, Any] = {
        "synced_at": synced_at,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "errors": [],
    }
    pagination: dict[str, dict[str, Any]] = {}

    def add_error(source: str, exc: BaseException) -> None:
        message = redact(str(exc))[:500]
        payload["errors"].append({"source": source, "message": message})
        if warn:
            warn(source, message, exc)

    def fetch_range(key: str, fetch: Any, window_start: date, window_end: date) -> None:
        stats = pagination.setdefault(key, {"windows": len(windows), "records": 0, "complete": True})
        try:
            value = external_call(
                "garmin",
                key,
                lambda: fetch(window_start.isoformat(), window_end.isoformat()),
                {"window_start": window_start.isoformat(), "window_end": window_end.isoformat()},
            )
            if isinstance(value, list):
                payload.setdefault(key, []).extend(value)
                stats["records"] = int(stats["records"]) + len(value)
            elif value is not None and key not in payload:
                payload[key] = value
        except Exception as exc:
            stats["complete"] = False
            stats["error"] = redact(str(exc))[:500]
            add_error(key, exc)

    for index, (window_start, window_end) in enumerate(windows, 1):
        if status:
            status(f"Garmin: Zeitraum {index}/{len(windows)} wird synchronisiert…")
        fetch_range("sleep", client.get_sleep_daily, window_start, window_end)
        fetch_range("hrv", client.get_hrv_data_range, window_start, window_end)
        fetch_range("body_battery", client.get_body_battery, window_start, window_end)
        fetch_range("activities", client.get_activities_by_date, window_start, window_end)

    max_metrics_start = today - timedelta(days=89)
    max_metrics_range = getattr(client, "get_max_metrics_range", None)
    max_metrics_fetch = (
        (lambda: max_metrics_range(max_metrics_start.isoformat(), today.isoformat()))
        if callable(max_metrics_range)
        else (lambda: client.get_max_metrics(today.isoformat()))
    )
    for key, fetch, details in (
        ("readiness", lambda: client.get_training_readiness(today.isoformat()), {"date": today.isoformat()}),
        ("race_predictions", client.get_race_predictions, None),
        (
            "max_metrics",
            max_metrics_fetch,
            {
                "window_start": max_metrics_start.isoformat(),
                "window_end": today.isoformat(),
                "range_supported": callable(max_metrics_range),
            },
        ),
    ):
        try:
            payload[key] = external_call("garmin", key, fetch, details)
        except Exception as exc:
            add_error(key, exc)

    weight_fetch = getattr(client, "get_weigh_ins", None) or getattr(client, "get_body_composition", None)
    if callable(weight_fetch):
        try:
            weight_start = today - timedelta(days=89)
            payload["weight"] = external_call(
                "garmin",
                "weight",
                lambda: weight_fetch(weight_start.isoformat(), today.isoformat()),
                {"window_start": weight_start.isoformat(), "window_end": today.isoformat()},
            )
        except Exception as exc:
            add_error("weight", exc)

    payload["provider_sync"] = {"pagination": pagination}
    return payload
