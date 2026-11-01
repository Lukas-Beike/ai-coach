"""Map Garmin Connect activity summaries to canonical ActivityRecord values.

The mapper is pure: no I/O, no logging, and no exceptions for provider data.
A row that cannot be identified or started is dropped with a MappingIssue. An
optional field that is present but invalid becomes None with a MappingIssue.
Issues name the record, the field and the reason, never the raw value.

Field precedence. Within one field, the first alias that carries a value wins.
A present but invalid value is reported and mapped to None; it does not fall
back to a later alias. The one exception is start time: an invalid
``startTimeGMT`` is reported and ``startTimeLocal`` is tried, because both name
the same moment.

* ``activityId`` (required): an integer, or text of 1 to 64 ASCII letters,
  digits, ``_`` or ``-`` that starts with a letter or digit -> ``activity_id``.
* ``startTimeGMT``, then ``startTimeLocal`` (one is required) -> ``started_at``.
  A naive ``startTimeGMT`` is read as UTC. A naive ``startTimeLocal`` is wall
  time in the athlete zone and follows ``localize_wall_time``. Aware text keeps
  the offset it was sent with; use ``local_date`` to read the athlete's date.
* ``activityType``: the dictionary form ``{"typeKey": ...}`` or, in the legacy
  form, the key as plain text.
* ``duration``, then ``movingTime`` (seconds). ``movingTime`` is the fallback that
  ``backend.activities.duplicates`` uses for ``duration``.
* ``duration`` alone (seconds) -> ``elapsed_duration_s``; the ``movingTime`` fallback
  is not elapsed time and stays out of it.
* ``movingDuration`` (seconds) -> ``moving_duration_s``, with no ``movingTime``
  fallback because ``movingTime`` already feeds ``duration_s``. Garmin
  ``duration`` is elapsed time, so duplicate detection also compares this moving
  time against the Intervals.icu moving time.
* ``distance`` (metres), ``activityTrainingLoad`` (Garmin training load),
  ``averageHR`` (bpm), ``avgPower``, then ``averagePower`` (watts).
* ``maxHR``, then ``maxHeartRate`` (bpm) -> ``max_hr``, the aliases that
  ``performance.max_hr`` reads first.
* ``maxSpeed`` (m/s) -> ``max_speed_mps``, and ``maxPower`` (watts) -> ``max_power_w``.
* ``steps`` (count) -> ``steps``.
* ``averageSpeed`` (m/s), ``elevationGain`` (m), ``normPower`` (W) and
  ``vO2MaxValue`` -> ``avg_speed_mps``, ``elevation_gain_m``,
  ``normalized_power`` and ``vo2max``.
* ``activityName`` (text, stripped and truncated to 200 characters).
* ``trainingEffectLabel`` (text, stripped, upper-cased and truncated to 50
  characters) -> ``training_effect_label``.

A dedicated ``training_load_activities`` row of the same ``activityId`` supplies
``activityTrainingLoad`` and ``trainingEffectLabel`` before the activity is stored
(``merge_training_load_rows``), so a re-projection of the stored row reads them too.

Sport and environment. A known ``typeKey`` uses ``GARMIN_ACTIVITY_TYPES``. An
environment that the key leaves UNKNOWN may be named by the activity name.
Any other key falls back to the legacy text classifiers, applied to the
space-joined key and name. OUTDOOR is set only where the key says so.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, tzinfo
from typing import Final

from backend.canonical.local_time import parse_provider_datetime
from backend.canonical.mapping import (
    MAX_ISSUE_TEXT_LENGTH,
    IssueReason,
    MappingIssue,
    MappingResult,
    coerce_number,
)
from backend.canonical.records import (
    MAX_TRAINING_EFFECT_LABEL_LENGTH,
    ActivityRecord,
    Provenance,
)
from backend.canonical.sports import classify_environment_text, classify_sport_text
from backend.canonical.validation import (
    HEART_RATE_BOUNDS,
    MAX_ACTIVITY_DISTANCE_M,
    MAX_ACTIVITY_DURATION_S,
    MAX_ACTIVITY_ELEVATION_M,
    MAX_ACTIVITY_LOAD,
    MAX_ACTIVITY_POWER_W,
    MAX_ACTIVITY_SPEED_MPS,
    MAX_ACTIVITY_STEPS,
    require_aware_datetime,
)
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)

# Version 5: maps the maximum speed, maximum power and step count.
# Version 4: a row with manualActivity exactly True is recorded as MANUAL origin.
# Version 3: maps the activity's maximum heart rate.
# Version 7: maps average speed, elevation gain, normalized power and VO2max.
# Version 8: maps the training-effect label (#1416).
MAPPER_VERSION: Final = 8
GARMIN_LABEL: Final = "Garmin Connect"
MAX_NAME_LENGTH: Final = 200
MAX_ACTIVITY_ID_LENGTH: Final = 64
_ACTIVITY_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_ROW_FIELD: Final = "activity"
_DURATION_KEYS: Final = ("duration", "movingTime")
_MOVING_DURATION_KEYS: Final = ("movingDuration",)
_POWER_KEYS: Final = ("avgPower", "averagePower")
_MAX_HR_KEYS: Final = ("maxHR", "maxHeartRate")
_MAX_SPEED_KEYS: Final = ("maxSpeed",)
_MAX_POWER_KEYS: Final = ("maxPower",)
_STEPS_KEYS: Final = ("steps",)
_AVERAGE_SPEED_KEYS: Final = ("averageSpeed",)
_ELEVATION_GAIN_KEYS: Final = ("elevationGain",)
_NORMALIZED_POWER_KEYS: Final = ("normPower",)
_VO2MAX_KEYS: Final = ("vO2MaxValue",)
_TRAINING_EFFECT_LABEL_KEY: Final = "trainingEffectLabel"
_TRAINING_LOAD_KEY: Final = "activityTrainingLoad"
# The dedicated training-load rows override these activity fields.
_TRAINING_LOAD_FIELDS: Final = (_TRAINING_LOAD_KEY, _TRAINING_EFFECT_LABEL_KEY)

# Exact Garmin activityType.typeKey values. The environment is set only where the
# key names it; otherwise UNKNOWN, which the activity name may still refine.
# Lap swimming is not named as indoor and open water is named as outdoor.
# The legacy text classifier does not recognise road_biking, mountain_biking or
# hiking, so those keys must come from this table.
GARMIN_ACTIVITY_TYPES: Final[Mapping[str, tuple[Sport, Environment]]] = {
    "cycling": (Sport.RIDE, Environment.UNKNOWN),
    "e_bike_fitness": (Sport.RIDE, Environment.UNKNOWN),
    "gravel_cycling": (Sport.RIDE, Environment.UNKNOWN),
    "mountain_biking": (Sport.RIDE, Environment.UNKNOWN),
    "road_biking": (Sport.RIDE, Environment.UNKNOWN),
    "indoor_cycling": (Sport.RIDE, Environment.INDOOR),
    "virtual_ride": (Sport.RIDE, Environment.VIRTUAL),
    "running": (Sport.RUN, Environment.UNKNOWN),
    "street_running": (Sport.RUN, Environment.UNKNOWN),
    "trail_running": (Sport.RUN, Environment.UNKNOWN),
    "track_running": (Sport.RUN, Environment.UNKNOWN),
    "treadmill_running": (Sport.RUN, Environment.INDOOR),
    "indoor_running": (Sport.RUN, Environment.INDOOR),
    "virtual_run": (Sport.RUN, Environment.VIRTUAL),
    "lap_swimming": (Sport.SWIM, Environment.UNKNOWN),
    "open_water_swimming": (Sport.SWIM, Environment.OUTDOOR),
    "walking": (Sport.WALK, Environment.UNKNOWN),
    "hiking": (Sport.HIKE, Environment.UNKNOWN),
    "strength_training": (Sport.STRENGTH, Environment.UNKNOWN),
    "rowing": (Sport.ROW, Environment.UNKNOWN),
    "indoor_rowing": (Sport.ROW, Environment.INDOOR),
    "cross_country_skiing_ws": (Sport.NORDIC_SKI, Environment.UNKNOWN),
    "resort_skiing_snowboarding_ws": (Sport.ALPINE_SKI, Environment.UNKNOWN),
    "yoga": (Sport.YOGA, Environment.UNKNOWN),
}


def map_garmin_activities(
    rows: object, *, zone: tzinfo, retrieved_at: datetime
) -> MappingResult[ActivityRecord]:
    """Map a Garmin activity list. Non-list input yields no records and one issue.

    ``retrieved_at`` must be timezone-aware; a naive value is a programming error
    and raises ValueError. ``zone`` must be a tzinfo: the athlete's zone for naive
    local times. A wrong type for either argument raises TypeError.
    """
    require_aware_datetime(retrieved_at, "retrieved_at")
    if not isinstance(zone, tzinfo):
        raise TypeError("zone must be a tzinfo")
    if not isinstance(rows, list):
        return MappingResult(
            issues=(MappingIssue(None, "rows", IssueReason.INVALID_TYPE),)
        )
    records: list[ActivityRecord] = []
    issues: list[MappingIssue] = []
    for row in rows:
        record = _map_row(row, zone=zone, retrieved_at=retrieved_at, issues=issues)
        if record is not None:
            records.append(record)
    return MappingResult(records=tuple(records), issues=tuple(issues))


def _map_row(
    row: object,
    *,
    zone: tzinfo,
    retrieved_at: datetime,
    issues: list[MappingIssue],
) -> ActivityRecord | None:
    if not isinstance(row, dict):
        issues.append(MappingIssue(None, _ROW_FIELD, IssueReason.INVALID_TYPE))
        return None
    activity_id = _activity_id(row, issues)
    ref = activity_id
    started_at = _start_time(row, zone, ref, issues)
    name = _name(row, ref, issues)
    type_key = _type_key(row, ref, issues)
    sport, environment = _sport_and_environment(type_key, name)
    duration = _optional_number(
        row, _DURATION_KEYS, (0.0, MAX_ACTIVITY_DURATION_S), ref, issues
    )
    # Issues for ``duration`` are already reported above.
    elapsed_duration = _optional_number(
        row, ("duration",), (0.0, MAX_ACTIVITY_DURATION_S), ref, []
    )
    moving_duration = _optional_number(
        row, _MOVING_DURATION_KEYS, (0.0, MAX_ACTIVITY_DURATION_S), ref, issues
    )
    distance = _optional_number(
        row, ("distance",), (0.0, MAX_ACTIVITY_DISTANCE_M), ref, issues
    )
    load = _optional_number(
        row, (_TRAINING_LOAD_KEY,), (0.0, MAX_ACTIVITY_LOAD), ref, issues
    )
    training_effect_label = _training_effect_label(row, ref, issues)
    avg_hr = _optional_number(row, ("averageHR",), HEART_RATE_BOUNDS, ref, issues)
    max_hr = _optional_number(row, _MAX_HR_KEYS, HEART_RATE_BOUNDS, ref, issues)
    max_speed = _optional_number(
        row, _MAX_SPEED_KEYS, (0.0, MAX_ACTIVITY_SPEED_MPS), ref, issues
    )
    max_power = _optional_number(
        row, _MAX_POWER_KEYS, (0.0, MAX_ACTIVITY_POWER_W), ref, issues
    )
    steps = _optional_number(row, _STEPS_KEYS, (0.0, MAX_ACTIVITY_STEPS), ref, issues)
    avg_power = _optional_number(
        row, _POWER_KEYS, (0.0, MAX_ACTIVITY_POWER_W), ref, issues
    )
    avg_speed = _optional_number(
        row, _AVERAGE_SPEED_KEYS, (0.0, MAX_ACTIVITY_SPEED_MPS), ref, issues
    )
    elevation_gain = _optional_number(
        row, _ELEVATION_GAIN_KEYS, (0.0, MAX_ACTIVITY_ELEVATION_M), ref, issues
    )
    normalized_power = _optional_number(
        row, _NORMALIZED_POWER_KEYS, (0.0, MAX_ACTIVITY_POWER_W), ref, issues
    )
    vo2max = _optional_number(row, _VO2MAX_KEYS, (0.0, 100.0), ref, issues)
    if activity_id is None or started_at is None:
        return None
    return ActivityRecord(
        activity_id=activity_id,
        provenance=_provenance(activity_id, retrieved_at, _recorded_by(row)),
        sport=sport,
        environment=environment,
        started_at=started_at,
        duration_s=duration,
        moving_duration_s=moving_duration,
        elapsed_duration_s=elapsed_duration,
        distance_m=distance,
        load=load,
        load_model=(
            LoadModel.GARMIN_TRAINING_LOAD if load is not None else LoadModel.UNKNOWN
        ),
        avg_hr=avg_hr,
        avg_power=avg_power,
        name=name,
        max_hr=max_hr,
        max_speed_mps=max_speed,
        max_power_w=max_power,
        steps=steps,
        avg_speed_mps=avg_speed,
        elevation_gain_m=elevation_gain,
        normalized_power=normalized_power,
        vo2max=vo2max,
        training_effect_label=training_effect_label,
    )


def merge_training_load_rows(activities: object, training_loads: object) -> object:
    """Return the activity rows with the dedicated training-load values merged in.

    A training-load row of the same ``activityId`` (or ``id``) replaces the
    activity's training load and training-effect label where it carries one.
    Anything that is not a list of rows is returned unchanged.
    """
    if not isinstance(activities, list) or not isinstance(training_loads, list):
        return activities
    by_id = {
        str(identity): row
        for row in training_loads
        if isinstance(row, dict)
        and not _is_absent(identity := row.get("activityId") or row.get("id"))
    }
    if not by_id:
        return activities
    merged: list[object] = []
    for activity in activities:
        load_row = (
            by_id.get(str(activity.get("activityId") or activity.get("id") or ""))
            if isinstance(activity, dict)
            else None
        )
        if not isinstance(activity, dict) or load_row is None:
            merged.append(activity)
            continue
        merged.append(
            {
                **activity,
                **{
                    key: load_row[key]
                    for key in _TRAINING_LOAD_FIELDS
                    if load_row.get(key) is not None
                },
            }
        )
    return merged


def _training_effect_label(
    row: dict[str, object], ref: str | None, issues: list[MappingIssue]
) -> str | None:
    value = row.get(_TRAINING_EFFECT_LABEL_KEY)
    if _is_absent(value):
        return None
    if not isinstance(value, str):
        issues.append(
            MappingIssue(ref, _TRAINING_EFFECT_LABEL_KEY, IssueReason.INVALID_TYPE)
        )
        return None
    return value.strip().upper()[:MAX_TRAINING_EFFECT_LABEL_LENGTH]


def _is_absent(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _present(
    row: dict[str, object], keys: tuple[str, ...]
) -> tuple[str, object] | None:
    """Return the first alias that carries a value, with the key that named it."""
    for key in keys:
        value = row.get(key)
        if not _is_absent(value):
            return key, value
    return None


def _activity_id(row: dict[str, object], issues: list[MappingIssue]) -> str | None:
    value = row.get("activityId")
    if _is_absent(value):
        issues.append(MappingIssue(None, "activityId", IssueReason.MISSING))
        return None
    if isinstance(value, bool) or not isinstance(value, int | str):
        issues.append(MappingIssue(None, "activityId", IssueReason.INVALID_TYPE))
        return None
    try:
        text = str(value).strip()
    except ValueError:  # An integer beyond the str() digit limit.
        issues.append(MappingIssue(None, "activityId", IssueReason.INVALID_TYPE))
        return None
    if len(text) > MAX_ACTIVITY_ID_LENGTH or not _ACTIVITY_ID_PATTERN.fullmatch(text):
        issues.append(MappingIssue(None, "activityId", IssueReason.INVALID_TYPE))
        return None
    return text


def _start_time(
    row: dict[str, object],
    zone: tzinfo,
    ref: str | None,
    issues: list[MappingIssue],
) -> datetime | None:
    """Prefer startTimeGMT; use startTimeLocal when GMT is absent or invalid."""
    gmt_text = row.get("startTimeGMT")
    local_text = row.get("startTimeLocal")
    if _is_absent(gmt_text) and _is_absent(local_text):
        issues.append(MappingIssue(ref, "startTime", IssueReason.MISSING))
        return None
    candidates: tuple[tuple[str, object, tzinfo], ...] = (
        ("startTimeGMT", gmt_text, UTC),
        ("startTimeLocal", local_text, zone),
    )
    for field, text, field_zone in candidates:
        if _is_absent(text):
            continue
        parsed = parse_provider_datetime(text, field_zone)
        if parsed is not None and _representable_in(parsed, zone):
            return parsed
        # IssueReason has no datetime member, so malformed text is INVALID_TYPE.
        issues.append(MappingIssue(ref, field, IssueReason.INVALID_TYPE))
    return None


def _representable_in(value: datetime, zone: tzinfo) -> bool:
    """Return True when local_date can read ``value`` in the athlete zone.

    A GMT instant is parsed in UTC, so near datetime's range it can still be
    unrepresentable in the athlete zone; this keeps such records out.
    """
    try:
        value.astimezone(zone)
    except OverflowError, ValueError:
        return False
    return True


def _name(
    row: dict[str, object], ref: str | None, issues: list[MappingIssue]
) -> str | None:
    value = row.get("activityName")
    if _is_absent(value):
        return None
    if not isinstance(value, str):
        issues.append(MappingIssue(ref, "activityName", IssueReason.INVALID_TYPE))
        return None
    return value.strip()[:MAX_NAME_LENGTH]


def _type_key(
    row: dict[str, object], ref: str | None, issues: list[MappingIssue]
) -> str | None:
    raw = row.get("activityType")
    if isinstance(raw, dict):
        field, value = "activityType.typeKey", raw.get("typeKey")
    else:
        field, value = "activityType", raw
    if _is_absent(value):
        return None
    if not isinstance(value, str):
        issues.append(MappingIssue(ref, field, IssueReason.INVALID_TYPE))
        return None
    return value.strip().casefold()[:MAX_ISSUE_TEXT_LENGTH]


def _sport_and_environment(
    type_key: str | None, name: str | None
) -> tuple[Sport, Environment]:
    identity = " ".join(part for part in (type_key, name) if part)
    known = GARMIN_ACTIVITY_TYPES.get(type_key) if type_key is not None else None
    if known is None:
        return classify_sport_text(identity), classify_environment_text(identity)
    sport, environment = known
    if environment is Environment.UNKNOWN:
        environment = classify_environment_text(identity)
    return sport, environment


def _optional_number(
    row: dict[str, object],
    keys: tuple[str, ...],
    bounds: tuple[float, float],
    ref: str | None,
    issues: list[MappingIssue],
) -> float | None:
    found = _present(row, keys)
    if found is None:
        return None
    field, value = found
    number = coerce_number(value)
    if number is None:
        issues.append(MappingIssue(ref, field, IssueReason.INVALID_NUMBER))
        return None
    lower, upper = bounds
    if not lower <= number <= upper:
        issues.append(MappingIssue(ref, field, IssueReason.OUT_OF_RANGE))
        return None
    return number


def _recorded_by(row: dict[str, object]) -> RecordingOrigin:
    """Only an explicit boolean True marks a manual entry; anything else is GARMIN."""
    if row.get("manualActivity") is True:
        return RecordingOrigin.MANUAL
    return RecordingOrigin.GARMIN


def _provenance(
    activity_id: str, retrieved_at: datetime, recorded_by: RecordingOrigin
) -> Provenance:
    return Provenance(
        provider=ProviderId.GARMIN,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=activity_id,
        recorded_by=recorded_by,
        retrieved_at=retrieved_at,
        label=GARMIN_LABEL,
    )
