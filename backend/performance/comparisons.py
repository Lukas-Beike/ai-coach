"""Pure performance trend and comparison projections."""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.performance import eftp, garmin_metrics, garmin_weight, trends, wellness

VO2MAX_UNIT = "ml/kg/min"


def performance_trend_average(
    snapshot: dict[str, Any],
    garmin: dict[str, Any],
    metrics: dict[str, dict[str, Any]],
    key: str,
    days: int,
    end_date: date,
) -> float | None:
    current_source = metrics.get(key, {}).get("source")
    if current_source == garmin_metrics.GARMIN_PERFORMANCE_SOURCE:
        if key == "weight_kg":
            return garmin_weight.garmin_weight_average(garmin, days, end_date)
        return trends.garmin_history_average(garmin, key, days, end_date)
    rows = (
        snapshot.get("recent_wellness")
        if isinstance(snapshot.get("recent_wellness"), list)
        else []
    )
    return trends.intervals_performance_average(
        [row for row in rows if isinstance(row, dict)], key, days, end_date
    )


def _performance_trend(
    snapshot: dict[str, Any],
    garmin: dict[str, Any],
    metrics: dict[str, dict[str, Any]],
    key: str,
    unit: str,
    today: date,
    higher_is_better: bool | None = True,
) -> dict[str, Any] | None:
    return wellness.comparison_value(
        metrics.get(key, {}).get("value"),
        performance_trend_average(snapshot, garmin, metrics, key, 30, today),
        unit,
        30,
        higher_is_better,
    )


def performance_comparisons(
    snapshot: dict[str, Any],
    garmin: dict[str, Any],
    metrics: dict[str, dict[str, Any]],
    recovery: dict[str, Any],
    load_context: dict[str, Any],
    wellness_rows: list[dict[str, Any]],
    activities: list[Any],
    today: date,
) -> dict[str, Any]:
    load = load_context["load"]
    last_7 = load_context["last_7"]
    previous_7 = load_context["previous_7"]
    previous_30 = load_context["previous_30"]

    def trend(
        key: str, unit: str = "", higher_is_better: bool | None = True
    ) -> dict[str, Any] | None:
        return _performance_trend(
            snapshot, garmin, metrics, key, unit, today, higher_is_better
        )

    readiness_trend = wellness.comparison_value(
        recovery["readiness"],
        performance_trend_average(
            snapshot,
            garmin,
            {"readiness": {"source": recovery["readiness_source"]}},
            "readiness",
            30,
            today,
        ),
        "",
        30,
    )
    return {
        "sleep_hours": wellness.comparison_value(
            recovery["sleep_hours"], recovery["sleep_average"], "h", 7
        ),
        "readiness": wellness.comparison_value(
            recovery["readiness"], recovery["readiness_average"], "", 7
        ),
        "restingHR": wellness.comparison_value(
            recovery["resting_hr"],
            recovery["resting_hr_average"],
            "bpm",
            7,
            higher_is_better=False,
        ),
        "hrv": wellness.comparison_value(
            recovery["hrv"], recovery["hrv_average"], "ms", 7
        ),
        "cycling_eftp_30d": wellness.comparison_value(
            metrics["cycling_eftp_watts"]["value"],
            eftp.eftp_30_day_average(wellness_rows, activities, today),
            "W",
            30,
        ),
        "fitness_ctl": wellness.comparison_value(
            load["ctl"],
            wellness.wellness_average(wellness_rows, ("ctl", "ctLoad"), 7, today),
            "",
            7,
        ),
        "form_tsb": wellness.comparison_value(
            load["tsb"], wellness.wellness_form_average(wellness_rows, 7, today), "", 7
        ),
        "fatigue_atl": wellness.comparison_value(
            load["atl"],
            wellness.wellness_average(wellness_rows, ("atl", "atlLoad"), 7, today),
            "",
            7,
            higher_is_better=False,
        ),
        "fatigue_atl_actual": wellness.comparison_value(
            load_context["actual_atl_current"],
            load_context["actual_atl_average"],
            "",
            7,
            higher_is_better=False,
        ),
        "training_load_7d": wellness.comparison_value(
            last_7["training_load"],
            previous_7["training_load"],
            "",
            7,
            label="vorherigen 7 Tagen",
        ),
        "training_volume_7d": wellness.comparison_value(
            last_7["duration_hours"],
            previous_30["duration_hours"] * 7 / 30,
            "h",
            30,
            label="Schnitt der 30 Tage davor",
        ),
        "weight_kg_30d": trend("weight_kg", "kg", None),
        "readiness_30d": readiness_trend,
        "cycling_ftp_watts_30d": trend("cycling_ftp_watts", "W"),
        "bike_threshold_hr_bpm_30d": trend("bike_threshold_hr_bpm", "bpm"),
        "run_threshold_watts_30d": trend("run_threshold_watts", "W"),
        "run_threshold_pace_seconds_per_km_30d": trend(
            "run_threshold_pace_seconds_per_km", "s/km", False
        ),
        "run_zone2_pace_seconds_per_km_30d": trend(
            "run_zone2_pace_seconds_per_km", "s/km", False
        ),
        "run_threshold_hr_bpm_30d": trend("run_threshold_hr_bpm", "bpm"),
        "cycling_vo2max_ml_kg_min_30d": trend("cycling_vo2max_ml_kg_min", VO2MAX_UNIT),
        "running_vo2max_ml_kg_min_30d": trend("running_vo2max_ml_kg_min", VO2MAX_UNIT),
        "run_5k_seconds_30d": trend("run_5k_seconds", "s", False),
        "run_10k_seconds_30d": trend("run_10k_seconds", "s", False),
        "run_half_marathon_seconds_30d": trend("run_half_marathon_seconds", "s", False),
        "run_marathon_seconds_30d": trend("run_marathon_seconds", "s", False),
    }
