"""Thirty-day cycling eFTP aggregation."""

from datetime import date, timedelta
from typing import Any

from backend.performance import activity_validation


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _sport_info_setting(wellness: dict[str, Any]) -> dict[str, Any]:
    match_terms = ("ride", "bike", "rad", "cycling")
    sport_info = wellness.get("sport_info", wellness.get("sportInfo", []))
    if not isinstance(sport_info, list):
        return {}
    for info in sport_info:
        if not isinstance(info, dict):
            continue
        raw_types = (
            info.get("types")
            if isinstance(info.get("types"), list)
            else [info.get("type"), info.get("sport"), info.get("sport_type")]
        )
        if any(
            any(term in str(activity_type or "").casefold() for term in match_terms)
            for activity_type in raw_types
        ):
            return info
    return {}


def _wellness_eftp_value(
    row: dict[str, Any], cutoff: date, anchor: date
) -> float | None:
    try:
        row_date = date.fromisoformat(str(row.get("id") or row.get("date") or "")[:10])
    except ValueError:
        return None
    if not cutoff <= row_date <= anchor:
        return None
    info = _sport_info_setting(row)
    value = activity_validation.bounded_performance_metric(
        "cycling_eftp_watts", _first_present(info, ("eftp", "eFTP"))
    )
    return float(value) if value is not None else None


def _activity_eftp_value(activity: Any, cutoff: date, anchor: date) -> float | None:
    if not isinstance(activity, dict):
        return None
    try:
        activity_date = date.fromisoformat(
            str(activity.get("start_date_local") or "")[:10]
        )
    except (TypeError, ValueError):
        return None
    if not cutoff <= activity_date <= anchor:
        return None
    raw_type = str(
        _first_present(
            activity, ("type", "sport", "sport_type", "activity_type", "name")
        )
        or ""
    ).casefold()
    if not any(term in raw_type for term in ("ride", "rad", "bike", "cycling")):
        return None
    value = activity_validation.bounded_performance_metric(
        "cycling_eftp_watts",
        _first_present(activity, ("icu_eftp", "eftp", "eFTP")),
    )
    return float(value) if value is not None else None


def eftp_30_day_average(
    wellness_rows: list[dict[str, Any]], activities: list[Any], end_date: date
) -> float | None:
    cutoff = end_date - timedelta(days=29)
    values: list[float] = []
    for row in wellness_rows:
        value = _wellness_eftp_value(row, cutoff, end_date)
        if value is not None:
            values.append(value)
    for activity in activities:
        value = _activity_eftp_value(activity, cutoff, end_date)
        if value is not None:
            values.append(value)
    return round(sum(values) / len(values), 1) if values else None
