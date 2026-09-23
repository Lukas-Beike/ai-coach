"""Current performance metric composition from explicit normalized inputs."""

import math
from typing import Any

from backend.activities.identity import activity_kind

PROVIDER_INTERVALS_NAME = "Intervals.icu"
PROVIDER_INTERVALS_WELLNESS_NAME = "Intervals.icu Wellness"
GARMIN_PERFORMANCE_SOURCE = "Garmin Connect"
VO2MAX_UNIT = "ml/kg/min"


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


def _metric(
    value: Any, unit: str, source: str | None, note: str = ""
) -> dict[str, Any]:
    number = _as_number(value)
    return {
        "value": number,
        "unit": unit,
        "source": source if number is not None else None,
        "note": note if number is not None else "",
    }


def _sport_setting(athlete: dict[str, Any], sport: str) -> dict[str, Any]:
    match_terms = (
        ("run", "lauf") if sport == "run" else ("ride", "bike", "rad", "cycling")
    )
    for setting in athlete.get("sport_settings", []):
        if not isinstance(setting, dict):
            continue
        types = setting.get("types") if isinstance(setting.get("types"), list) else []
        if any(
            any(term in str(activity_type).casefold() for term in match_terms)
            for activity_type in types
        ):
            return setting
    return {}


def _sport_info_setting(wellness: dict[str, Any], sport: str) -> dict[str, Any]:
    match_terms = (
        ("run", "lauf") if sport == "run" else ("ride", "bike", "rad", "cycling")
    )
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


def _intervals_eftp_value(setting: Any) -> Any:
    """Read Intervals.icu's estimated FTP without falling back to user FTP."""
    if not isinstance(setting, dict):
        return None
    mmp_model = setting.get("mmp_model")
    if isinstance(mmp_model, dict):
        value = _first_present(mmp_model, ("ftp", "eftp", "eFTP"))
        if value not in (None, ""):
            return value
    return _first_present(setting, ("eftp", "eFTP"))


def _intervals_max_hr_metric(
    sport: str,
    setting: dict[str, Any],
    wellness_setting: dict[str, Any],
    activities: list[Any],
    athlete: dict[str, Any],
) -> dict[str, Any]:
    """Return sport-specific max HR with an explicit source."""
    max_hr_keys = ("max_hr", "maxHR", "maxHeartRate", "max_heartrate")
    candidates: list[tuple[Any, str]] = [
        (_first_present(setting, max_hr_keys), PROVIDER_INTERVALS_NAME),
        (
            _first_present(wellness_setting, max_hr_keys),
            PROVIDER_INTERVALS_WELLNESS_NAME,
        ),
    ]
    activity_values: list[float | int] = []
    for activity in activities:
        if activity_kind(activity) != sport:
            continue
        value = _as_number(_first_present(activity, max_hr_keys))
        if value is not None and 80 <= float(value) <= 260:
            activity_values.append(value)
    if activity_values:
        candidates.append((max(activity_values), PROVIDER_INTERVALS_NAME))
    candidates.extend([(_first_present(athlete, max_hr_keys), PROVIDER_INTERVALS_NAME)])
    for value, source in candidates:
        number = _as_number(value)
        if number is not None and 80 <= float(number) <= 260:
            return _metric(number, "bpm", source)
    return _metric(None, "bpm", None)


def _threshold_pace_seconds(value: Any) -> float | int | None:
    number = _as_number(value)
    if number is None or number <= 0:
        return None
    return round(1000 / number) if number < 20 else number


def _zone2_pace_seconds(value: Any) -> float | int | None:
    pace = _threshold_pace_seconds(value)
    return pace if pace is not None and 120 <= float(pace) <= 1800 else None


def _height_in_cm(value: Any) -> float | int | None:
    number = _as_number(value)
    if number is not None and 1.2 <= float(number) <= 2.5:
        return round(float(number) * 100, 1)
    return number


def _performance_snapshot_inputs(
    snapshot: dict[str, Any],
) -> tuple[
    dict[str, Any],
    list[Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    athlete = (
        snapshot.get("athlete") if isinstance(snapshot.get("athlete"), dict) else {}
    )
    wellness_rows = (
        [row for row in snapshot.get("recent_wellness", []) if isinstance(row, dict)]
        if isinstance(snapshot.get("recent_wellness"), list)
        else []
    )
    activities = (
        snapshot.get("recent_activities")
        if isinstance(snapshot.get("recent_activities"), list)
        else []
    )
    latest_wellness = max(
        wellness_rows, key=lambda row: str(row.get("id") or ""), default={}
    )
    ride = _sport_setting(athlete, "ride")
    run = _sport_setting(athlete, "run")
    wellness_ride = _sport_info_setting(latest_wellness, "ride")
    wellness_run = _sport_info_setting(latest_wellness, "run")
    return athlete, activities, latest_wellness, ride, run, wellness_ride, wellness_run


def _latest_ride_activity(activities: list[Any]) -> dict[str, Any]:
    ride_terms = ("ride", "rad", "bike", "cycling")
    valid_activities = (
        activity for activity in activities if isinstance(activity, dict)
    )
    ordered = sorted(
        valid_activities,
        key=lambda item: str(item.get("start_date_local") or ""),
        reverse=True,
    )
    return next(
        (
            activity
            for activity in ordered
            if any(
                term
                in str(
                    _first_present(
                        activity,
                        ("type", "sport", "sport_type", "activity_type", "name"),
                    )
                    or ""
                ).casefold()
                for term in ride_terms
            )
        ),
        {},
    )


def _first_performance_source(
    sources: tuple[tuple[Any, str], ...],
) -> tuple[Any, str | None]:
    return next(
        ((value, source) for value, source in sources if _as_number(value) is not None),
        (None, None),
    )


def _performance_body_metrics(
    athlete: dict[str, Any],
    latest_wellness: dict[str, Any],
    profile: dict[str, Any],
    garmin_metrics: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    weight_value, weight_source = _first_performance_source(
        (
            (garmin_metrics["weight_kg"]["value"], GARMIN_PERFORMANCE_SOURCE),
            (
                _first_present(latest_wellness, ("weight",)),
                PROVIDER_INTERVALS_WELLNESS_NAME,
            ),
            (_first_present(athlete, ("weight",)), PROVIDER_INTERVALS_NAME),
            (profile.get("weight_kg"), "Manuell"),
        )
    )
    body_fat_value, body_fat_source = _first_performance_source(
        (
            (
                _first_present(latest_wellness, ("bodyFat", "body_fat")),
                PROVIDER_INTERVALS_WELLNESS_NAME,
            ),
            (_first_present(athlete, ("bodyFat", "body_fat")), PROVIDER_INTERVALS_NAME),
            (profile.get("body_fat_pct"), "Manuell"),
        )
    )
    height_value, height_source = _first_performance_source(
        (
            (_first_present(athlete, ("height_cm", "height")), PROVIDER_INTERVALS_NAME),
            (profile.get("height_cm"), "Manuell"),
        )
    )
    weight_metric = (
        garmin_metrics["weight_kg"]
        if weight_source == GARMIN_PERFORMANCE_SOURCE
        else _metric(weight_value, "kg", weight_source)
    )
    return {
        "weight_kg": weight_metric,
        "body_fat_pct": _metric(body_fat_value, "%", body_fat_source),
        "height_cm": _metric(_height_in_cm(height_value), "cm", height_source),
    }


def _preferred_performance_metric(
    garmin_metrics: dict[str, dict[str, Any]], key: str, fallback: dict[str, Any]
) -> dict[str, Any]:
    current = garmin_metrics[key]
    return current if current["value"] is not None else fallback


def _performance_threshold_metrics(
    athlete: dict[str, Any],
    ride: dict[str, Any],
    run: dict[str, Any],
    wellness_ride: dict[str, Any],
    wellness_run: dict[str, Any],
    garmin_metrics: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    generic_lthr = _first_present(athlete, ("lthr",))
    bike_lthr = _first_present(ride, ("lthr",)) or _first_present(
        wellness_ride, ("lthr",)
    )
    run_lthr = _first_present(run, ("lthr",)) or _first_present(wellness_run, ("lthr",))
    run_zone2_pace = _first_present(
        run,
        (
            "zone2_pace",
            "zone_2_pace",
            "z2_pace",
            "pace_zone2",
            "paceZone2",
            "zone2Pace",
        ),
    ) or _first_present(
        wellness_run,
        (
            "zone2_pace",
            "zone_2_pace",
            "z2_pace",
            "pace_zone2",
            "paceZone2",
            "zone2Pace",
        ),
    )
    return {
        "cycling_ftp_watts": _preferred_performance_metric(
            garmin_metrics,
            "cycling_ftp_watts",
            _metric(
                _first_present(ride, ("ftp", "indoor_ftp"))
                or _first_present(wellness_ride, ("ftp", "indoor_ftp"))
                or _first_present(athlete, ("icu_ftp",)),
                "W",
                PROVIDER_INTERVALS_NAME,
            ),
        ),
        "run_threshold_watts": _preferred_performance_metric(
            garmin_metrics,
            "run_threshold_watts",
            _metric(
                _first_present(run, ("ftp", "indoor_ftp"))
                or _first_present(wellness_run, ("ftp", "indoor_ftp")),
                "W",
                PROVIDER_INTERVALS_NAME,
            ),
        ),
        "run_threshold_pace_seconds_per_km": _preferred_performance_metric(
            garmin_metrics,
            "run_threshold_pace_seconds_per_km",
            _metric(
                _threshold_pace_seconds(
                    _first_present(run, ("threshold_pace",))
                    or _first_present(wellness_run, ("threshold_pace",))
                ),
                "s/km",
                PROVIDER_INTERVALS_NAME,
            ),
        ),
        "run_zone2_pace_seconds_per_km": _metric(
            _zone2_pace_seconds(run_zone2_pace),
            "s/km",
            PROVIDER_INTERVALS_NAME,
        ),
        "bike_threshold_hr_bpm": _preferred_performance_metric(
            garmin_metrics,
            "bike_threshold_hr_bpm",
            _metric(
                bike_lthr or generic_lthr,
                "bpm",
                PROVIDER_INTERVALS_NAME if bike_lthr else "Intervals.icu (allgemein)",
            ),
        ),
        "run_threshold_hr_bpm": _preferred_performance_metric(
            garmin_metrics,
            "run_threshold_hr_bpm",
            _metric(
                run_lthr or generic_lthr,
                "bpm",
                PROVIDER_INTERVALS_NAME if run_lthr else "Intervals.icu (allgemein)",
            ),
        ),
    }


def _performance_vo2_and_prediction_metrics(
    athlete: dict[str, Any],
    ride: dict[str, Any],
    run: dict[str, Any],
    wellness_ride: dict[str, Any],
    wellness_run: dict[str, Any],
    garmin_metrics: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    cycling_vo2 = (
        _first_present(ride, ("vo2max", "vo2_max", "cycling_vo2max"))
        or _first_present(wellness_ride, ("vo2max", "vo2_max", "cycling_vo2max"))
        or _first_present(athlete, ("cycling_vo2max", "vo2max", "vo2_max"))
    )
    running_vo2 = (
        _first_present(run, ("vo2max", "vo2_max", "running_vo2max"))
        or _first_present(wellness_run, ("vo2max", "vo2_max", "running_vo2max"))
        or _first_present(athlete, ("running_vo2max", "vo2max", "vo2_max"))
    )
    return {
        "cycling_vo2max_ml_kg_min": (
            garmin_metrics["cycling_vo2max_ml_kg_min"]
            if garmin_metrics["cycling_vo2max_ml_kg_min"]["value"] is not None
            else _metric(cycling_vo2, VO2MAX_UNIT, PROVIDER_INTERVALS_NAME)
        ),
        "running_vo2max_ml_kg_min": (
            garmin_metrics["running_vo2max_ml_kg_min"]
            if garmin_metrics["running_vo2max_ml_kg_min"]["value"] is not None
            else _metric(running_vo2, VO2MAX_UNIT, PROVIDER_INTERVALS_NAME)
        ),
        **{
            key: (
                garmin_metrics[key]
                if garmin_metrics[key]["value"] is not None
                else _metric(None, "s", None)
            )
            for key in (
                "run_5k_seconds",
                "run_10k_seconds",
                "run_half_marathon_seconds",
                "run_marathon_seconds",
            )
        },
    }


def current_performance_metrics(
    snapshot: dict[str, Any],
    profile: dict[str, Any],
    garmin_metrics: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    athlete, activities, latest_wellness, ride, run, wellness_ride, wellness_run = (
        _performance_snapshot_inputs(snapshot)
    )
    latest_ride_activity = _latest_ride_activity(activities)
    latest_ride_eftp = _first_present(
        latest_ride_activity, ("icu_eftp", "eftp", "eFTP")
    )
    current_ride_eftp = _intervals_eftp_value(ride) or _intervals_eftp_value(
        wellness_ride
    )
    cycling_max_hr = _intervals_max_hr_metric(
        "cycling", ride, wellness_ride, activities, athlete
    )
    running_max_hr = _intervals_max_hr_metric(
        "running", run, wellness_run, activities, athlete
    )
    if garmin_metrics["cycling_max_hr_bpm"]["value"] is not None:
        cycling_max_hr = garmin_metrics["cycling_max_hr_bpm"]
    if garmin_metrics["running_max_hr_bpm"]["value"] is not None:
        running_max_hr = garmin_metrics["running_max_hr_bpm"]
    body_metrics = _performance_body_metrics(
        athlete, latest_wellness, profile, garmin_metrics
    )
    threshold_metrics = _performance_threshold_metrics(
        athlete, ride, run, wellness_ride, wellness_run, garmin_metrics
    )
    vo2_and_predictions = _performance_vo2_and_prediction_metrics(
        athlete, ride, run, wellness_ride, wellness_run, garmin_metrics
    )
    return {
        **body_metrics,
        **threshold_metrics,
        "cycling_eftp_watts": _metric(
            current_ride_eftp or latest_ride_eftp, "W", PROVIDER_INTERVALS_NAME
        ),
        "cycling_max_hr_bpm": cycling_max_hr,
        "running_max_hr_bpm": running_max_hr,
        **vo2_and_predictions,
    }
