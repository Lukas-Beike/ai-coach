"""Garmin performance-history merge and retention at ingest.

The sync runs this on a fetched payload before it is stored. The latest-value
sections are replaced on each sync, so the accumulated history is the only stored
record of their earlier days. The day's values come from the health mapper, the one
Garmin health parser, read by the rules of the canonical Garmin metrics.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.decimal_text import provider_number
from backend.canonical.vocabulary import MetricKind
from backend.performance import freshness as performance_freshness
from backend.performance.garmin_canonical import garmin_metrics_of
from backend.performance.garmin_metrics import garmin_performance_metrics
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.providers.garmin_weight_walk import WEIGHT_SECTIONS
from backend.sync import garmin_metric_history
from backend.sync.garmin_payload_metrics import garmin_source_observed_at

# The sections the history records, read as the current Garmin metrics read them.
_CURRENT_SECTIONS: Final = (
    "max_metrics",
    "race_predictions",
    "running_threshold",
    "cycling_ftp",
    "heart_rate_zones",
    "readiness",
    *WEIGHT_SECTIONS,
)
# The plausible window of a historical FTP value.
_FTP_HISTORY_RANGE: Final = (20, 2000)


def append_garmin_performance_history(
    payload: dict[str, Any],
    previous: dict[str, Any] | None,
    current_date: date,
) -> None:
    history = list((previous or {}).get("performance_history") or []) + list(
        payload.get("performance_history") or []
    )
    unique = _merged_history(history)
    for key, data in current_garmin_metrics(payload, current_date).items():
        if (
            data.get("value") is None
            or data.get("freshness") != "current"
            or not data.get("observed_at")
        ):
            continue
        observed = iso_date_prefix(str(data["observed_at"]))
        entry = unique.setdefault(observed, {"date": observed, "metrics": {}})
        entry["metrics"][key] = data["value"]
    # Historical FTP rows are the only source allowed to add past FTP values;
    # current FTP settings are intentionally not backfilled into this series.
    start = current_date - timedelta(days=89)
    for day, value in _ftp_history(payload, start, current_date).items():
        entry = unique.setdefault(day, {"date": day, "metrics": {}})
        entry["metrics"]["cycling_ftp_watts"] = value
    provider_metrics = _provider_metrics(payload, start, current_date)
    payload["provider_metrics"] = provider_metrics
    payload["performance_history"] = [unique[key] for key in sorted(unique)[-90:]]


def current_garmin_metrics(
    payload: dict[str, Any], current_date: date
) -> dict[str, dict[str, Any]]:
    """The labelled, freshness-stamped Garmin metrics and readiness of a payload.

    The latest-value sections are mapped by the health mapper and read by the rules
    of the canonical Garmin metrics, without the activity max heart rate fallback.
    """
    status = performance_freshness.GarminSyncStatus.from_state(payload)
    canonical = garmin_metrics_of(
        _mapped(
            {name: payload[name] for name in _CURRENT_SECTIONS if name in payload},
            current_date,
        )
    )
    current = garmin_performance_metrics(status, current_date, canonical)
    # The newest readiness record counts even without a usable score, so an
    # older day's score never stands in for it.
    newest = garmin_source_observed_at(payload.get("readiness"))
    readiness = canonical.performance_history.get("readiness", {})
    value = readiness.get(date.fromisoformat(newest)) if newest else None
    current["readiness"] = performance_freshness.garmin_metric_freshness(
        status,
        "readiness",
        {"value": None if value is None else provider_number(value)},
        current_date,
    )
    return current


def _mapped(sections: dict[str, Any], current_date: date) -> tuple[Any, ...]:
    """Map ``sections``; an undated latest value falls on the local sync day."""
    retrieved_at = datetime.combine(current_date, time(12), tzinfo=UTC)
    return map_garmin_health(sections, zone=UTC, retrieved_at=retrieved_at).records


def _ftp_history(
    payload: dict[str, Any], start: date, current_date: date
) -> dict[str, float]:
    """The dated cycling FTP of the history section per day; a later record wins."""
    low, high = _FTP_HISTORY_RANGE
    return {
        item.observed_on.isoformat(): round(item.value.value, 2)
        for item in _mapped(
            {"cycling_ftp_history": payload.get("cycling_ftp_history")}, current_date
        )
        if item.kind is MetricKind.FTP
        and start <= item.observed_on <= current_date
        and low <= item.value.value <= high
    }


def _merged_history(history: list) -> dict[str, dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for item in history:
        if (
            isinstance(item, dict)
            and item.get("date")
            and isinstance(item.get("metrics"), dict)
        ):
            entry = unique.setdefault(
                str(item["date"]), {"date": str(item["date"]), "metrics": {}}
            )
            entry["metrics"].update(item["metrics"])
    return unique


def _provider_metrics(
    payload: dict[str, Any], start: date, current_date: date
) -> dict[str, Any]:
    return {
        source: _project_provider_metric(
            payload, source, aggregation, start, current_date
        )
        for source, aggregation in (
            ("endurance_score", "daily"),
            ("running_tolerance", "daily"),
            ("training_readiness_history", "daily"),
            ("weekly_training_status", "weekly"),
        )
    }


def _project_provider_metric(
    payload: dict[str, Any],
    source: str,
    aggregation: str,
    start: date,
    current_date: date,
) -> dict[str, Any]:
    details = (payload.get("source_freshness") or {}).get(source, {})
    pagination = ((payload.get("provider_sync") or {}).get("pagination") or {}).get(
        source, {}
    )
    error_sources = {
        item.get("source")
        for item in payload.get("errors") or []
        if isinstance(item, dict)
    }
    state = _provider_metric_state(source, details, pagination, error_sources)
    data = garmin_metric_history.projected_metric(
        payload.get(source),
        start=start,
        end=current_date,
        aggregation=aggregation,
        metric=source,
        synced_at=payload.get("synced_at"),
    )
    data["status"] = (
        "current" if data["points"] and details.get("freshness") == "current" else state
    )
    return data


def _provider_metric_state(
    source: str,
    details: dict[str, Any],
    pagination: dict[str, Any],
    error_sources: set[Any],
) -> str:
    if details.get("freshness") == "stale":
        return "stale"
    if source in error_sources or pagination.get("status") == "failed":
        return "failed"
    if pagination.get("available") is False:
        return "unsupported"
    return "unknown"
