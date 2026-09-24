"""Pure Garmin measurement-age and freshness projections."""

from __future__ import annotations

from datetime import date
from typing import Any


def measurement_age(observed_at: Any, current_date: date) -> dict[str, Any]:
    """Describe observation age independently of a successful provider read."""
    try:
        days = (current_date - date.fromisoformat(str(observed_at)[:10])).days
    except (TypeError, ValueError):
        return {"measurement_status": "unknown", "measurement_age_days": None}
    if days == 0:
        measurement_status = "today"
    elif days > 0:
        measurement_status = "earlier"
    else:
        measurement_status = "future"
    return {"measurement_status": measurement_status, "measurement_age_days": days}


def garmin_source_freshness(
    snapshot: dict[str, Any], current_date: date
) -> dict[str, Any]:
    return {
        source: {**details, **measurement_age(details.get("observed_at"), current_date)}
        for source, details in (snapshot.get("source_freshness") or {}).items()
        if isinstance(details, dict)
    }


def garmin_metric_freshness(
    snapshot: dict[str, Any], source: str, value: dict[str, Any], current_date: date
) -> dict[str, Any]:
    """Expose observation and retrieval dates without treating a retained value as a new reading."""
    freshness = (snapshot.get("source_freshness") or {}).get(source) or {}
    status = freshness.get("freshness", "unknown")
    observed_at = value.get("observed_at", freshness.get("observed_at"))
    result = {
        **value,
        "freshness": status,
        "fetched_at": freshness.get("fetched_at"),
        "observed_at": observed_at,
        **measurement_age(observed_at, current_date),
    }
    if result["measurement_status"] == "earlier":
        result["note"] = "; ".join(
            part
            for part in (
                str(result.get("note") or ""),
                f"Messung ist {result['measurement_age_days']} Tage alt; das Abrufdatum ist keine neue Messung.",
            )
            if part
        )
    if status in {"stale", "partial"} and value.get("value") is not None:
        label = (
            "Letzter guter Wert; Quelle nicht aktualisiert"
            if status == "stale"
            else "Quelle nur teilweise aktualisiert"
        )
        result["note"] = "; ".join(
            part for part in (str(result.get("note") or ""), label) if part
        )
    return result
