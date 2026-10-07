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
from functools import partial
from typing import Any

try:
    from garminconnect import Garmin as GarminClient
except ImportError:  # Optional dependency for installations without Garmin enabled.
    GarminClient = None  # type: ignore[assignment,misc]


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
    # ``None`` follows the collection profile: full/default collections include
    # historic metrics, while recovery/current-metric-free activity or
    # historical-minimal collections remain activities-only.  Callers can set
    # an explicit boolean to override that profile.
    include_historic_metrics: bool | None = None


class GarminClientFactory:
    """Create the optional Garmin SDK client without leaking it into the app root."""

    @staticmethod
    def available() -> bool:
        return GarminClient is not None

    @staticmethod
    def create(email: str | None, password: str | None) -> Any:
        if GarminClient is None:
            raise RuntimeError("The optional Garmin client library is unavailable.")
        return GarminClient(email, password)


def normalize_range_records(source: str, value: Any) -> list[dict[str, Any]]:
    """Normalize the current SDK range contracts, rejecting unknown response shapes."""
    if source == "hrv" and isinstance(value, dict) and "hrvSummaries" in value:
        value = value["hrvSummaries"]
    if not isinstance(value, list) or any(
        not isinstance(record, dict) for record in value
    ):
        raise ValueError(f"Invalid Garmin {source} range response")
    return value


def _add_error(
    payload: dict[str, Any],
    source: str,
    exc: BaseException,
    redact: Redact,
    warn: WarningLogger | None,
) -> None:
    message = redact(str(exc))[:500]
    payload["errors"].append({"source": source, "message": message})
    if warn:
        warn(source, message, exc)


def _fetch_range(
    payload: dict[str, Any],
    pagination: dict[str, dict[str, Any]],
    key: str,
    fetch: Any,
    window_start: date,
    window_end: date,
    windows_count: int,
    external_call: ExternalCall,
    redact: Redact,
    warn: WarningLogger | None,
    capability_allowed: CapabilityAllowed | None,
    capability_failure: CapabilityFailure | None,
    capability_success: CapabilitySuccess | None,
) -> None:
    stats = pagination.setdefault(
        key, {"windows": windows_count, "records": 0, "complete": True}
    )
    if capability_allowed is not None and not capability_allowed(key):
        stats.update({"complete": False, "paused": True, "error": "capability_paused"})
        return
    try:
        value = external_call(
            "garmin",
            key,
            lambda: fetch(window_start.isoformat(), window_end.isoformat()),
            {
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            },
        )
        records = normalize_range_records(key, value)
        payload.setdefault(key, []).extend(records)
        stats["records"] = int(stats["records"]) + len(records)
        stats.setdefault("completed_windows", []).append(
            {"start": window_start.isoformat(), "end": window_end.isoformat()}
        )
        if capability_success:
            capability_success(key)
    except Exception as exc:  # noqa: BLE001 - SDK errors vary; retain other sources and redact.
        stats["complete"] = False
        stats["error"] = redact(str(exc))[:500]
        if capability_failure:
            capability_failure(key, exc)
        _add_error(payload, key, exc, redact, warn)


def _collect_ranges(
    client: Any,
    windows: list[tuple[date, date]],
    payload: dict[str, Any],
    pagination: dict[str, dict[str, Any]],
    include_recovery: bool,
    include_current_metrics: bool,
    status: StatusCallback | None,
    external_call: ExternalCall,
    redact: Redact,
    warn: WarningLogger | None,
    capability_allowed: CapabilityAllowed | None,
    capability_failure: CapabilityFailure | None,
    capability_success: CapabilitySuccess | None,
) -> None:
    for index, (window_start, window_end) in enumerate(windows, 1):
        if status:
            status(f"Garmin: Zeitraum {index}/{len(windows)} wird synchronisiert…")
        requests = [("activities", client.get_activities_by_date)]
        include_load = include_recovery or include_current_metrics
        training_load_fetch = (
            getattr(client, "get_training_load_activities", None)
            if include_load
            else None
        )
        if include_load and callable(training_load_fetch):
            requests.append(("training_load_activities", training_load_fetch))
        if include_recovery:
            requests[0:0] = [
                ("sleep", client.get_sleep_daily),
                ("hrv", client.get_hrv_data_range),
            ]
        with ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="garmin-range"
        ) as executor:
            futures = [
                executor.submit(
                    _fetch_range,
                    payload,
                    pagination,
                    key,
                    fetch,
                    window_start,
                    window_end,
                    len(windows),
                    external_call,
                    redact,
                    warn,
                    capability_allowed,
                    capability_failure,
                    capability_success,
                )
                for key, fetch in requests
            ]
            for future in futures:
                future.result()


def _daily_stats_records(value: Any, current: date) -> list[dict[str, Any]]:
    records = value if isinstance(value, list) else [value]
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("Invalid Garmin daily_stats response")
    return [
        record
        if any(key in record for key in ("calendarDate", "summaryDate", "date"))
        else {"calendarDate": current.isoformat(), **record}
        for record in records
    ]


def _collect_daily_stats_day(
    fetch: Any,
    current: date,
    payload: dict[str, Any],
    stats: dict[str, Any],
    external_call: ExternalCall,
    redact: Redact,
    warn: WarningLogger | None,
    source: str = "daily_stats",
) -> None:
    try:
        value = external_call(
            "garmin",
            source,
            lambda: fetch(current.isoformat()),
            {"date": current.isoformat()},
        )
        records = _daily_stats_records(value, current)
        payload.setdefault(source, []).extend(records)
        stats["records"] = int(stats["records"]) + len(records)
    except Exception as exc:  # noqa: BLE001 - SDK errors vary; retain other sources and redact.
        stats["complete"] = False
        stats["error"] = redact(str(exc))[:500]
        _add_error(payload, source, exc, redact, warn)


def _collect_daily_stats(
    client: Any,
    windows: list[tuple[date, date]],
    payload: dict[str, Any],
    pagination: dict[str, dict[str, Any]],
    external_call: ExternalCall,
    redact: Redact,
    warn: WarningLogger | None,
    source: str = "daily_stats",
    method: str = "get_user_summary",
) -> None:
    fetch = getattr(client, method, None)
    if not callable(fetch):
        return
    stats = pagination.setdefault(
        source, {"windows": len(windows), "records": 0, "complete": True}
    )
    for window_start, window_end in windows:
        current = window_start
        while current <= window_end:
            _collect_daily_stats_day(
                fetch, current, payload, stats, external_call, redact, warn, source
            )
            current += timedelta(days=1)


def _collect_resting_hr(
    client: Any,
    windows: list[tuple[date, date]],
    payload: dict[str, Any],
    pagination: dict[str, dict[str, Any]],
    external_call: ExternalCall,
    redact: Redact,
    warn: WarningLogger | None,
) -> None:
    fetch = getattr(client, "get_heart_rates", None)
    if not callable(fetch):
        return
    stats = pagination.setdefault(
        "resting_hr", {"windows": len(windows), "records": 0, "complete": True}
    )
    for window_start, window_end in windows:
        current = window_start
        while current <= window_end:
            try:
                value = external_call(
                    "garmin",
                    "resting_hr",
                    partial(fetch, current.isoformat()),
                    {"date": current.isoformat()},
                )
                if not isinstance(value, dict):
                    raise TypeError("Invalid Garmin resting_hr response")
                if not any(
                    key in value for key in ("calendarDate", "date", "summaryDate")
                ):
                    value = {"calendarDate": current.isoformat(), **value}
                payload.setdefault("resting_hr", []).append(value)
                stats["records"] = int(stats["records"]) + 1
            except Exception as exc:  # noqa: BLE001 - SDK errors vary; retain other sources and redact.
                stats["complete"] = False
                stats["error"] = redact(str(exc))[:500]
                _add_error(payload, "resting_hr", exc, redact, warn)
            current += timedelta(days=1)


def _collect_current_metrics(
    client: Any,
    today: date,
    payload: dict[str, Any],
    external_call: ExternalCall,
    redact: Redact,
    warn: WarningLogger | None,
) -> None:
    fetch = getattr(client, "get_heart_rate_zones", None)
    if callable(fetch):
        _collect_optional_metric(
            payload, "heart_rate_zones", fetch, None, external_call, redact, warn
        )
    if callable(getattr(client, "get_user_profile", None)) and callable(
        getattr(client, "get_gear", None)
    ):
        _collect_optional_metric(
            payload,
            "gear",
            lambda: _gear_inventory(client, external_call),
            None,
            external_call,
            redact,
            warn,
        )
    max_metrics_start = today - timedelta(days=89)
    max_metrics_range = getattr(client, "get_max_metrics_range", None)
    metrics = (
        (
            "daily_training_status",
            lambda: client.get_daily_training_status(today.isoformat()),
            {"date": today.isoformat()},
        ),
        (
            "training_load_balance",
            lambda: client.get_training_four_week_load_balance(today.isoformat()),
            {"date": today.isoformat()},
        ),
        (
            "readiness",
            lambda: client.get_training_readiness(today.isoformat()),
            {"date": today.isoformat()},
        ),
        ("race_predictions", client.get_race_predictions, None),
        (
            "max_metrics",
            lambda: client.get_max_metrics_range(
                max_metrics_start.isoformat(), today.isoformat()
            ),
            {
                "window_start": max_metrics_start.isoformat(),
                "window_end": today.isoformat(),
                "range_supported": callable(max_metrics_range),
            },
        ),
    )
    for key, metric_fetch, details in metrics:
        if key == "daily_training_status" and not callable(
            getattr(client, "get_daily_training_status", None)
        ):
            continue
        if key == "training_load_balance" and not callable(
            getattr(client, "get_training_four_week_load_balance", None)
        ):
            continue
        _collect_optional_metric(
            payload, key, metric_fetch, details, external_call, redact, warn
        )
    fetch = getattr(client, "get_cycling_ftp", None)
    if callable(fetch):
        _collect_optional_metric(
            payload, "cycling_ftp", fetch, None, external_call, redact, warn
        )
    fetch = getattr(client, "get_lactate_threshold", None)
    if callable(fetch):
        _collect_optional_metric(
            payload,
            "running_threshold",
            lambda: fetch(latest=True),
            {"latest": True},
            external_call,
            redact,
            warn,
        )
    fetch = getattr(client, "get_weigh_ins", None)
    if callable(fetch):
        weight_start = today - timedelta(days=89)
        _collect_optional_metric(
            payload,
            "weight",
            lambda: fetch(weight_start.isoformat(), today.isoformat()),
            {"window_start": weight_start.isoformat(), "window_end": today.isoformat()},
            external_call,
            redact,
            warn,
        )


def _collect_historic_metrics(
    client: Any,
    today: date,
    payload: dict[str, Any],
    pagination: dict[str, dict[str, Any]],
    external_call: ExternalCall,
    redact: Redact,
    warn: WarningLogger | None,
    capability_allowed: CapabilityAllowed | None,
    capability_failure: CapabilityFailure | None,
    capability_success: CapabilitySuccess | None,
) -> None:
    """Fetch optional, bounded historical metrics with explicit SDK semantics."""
    start = today - timedelta(days=89)
    end = today
    requests = (
        (
            "cycling_ftp_history",
            getattr(client, "get_functional_threshold_power_range", None),
            lambda fetch: fetch(
                start.isoformat(),
                end.isoformat(),
                sport="CYCLING",
                aggregation="daily",
            ),
            "daily",
        ),
        (
            "endurance_score",
            getattr(client, "get_endurance_score", None),
            lambda fetch: fetch(start.isoformat(), end.isoformat()),
            "weekly",
        ),
        (
            "running_tolerance",
            getattr(client, "get_running_tolerance", None),
            lambda fetch: fetch(
                start.isoformat(), end.isoformat(), aggregation="weekly"
            ),
            "weekly",
        ),
    )
    for key, fetch, invoke, aggregation in requests:
        stats = pagination.setdefault(
            key,
            {
                "windows": 1,
                "records": 0,
                "complete": True,
                "available": callable(fetch),
                "status": "pending" if callable(fetch) else "unsupported",
                "aggregation": aggregation,
            },
        )
        if not callable(fetch):
            continue
        if capability_allowed is not None and not capability_allowed(key):
            stats.update({"complete": False, "paused": True, "status": "paused"})
            continue
        details = {
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "aggregation": aggregation,
        }
        if key == "cycling_ftp_history":
            details["sport"] = "CYCLING"
        try:
            value = external_call("garmin", key, partial(invoke, fetch), details)
            if not isinstance(value, (dict, list)):
                raise TypeError(f"Invalid Garmin {key} response")
            if isinstance(value, list) and any(
                not isinstance(item, dict) for item in value
            ):
                raise TypeError(f"Invalid Garmin {key} response records")
            payload[key] = value
            stats.update(
                {
                    "records": len(value) if isinstance(value, list) else 1,
                    "status": "complete",
                    "completed_windows": [details],
                }
            )
            if capability_success:
                capability_success(key)
        except Exception as exc:  # noqa: BLE001 - optional metric failures are isolated.
            stats.update(
                {"complete": False, "status": "failed", "error": redact(str(exc))[:500]}
            )
            if capability_failure:
                capability_failure(key, exc)
            _add_error(payload, key, exc, redact, warn)


def _gear_inventory(client: Any, external_call: ExternalCall) -> list[dict[str, Any]]:
    profile = external_call("garmin", "gear_profile", client.get_user_profile, None)
    profile_number = profile.get("id") if isinstance(profile, dict) else None
    if not profile_number:
        raise ValueError("Garmin gear profile is unavailable")
    inventory = external_call(
        "garmin", "gear_inventory", lambda: client.get_gear(profile_number), None
    )
    if isinstance(inventory, dict):
        inventory = inventory.get("gear")
    if not isinstance(inventory, list) or len(inventory) > 100:
        raise ValueError("Invalid Garmin gear inventory")
    result = []
    for item in inventory:
        normalized = _normalize_gear_row(item)
        if normalized is None:
            continue
        stats = _gear_usage_stats(client, normalized["gearUUID"], external_call)
        result.append({**normalized, "stats": stats or {}})
    return result


def _normalize_gear_row(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    gear_uuid = item.get("gearUUID") or item.get("uuid")
    if not gear_uuid:
        return None
    gear_name = (
        item.get("gearName")
        or item.get("displayName")
        or item.get("customMakeModel")
        or " ".join(
            str(item.get(key) or "").strip()
            for key in ("gearMakeName", "gearModelName")
            if item.get(key)
        )
    )
    return {
        **item,
        "gearUUID": str(gear_uuid),
        **({"gearName": str(gear_name)} if gear_name else {}),
    }


def _gear_usage_stats(
    client: Any, gear_uuid: str, external_call: ExternalCall
) -> dict[str, Any] | None:
    try:
        result = external_call(
            "garmin",
            "gear_usage",
            partial(client.get_gear_stats, gear_uuid),
            None,
        )
    except Exception:  # noqa: BLE001 - omit only this unavailable optional row.
        return None
    return result if isinstance(result, dict) else None


def _collect_optional_metric(
    payload: dict[str, Any],
    key: str,
    fetch: Any,
    details: Any,
    external_call: ExternalCall,
    redact: Redact,
    warn: WarningLogger | None,
) -> None:
    try:
        payload[key] = external_call("garmin", key, fetch, details)
    except Exception as exc:  # noqa: BLE001 - SDK errors vary; retain other sources and redact.
        _add_error(payload, key, exc, redact, warn)


def _validate_current_metrics(
    payload: dict[str, Any], redact: Redact, warn: WarningLogger | None
) -> None:
    keys = (
        "daily_training_status",
        "training_load_balance",
        "heart_rate_zones",
        "readiness",
        "race_predictions",
        "max_metrics",
        "cycling_ftp",
        "running_threshold",
        "weight",
        "gear",
        "cycling_ftp_history",
        "endurance_score",
        "running_tolerance",
    )
    for key in keys:
        if key in ("daily_training_status", "training_load_balance") and key in payload:
            if isinstance(payload[key], dict):
                continue
            payload.pop(key)
            _add_error(
                payload,
                key,
                ValueError(f"Invalid Garmin {key} response"),
                redact,
                warn,
            )
            continue
        if key in payload and not isinstance(payload[key], (dict, list)):
            payload.pop(key)
            _add_error(
                payload, key, ValueError(f"Invalid Garmin {key} response"), redact, warn
            )


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
    payload: dict[str, Any] = {
        "synced_at": synced_at,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "errors": [],
    }
    pagination: dict[str, dict[str, Any]] = {}
    _collect_ranges(
        client,
        windows,
        payload,
        pagination,
        collection_options.include_recovery,
        collection_options.include_current_metrics,
        status,
        external_call,
        redact,
        warn,
        capability_allowed,
        capability_failure,
        capability_success,
    )
    if collection_options.include_recovery:
        _collect_daily_stats(
            client, windows, payload, pagination, external_call, redact, warn
        )
        _collect_resting_hr(
            client, windows, payload, pagination, external_call, redact, warn
        )
        _collect_daily_stats(
            client,
            windows,
            payload,
            pagination,
            external_call,
            redact,
            warn,
            source="training_status",
            method="get_training_status",
        )
    if collection_options.include_current_metrics:
        _collect_current_metrics(client, today, payload, external_call, redact, warn)
    include_historic_metrics = collection_options.include_historic_metrics
    if include_historic_metrics is None:
        include_historic_metrics = (
            options is None
            or collection_options.include_recovery
            or collection_options.include_current_metrics
        )
    if include_historic_metrics:
        _collect_historic_metrics(
            client,
            today,
            payload,
            pagination,
            external_call,
            redact,
            warn,
            capability_allowed,
            capability_failure,
            capability_success,
        )
    payload["provider_sync"] = {"pagination": pagination}
    _validate_current_metrics(payload, redact, warn)
    return payload
