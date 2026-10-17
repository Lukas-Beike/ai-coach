"""Current performance metric composition from explicit normalized inputs."""

import math
from typing import Any

from backend.activities.identity import activity_kind
from backend.canonical.decimal_text import comma_decimal_float
from backend.canonical.records import Observation
from backend.canonical.vocabulary import ProviderId
from backend.performance.canonical_current import CanonicalCurrentInputs
from backend.providers import intervals_performance_fields as intervals_perf_fields
from backend.providers.source_labels import (
    SourceView,
    observation_source_label,
    provider_label,
)

PROVIDER_INTERVALS_NAME = provider_label(
    ProviderId.INTERVALS, SourceView.CURRENT_METRIC
)
# provider_label has no view for this wellness label, so it stays a literal.
PROVIDER_INTERVALS_WELLNESS_NAME = "Intervals.icu Wellness"
GARMIN_PERFORMANCE_SOURCE = provider_label(ProviderId.GARMIN, SourceView.CURRENT_METRIC)
VO2MAX_UNIT = "ml/kg/min"


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def as_number(value: Any) -> float | int | None:
    """Return a finite number parsed from a provider value, or None."""
    try:
        number = comma_decimal_float(value)
    except TypeError, ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def metric(
    value: Any,
    unit: str,
    source: str | None,
    note: str = "",
    provider: ProviderId | None = None,
) -> dict[str, Any]:
    """Return a metric entry whose source fields are set only for a value."""
    number = as_number(value)
    return {
        "value": number,
        "unit": unit,
        "source": source if number is not None else None,
        "source_provider": (
            provider.value if provider is not None and number is not None else None
        ),
        "note": note if number is not None else "",
    }


def _canonical_metric(observation: Observation, unit: str) -> dict[str, Any]:
    """Return a metric for a canonical observation, labelled as the legacy view."""
    return metric(
        observation.value.value,
        unit,
        observation_source_label(observation, SourceView.CURRENT_METRIC),
        provider=observation.provenance.provider,
    )


def _matching_observation(
    candidates: tuple[Observation, ...], legacy_value: Any
) -> Observation | None:
    """Return the sport candidate whose value equals the legacy-selected value.

    The legacy reader takes the first matching sport setting, which is not known
    here, so any candidate with that same number carries the same value and label.
    Without a legacy value, or without a matching candidate, the caller keeps the
    legacy path.
    """
    if not legacy_value:
        return None
    number = as_number(legacy_value)
    if number is None:
        return None
    return next(
        (
            candidate
            for candidate in candidates
            if as_number(candidate.value.value) == number
        ),
        None,
    )


def _threshold_hr_metric(
    canonical_sport: tuple[Observation, ...],
    sport_value: Any,
    canonical_athlete: Observation | None,
    athlete_value: Any,
) -> dict[str, Any]:
    """Sport threshold HR, then the athlete-wide value, canonical before legacy.

    A canonical sport candidate is used only when its value equals the legacy sport
    value (sport setting, then wellness row). The athlete-wide value is a single
    athlete field, so its canonical row is unambiguous.
    """
    matched = _matching_observation(canonical_sport, sport_value)
    if matched is not None:
        return _canonical_metric(matched, "bpm")
    if sport_value:
        return metric(
            sport_value, "bpm", PROVIDER_INTERVALS_NAME, provider=ProviderId.INTERVALS
        )
    if canonical_athlete is not None:
        return _canonical_metric(canonical_athlete, "bpm")
    return metric(
        athlete_value,
        "bpm",
        "Intervals.icu (allgemein)",
        provider=ProviderId.INTERVALS,
    )


def _vo2max_metric(
    canonical_sport: tuple[Observation, ...], sport_value: Any, athlete_value: Any
) -> dict[str, Any]:
    """Sport VO2max: a canonical candidate matching the legacy sport value, else legacy."""
    matched = _matching_observation(canonical_sport, sport_value)
    if matched is not None:
        return _canonical_metric(matched, VO2MAX_UNIT)
    return metric(
        sport_value or athlete_value,
        VO2MAX_UNIT,
        PROVIDER_INTERVALS_NAME,
        provider=ProviderId.INTERVALS,
    )


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
        value = as_number(_first_present(activity, max_hr_keys))
        if value is not None and 80 <= float(value) <= 260:
            activity_values.append(value)
    if activity_values:
        candidates.append((max(activity_values), PROVIDER_INTERVALS_NAME))
    candidates.extend([(_first_present(athlete, max_hr_keys), PROVIDER_INTERVALS_NAME)])
    for value, source in candidates:
        number = as_number(value)
        if number is not None and 80 <= float(number) <= 260:
            return metric(number, "bpm", source, provider=ProviderId.INTERVALS)
    return metric(None, "bpm", None)


def _threshold_pace_seconds(value: Any) -> float | int | None:
    number = as_number(value)
    if number is None or number <= 0:
        return None
    return round(1000 / number) if number < 20 else number


def _zone2_pace_seconds(value: Any) -> float | int | None:
    pace = _threshold_pace_seconds(value)
    return pace if pace is not None and 120 <= float(pace) <= 1800 else None


def _height_in_cm(value: Any) -> float | int | None:
    number = as_number(value)
    if number is not None and 1.2 <= float(number) <= 2.5:
        return round(float(number) * 100, 1)
    return number


def _performance_snapshot_inputs(
    snapshot: dict[str, Any],
    activities_override: list[Any] | None = None,
    wellness_override: list[dict[str, Any]] | None = None,
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
    wellness_rows: list[dict[str, Any]] = []
    if wellness_override is not None:
        wellness_rows = wellness_override
    elif isinstance(snapshot.get("recent_wellness"), list):
        wellness_rows = [
            row for row in snapshot["recent_wellness"] if isinstance(row, dict)
        ]
    activities: list[Any] = []
    if activities_override is not None:
        activities = activities_override
    elif isinstance(snapshot.get("recent_activities"), list):
        activities = snapshot["recent_activities"]
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
    sources: tuple[tuple[Any, str, ProviderId | None], ...],
) -> tuple[Any, str | None, ProviderId | None]:
    return next(
        (
            (value, source, provider)
            for value, source, provider in sources
            if as_number(value) is not None
        ),
        (None, None, None),
    )


def _canonical_or_legacy(
    observation: Observation | None,
    legacy_value: Any,
    legacy_source: str,
    legacy_provider: ProviderId | None,
) -> tuple[Any, str, ProviderId | None]:
    """Return a canonical observation's value, label and provider, else the legacy triple."""
    if observation is None:
        return legacy_value, legacy_source, legacy_provider
    return (
        observation.value.value,
        observation_source_label(observation, SourceView.CURRENT_METRIC),
        observation.provenance.provider,
    )


def _performance_body_metrics(
    athlete: dict[str, Any],
    latest_wellness: dict[str, Any],
    profile: dict[str, Any],
    garmin_metrics: dict[str, dict[str, Any]],
    canonical: CanonicalCurrentInputs | None,
) -> dict[str, dict[str, Any]]:
    weight_value, weight_source, weight_provider = _first_performance_source(
        (
            (
                garmin_metrics["weight_kg"]["value"],
                GARMIN_PERFORMANCE_SOURCE,
                ProviderId.GARMIN,
            ),
            _canonical_or_legacy(
                None if canonical is None else canonical.wellness_weight,
                _first_present(latest_wellness, ("weight",)),
                PROVIDER_INTERVALS_WELLNESS_NAME,
                ProviderId.INTERVALS,
            ),
            _canonical_or_legacy(
                None if canonical is None else canonical.athlete_weight,
                _first_present(athlete, ("weight",)),
                PROVIDER_INTERVALS_NAME,
                ProviderId.INTERVALS,
            ),
            (profile.get("weight_kg"), "Manuell", None),
            _canonical_or_legacy(
                None if canonical is None else canonical.wahoo_weight,
                None,
                "",
                ProviderId.WAHOO,
            ),
        )
    )
    body_fat_value, body_fat_source, body_fat_provider = _first_performance_source(
        (
            (
                _first_present(latest_wellness, ("bodyFat", "body_fat")),
                PROVIDER_INTERVALS_WELLNESS_NAME,
                ProviderId.INTERVALS,
            ),
            (
                _first_present(athlete, ("bodyFat", "body_fat")),
                PROVIDER_INTERVALS_NAME,
                ProviderId.INTERVALS,
            ),
            (profile.get("body_fat_pct"), "Manuell", None),
        )
    )
    height_value, height_source, height_provider = _first_performance_source(
        (
            (
                _first_present(athlete, ("height_cm", "height")),
                PROVIDER_INTERVALS_NAME,
                ProviderId.INTERVALS,
            ),
            (profile.get("height_cm"), "Manuell", None),
        )
    )
    weight_metric = (
        garmin_metrics["weight_kg"]
        if weight_source == GARMIN_PERFORMANCE_SOURCE
        else metric(weight_value, "kg", weight_source, provider=weight_provider)
    )
    return {
        "weight_kg": weight_metric,
        "body_fat_pct": metric(
            body_fat_value, "%", body_fat_source, provider=body_fat_provider
        ),
        "height_cm": metric(
            _height_in_cm(height_value),
            "cm",
            height_source,
            provider=height_provider,
        ),
    }


def _preferred_performance_metric(
    garmin_metrics: dict[str, dict[str, Any]], key: str, fallback: dict[str, Any]
) -> dict[str, Any]:
    current = garmin_metrics[key]
    return current if current["value"] is not None else fallback


def _cycling_ftp_fallback(
    intervals: dict[str, Any], canonical: CanonicalCurrentInputs | None
) -> dict[str, Any]:
    """Return the Intervals cycling FTP, else the stored Wahoo FTP, labelled as Wahoo."""
    if (
        intervals["value"] is not None
        or canonical is None
        or canonical.wahoo_ftp is None
    ):
        return intervals
    return _canonical_metric(canonical.wahoo_ftp, "W")


def _performance_threshold_metrics(
    athlete: dict[str, Any],
    ride: dict[str, Any],
    run: dict[str, Any],
    wellness_ride: dict[str, Any],
    wellness_run: dict[str, Any],
    garmin_metrics: dict[str, dict[str, Any]],
    canonical: CanonicalCurrentInputs | None,
) -> dict[str, dict[str, Any]]:
    generic_lthr = _first_present(athlete, ("lthr",))
    bike_lthr = _first_present(ride, ("lthr",)) or _first_present(
        wellness_ride, ("lthr",)
    )
    run_lthr = _first_present(run, ("lthr",)) or _first_present(wellness_run, ("lthr",))
    canonical_athlete = None if canonical is None else canonical.athlete_threshold_hr
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
            _cycling_ftp_fallback(
                metric(
                    _first_present(ride, ("ftp", "indoor_ftp"))
                    or _first_present(wellness_ride, ("ftp", "indoor_ftp"))
                    or _first_present(
                        athlete, intervals_perf_fields.CONFIGURED_FTP_ALIASES
                    ),
                    "W",
                    PROVIDER_INTERVALS_NAME,
                    provider=ProviderId.INTERVALS,
                ),
                canonical,
            ),
        ),
        "run_threshold_watts": _preferred_performance_metric(
            garmin_metrics,
            "run_threshold_watts",
            metric(
                _first_present(run, ("ftp", "indoor_ftp"))
                or _first_present(wellness_run, ("ftp", "indoor_ftp")),
                "W",
                PROVIDER_INTERVALS_NAME,
                provider=ProviderId.INTERVALS,
            ),
        ),
        "run_threshold_pace_seconds_per_km": _preferred_performance_metric(
            garmin_metrics,
            "run_threshold_pace_seconds_per_km",
            metric(
                _threshold_pace_seconds(
                    _first_present(run, ("threshold_pace",))
                    or _first_present(wellness_run, ("threshold_pace",))
                ),
                "s/km",
                PROVIDER_INTERVALS_NAME,
                provider=ProviderId.INTERVALS,
            ),
        ),
        "run_zone2_pace_seconds_per_km": metric(
            _zone2_pace_seconds(run_zone2_pace),
            "s/km",
            PROVIDER_INTERVALS_NAME,
            provider=ProviderId.INTERVALS,
        ),
        "bike_threshold_hr_bpm": _preferred_performance_metric(
            garmin_metrics,
            "bike_threshold_hr_bpm",
            _threshold_hr_metric(
                () if canonical is None else canonical.bike_threshold_hr,
                bike_lthr,
                canonical_athlete,
                generic_lthr,
            ),
        ),
        "run_threshold_hr_bpm": _preferred_performance_metric(
            garmin_metrics,
            "run_threshold_hr_bpm",
            _threshold_hr_metric(
                () if canonical is None else canonical.run_threshold_hr,
                run_lthr,
                canonical_athlete,
                generic_lthr,
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
    canonical: CanonicalCurrentInputs | None,
) -> dict[str, dict[str, Any]]:
    cycling_sport_vo2 = _first_present(
        ride, ("vo2max", "vo2_max", "cycling_vo2max")
    ) or _first_present(wellness_ride, ("vo2max", "vo2_max", "cycling_vo2max"))
    running_sport_vo2 = _first_present(
        run, ("vo2max", "vo2_max", "running_vo2max")
    ) or _first_present(wellness_run, ("vo2max", "vo2_max", "running_vo2max"))
    cycling_athlete_vo2 = _first_present(
        athlete, ("cycling_vo2max", "vo2max", "vo2_max")
    )
    running_athlete_vo2 = _first_present(
        athlete, ("running_vo2max", "vo2max", "vo2_max")
    )
    return {
        "cycling_vo2max_ml_kg_min": _preferred_performance_metric(
            garmin_metrics,
            "cycling_vo2max_ml_kg_min",
            _vo2max_metric(
                () if canonical is None else canonical.cycling_vo2max,
                cycling_sport_vo2,
                cycling_athlete_vo2,
            ),
        ),
        "running_vo2max_ml_kg_min": _preferred_performance_metric(
            garmin_metrics,
            "running_vo2max_ml_kg_min",
            _vo2max_metric(
                () if canonical is None else canonical.running_vo2max,
                running_sport_vo2,
                running_athlete_vo2,
            ),
        ),
        **{
            key: _preferred_performance_metric(
                garmin_metrics, key, metric(None, "s", None)
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
    *,
    canonical: CanonicalCurrentInputs | None = None,
    activities: list[Any] | None = None,
    wellness_rows: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Compose current metrics; ``canonical`` replaces the Intervals sport values.

    ``activities`` and ``wellness_rows`` are the canonical rows of the performance
    context. Without them, and without ``canonical``, the legacy snapshot chain is
    used unchanged.
    """
    athlete, activities, latest_wellness, ride, run, wellness_ride, wellness_run = (
        _performance_snapshot_inputs(snapshot, activities, wellness_rows)
    )
    latest_ride_activity = _latest_ride_activity(activities)
    latest_ride_eftp = _first_present(
        latest_ride_activity, intervals_perf_fields.ESTIMATED_FTP_ALIASES
    )
    # Remaining snapshot read: EFTP observations are stored, but the current value
    # follows the first matching sport setting, then sportInfo, then the latest
    # ride, an order the observations do not yet reproduce.
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
        athlete, latest_wellness, profile, garmin_metrics, canonical
    )
    threshold_metrics = _performance_threshold_metrics(
        athlete, ride, run, wellness_ride, wellness_run, garmin_metrics, canonical
    )
    vo2_and_predictions = _performance_vo2_and_prediction_metrics(
        athlete, ride, run, wellness_ride, wellness_run, garmin_metrics, canonical
    )
    return {
        **body_metrics,
        **threshold_metrics,
        "cycling_eftp_watts": metric(
            current_ride_eftp or latest_ride_eftp,
            "W",
            PROVIDER_INTERVALS_NAME,
            provider=ProviderId.INTERVALS,
        ),
        "cycling_max_hr_bpm": cycling_max_hr,
        "running_max_hr_bpm": running_max_hr,
        **vo2_and_predictions,
    }
