"""Enumerations that name canonical concepts without provider-specific payloads."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Final


class ProviderId(StrEnum):
    INTERVALS = "intervals"
    GARMIN = "garmin"
    WAHOO = "wahoo"


class SourceKind(StrEnum):
    PROVIDER_REPORTED = "provider_reported"
    DEVICE_MEASURED = "device_measured"
    DERIVED = "derived"
    AI_ESTIMATE = "ai_estimate"
    ATHLETE_ENTERED = "athlete_entered"
    PROFILE = "profile"


class RecordingOrigin(StrEnum):
    """Device brand or app that recorded an activity."""

    GARMIN = "garmin"
    WAHOO = "wahoo"
    STRAVA = "strava"
    ZWIFT = "zwift"
    MANUAL = "manual"
    UPLOAD = "upload"
    UNKNOWN = "unknown"


class DeviceType(StrEnum):
    """The device class that recorded the activity."""

    WATCH = "watch"
    BIKE_COMPUTER = "bike_computer"
    CHEST_STRAP = "chest_strap"
    POWER_METER = "power_meter"


class Sport(StrEnum):
    RIDE = "ride"
    RUN = "run"
    SWIM = "swim"
    WALK = "walk"
    HIKE = "hike"
    STRENGTH = "strength"
    ROW = "row"
    NORDIC_SKI = "nordic_ski"
    ALPINE_SKI = "alpine_ski"
    YOGA = "yoga"
    OTHER = "other"


class Environment(StrEnum):
    OUTDOOR = "outdoor"
    INDOOR = "indoor"
    VIRTUAL = "virtual"
    UNKNOWN = "unknown"


class LoadModel(StrEnum):
    """Provider model that produced an activity's reported training load.

    Every member is a provider's own calculation, never a local method: a local
    session-RPE load is not a LoadModel (see #1427). ``UNKNOWN`` marks a load whose
    model the provider does not name.
    """

    INTERVALS_TRAINING_LOAD = "intervals_training_load"
    GARMIN_TRAINING_LOAD = "garmin_training_load"
    TRIMP = "trimp"
    TSS = "tss"
    UNKNOWN = "unknown"


class MetricKind(StrEnum):
    """Metric concepts. Each member carries exactly one canonical unit."""

    WEIGHT = "weight"
    BODY_FAT = "body_fat"
    FTP = "ftp"
    THRESHOLD_HR = "threshold_hr"
    MAX_HR = "max_hr"
    RESTING_HR = "resting_hr"
    HRV_RMSSD = "hrv_rmssd"
    HRV_SDNN = "hrv_sdnn"
    HRV_WEEKLY_AVERAGE = "hrv_weekly_average"
    SLEEP_DURATION = "sleep_duration"
    SLEEP_SCORE = "sleep_score"
    VO2MAX = "vo2max"
    THRESHOLD_PACE = "threshold_pace"
    BODY_BATTERY = "body_battery"
    READINESS = "readiness"
    CTL = "ctl"
    ATL = "atl"
    TRAINING_LOAD = "training_load"
    FORM = "form"
    EFTP = "eftp"
    RUN_THRESHOLD_POWER = "run_threshold_power"
    DAILY_ENERGY_TOTAL = "daily_energy_total"
    DAILY_ENERGY_ACTIVE = "daily_energy_active"
    STEPS = "steps"
    FLOORS = "floors"
    STRESS = "stress"
    RACE_PREDICTION_5K = "race_prediction_5k"
    RACE_PREDICTION_10K = "race_prediction_10k"
    RACE_PREDICTION_HALF = "race_prediction_half"
    RACE_PREDICTION_FULL = "race_prediction_full"
    ENDURANCE_SCORE = "endurance_score"
    # Provider-reported domains retained since schema version 15. Each kind holds
    # one statistic per source series, so related provider values (targets, group
    # values, charged and drained totals) are separate kinds, never one kind with a
    # varying aggregation.
    DAILY_ENERGY_RESTING = "daily_energy_resting"
    BODY_BATTERY_CHARGED = "body_battery_charged"
    BODY_BATTERY_DRAINED = "body_battery_drained"
    # Garmin's acute and chronic training load, distinct from Intervals.icu ATL/CTL.
    ACUTE_LOAD = "acute_load"
    CHRONIC_LOAD = "chronic_load"
    ACUTE_CHRONIC_RATIO = "acute_chronic_ratio"
    LOAD_BALANCE_AEROBIC_LOW = "load_balance_aerobic_low"
    LOAD_BALANCE_AEROBIC_LOW_TARGET_MIN = "load_balance_aerobic_low_target_min"
    LOAD_BALANCE_AEROBIC_LOW_TARGET_MAX = "load_balance_aerobic_low_target_max"
    LOAD_BALANCE_AEROBIC_HIGH = "load_balance_aerobic_high"
    LOAD_BALANCE_AEROBIC_HIGH_TARGET_MIN = "load_balance_aerobic_high_target_min"
    LOAD_BALANCE_AEROBIC_HIGH_TARGET_MAX = "load_balance_aerobic_high_target_max"
    LOAD_BALANCE_ANAEROBIC = "load_balance_anaerobic"
    LOAD_BALANCE_ANAEROBIC_TARGET_MIN = "load_balance_anaerobic_target_min"
    LOAD_BALANCE_ANAEROBIC_TARGET_MAX = "load_balance_anaerobic_target_max"
    # A provider-defined score without a known physical unit.
    RUNNING_TOLERANCE = "running_tolerance"
    ENDURANCE_SCORE_GROUP_AVERAGE = "endurance_score_group_average"
    ENDURANCE_SCORE_GROUP_MAX = "endurance_score_group_max"
    # Subjective ratings imported from a provider; physiological stress is STRESS.
    SUBJECTIVE_FATIGUE = "subjective_fatigue"
    SUBJECTIVE_SORENESS = "subjective_soreness"
    SUBJECTIVE_STRESS = "subjective_stress"
    SUBJECTIVE_MOOD = "subjective_mood"
    # Athlete settings reported by a provider (mapper version 9 of Intervals.icu).
    W_PRIME = "w_prime"
    HEIGHT = "height"
    ZONE2_PACE = "zone2_pace"

    @property
    def unit(self) -> str:
        return _METRIC_UNITS[self]


_METRIC_UNITS: Final[Mapping[MetricKind, str]] = {
    MetricKind.WEIGHT: "kg",
    MetricKind.BODY_FAT: "%",
    MetricKind.FTP: "W",
    MetricKind.THRESHOLD_HR: "bpm",
    MetricKind.MAX_HR: "bpm",
    MetricKind.RESTING_HR: "bpm",
    MetricKind.HRV_RMSSD: "ms",
    MetricKind.HRV_SDNN: "ms",
    MetricKind.HRV_WEEKLY_AVERAGE: "ms",
    MetricKind.SLEEP_DURATION: "s",
    MetricKind.SLEEP_SCORE: "score",
    MetricKind.VO2MAX: "ml/kg/min",
    MetricKind.THRESHOLD_PACE: "m/s",
    MetricKind.BODY_BATTERY: "score",
    MetricKind.READINESS: "score",
    MetricKind.CTL: "load",
    MetricKind.ATL: "load",
    MetricKind.TRAINING_LOAD: "load",
    MetricKind.FORM: "load",
    MetricKind.EFTP: "W",
    MetricKind.RUN_THRESHOLD_POWER: "W",
    MetricKind.DAILY_ENERGY_TOTAL: "kcal",
    MetricKind.DAILY_ENERGY_ACTIVE: "kcal",
    MetricKind.STEPS: "count",
    MetricKind.FLOORS: "count",
    MetricKind.STRESS: "score",
    MetricKind.RACE_PREDICTION_5K: "s",
    MetricKind.RACE_PREDICTION_10K: "s",
    MetricKind.RACE_PREDICTION_HALF: "s",
    MetricKind.RACE_PREDICTION_FULL: "s",
    MetricKind.ENDURANCE_SCORE: "score",
    MetricKind.DAILY_ENERGY_RESTING: "kcal",
    MetricKind.BODY_BATTERY_CHARGED: "score",
    MetricKind.BODY_BATTERY_DRAINED: "score",
    MetricKind.ACUTE_LOAD: "load",
    MetricKind.CHRONIC_LOAD: "load",
    MetricKind.ACUTE_CHRONIC_RATIO: "ratio",
    MetricKind.LOAD_BALANCE_AEROBIC_LOW: "load",
    MetricKind.LOAD_BALANCE_AEROBIC_LOW_TARGET_MIN: "load",
    MetricKind.LOAD_BALANCE_AEROBIC_LOW_TARGET_MAX: "load",
    MetricKind.LOAD_BALANCE_AEROBIC_HIGH: "load",
    MetricKind.LOAD_BALANCE_AEROBIC_HIGH_TARGET_MIN: "load",
    MetricKind.LOAD_BALANCE_AEROBIC_HIGH_TARGET_MAX: "load",
    MetricKind.LOAD_BALANCE_ANAEROBIC: "load",
    MetricKind.LOAD_BALANCE_ANAEROBIC_TARGET_MIN: "load",
    MetricKind.LOAD_BALANCE_ANAEROBIC_TARGET_MAX: "load",
    MetricKind.RUNNING_TOLERANCE: "unknown",
    MetricKind.ENDURANCE_SCORE_GROUP_AVERAGE: "score",
    MetricKind.ENDURANCE_SCORE_GROUP_MAX: "score",
    MetricKind.SUBJECTIVE_FATIGUE: "rating",
    MetricKind.SUBJECTIVE_SORENESS: "rating",
    MetricKind.SUBJECTIVE_STRESS: "rating",
    MetricKind.SUBJECTIVE_MOOD: "rating",
    MetricKind.W_PRIME: "J",
    MetricKind.HEIGHT: "cm",
    MetricKind.ZONE2_PACE: "m/s",
}


# Members that no provider mapper produces. Stored text values must stay readable,
# so a member leaves the vocabulary only through a retirement mapping (see
# tests/test_canonical_enum_retirement.py), never by deletion.
UNPRODUCED_LOAD_MODELS: Final[Mapping[LoadModel, str]] = {
    LoadModel.TRIMP: "no provider reports TRIMP; retained so a stored value stays readable",
}
UNPRODUCED_METRIC_KINDS: Final[Mapping[MetricKind, str]] = {
    MetricKind.TRAINING_LOAD: (
        "never produced: activity loads carry LoadModel and Garmin's daily load is "
        "ACUTE_LOAD; retained so a stored value stays readable"
    ),
}
# Kinds stored for export, backup and history that no reader uses yet. A kind
# leaves this list when a consumer reads it; the vocabulary accountability test
# fails while the list and the code disagree.
EXPORT_ONLY_METRIC_KINDS: Final[Mapping[MetricKind, str]] = {
    MetricKind.TRAINING_LOAD: "never produced (see UNPRODUCED_METRIC_KINDS)",
    MetricKind.STRESS: (
        "Garmin daily physiological stress, stored for export and history; no "
        "reader showed it before the canonical model"
    ),
    MetricKind.BODY_BATTERY_CHARGED: (
        "Garmin daily charged total, stored for export and history; no reader "
        "showed it before the canonical model"
    ),
    MetricKind.BODY_BATTERY_DRAINED: (
        "Garmin daily drained total, stored for export and history; no reader "
        "showed it before the canonical model"
    ),
}


class ObservationAggregation(StrEnum):
    """How an observation's value summarizes its instant or period (optional)."""

    # One value at one instant, such as a timed Body Battery level.
    SAMPLE = "sample"
    # The sum over the period, such as charged Body Battery or daily energy.
    TOTAL = "total"
    MEAN = "mean"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"


class CategoricalDomain(StrEnum):
    """Provider status vocabularies kept as codes, never as numeric measurements.

    Stored as text without a SQL CHECK, so a mapper can add a domain without a
    schema change.
    """

    TRAINING_STATUS = "training_status"
    READINESS_LEVEL = "readiness_level"
    HRV_STATUS = "hrv_status"


class SleepKind(StrEnum):
    NIGHT = "night"
    UNKNOWN = "unknown"


class ZoneConfigurationMetric(StrEnum):
    """Metric of a zone configuration. Separate from ZoneMetric, whose members are
    CHECKed by the released activity detail tables."""

    HEART_RATE = "heart_rate"
    POWER = "power"
    PACE = "pace"


class ZonePercentBasis(StrEnum):
    """The reference value that percent zone limits are relative to."""

    THRESHOLD = "threshold"
    MAXIMUM = "maximum"
    # Heart-rate reserve: maximum minus resting heart rate.
    RESERVE = "reserve"


class ProjectionState(StrEnum):
    """Lifecycle of a row projected from one source record (schema version 15).

    A reprojection that no longer emits a row retires it instead of deleting it.
    """

    ACTIVE = "active"
    RETIRED = "retired"


class ProviderRecordState(StrEnum):
    """Lifecycle of a raw provider record. Deleted records are kept for sync."""

    ACTIVE = "active"
    DELETED = "deleted"


class ActivityRecordState(StrEnum):
    """Lifecycle of a provider activity record linked to a canonical session."""

    ACTIVE = "active"
    DELETED = "deleted"
    INVALID = "invalid"


class ActivityLinkKind(StrEnum):
    """How an activity session was linked to its primary provider activity."""

    SINGLE = "single"
    EXACT = "exact"
    HEURISTIC = "heuristic"
    CONFIRMED = "confirmed"


class ActivitySessionState(StrEnum):
    """Lifecycle of a canonical activity session."""

    ACTIVE = "active"
    HIDDEN = "hidden"
    DUPLICATE = "duplicate"
    DELETED = "deleted"


class RemoteEntityKind(StrEnum):
    """Kind of local entity that a provider-neutral remote link refers to."""

    LIBRARY_WORKOUT = "library_workout"
    PLANNED_UNIT = "planned_unit"
    COMPETITION = "competition"
    # A canonical metric value written to a provider field by an explicit export.
    OBSERVATION = "observation"


class RemoteLinkState(StrEnum):
    """Synchronization state of one local entity at one remote provider."""

    # The entity has no confirmed remote identifier at this provider yet.
    PENDING = "pending"
    # A remote identifier is known and was reconciled with the local entity.
    SYNCED = "synced"


class ActivityDetailKind(StrEnum):
    """One detail set stored per provider activity and kind (schema version 10)."""

    STREAMS = "streams"
    LAPS = "laps"
    HEART_RATE_ZONES = "heart_rate_zones"
    POWER_ZONES = "power_zones"


class ActivityDetailOrigin(StrEnum):
    """How a detail set reached the database."""

    # Mapped from a provider response fetched by this build.
    FETCH = "fetch"
    # Mapped from a detail document cached by an earlier release.
    LEGACY_BACKFILL = "legacy_backfill"


class StreamChannel(StrEnum):
    """Time-series channels, each in one canonical unit named by its suffix."""

    TIME_S = "time_s"
    DISTANCE_M = "distance_m"
    ALTITUDE_M = "altitude_m"
    GRADE_PCT = "grade_pct"
    SPEED_MPS = "speed_mps"
    POWER_W = "power_w"
    HEART_RATE_BPM = "heart_rate_bpm"
    CADENCE_RPM = "cadence_rpm"
    TEMPERATURE_C = "temperature_c"
    # 1 while moving, 0 while paused.
    MOVING = "moving"


class StreamResolution(StrEnum):
    """Whether a stream set keeps every recorded point."""

    FULL = "full"
    DOWNSAMPLED = "downsampled"


class LapKind(StrEnum):
    LAP = "lap"
    WORK = "work"
    RECOVERY = "recovery"
    WARMUP = "warmup"
    COOLDOWN = "cooldown"


class LapSource(StrEnum):
    """What produced a lap set."""

    # Intervals detected or labelled by the provider's analysis.
    PROVIDER_INTERVALS = "provider_intervals"
    # Laps recorded by the device (manual or automatic lap button).
    DEVICE_LAPS = "device_laps"
    # Fixed-distance splits computed by the provider.
    SPLITS = "splits"


class ZoneMetric(StrEnum):
    HEART_RATE = "heart_rate"
    POWER = "power"

    @property
    def detail_kind(self) -> ActivityDetailKind:
        return ZONE_DETAIL_KINDS[self]


# Each zone metric is stored as its own detail kind; a new metric needs an entry.
ZONE_DETAIL_KINDS: Final[Mapping[ZoneMetric, ActivityDetailKind]] = {
    ZoneMetric.HEART_RATE: ActivityDetailKind.HEART_RATE_ZONES,
    ZoneMetric.POWER: ActivityDetailKind.POWER_ZONES,
}


class ZoneBoundarySource(StrEnum):
    """Where the zone boundaries of a time-in-zone distribution came from."""

    PROVIDER_REPORTED = "provider_reported"
    PROFILE = "profile"
    UNKNOWN = "unknown"
