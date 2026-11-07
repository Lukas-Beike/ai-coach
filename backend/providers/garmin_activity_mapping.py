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
  When ``started_at`` comes from ``startTimeGMT``, the difference to
  ``startTimeLocal`` is the device's UTC offset -> ``local_offset_minutes``.
* ``activityType``: the dictionary form ``{"typeKey": ...}`` or, in the legacy
  form, the key as plain text. The key gives sport, environment, terrain and
  motor assistance (``GARMIN_ACTIVITY_TYPES``, ``GARMIN_ACTIVITY_QUALIFIERS``)
  and is kept as ``native_type``.
* ``duration_s``: ``activity_duration_s`` of ``movingDuration``, the timer time
  (``duration``, then ``movingTime``) and the elapsed time below.
* ``elapsedDuration``, then ``duration`` alone (seconds) -> ``elapsed_duration_s``;
  the ``movingTime`` fallback is not elapsed time and stays out of it. For a
  strength activity, ``duration`` is only the active timer time, so the
  canonical rule takes the longer elapsed time (the whole session).
* ``movingDuration`` (seconds) -> ``moving_duration_s``, with no ``movingTime``
  fallback because ``movingTime`` is a timer-time alias.
* ``distance`` (metres), ``activityTrainingLoad`` (Garmin training load),
  ``averageHR`` (bpm), ``avgPower``, then ``averagePower`` (watts).
* ``maxHR``, then ``maxHeartRate`` (bpm) -> ``max_hr``, the aliases that
  ``performance.max_hr`` reads first.
* ``maxSpeed`` (m/s) -> ``max_speed_mps``, and ``maxPower`` (watts) -> ``max_power_w``.
* ``steps`` (count) -> ``steps``.
* ``averageSpeed`` (m/s), ``elevationGain`` (m), ``normPower`` (W) and
  ``vO2MaxValue`` -> ``avg_speed_mps``, ``elevation_gain_m``,
  ``normalized_power`` and ``vo2max``.
* ``avgGradeAdjustedSpeed`` (m/s) -> ``grade_adjusted_speed_mps``, the pace
  input of the local session load (card M6).
* ``activityName`` (text, stripped and truncated to 200 characters).
* ``trainingEffectLabel`` (text, stripped, upper-cased and truncated to 50
  characters) -> ``training_effect_label``.
* ``aerobicTrainingEffect`` (legacy ``trainingEffect``) and
  ``anaerobicTrainingEffect`` (Garmin's 0.0-5.0 scale) ->
  ``aerobic_training_effect`` and ``anaerobic_training_effect``.
* ``maxElevation`` and ``minElevation`` (metres) -> ``elevation_high_m`` and
  ``elevation_low_m``; ``elevationLoss`` (m) -> ``elevation_loss_m``.
* ``minTemperature`` and ``maxTemperature`` (°C) -> ``min_temp_c``, ``max_temp_c``.
  A minimum above its maximum drops both of the pair with one issue.
* ``waterEstimated`` (ml, Garmin's estimate) -> ``water_estimated_ml``;
  ``lapCount`` -> ``lap_count``.
* ``calories`` (kcal, Garmin's whole-session estimate including the resting
  share) -> ``energy_kcal``; zero means not estimated and becomes None (card M8).
* ``averageBikingCadenceInRevPerMinute`` (rpm) -> ``avg_cadence``; else
  ``averageRunningCadenceInStepsPerMinute`` (steps/min) halved to one-leg rpm.
* ``hrTimeInZone_<n>`` and ``powerTimeInZone_<n>`` (seconds, by Garmin's own
  zones) -> ``hr_zone_times_s`` and ``power_zone_times_s`` as zones ``Z<n>``.
  One invalid zone drops that distribution with one issue.
* ``eventType.typeKey`` ``race`` -> ``purpose`` RACE and ``transportation`` ->
  COMMUTE; every other event type (``uncategorized``, ``training`` ...) leaves
  ``purpose`` unset, as does a missing key. A key that is not text is one issue.

* ``directWorkoutRpe`` (10..100) / 10 -> ``rpe`` (1..10); ``directWorkoutFeel``
  (0 very weak .. 100 very strong) -> ``feel`` on the 1 (strong) .. 5 (weak)
  scale, as Intervals.icu imports it; ``minHR`` (bpm) -> ``min_hr``.

Dedicated rows of the same ``activityId`` supply values before the activity is
mapped (``merge_training_load_rows``): a ``training_load_activities`` row
``activityTrainingLoad``, ``trainingEffectLabel`` and the training-effect values,
an ``activity_ratings`` row (from the single-activity ``summaryDTO``) the RPE,
feel and minimum heart rate; a re-projection of the stored row reads them too.

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

from backend.canonical.local_time import (
    parse_provider_datetime,
    wall_clock_offset_minutes,
)
from backend.canonical.mapping import (
    MAX_ISSUE_TEXT_LENGTH,
    IssueReason,
    MappingIssue,
    MappingResult,
    coerce_number,
)
from backend.canonical.records import (
    MAX_ACTIVITY_ENERGY_KCAL,
    MAX_LAP_COUNT,
    MAX_NATIVE_TYPE_LENGTH,
    MAX_TRAINING_EFFECT,
    MAX_TRAINING_EFFECT_LABEL_LENGTH,
    MAX_WATER_ESTIMATE_ML,
    MAX_ZONE_COUNT,
    TEMPERATURE_C_BOUNDS,
    ActivityRecord,
    Provenance,
    activity_duration_s,
)
from backend.canonical.sports import classify_environment_text, classify_sport_text
from backend.canonical.validation import (
    HEART_RATE_BOUNDS,
    MAX_ACTIVITY_ALTITUDE_M,
    MAX_ACTIVITY_CADENCE_RPM,
    MAX_ACTIVITY_DISTANCE_M,
    MAX_ACTIVITY_DURATION_S,
    MAX_ACTIVITY_ELEVATION_M,
    MAX_ACTIVITY_LOAD,
    MAX_ACTIVITY_POWER_W,
    MAX_ACTIVITY_SPEED_MPS,
    MAX_ACTIVITY_STEPS,
    MIN_ACTIVITY_ALTITUDE_M,
    require_aware_datetime,
)
from backend.canonical.vocabulary import (
    ActivityPurpose,
    Assist,
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
    Terrain,
)

# Version 5: maps the maximum speed, maximum power and step count.
# Version 4: a row with manualActivity exactly True is recorded as MANUAL origin.
# Version 3: maps the activity's maximum heart rate.
# Version 7: maps average speed, elevation gain, normalized power and VO2max.
# Version 9: strength duration is the elapsed session time.
# Version 8: maps the training-effect label (#1416).
# Version 10: trail and obstacle runs are outdoor, so analyses leave them out like
# Intervals.icu trail runs.
# Version 11: the device's UTC offset dates the activity where it was recorded.
# Version 12: the duration follows the canonical rule (``activity_duration_s``):
# moving time before the timer ``duration``.
# Version 13: maps terrain, motor assistance and the native type key, and knows
# the cyclocross, BMX, track cycling, e-MTB, skate and backcountry skiing,
# indoor and treadmill walking, Pilates, HIIT and indoor cardio keys (#1670).
# Version 14: maps HR and power zone times, aerobic and anaerobic training
# effect, altitude extremes, elevation loss, temperature range, estimated sweat
# loss, lap count and average cadence (#1724).
# Version 15: maps avgGradeAdjustedSpeed, the pace input of the local session
# load (card M6, #1725).
# Version 16: maps the athlete's RPE and feel and the minimum heart rate from the
# merged activity_ratings rows (#1724).
# Version 17: maps eventType.typeKey race and transportation to the activity
# purpose (#1678).
# Version 18: maps calories, the device's energy estimate (card M8, #1680).
MAPPER_VERSION: Final = 18
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
_GRADE_ADJUSTED_SPEED_KEYS: Final = ("avgGradeAdjustedSpeed",)
_ELEVATION_GAIN_KEYS: Final = ("elevationGain",)
_NORMALIZED_POWER_KEYS: Final = ("normPower",)
_VO2MAX_KEYS: Final = ("vO2MaxValue",)
_TRAINING_EFFECT_LABEL_KEY: Final = "trainingEffectLabel"
_EVENT_TYPE_KEY: Final = "eventType"
# Garmin event types that name a purpose; every other type is plain training.
_EVENT_PURPOSES: Final = {
    "race": ActivityPurpose.RACE,
    "transportation": ActivityPurpose.COMMUTE,
}
_TRAINING_LOAD_KEY: Final = "activityTrainingLoad"
_AEROBIC_EFFECT_KEYS: Final = ("aerobicTrainingEffect", "trainingEffect")
_ANAEROBIC_EFFECT_KEYS: Final = ("anaerobicTrainingEffect",)
# The dedicated training-load rows override these activity fields, each named
# by its aliases.
_RPE_KEY: Final = "directWorkoutRpe"
_FEEL_KEY: Final = "directWorkoutFeel"
_MIN_HR_KEYS: Final = ("minHR",)
_TRAINING_LOAD_FIELDS: Final = (
    (_TRAINING_LOAD_KEY,),
    (_TRAINING_EFFECT_LABEL_KEY,),
    _AEROBIC_EFFECT_KEYS,
    _ANAEROBIC_EFFECT_KEYS,
    # The activity_ratings rows (single-activity summaryDTO).
    (_RPE_KEY,),
    (_FEEL_KEY,),
    _MIN_HR_KEYS,
)
# Garmin rates RPE 10..100 and feel 0 (very weak) .. 100 (very strong).
_RPE_BOUNDS: Final = (10.0, 100.0)
_FEEL_BOUNDS: Final = (0.0, 100.0)
_TRAINING_EFFECT_BOUNDS: Final = (0.0, MAX_TRAINING_EFFECT)
_ALTITUDE_BOUNDS: Final = (MIN_ACTIVITY_ALTITUDE_M, MAX_ACTIVITY_ALTITUDE_M)
_BIKE_CADENCE_KEYS: Final = ("averageBikingCadenceInRevPerMinute",)
_RUN_CADENCE_KEYS: Final = ("averageRunningCadenceInStepsPerMinute",)
# Garmin reports zone times as numbered keys, zone 1 first.
_HR_ZONE_PREFIX: Final = "hrTimeInZone_"
_POWER_ZONE_PREFIX: Final = "powerTimeInZone_"

# Exact Garmin activityType.typeKey values. The environment is set only where the
# key names it;
# otherwise UNKNOWN, which the activity name may still refine.
# Lap swimming is not named as indoor and open water is named as outdoor.
# The legacy text classifier does not recognise road_biking, mountain_biking or
# hiking, so those keys must come from this table.
GARMIN_ACTIVITY_TYPES: Final[Mapping[str, tuple[Sport, Environment]]] = {
    "cycling": (Sport.RIDE, Environment.UNKNOWN),
    "bmx": (Sport.RIDE, Environment.UNKNOWN),
    "cyclocross": (Sport.RIDE, Environment.OUTDOOR),
    "e_bike_fitness": (Sport.RIDE, Environment.UNKNOWN),
    "e_bike_mountain": (Sport.RIDE, Environment.UNKNOWN),
    "gravel_cycling": (Sport.RIDE, Environment.UNKNOWN),
    "mountain_biking": (Sport.RIDE, Environment.UNKNOWN),
    "road_biking": (Sport.RIDE, Environment.UNKNOWN),
    "track_cycling": (Sport.RIDE, Environment.UNKNOWN),
    "indoor_cycling": (Sport.RIDE, Environment.INDOOR),
    "virtual_ride": (Sport.RIDE, Environment.VIRTUAL),
    "running": (Sport.RUN, Environment.UNKNOWN),
    "street_running": (Sport.RUN, Environment.UNKNOWN),
    "trail_running": (Sport.RUN, Environment.OUTDOOR),
    # Obstacle runs are off-road; ultra runs may be road or trail, so they stay unknown.
    "obstacle_run": (Sport.RUN, Environment.OUTDOOR),
    "track_running": (Sport.RUN, Environment.UNKNOWN),
    "treadmill_running": (Sport.RUN, Environment.INDOOR),
    "indoor_running": (Sport.RUN, Environment.INDOOR),
    "virtual_run": (Sport.RUN, Environment.VIRTUAL),
    "lap_swimming": (Sport.SWIM, Environment.UNKNOWN),
    "open_water_swimming": (Sport.SWIM, Environment.OUTDOOR),
    "walking": (Sport.WALK, Environment.UNKNOWN),
    "indoor_walking": (Sport.WALK, Environment.INDOOR),
    "treadmill_walking": (Sport.WALK, Environment.INDOOR),
    "hiking": (Sport.HIKE, Environment.UNKNOWN),
    "strength_training": (Sport.STRENGTH, Environment.UNKNOWN),
    "rowing": (Sport.ROW, Environment.UNKNOWN),
    "indoor_rowing": (Sport.ROW, Environment.INDOOR),
    "cross_country_skiing_ws": (Sport.NORDIC_SKI, Environment.UNKNOWN),
    "skate_skiing_ws": (Sport.NORDIC_SKI, Environment.UNKNOWN),
    "resort_skiing_snowboarding_ws": (Sport.ALPINE_SKI, Environment.UNKNOWN),
    "backcountry_skiing_snowboarding_ws": (Sport.ALPINE_SKI, Environment.OUTDOOR),
    "backcountry_skiing": (Sport.ALPINE_SKI, Environment.OUTDOOR),
    "yoga": (Sport.YOGA, Environment.UNKNOWN),
    "pilates": (Sport.OTHER, Environment.UNKNOWN),
    "hiit": (Sport.OTHER, Environment.UNKNOWN),
    "indoor_cardio": (Sport.OTHER, Environment.INDOOR),
}

# Terrain and motor assistance of the type keys that name them. Every other key
# of GARMIN_ACTIVITY_TYPES is (UNKNOWN, NONE); a key outside it is (UNKNOWN, UNKNOWN).
GARMIN_ACTIVITY_QUALIFIERS: Final[Mapping[str, tuple[Terrain, Assist]]] = {
    "road_biking": (Terrain.ROAD, Assist.NONE),
    "gravel_cycling": (Terrain.GRAVEL, Assist.NONE),
    "mountain_biking": (Terrain.MOUNTAIN, Assist.NONE),
    "track_cycling": (Terrain.TRACK, Assist.NONE),
    "e_bike_fitness": (Terrain.UNKNOWN, Assist.ELECTRIC),
    "e_bike_mountain": (Terrain.MOUNTAIN, Assist.ELECTRIC),
    "street_running": (Terrain.ROAD, Assist.NONE),
    "trail_running": (Terrain.TRAIL, Assist.NONE),
    "obstacle_run": (Terrain.TRAIL, Assist.NONE),
    "track_running": (Terrain.TRACK, Assist.NONE),
    "treadmill_running": (Terrain.TREADMILL, Assist.NONE),
    "treadmill_walking": (Terrain.TREADMILL, Assist.NONE),
    "lap_swimming": (Terrain.POOL, Assist.NONE),
    "open_water_swimming": (Terrain.OPEN_WATER, Assist.NONE),
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
    terrain, assist = _qualifiers(type_key)
    timer = _optional_number(
        row, _DURATION_KEYS, (0.0, MAX_ACTIVITY_DURATION_S), ref, issues
    )
    # Issues for ``duration`` are already reported above.
    raw_elapsed = _optional_number(
        row, ("elapsedDuration",), (0.0, MAX_ACTIVITY_DURATION_S), ref, issues
    )
    # Issues for ``duration`` are already reported above.
    elapsed_duration = (
        raw_elapsed
        if raw_elapsed is not None
        else _optional_number(
            row, ("duration",), (0.0, MAX_ACTIVITY_DURATION_S), ref, []
        )
    )
    moving_duration = _optional_number(
        row, _MOVING_DURATION_KEYS, (0.0, MAX_ACTIVITY_DURATION_S), ref, issues
    )
    # Garmin ``duration`` of a strength activity is the active timer time without
    # rest between sets; the canonical rule takes the whole session instead.
    duration = activity_duration_s(
        sport, moving=moving_duration, timer=timer, elapsed=elapsed_duration
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
    min_hr = _optional_number(row, _MIN_HR_KEYS, HEART_RATE_BOUNDS, ref, issues)
    raw_rpe = _optional_number(row, (_RPE_KEY,), _RPE_BOUNDS, ref, issues)
    raw_feel = _optional_number(row, (_FEEL_KEY,), _FEEL_BOUNDS, ref, issues)
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
    grade_adjusted_speed = _optional_number(
        row, _GRADE_ADJUSTED_SPEED_KEYS, (0.0, MAX_ACTIVITY_SPEED_MPS), ref, issues
    )
    elevation_gain = _optional_number(
        row, _ELEVATION_GAIN_KEYS, (0.0, MAX_ACTIVITY_ELEVATION_M), ref, issues
    )
    normalized_power = _optional_number(
        row, _NORMALIZED_POWER_KEYS, (0.0, MAX_ACTIVITY_POWER_W), ref, issues
    )
    vo2max = _optional_number(row, _VO2MAX_KEYS, (0.0, 100.0), ref, issues)
    aerobic_effect = _optional_number(
        row, _AEROBIC_EFFECT_KEYS, _TRAINING_EFFECT_BOUNDS, ref, issues
    )
    anaerobic_effect = _optional_number(
        row, _ANAEROBIC_EFFECT_KEYS, _TRAINING_EFFECT_BOUNDS, ref, issues
    )
    elevation_low, elevation_high = _ordered_pair(
        row, ("minElevation", "maxElevation"), _ALTITUDE_BOUNDS, ref, issues
    )
    min_temp, max_temp = _ordered_pair(
        row, ("minTemperature", "maxTemperature"), TEMPERATURE_C_BOUNDS, ref, issues
    )
    elevation_loss = _optional_number(
        row, ("elevationLoss",), (0.0, MAX_ACTIVITY_ELEVATION_M), ref, issues
    )
    water = _optional_number(
        row, ("waterEstimated",), (0.0, MAX_WATER_ESTIMATE_ML), ref, issues
    )
    lap_count = _optional_number(row, ("lapCount",), (0.0, MAX_LAP_COUNT), ref, issues)
    calories = _optional_number(
        row, ("calories",), (0.0, MAX_ACTIVITY_ENERGY_KCAL), ref, issues
    )
    cadence = _cadence(row, ref, issues)
    hr_zones = _zone_times(row, _HR_ZONE_PREFIX, ref, issues)
    power_zones = _zone_times(row, _POWER_ZONE_PREFIX, ref, issues)
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
        min_hr=min_hr,
        rpe=None if raw_rpe is None else raw_rpe / 10,
        feel=None if raw_feel is None else garmin_feel(raw_feel),
        max_speed_mps=max_speed,
        max_power_w=max_power,
        steps=steps,
        avg_speed_mps=avg_speed,
        grade_adjusted_speed_mps=grade_adjusted_speed,
        elevation_gain_m=elevation_gain,
        normalized_power=normalized_power,
        vo2max=vo2max,
        training_effect_label=training_effect_label,
        aerobic_training_effect=aerobic_effect,
        anaerobic_training_effect=anaerobic_effect,
        elevation_high_m=elevation_high,
        elevation_low_m=elevation_low,
        elevation_loss_m=elevation_loss,
        min_temp_c=min_temp,
        max_temp_c=max_temp,
        water_estimated_ml=water,
        energy_kcal=calories or None,
        lap_count=lap_count,
        avg_cadence=cadence,
        hr_zone_times_s=hr_zones,
        power_zone_times_s=power_zones,
        local_offset_minutes=_local_offset(row, started_at),
        terrain=terrain,
        assist=assist,
        native_type=type_key[:MAX_NATIVE_TYPE_LENGTH] if type_key else None,
        purpose=_purpose(row, ref, issues),
    )


def garmin_feel(value: float) -> float:
    """Garmin feel 0..100 (higher = stronger) on the 1..5 feel scale, 1 = strong.

    This is the conversion Intervals.icu applies when it imports the rating
    (100 -> 1), so both copies of one session carry the same value.
    """
    return 5.0 - value / 25.0


def merge_training_load_rows(activities: object, training_loads: object) -> object:
    """Return the activity rows with the dedicated training-load values merged in.

    A training-load row of the same ``activityId`` (or ``id``) replaces the
    activity's training load and training-effect label where it carries one.
    Anything that is not a list of rows is returned unchanged.
    """
    if not isinstance(activities, list) or not isinstance(training_loads, list):
        return activities
    # Rows of one id combine in order: a later row's value replaces an earlier one.
    by_id: dict[str, dict[str, object]] = {}
    for row in training_loads:
        if isinstance(row, dict) and not _is_absent(
            identity := row.get("activityId") or row.get("id")
        ):
            # An explicit null clears an earlier value: a rating removed on the watch.
            by_id.setdefault(str(identity), {}).update(row)
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
        merged.append(_with_load_fields(activity, load_row))
    return merged


def _with_load_fields(
    activity: dict[str, object], load_row: dict[str, object]
) -> dict[str, object]:
    """Replace each field the load row carries, dropping the activity's aliases."""
    result = dict(activity)
    for aliases in _TRAINING_LOAD_FIELDS:
        carried = {
            key: load_row[key] for key in aliases if load_row.get(key) is not None
        }
        if carried:
            for key in aliases:
                result.pop(key, None)
            result.update(carried)
    return result


def _purpose(
    row: dict[str, object], ref: str | None, issues: list[MappingIssue]
) -> ActivityPurpose | None:
    event = row.get(_EVENT_TYPE_KEY)
    if event is None:
        return None
    key = event.get("typeKey") if isinstance(event, dict) else event
    if key is None:
        return None
    if not isinstance(key, str):
        issues.append(MappingIssue(ref, _EVENT_TYPE_KEY, IssueReason.INVALID_TYPE))
        return None
    return _EVENT_PURPOSES.get(key.strip().casefold())


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


def _local_offset(row: dict[str, object], started_at: datetime) -> int | None:
    """Return the device's UTC offset, known only when GMT gave the start."""
    if parse_provider_datetime(row.get("startTimeGMT"), UTC) != started_at:
        return None
    return wall_clock_offset_minutes(row.get("startTimeLocal"), started_at)


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


def _qualifiers(type_key: str | None) -> tuple[Terrain, Assist]:
    if type_key is None or type_key not in GARMIN_ACTIVITY_TYPES:
        return Terrain.UNKNOWN, Assist.UNKNOWN
    return GARMIN_ACTIVITY_QUALIFIERS.get(type_key, (Terrain.UNKNOWN, Assist.NONE))


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


def _ordered_pair(
    row: dict[str, object],
    keys: tuple[str, str],
    bounds: tuple[float, float],
    ref: str | None,
    issues: list[MappingIssue],
) -> tuple[float | None, float | None]:
    """Return a (minimum, maximum) pair; a minimum above its maximum drops both."""
    low_key, high_key = keys
    low = _optional_number(row, (low_key,), bounds, ref, issues)
    high = _optional_number(row, (high_key,), bounds, ref, issues)
    if low is not None and high is not None and low > high:
        issues.append(MappingIssue(ref, low_key, IssueReason.OUT_OF_RANGE))
        return None, None
    return low, high


def _cadence(
    row: dict[str, object], ref: str | None, issues: list[MappingIssue]
) -> float | None:
    """Bike rpm as reported; run steps per minute halved to one-leg rpm."""
    bike = _optional_number(
        row, _BIKE_CADENCE_KEYS, (0.0, MAX_ACTIVITY_CADENCE_RPM), ref, issues
    )
    if bike:
        return bike
    steps = _optional_number(
        row, _RUN_CADENCE_KEYS, (0.0, 2 * MAX_ACTIVITY_CADENCE_RPM), ref, issues
    )
    return bike if steps is None else steps / 2


def _zone_times(
    row: dict[str, object], prefix: str, ref: str | None, issues: list[MappingIssue]
) -> tuple[tuple[str, float], ...] | None:
    """Return ``<prefix><n>`` seconds as ``Z<n>`` zones; one bad zone drops all."""
    zones: list[tuple[str, float]] = []
    for number in range(1, MAX_ZONE_COUNT + 1):
        key = f"{prefix}{number}"
        if _is_absent(row.get(key)):
            continue
        seconds = _optional_number(
            row, (key,), (0.0, MAX_ACTIVITY_DURATION_S), ref, issues
        )
        if seconds is None:
            return None
        zones.append((f"Z{number}", seconds))
    return tuple(zones) or None


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
