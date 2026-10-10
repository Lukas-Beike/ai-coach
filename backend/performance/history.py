"""Garmin performance-history merge and retention orchestration."""

from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.performance import freshness as performance_freshness
from backend.performance import garmin_metric_history
from backend.performance import garmin_metrics as performance_garmin_metrics
from backend.performance import wellness as performance_wellness


def append_garmin_performance_history(
    payload: dict[str, Any],
    previous: dict[str, Any] | None,
    current_date: date,
) -> None:
    history = list((previous or {}).get("performance_history") or []) + list(
        payload.get("performance_history") or []
    )
    unique = _merged_history(history)
    current = performance_garmin_metrics.garmin_performance_metrics(
        payload, current_date
    )
    current["readiness"] = performance_freshness.garmin_metric_freshness(
        payload,
        "readiness",
        {"value": performance_wellness.readiness_score_value(payload.get("readiness"))},
        current_date,
    )
    for key, data in current.items():
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
    for row in garmin_metric_history.ftp_points(
        payload.get("cycling_ftp_history"),
        start=start,
        end=current_date,
    ):
        entry = unique.setdefault(row["date"], {"date": row["date"], "metrics": {}})
        entry["metrics"]["cycling_ftp_watts"] = row["value"]
    provider_metrics = _provider_metrics(payload, start, current_date)
    payload["provider_metrics"] = provider_metrics
    payload["performance_history"] = [unique[key] for key in sorted(unique)[-90:]]


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
            ("endurance_score", "weekly"),
            ("running_tolerance", "weekly"),
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
