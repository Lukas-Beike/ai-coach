"""Dependency-light Garmin collection adapter.

The application owns authentication, persistence, locking, and redaction.
This module only coordinates calls on an already authenticated Garmin client
and returns a bounded, provider-labelled collection result.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any


ExternalCall = Callable[[str, str, Callable[[], Any], dict[str, Any] | None], Any]
Redact = Callable[[str], str]
WarningLogger = Callable[[str, str, BaseException], None]
StatusCallback = Callable[[str], None]
CapabilityAllowed = Callable[[str], bool]
CapabilityFailure = Callable[[str, BaseException], None]
CapabilitySuccess = Callable[[str], None]


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
        if capability_allowed is not None and not capability_allowed(key):
            stats["complete"] = False
            stats["paused"] = True
            stats["error"] = "capability_paused"
            return
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
            if capability_success:
                capability_success(key)
        except Exception as exc:
            stats["complete"] = False
            stats["error"] = redact(str(exc))[:500]
            if capability_failure:
                capability_failure(key, exc)
            add_error(key, exc)

    for index, (window_start, window_end) in enumerate(windows, 1):
        if status:
            status(f"Garmin: Zeitraum {index}/{len(windows)} wird synchronisiert…")
        requests = (
            ("sleep", client.get_sleep_daily),
            ("hrv", client.get_hrv_data_range),
            ("body_battery", client.get_body_battery),
            ("activities", client.get_activities_by_date),
        )
        # Garmin's range endpoints are independent. Keep the concurrency
        # deliberately at two calls so the provider is not flooded and the
        # persisted job can still report one bounded window at a time.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="garmin-range") as executor:
            futures = [
                executor.submit(fetch_range, key, fetch, window_start, window_end)
                for key, fetch in requests
            ]
            for future in futures:
                future.result()

    daily_stats_fetch = getattr(client, "get_user_summary", None) or getattr(client, "get_stats", None)
    if callable(daily_stats_fetch):
        stats = pagination.setdefault("daily_stats", {"windows": len(windows), "records": 0, "complete": True})
        for window_start, window_end in windows:
            current = window_start
            while current <= window_end:
                try:
                    value = external_call(
                        "garmin",
                        "daily_stats",
                        lambda current=current: daily_stats_fetch(current.isoformat()),
                        {"date": current.isoformat()},
                    )
                    records = value if isinstance(value, list) else [value]
                    for record in records:
                        if isinstance(record, dict):
                            if not any(key in record for key in ("calendarDate", "summaryDate", "date")):
                                record = {"calendarDate": current.isoformat(), **record}
                            payload.setdefault("daily_stats", []).append(record)
                            stats["records"] = int(stats["records"]) + 1
                except Exception as exc:
                    stats["complete"] = False
                    stats["error"] = redact(str(exc))[:500]
                    add_error("daily_stats", exc)
                current += timedelta(days=1)

    heart_rate_fetch = getattr(client, "get_heart_rates", None)
    if callable(heart_rate_fetch):
        stats = pagination.setdefault("resting_hr", {"windows": len(windows), "records": 0, "complete": True})
        for window_start, window_end in windows:
            current = window_start
            while current <= window_end:
                try:
                    value = external_call(
                        "garmin",
                        "resting_hr",
                        lambda current=current: heart_rate_fetch(current.isoformat()),
                        {"date": current.isoformat()},
                    )
                    if value is not None:
                        if isinstance(value, dict) and not any(key in value for key in ("calendarDate", "date", "summaryDate")):
                            value = {"calendarDate": current.isoformat(), **value}
                        payload.setdefault("resting_hr", []).append(value)
                        stats["records"] = int(stats["records"]) + 1
                except Exception as exc:
                    stats["complete"] = False
                    stats["error"] = redact(str(exc))[:500]
                    add_error("resting_hr", exc)
                current += timedelta(days=1)

    heart_rate_zones_fetch = getattr(client, "get_heart_rate_zones", None)
    if callable(heart_rate_zones_fetch):
        try:
            payload["heart_rate_zones"] = external_call(
                "garmin", "heart_rate_zones", heart_rate_zones_fetch, None
            )
        except Exception as exc:
            add_error("heart_rate_zones", exc)

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

    cycling_ftp_fetch = getattr(client, "get_cycling_ftp", None)
    if not callable(cycling_ftp_fetch):
        connectapi = getattr(client, "connectapi", None)
        if callable(connectapi):
            cycling_ftp_fetch = lambda: connectapi(
                "/biometric-service/biometric/latestFunctionalThresholdPower/CYCLING"
            )
    if callable(cycling_ftp_fetch):
        try:
            payload["cycling_ftp"] = external_call("garmin", "cycling_ftp", cycling_ftp_fetch, None)
        except Exception as exc:
            add_error("cycling_ftp", exc)

    running_threshold_fetch = getattr(client, "get_lactate_threshold", None)
    if callable(running_threshold_fetch):
        try:
            payload["running_threshold"] = external_call(
                "garmin", "running_threshold", lambda: running_threshold_fetch(latest=True), {"latest": True}
            )
        except TypeError:
            try:
                payload["running_threshold"] = external_call("garmin", "running_threshold", running_threshold_fetch, None)
            except Exception as exc:
                add_error("running_threshold", exc)
        except Exception as exc:
            add_error("running_threshold", exc)
    elif callable(getattr(client, "connectapi", None)):
        connectapi = client.connectapi
        try:
            payload["running_threshold"] = {
                "speed_and_heart_rate": external_call(
                    "garmin", "running_threshold_speed_hr", lambda: connectapi("/biometric-service/biometric/latestLactateThreshold"), None
                ),
                "power": external_call(
                    "garmin", "running_threshold_power", lambda: connectapi(
                        f"/biometric-service/biometric/powerToWeight/latest/{today.isoformat()}?sport=Running"
                    ), {"date": today.isoformat(), "sport": "Running"}
                ),
            }
        except Exception as exc:
            add_error("running_threshold", exc)

    # get_lactate_threshold() already contains the cycling heart-rate field
    # when Garmin provides it (heartRateCycling). The separate range endpoint
    # is undocumented and has started returning an unprocessable response for
    # otherwise healthy accounts. Keep the collector on the supported client
    # method; garmin_performance_metrics() can read heartRateCycling from the
    # running_threshold payload and falls back to the other source sections.

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
