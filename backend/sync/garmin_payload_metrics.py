"""Ingest-time normalization of a fetched Garmin payload's performance sections.

Only the sync's performance-history merge reads these, before the payload is
stored. Read paths use ``backend.performance.garmin_metrics`` over canonical values.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

from backend.activities.identity import activity_kind
from backend.athlete.local_date import iso_date_prefix
from backend.canonical.mapping import coerce_comma_decimal_number
from backend.performance import freshness as performance_freshness
from backend.performance.current_metrics import as_number as _as_number
from backend.performance.garmin_canonical import profile_max_hr_for
from backend.performance.garmin_metrics import (
    RACE_PREDICTION_KEYS,
    assemble_garmin_metrics,
    garmin_bounded_metric,
)
from backend.providers import garmin_performance_fields as garmin_perf_fields
from backend.providers.garmin_fields import colon_time_parts
from backend.providers.garmin_fields import first_present as _first_present
from backend.sync import garmin_weight

_OBSERVATION_DATE_FIELDS = garmin_perf_fields.OBSERVATION_DATE_FIELDS


def _garmin_record_date(value: Any) -> str | None:
    """Return a validated ISO date from a Garmin date or timestamp value."""
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value <= 100_000_000_000:
            return None
        try:
            return datetime.fromtimestamp(float(value) / 1000, UTC).date().isoformat()
        except OverflowError, OSError, ValueError:
            return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        return date.fromisoformat(iso_date_prefix(text)).isoformat()
    except AttributeError, TypeError, ValueError:
        return None


def garmin_record_observation_date(record: dict[str, Any]) -> str | None:
    """Return the first valid observation date represented by one record."""
    if not isinstance(record, dict):
        return None
    for field in _OBSERVATION_DATE_FIELDS:
        value = record.get(field)
        if value not in (None, ""):
            return _garmin_record_date(value)
    return None


def _garmin_nested_records(record: dict[str, Any]) -> list[Any]:
    return [item for item in record.values() if isinstance(item, (dict, list))]


def garmin_source_observed_at(value: Any) -> str | None:
    """Return the newest valid observation date in nested Garmin data."""
    dates: list[str] = []
    pending = [value]
    visited: set[int] = set()
    while pending:
        record = pending.pop()
        if isinstance(record, dict):
            marker = id(record)
            if marker in visited:
                continue
            visited.add(marker)
            observed_at = garmin_record_observation_date(record)
            if observed_at:
                dates.append(observed_at)
            pending.extend(_garmin_nested_records(record))
        elif isinstance(record, list):
            marker = id(record)
            if marker in visited:
                continue
            visited.add(marker)
            pending.extend(record)
    return max(dates, default=None)


def _garmin_key(value: Any) -> str:
    return "".join(
        character for character in str(value).casefold() if character.isalnum()
    )


def _garmin_numeric(value: Any) -> float | int | None:
    if isinstance(value, dict):
        value = _first_present(
            value,
            (
                "value",
                "val",
                "amount",
                "seconds",
                "time",
                "raceTime",
                "racePredictionTime",
            ),
        )
    return coerce_comma_decimal_number(value)


def _garmin_vo2_value(value: Any) -> float | int | None:
    number = _garmin_numeric(value)
    return number if number is not None and 20 <= float(number) <= 100 else None


def _garmin_colon_duration_seconds(value: str) -> int | None:
    numbers = colon_time_parts(value)
    if numbers is None:
        return None
    seconds = (
        numbers[-1]
        + numbers[-2] * 60
        + (numbers[-3] * 3600 if len(numbers) == 3 else 0)
    )
    return seconds if 60 <= seconds <= 100_000 else None


def garmin_duration_seconds(value: Any) -> float | int | None:
    if isinstance(value, dict):
        value = _first_present(
            value,
            (
                "raceTime",
                "racePredictionTime",
                "predictedTime",
                "time",
                "seconds",
                "value",
            ),
        )
    if isinstance(value, str) and ":" in value:
        parsed_duration = _garmin_colon_duration_seconds(value)
        if parsed_duration is not None:
            return parsed_duration
    number = _as_number(value)
    if number is None:
        return None
    if number > 100_000:
        number /= 1000
    if not 60 <= number <= 100_000:
        return None
    return int(number) if float(number).is_integer() else round(number, 2)


def _garmin_race_slot(value: Any) -> str | None:
    key = _garmin_key(value)
    if any(term in key for term in ("halfmarathon", "half")):
        return "run_half_marathon_seconds"
    if "marathon" in key:
        return "run_marathon_seconds"
    if any(term in key for term in ("10k", "10km", "10000m")):
        return "run_10k_seconds"
    if any(term in key for term in ("5k", "5km", "5000m")):
        return "run_5k_seconds"
    return None


def _garmin_race_time(record: Any) -> float | int | None:
    return garmin_duration_seconds(record)


def _collect_garmin_numeric_values(
    item: Any, keys: set[str], values: list[float | int]
) -> None:
    if isinstance(item, dict):
        for key, child in item.items():
            if _garmin_key(key) in keys:
                number = _garmin_numeric(child)
                if number is not None:
                    values.append(number)
            _collect_garmin_numeric_values(child, keys, values)
    elif isinstance(item, list):
        for child in item[:500]:
            _collect_garmin_numeric_values(child, keys, values)


def _garmin_last_numeric(value: Any, keys: set[str]) -> float | int | None:
    values: list[float | int] = []
    _collect_garmin_numeric_values(value, keys, values)
    return values[-1] if values else None


def _garmin_last_value(value: Any, keys: set[str]) -> Any:
    values: list[Any] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if _garmin_key(key) in keys:
                    values.append(child)
                visit(child)
        elif isinstance(item, list):
            for child in item[:500]:
                visit(child)

    visit(value)
    return values[-1] if values else None


def _garmin_pace_seconds(value: Any) -> float | int | None:
    if isinstance(value, str) and ":" in value:
        numbers = colon_time_parts(value)
        if numbers is not None:
            value = (
                numbers[-1]
                + numbers[-2] * 60
                + (numbers[-3] * 3600 if len(numbers) == 3 else 0)
            )
    number = _garmin_numeric(value)
    if number is None or number <= 0:
        return None
    if number < 1:
        pace = 100 / number
    elif number < 20:
        pace = 1000 / number
    else:
        pace = number
    return round(pace) if 120 <= pace <= 900 else None


def _garmin_mapping_nodes(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _garmin_mapping_nodes(child)
    elif isinstance(value, list):
        for child in value[:100]:
            yield from _garmin_mapping_nodes(child)


def _garmin_sport_category(value: Any) -> str:
    sport = _garmin_key(value)
    if any(term in sport for term in ("cycling", "cycl", "bike", "ride")):
        return "cycling"
    if any(term in sport for term in ("running", "run")):
        return "running"
    return "generic"


def garmin_profile_max_hr(snapshot: dict[str, Any]) -> dict[str, float | int]:
    values: dict[str, list[float | int]] = {"cycling": [], "running": [], "generic": []}
    for item in _garmin_mapping_nodes(snapshot.get("heart_rate_zones")):
        max_hr = _as_number(
            _first_present(item, garmin_perf_fields.MAX_HEART_RATE_ALIASES)
        )
        if max_hr is not None and 80 <= float(max_hr) <= 260:
            values[
                _garmin_sport_category(
                    _first_present(item, ("sport", "sportType", "activityType"))
                )
            ].append(max_hr)
    return {kind: max(items) for kind, items in values.items() if items}


def _garmin_collect_vo2_values(
    value: Any, values: dict[str, list[float | int]], path: tuple[str, ...] = ()
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _garmin_key(key)
            if "vo2max" in normalized or ("vo2" in normalized and "max" in normalized):
                number = _garmin_vo2_value(item)
                if number is not None:
                    context = _garmin_key(" ".join((*path, str(key))))
                    values[_garmin_sport_category(context)].append(number)
            _garmin_collect_vo2_values(item, values, (*path, str(key)))
    elif isinstance(value, list):
        for item in value[:100]:
            _garmin_collect_vo2_values(item, values, path)


def _garmin_vo2_metrics(
    max_metrics: Any,
) -> tuple[float | int | None, float | int | None]:
    values: dict[str, list[float | int]] = {"cycling": [], "running": [], "generic": []}
    _garmin_collect_vo2_values(max_metrics, values)
    running = values["generic"][-1] if values["generic"] else None
    if values["running"]:
        running = values["running"][-1]
    return values["cycling"][-1] if values["cycling"] else None, running


def _garmin_store_race_value(
    slot: str | None, candidate: Any, values: dict[str, float | int | None]
) -> None:
    if slot and candidate not in (None, "") and values[slot] is None:
        values[slot] = _garmin_race_time(candidate)


def _garmin_store_direct_race_value(
    item: Any, path: tuple[str, ...], values: dict[str, float | int | None]
) -> None:
    slot = _garmin_race_slot(" ".join(path))
    if slot and values[slot] is None:
        candidate = _garmin_race_time(item)
        if candidate is not None:
            values[slot] = candidate


def _garmin_collect_race_predictions(
    value: Any,
    values: dict[str, float | int | None],
    path: tuple[str, ...] = (),
) -> None:
    if isinstance(value, dict):
        distance = _first_present(
            value, ("raceDistance", "distanceName", "raceType", "distance")
        )
        time_value = _first_present(
            value,
            ("raceTime", "racePredictionTime", "predictedTime", "time", "seconds"),
        )
        _garmin_store_race_value(
            _garmin_race_slot(distance) if isinstance(distance, str) else None,
            time_value,
            values,
        )
        for key, item in value.items():
            nested_path = (*path, str(key))
            _garmin_store_direct_race_value(item, nested_path, values)
            _garmin_collect_race_predictions(item, values, nested_path)
    elif isinstance(value, list):
        for item in value[:100]:
            _garmin_collect_race_predictions(item, values, path)


def _garmin_race_predictions(value: Any) -> dict[str, float | int | None]:
    races: dict[str, float | int | None] = dict.fromkeys(RACE_PREDICTION_KEYS)
    _garmin_collect_race_predictions(value, races)
    return races


def _garmin_payload_race_values(
    snapshot: dict[str, Any],
) -> dict[str, float | int | None]:
    race_predictions = snapshot.get("race_predictions")
    return _garmin_race_predictions(
        race_predictions if isinstance(race_predictions, (dict, list)) else {}
    )


def _garmin_payload_thresholds(
    snapshot: dict[str, Any],
) -> tuple[
    float | int | None,
    float | int | None,
    float | int | None,
    float | int | None,
    float | int | None,
]:
    running_threshold = snapshot.get("running_threshold")
    cycling_ftp = garmin_bounded_metric(
        _garmin_last_numeric(
            snapshot.get("cycling_ftp"),
            {"functionalthresholdpower", "ftp", "cyclingftp"},
        ),
        50,
        700,
    )
    running_power = garmin_bounded_metric(
        _garmin_last_numeric(
            running_threshold,
            {"functionalthresholdpower", "ftp", "runningftp", "power"},
        ),
        50,
        800,
    )
    running_pace = _garmin_pace_seconds(
        _garmin_last_value(
            running_threshold,
            {
                "speed",
                "speedinmeterspersecond",
                "speedmeterspersecond",
                "lactatethresholdspeed",
                "thresholdspeed",
                "pace",
                "paceinsecondsperkilometer",
                "thresholdpace",
            },
        )
    )
    running_hr = garmin_bounded_metric(
        _garmin_last_numeric(
            running_threshold,
            {"heartrate", "hearrate", "heartraterunning", "lthr"},
        ),
        80,
        230,
    )
    cycling_hr = garmin_bounded_metric(
        _garmin_last_numeric(running_threshold, {"heartratecycling"}),
        80,
        230,
    )
    return cycling_ftp, running_power, running_pace, running_hr, cycling_hr


def _garmin_activity_max_hr_samples(
    activities: list[Any], kind: str
) -> list[float | int]:
    values: list[float | int] = []
    for activity in activities:
        if not isinstance(activity, dict) or activity_kind(activity) != kind:
            continue
        value = _as_number(
            _first_present(activity, ("maxHR", "maxHeartRate", "max_heartrate"))
        )
        if value is not None and 80 <= float(value) <= 260:
            values.append(value)
    return values


def _garmin_payload_max_hr_samples(
    snapshot: dict[str, Any],
) -> tuple[dict[str, float | int], dict[str, list[float | int]], dict[str, str | None]]:
    """Profile max HR, else the stored sport max HR and the payload's activities."""
    profile_max_hr = garmin_profile_max_hr(snapshot)
    values: dict[str, list[float | int]] = {"cycling": [], "running": []}
    stored = snapshot.get("sport_max_hr")
    if not isinstance(stored, dict):
        stored = {}
    activities = snapshot.get("activities")
    if not isinstance(activities, list):
        activities = []
    for kind, samples in values.items():
        profile_value = profile_max_hr_for(profile_max_hr, kind)
        if profile_value is not None:
            samples.append(profile_value)
            continue
        stored_value = _as_number(stored.get(kind))
        if stored_value is not None and 80 <= float(stored_value) <= 260:
            samples.append(stored_value)
        samples.extend(_garmin_activity_max_hr_samples(activities, kind))
    observed_at = {
        kind: _garmin_activity_observed_at(activities, kind, max(samples, default=None))
        for kind, samples in values.items()
    }
    return profile_max_hr, values, observed_at


def _garmin_activity_observed_at(
    activities: list[Any], kind: str, maximum_hr: Any
) -> str | None:
    observed_dates = [
        garmin_source_observed_at(activity)
        for activity in activities
        if isinstance(activity, dict)
        and activity_kind(activity) == kind
        and _as_number(
            _first_present(activity, ("maxHR", "maxHeartRate", "max_heartrate"))
        )
        == maximum_hr
    ]
    return max((value for value in observed_dates if value), default=None)


def garmin_payload_performance_metrics(
    payload: dict[str, Any], current_date: date
) -> dict[str, dict[str, Any]]:
    """Normalize a fetched Garmin payload's performance sections at ingest.

    Only the sync's performance-history merge uses this, before the payload is
    stored; read paths use ``garmin_performance_metrics``.
    """
    max_metrics = payload.get("max_metrics")
    return assemble_garmin_metrics(
        performance_freshness.GarminSyncStatus.from_state(payload),
        current_date,
        garmin_weight.garmin_weight_metric(payload),
        _garmin_vo2_metrics(
            max_metrics if isinstance(max_metrics, (dict, list)) else {}
        ),
        _garmin_payload_race_values(payload),
        _garmin_payload_thresholds(payload),
        _garmin_payload_max_hr_samples(payload),
    )
