"""Dependency-light Garmin collection adapter.

The application owns authentication, persistence, locking, and redaction.
This module only coordinates calls on an already authenticated Garmin client
and returns a bounded, provider-labelled collection result.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

from backend.providers.descriptors import GARMIN_ID

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
    def create(
        email: str | None, password: str | None, *, return_on_mfa: bool = False
    ) -> Any:
        if GarminClient is None:
            raise RuntimeError("The optional Garmin client library is unavailable.")
        if return_on_mfa:
            return GarminClient(email, password, return_on_mfa=True)
        return GarminClient(email, password)


def authenticate_client(
    client_factory: GarminClientFactory,
    email: str | None,
    password: str | None,
    login_argument: str,
    *,
    external_call: ExternalCall,
    tokenstore_exists: bool,
) -> tuple[Any, bool]:
    """Create and authenticate one Garmin SDK client through provider transport."""
    client = client_factory.create(email, password, return_on_mfa=True)
    mfa_status, _ = external_call(
        GARMIN_ID,
        "login",
        lambda: client.login(login_argument),
        {
            "email_configured": bool(email),
            "tokenstore_exists": tokenstore_exists,
        },
    )
    return client, bool(mfa_status)


def targeted_analysis_sources() -> dict[str, dict[str, tuple[str | None, Any]]]:
    """Return bounded targeted-read contracts supported by garminconnect 0.3.19.

    The call shapes match the pinned SDK. At runtime, an SDK method absent from
    the installed client remains an unsupported capability; never guess a
    Garmin endpoint from a newer or unrelated client.
    """
    date_range = lambda method, first, last: method(first.isoformat(), last.isoformat())
    latest_date = lambda method, _first, last: method(last.isoformat())
    no_dates = lambda method, _first, _last: method()
    return {
        "sessions": {"activities": ("get_activities_by_date", date_range)},
        "load": {
            "activities": ("get_activities_by_date", date_range),
            "training_load_activities": ("get_training_load_activities", date_range),
            "daily_training_status": ("get_daily_training_status", latest_date),
            "training_load_balance": (
                "get_training_four_week_load_balance",
                latest_date,
            ),
            "weekly_training_status": ("get_weekly_training_status", date_range),
        },
        "performance": {
            "cycling_ftp": ("get_cycling_ftp", no_dates),
            "running_threshold": (
                "get_lactate_threshold",
                lambda method, _first, _last: method(latest=True),
            ),
            "race_predictions": ("get_race_predictions", no_dates),
            "max_metrics": ("get_max_metrics_range", date_range),
            "cycling_ftp_history": (
                "get_functional_threshold_power_range",
                lambda method, first, last: method(
                    first.isoformat(),
                    last.isoformat(),
                    sport="CYCLING",
                    aggregation="daily",
                ),
            ),
            "endurance_score": ("get_endurance_score", date_range),
            "running_tolerance": (
                "get_running_tolerance",
                lambda method, first, last: method(
                    first.isoformat(), last.isoformat(), aggregation="weekly"
                ),
            ),
            "training_readiness_history": ("get_training_readiness_range", date_range),
            "weekly_training_status": ("get_weekly_training_status", date_range),
        },
        "recovery": {
            "sleep": ("get_sleep_daily", date_range),
            "hrv": ("get_hrv_data_range", date_range),
            "readiness": ("get_training_readiness_range", date_range),
            "daily_stats": ("get_daily_summaries", date_range),
            "resting_hr": ("get_heart_rates", None),
        },
    }


def preserve_weight_response(value: Any) -> list[dict[str, Any]]:
    """Keep Garmin's raw weigh-in response intact for snapshot history.

    ``get_weigh_ins`` is already bounded by its date arguments. The returned
    object may contain historic samples and multiple measurements per day; the
    owning snapshot projection, not transport, decides what to display.
    """
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    raise ValueError("Invalid Garmin weight response")


_WEIGHT_SNAPSHOT_SECTIONS = ("weighIns", "weigh_ins", "weight")
_WEIGHT_OPAQUE_SECTIONS_KEY = "_garmin_weight_opaque_sections"


def _sort_weight_metadata_list(rows: list[Any]) -> None:
    rows.sort(
        key=lambda row: (
            _weight_reading_order(row) if isinstance(row, dict) else (False, 0.0)
        ),
        reverse=True,
    )


def _merge_opaque_section_state(target: dict[str, list[Any]], value: Any) -> None:
    if isinstance(value, dict) and isinstance(value.get("sections"), dict):
        for name, rows in value["sections"].items():
            if isinstance(rows, list):
                for row in rows:
                    _preserve_opaque_weight_section(target, name, row)
        if "existing_value" in value:
            _preserve_opaque_weight_section(
                target, "_reserved_metadata", value["existing_value"]
            )
        return
    _preserve_opaque_weight_section(target, "_reserved_metadata", value)


def _merge_weight_metadata(
    target: dict[str, Any], source: dict[str, Any], *, envelope: bool = False
) -> None:
    for key, value in source.items():
        if envelope and (
            key in _WEIGHT_SNAPSHOT_SECTIONS or key == _WEIGHT_OPAQUE_SECTIONS_KEY
        ):
            continue
        _merge_weight_metadata_value(target, key, value)


def _merge_weight_metadata_value(target: dict[str, Any], key: str, value: Any) -> None:
    current = target.get(key)
    if isinstance(current, dict) and isinstance(value, dict):
        _merge_weight_metadata(current, value)
    elif isinstance(current, list) and isinstance(value, list):
        _merge_weight_metadata_lists(current, value)
    else:
        target[key] = copy.deepcopy(value)
        if isinstance(target[key], list):
            _sort_weight_metadata_list(target[key])


def _merge_weight_metadata_lists(target: list[Any], source: list[Any]) -> None:
    seen = {json.dumps(item, sort_keys=True, default=str) for item in target}
    for item in source:
        identity = json.dumps(item, sort_keys=True, default=str)
        if identity not in seen:
            seen.add(identity)
            target.append(item)
    _sort_weight_metadata_list(target)


def _weight_snapshot_documents(source: Any) -> list[dict[str, Any]]:
    documents = [source] if isinstance(source, dict) else source
    return (
        [row for row in documents if isinstance(row, dict)]
        if isinstance(documents, list)
        else []
    )


def _is_flat_weight_reading(document: dict[str, Any]) -> bool:
    return any(
        key in document for key in ("weight", "weightKg", "weight_kg")
    ) and not any(
        isinstance(document.get(name), list) for name in _WEIGHT_SNAPSHOT_SECTIONS
    )


def _collect_weight_document(
    document: dict[str, Any],
    readings: list[dict[str, Any]],
    metadata: dict[str, Any],
    opaque_sections: dict[str, list[Any]],
) -> None:
    if _is_flat_weight_reading(document):
        readings.append(document)
        return
    opaque_state = document.get(_WEIGHT_OPAQUE_SECTIONS_KEY)
    if opaque_state is not None:
        _merge_opaque_section_state(opaque_sections, opaque_state)
    _merge_weight_metadata(metadata, document, envelope=True)
    for name in _WEIGHT_SNAPSHOT_SECTIONS:
        rows = document.get(name)
        if isinstance(rows, list):
            readings.extend(row for row in rows if isinstance(row, dict))
        elif document.get(name) is not None:
            _preserve_opaque_weight_section(opaque_sections, name, document[name])


def _merge_weight_readings(
    readings: list[dict[str, Any]], previous_count: int
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for index, reading in enumerate(readings):
        identities = _weight_snapshot_identities(reading)
        position = next(
            (positions[key] for key in identities if key in positions), None
        )
        if position is None:
            position = len(merged)
            merged.append(reading)
        elif index >= previous_count:
            merged[position] = reading
        for key in identities:
            positions[key] = position
    merged.sort(key=_weight_reading_order, reverse=True)
    return merged


def _weight_snapshot_identities(reading: dict[str, Any]) -> tuple[str, ...]:
    identities = [
        f"id:{key}:{reading[key]}"
        for key in (
            "samplePk",
            "sample_pk",
            "measurementId",
            "measurement_id",
            "weighInId",
            "recordId",
            "id",
        )
        if reading.get(key) not in (None, "")
    ]
    if identities:
        return tuple(identities)
    return (
        "raw:" + json.dumps(reading, sort_keys=True, ensure_ascii=False, default=str),
    )


def _preserve_opaque_weight_section(
    target: dict[str, list[Any]], name: str, value: Any
) -> None:
    rows = target.setdefault(name, [])
    identity = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    if all(
        json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) != identity
        for row in rows
    ):
        rows.append(copy.deepcopy(value))


def _weight_reading_order(reading: dict[str, Any]) -> tuple[bool, float]:
    for key in (
        "timestampGMT",
        "timestamp",
        "measurementDate",
        "calendarDate",
        "summaryDate",
        "date",
    ):
        value = reading.get(key)
        try:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                seconds = value / 1000 if value > 100_000_000_000 else value
                return True, float(seconds)
            if isinstance(value, str):
                parsed = datetime.fromisoformat(value.strip())
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return True, parsed.timestamp()
        except OverflowError, OSError, TypeError, ValueError:
            continue
    return False, 0.0


def merge_weight_snapshots(incoming: Any, previous: Any) -> list[Any]:
    """Merge unique raw weigh-ins into one envelope, with newest readings first."""
    metadata: dict[str, Any] = {}
    readings: list[dict[str, Any]] = []
    opaque_sections: dict[str, list[Any]] = {}
    previous_count = 0
    for source, is_previous in ((previous, True), (incoming, False)):
        for document in _weight_snapshot_documents(source):
            _collect_weight_document(document, readings, metadata, opaque_sections)
        if is_previous:
            previous_count = len(readings)

    envelope: dict[str, Any] = {
        "weight": _merge_weight_readings(readings, previous_count)
    }
    envelope.update(metadata)
    if opaque_sections:
        envelope[_WEIGHT_OPAQUE_SECTIONS_KEY] = {"sections": opaque_sections}
    return [envelope]


def fetch_targeted_analysis(
    client: Any,
    area: str,
    start: date,
    end: date,
    *,
    external_call: ExternalCall,
    capability_allowed: Callable[[str], bool],
    capability_failure: Callable[[str, BaseException], None],
    capability_success: Callable[[str], None],
    warn: WarningLogger,
) -> tuple[dict[str, Any], dict[str, bool]]:
    """Fetch and shape one bounded targeted analysis area from Garmin."""
    sources = targeted_analysis_sources()[area]
    payload: dict[str, Any] = {}
    complete: dict[str, bool] = {}
    for source, (method_name, invoke) in sources.items():
        method = getattr(client, method_name, None) if method_name else None
        if not callable(method) or not capability_allowed(source):
            complete[source] = False
            continue
        if source == "resting_hr":
            payload[source], complete[source] = _fetch_resting_hr_days(
                method,
                start,
                end,
                external_call=external_call,
                capability_failure=capability_failure,
                capability_success=capability_success,
                warn=warn,
            )
            continue
        value, complete[source] = _fetch_analysis_range(
            source,
            method,
            invoke,
            start,
            end,
            external_call=external_call,
            capability_failure=capability_failure,
            capability_success=capability_success,
            warn=warn,
        )
        if complete[source]:
            payload[source] = value
    return payload, complete


def _fetch_resting_hr_days(
    method: Callable[..., Any],
    start: date,
    end: date,
    *,
    external_call: ExternalCall,
    capability_failure: Callable[[str, BaseException], None],
    capability_success: Callable[[str], None],
    warn: WarningLogger,
) -> tuple[list[dict[str, Any]], bool]:
    source = "resting_hr"
    rows: list[dict[str, Any]] = []
    failed = False
    for offset in range((end - start).days + 1):
        day = (start + timedelta(days=offset)).isoformat()

        def fetch_day(day: str = day, method: Callable[..., Any] = method) -> Any:
            return method(day)

        try:
            value = external_call(GARMIN_ID, source, fetch_day, {"date": day})
            if not isinstance(value, dict):
                raise TypeError("Invalid Garmin resting_hr response")
            if not any(key in value for key in ("calendarDate", "date", "summaryDate")):
                value = {"calendarDate": day, **value}
            rows.append(value)
        except Exception as exc:  # noqa: BLE001 - retain successful days.
            failed = True
            capability_failure(source, exc)
            warn(source, "Garmin analysis source failed", exc)
    if not failed:
        capability_success(source)
    return rows, not failed


def _fetch_analysis_range(
    source: str,
    method: Callable[..., Any],
    invoke: Callable[..., Any] | None,
    start: date,
    end: date,
    *,
    external_call: ExternalCall,
    capability_failure: Callable[[str, BaseException], None],
    capability_success: Callable[[str], None],
    warn: WarningLogger,
) -> tuple[Any, bool]:
    try:
        assert invoke is not None

        def fetch(
            invoke: Callable[..., Any] = invoke,
            method: Callable[..., Any] = method,
        ) -> Any:
            return invoke(method, start, end)

        value = external_call(
            GARMIN_ID,
            source,
            fetch,
            {"start": start.isoformat(), "end": end.isoformat()},
        )
        value = _normalize_targeted_analysis_response(source, value)
    except Exception as exc:  # noqa: BLE001 - isolate provider failures per source.
        capability_failure(source, exc)
        warn(source, "Garmin analysis source failed", exc)
        return None, False
    capability_success(source)
    return value, True


def fetch_targeted_nutrition(
    client: Any,
    source: str,
    start: date,
    end: date,
    *,
    external_call: ExternalCall,
) -> tuple[list[dict[str, Any]], bool]:
    """Fetch one bounded body measurement or daily energy range."""
    method_name = "get_weigh_ins" if source == "weight" else "get_daily_summaries"
    fetch = getattr(client, method_name, None)
    if not callable(fetch):
        raise NotImplementedError(f"Unsupported Garmin {source} range")
    value = external_call(
        GARMIN_ID,
        source,
        lambda: fetch(start.isoformat(), end.isoformat()),
        {"start": start.isoformat(), "end": end.isoformat()},
    )
    if source == "weight":
        return preserve_weight_response(value), True
    records = value.get("data") if isinstance(value, dict) else value
    if not isinstance(records, list) or any(
        not isinstance(row, dict) for row in records
    ):
        raise ValueError("Invalid Garmin daily_stats response")
    bounded = []
    complete = True
    for row in records:
        raw_day = row.get("calendarDate") or row.get("summaryDate") or row.get("date")
        try:
            observed = date.fromisoformat(str(raw_day)[:10])
        except ValueError:
            complete = False
            continue
        if start <= observed <= end:
            bounded.append(row)
    return bounded, complete


def _normalize_targeted_analysis_response(source: str, value: Any) -> Any:
    if not isinstance(value, (dict, list)):
        raise TypeError(f"Invalid Garmin {source} response")
    if source == "daily_stats" and isinstance(value, dict):
        value = value.get("data")
    if source == "hrv" and isinstance(value, dict):
        value = value.get("hrvSummaries")
    if source in {"daily_stats", "hrv"} and (
        not isinstance(value, list) or any(not isinstance(row, dict) for row in value)
    ):
        raise TypeError(f"Invalid Garmin {source} response records")
    return value


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
        covered = (
            _collect_daily_summaries_window(
                client, window_start, window_end, payload, stats, external_call
            )
            if source == "daily_stats"
            else set()
        )
        current = window_start
        while current <= window_end:
            if current.isoformat() not in covered:
                _collect_daily_stats_day(
                    fetch, current, payload, stats, external_call, redact, warn, source
                )
            current += timedelta(days=1)


def _collect_daily_summaries_window(
    client: Any,
    start: date,
    end: date,
    payload: dict[str, Any],
    stats: dict[str, Any],
    external_call: ExternalCall,
) -> set[str]:
    fetch = getattr(client, "get_daily_summaries", None)
    if not callable(fetch):
        return set()
    try:
        response = external_call(
            "garmin",
            "daily_stats",
            partial(fetch, start.isoformat(), end.isoformat()),
            {"start": start.isoformat(), "end": end.isoformat()},
        )
        records = response.get("data") if isinstance(response, dict) else response
        if not isinstance(records, list) or any(
            not isinstance(row, dict) for row in records
        ):
            return set()
    except Exception:  # noqa: BLE001 - the per-day reader reports any actual gaps.
        return set()
    accepted: list[dict[str, Any]] = []
    covered: set[str] = set()
    for row in records:
        day = row.get("calendarDate") or row.get("summaryDate") or row.get("date")
        try:
            observed = date.fromisoformat(day[:10]) if isinstance(day, str) else None
        except ValueError:
            observed = None
        if observed is not None and start <= observed <= end:
            accepted.append(row)
            covered.add(observed.isoformat())
    payload.setdefault("daily_stats", []).extend(accepted)
    stats["records"] = int(stats["records"]) + len(accepted)
    return covered


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
        (
            "training_readiness_history",
            getattr(client, "get_training_readiness_range", None),
            lambda fetch: fetch(start.isoformat(), end.isoformat()),
            "daily",
        ),
        (
            "weekly_training_status",
            getattr(client, "get_weekly_training_status", None),
            lambda fetch: fetch(start.isoformat(), end.isoformat()),
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
        _fetch_historic_metric(
            key,
            fetch,
            invoke,
            details,
            stats,
            payload,
            external_call,
            redact,
            warn,
            capability_failure,
            capability_success,
        )


def _fetch_historic_metric(
    key,
    fetch,
    invoke,
    details,
    stats,
    payload,
    external_call,
    redact,
    warn,
    capability_failure,
    capability_success,
) -> None:
    try:
        value = external_call("garmin", key, partial(invoke, fetch), details)
        _validate_historic_metric(value, key)
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
        linked = _gear_activity_ids(client, normalized["gearUUID"], external_call)
        result.append({**normalized, "stats": stats or {}, **(linked or {})})
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


GEAR_ACTIVITIES_LIMIT = 1000


def _gear_activity_ids(
    client: Any, gear_uuid: str, external_call: ExternalCall
) -> dict[str, Any] | None:
    """Read the Garmin activities linked to one gear item (read-only).

    ``None`` means the link list is unknown (method missing or call failed), which
    is not the same as an empty list of activities.
    """
    fetch = getattr(client, "get_gear_activities", None)
    if not callable(fetch):
        return None
    try:
        result = external_call(
            "garmin",
            "gear_activities",
            partial(fetch, gear_uuid, GEAR_ACTIVITIES_LIMIT),
            None,
        )
    except Exception:  # noqa: BLE001 - omit only this unavailable optional row.
        return None
    if not isinstance(result, list):
        return None
    if not result and callable(getattr(client, "connectapi", None)):
        # 0.3.19 maps this endpoint's 404 to []. Check only ambiguous empty
        # results against the same authenticated URL so genuine empty 200s clear links.
        base = getattr(client, "garmin_connect_activities_baseurl", None)
        if not isinstance(base, str):
            return None
        try:
            verified = external_call(
                "garmin",
                "gear_activities",
                lambda: client.connectapi(
                    f"{base}{gear_uuid}/gear",
                    params={"start": 0, "limit": GEAR_ACTIVITIES_LIMIT},
                ),
                None,
            )
        except Exception:  # noqa: BLE001 - a hidden 404 leaves old links stale.
            return None
        if not isinstance(verified, list):
            return None
        result = verified
    ids = list(
        dict.fromkeys(
            str(item["activityId"])
            for item in result
            if isinstance(item, dict) and item.get("activityId") not in (None, "")
        )
    )
    linked: dict[str, Any] = {"activity_ids": ids}
    if len(result) >= GEAR_ACTIVITIES_LIMIT:
        linked["activity_ids_truncated"] = True
    return linked


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


ACTIVITY_DETAIL_MAX_CHART_POINTS = 2000


def collect_garmin_activity_detail(
    client: Any,
    activity_id: str,
    *,
    external_call: ExternalCall,
    redact: Redact,
    warn: WarningLogger | None = None,
    capability_allowed: CapabilityAllowed | None = None,
    capability_failure: CapabilityFailure | None = None,
    capability_success: CapabilitySuccess | None = None,
) -> dict[str, Any]:
    """Collect one Garmin activity's detail parts, keeping each part that succeeds.

    Every part is a separate call. A paused part is skipped without a call and
    its capability is listed in ``skipped``; a failed part is omitted from the
    result and recorded in ``errors`` after redaction. ``errors`` and ``skipped``
    are present only when at least one part failed or was skipped.
    """
    payload: dict[str, Any] = {"activity_id": activity_id, "errors": []}
    skipped: list[str] = []
    # (capability key, payload key, fetch). The capability key also names the
    # external call, matching ``_fetch_range``.
    parts: tuple[tuple[str, str, Callable[[], Any]], ...] = (
        (
            "activity_details",
            "details",
            lambda: client.get_activity_details(
                activity_id, maxchart=ACTIVITY_DETAIL_MAX_CHART_POINTS
            ),
        ),
        ("activity_splits", "splits", lambda: client.get_activity_splits(activity_id)),
        (
            "activity_hr_zones",
            "hr_zones",
            lambda: client.get_activity_hr_in_timezones(activity_id),
        ),
        (
            "activity_power_zones",
            "power_zones",
            lambda: client.get_activity_power_in_timezones(activity_id),
        ),
    )
    for capability, key, fetch in parts:
        if capability_allowed is not None and not capability_allowed(capability):
            skipped.append(capability)
            continue
        try:
            payload[key] = external_call(
                "garmin", capability, fetch, {"activity_id": activity_id}
            )
            if capability_success is not None:
                capability_success(capability)
        except Exception as exc:  # noqa: BLE001 - SDK errors vary; keep other parts and redact.
            if capability_failure is not None:
                capability_failure(capability, exc)
            _add_error(payload, capability, exc, redact, warn)
    if not payload["errors"]:
        del payload["errors"]
    if skipped:
        payload["skipped"] = skipped
    return payload


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


def _validate_historic_metric(value: Any, key: str) -> None:
    if not isinstance(value, (dict, list)):
        raise TypeError(f"Invalid Garmin {key} response")
    if isinstance(value, list) and any(not isinstance(item, dict) for item in value):
        raise TypeError(f"Invalid Garmin {key} response records")
