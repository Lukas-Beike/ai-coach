"""Garmin performance-history merge and retention orchestration."""

from datetime import date
from typing import Any

from backend.performance import freshness as performance_freshness
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
        observed = str(data["observed_at"])[:10]
        entry = unique.setdefault(observed, {"date": observed, "metrics": {}})
        entry["metrics"][key] = data["value"]
    payload["performance_history"] = [unique[key] for key in sorted(unique)[-90:]]
