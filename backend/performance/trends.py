"""Pure historical performance trend projections."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from backend.performance import activity_validation, wellness


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_number(value: Any) -> float | int | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def garmin_history_average(
    snapshot: dict[str, Any], key: str, days: int, end_date: date
) -> float | None:
    cutoff = end_date - timedelta(days=days - 1)
    values: list[float] = []
    history = (
        snapshot.get("performance_history")
        if isinstance(snapshot.get("performance_history"), list)
        else []
    )
    for item in history:
        if not isinstance(item, dict):
            continue
        try:
            item_date = date.fromisoformat(str(item.get("date"))[:10])
        except (TypeError, ValueError):
            continue
        if not cutoff <= item_date <= end_date:
            continue
        value = _as_number((item.get("metrics") or {}).get(key))
        if value is not None:
            values.append(float(value))
    return round(sum(values) / len(values), 2) if values else None


def _sport_info_setting(wellness_row: dict[str, Any], sport: str) -> dict[str, Any]:
    match_terms = (
        ("run", "lauf")
        if sport == "run"
        else (
            "ride",
            "bike",
            "rad",
            "cycling",
        )
    )
    sport_info = wellness_row.get("sport_info", wellness_row.get("sportInfo", []))
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


def _threshold_pace_seconds(value: Any) -> float | int | None:
    number = _as_number(value)
    if number is None or number <= 0:
        return None
    return round(1000 / number) if number < 20 else number


def _zone2_pace_seconds(value: Any) -> float | int | None:
    pace = _threshold_pace_seconds(value)
    return pace if pace is not None and 120 <= float(pace) <= 1800 else None


def intervals_performance_average(
    rows: list[dict[str, Any]], key: str, days: int, end_date: date
) -> float | None:
    cutoff = end_date - timedelta(days=days - 1)
    values: list[float] = []
    for row in rows:
        try:
            row_date = date.fromisoformat(
                str(row.get("id") or row.get("date") or "")[:10]
            )
        except (TypeError, ValueError):
            continue
        if not cutoff <= row_date <= end_date:
            continue
        ride = _sport_info_setting(row, "ride")
        run = _sport_info_setting(row, "run")
        candidates: dict[str, Any] = {
            "cycling_ftp_watts": _first_present(ride, ("ftp", "indoor_ftp")),
            "bike_threshold_hr_bpm": _first_present(ride, ("lthr",)),
            "cycling_vo2max_ml_kg_min": _first_present(
                ride, ("vo2max", "vo2_max", "cycling_vo2max")
            ),
            "run_threshold_watts": _first_present(
                run, ("ftp", "indoor_ftp", "eftp", "eFTP")
            ),
            "run_threshold_pace_seconds_per_km": _threshold_pace_seconds(
                _first_present(run, ("threshold_pace",))
            ),
            "run_zone2_pace_seconds_per_km": _zone2_pace_seconds(
                _first_present(
                    run,
                    (
                        "zone2_pace",
                        "zone_2_pace",
                        "z2_pace",
                        "pace_zone2",
                        "paceZone2",
                        "zone2Pace",
                    ),
                )
            ),
            "run_threshold_hr_bpm": _first_present(run, ("lthr",)),
            "running_vo2max_ml_kg_min": _first_present(
                run, ("vo2max", "vo2_max", "running_vo2max")
            ),
            "weight_kg": _first_present(row, ("weight",)),
            "readiness": wellness.readiness_score_value(
                _first_present(
                    row,
                    (
                        "readiness",
                        "readinessScore",
                        "readiness_score",
                        "trainingReadiness",
                        "training_readiness",
                    ),
                )
            ),
        }
        value = activity_validation.bounded_performance_metric(key, candidates.get(key))
        if value is not None:
            values.append(float(value))
    return round(sum(values) / len(values), 2) if values else None
