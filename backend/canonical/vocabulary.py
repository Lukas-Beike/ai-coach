"""Enumerations that name canonical concepts without provider-specific payloads."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Final


class ProviderId(StrEnum):
    INTERVALS = "intervals"
    GARMIN = "garmin"
    WAHOO = "wahoo"


# Which provider's record leads a session, its measured values, streams and
# laps, best first. Intervals.icu is output only and ranks last.
PROVIDER_PRECEDENCE: Final = (ProviderId.WAHOO, ProviderId.GARMIN, ProviderId.INTERVALS)


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


class ActivityPurpose(StrEnum):
    """Why an activity was done, where a source says so.

    RACE and COMMUTE come from the provider's event type (Garmin
    ``eventType.typeKey``) or, for RACE, from a stored competition on the same
    local date and sport. WARMUP and COOLDOWN are reserved for the athlete's own
    marking. An activity without any of these is ordinary training.
    """

    TRAINING = "training"
    RACE = "race"
    COMMUTE = "commute"
    WARMUP = "warmup"
    COOLDOWN = "cooldown"


class Terrain(StrEnum):
    """The surface an activity was done on, where the provider type names it.

    Orthogonal to ``Sport`` and ``Environment``: a trail run is a RUN, OUTDOOR,
    TRAIL. UNKNOWN when the type names no surface.
    """

    ROAD = "road"
    TRAIL = "trail"
    TRACK = "track"
    GRAVEL = "gravel"
    MOUNTAIN = "mountain"
    TREADMILL = "treadmill"
    POOL = "pool"
    OPEN_WATER = "open_water"
    UNKNOWN = "unknown"


class Assist(StrEnum):
    """Motor assistance: ELECTRIC for e-bikes, NONE when the provider type names a
    sport without assistance, UNKNOWN when the type is not known."""

    NONE = "none"
    ELECTRIC = "electric"
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
    # Night values of the Garmin sleep record (mapper 18): mean and lowest SpO2,
    # mean respiration rate and mean heart rate while asleep.
    SPO2 = "spo2"
    SPO2_LOWEST = "spo2_lowest"
    RESPIRATION_RATE = "respiration_rate"
    SLEEPING_HR = "sleeping_hr"
    VO2MAX = "vo2max"
    THRESHOLD_PACE = "threshold_pace"
    BODY_BATTERY = "body_battery"
    READINESS = "readiness"
    CTL = "ctl"
    ATL = "atl"
    TRAINING_LOAD = "training_load"
    FORM = "form"
    EFTP = "eftp"
    # Legacy: running threshold power is FTP with sport RUN for every provider.
    # Only rows stored before Garmin health mapper 17 still carry this kind.
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
    # The sport setting's indoor FTP (mapper version 10 of Intervals.icu). Only the
    # plan zones of indoor and virtual workouts read this kind. FTP stays the
    # setting's ``ftp``; a setting without ``ftp`` (absent or null) also stores its
    # ``indoor_ftp`` as FTP, as the current metrics read it.
    INDOOR_FTP = "indoor_ftp"
    # Local TSS-scale load and intensity factor of one session (card M6).
    SESSION_LOAD = "session_load"
    INTENSITY_FACTOR = "intensity_factor"
    # Local efficiency, variability, work and decoupling of one session (card M8).
    EFFICIENCY_FACTOR = "efficiency_factor"
    VARIABILITY_INDEX = "variability_index"
    MECHANICAL_WORK = "mechanical_work"
    AEROBIC_DECOUPLING = "aerobic_decoupling"
    # Garmin Body Battery levels around one night, derived locally (#1686): the
    # last level up to four hours before sleep and the first after waking.
    BODY_BATTERY_BEFORE_SLEEP = "body_battery_before_sleep"
    MORNING_BODY_BATTERY = "morning_body_battery"

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
    MetricKind.SPO2: "%",
    MetricKind.SPO2_LOWEST: "%",
    MetricKind.RESPIRATION_RATE: "brpm",
    MetricKind.SLEEPING_HR: "bpm",
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
    MetricKind.INDOOR_FTP: "W",
    MetricKind.SESSION_LOAD: "load",
    MetricKind.INTENSITY_FACTOR: "%",
    # Ride W/bpm, run (m/min)/bpm; the derivation names the unit of each value.
    MetricKind.EFFICIENCY_FACTOR: "ratio",
    MetricKind.VARIABILITY_INDEX: "ratio",
    MetricKind.MECHANICAL_WORK: "kJ",
    MetricKind.AEROBIC_DECOUPLING: "%",
    MetricKind.BODY_BATTERY_BEFORE_SLEEP: "score",
    MetricKind.MORNING_BODY_BATTERY: "score",
}


# Members that no provider mapper produces. Stored text values must stay readable,
# so a member leaves the vocabulary only through a retirement mapping (see
# tests/test_canonical_enum_retirement.py), never by deletion.
UNPRODUCED_LOAD_MODELS: Final[Mapping[LoadModel, str]] = {
    LoadModel.TRIMP: "no provider reports TRIMP; retained so a stored value stays readable",
    LoadModel.INTERVALS_TRAINING_LOAD: (
        "no longer produced: Intervals.icu is output-only and its activity mapper "
        "is retired; retained so a restored backup's stored value stays readable"
    ),
}
UNPRODUCED_METRIC_KINDS: Final[Mapping[MetricKind, str]] = {
    **dict.fromkeys(
        (
            MetricKind.HRV_SDNN,
            MetricKind.CTL,
            MetricKind.ATL,
            MetricKind.FORM,
            MetricKind.EFTP,
            MetricKind.SUBJECTIVE_FATIGUE,
            MetricKind.SUBJECTIVE_SORENESS,
            MetricKind.SUBJECTIVE_STRESS,
            MetricKind.SUBJECTIVE_MOOD,
            MetricKind.W_PRIME,
            MetricKind.HEIGHT,
            MetricKind.ZONE2_PACE,
            MetricKind.INDOOR_FTP,
        ),
        "no longer produced: Intervals.icu is output-only and its wellness mapper is "
        "retired; retained so a restored backup's stored value stays readable",
    ),
    MetricKind.TRAINING_LOAD: (
        "never produced: activity loads carry LoadModel and Garmin's daily load is "
        "ACUTE_LOAD; retained so a stored value stays readable"
    ),
    MetricKind.RUN_THRESHOLD_POWER: (
        "no longer produced: running threshold power is FTP with sport RUN since "
        "Garmin health mapper 17; retained so rows stored earlier stay readable"
    ),
    MetricKind.SESSION_LOAD: (
        "derived locally per session by backend.sync.local_load (card M6), never "
        "by a provider mapper"
    ),
    MetricKind.INTENSITY_FACTOR: (
        "derived locally per session by backend.sync.local_load (card M6), never "
        "by a provider mapper"
    ),
    **{
        kind: (
            "derived locally per session by backend.sync.session_metrics (card "
            "M8), never by a provider mapper"
        )
        for kind in (
            MetricKind.EFFICIENCY_FACTOR,
            MetricKind.VARIABILITY_INDEX,
            MetricKind.MECHANICAL_WORK,
            MetricKind.AEROBIC_DECOUPLING,
        )
    },
    **{
        kind: (
            "derived locally per night by backend.performance.morning_battery_service "
            "from the Garmin NIGHT period and BODY_BATTERY levels, never by a "
            "provider mapper"
        )
        for kind in (
            MetricKind.BODY_BATTERY_BEFORE_SLEEP,
            MetricKind.MORNING_BODY_BATTERY,
        )
    },
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
    **dict.fromkeys(
        (
            MetricKind.CTL,
            MetricKind.ATL,
            MetricKind.FORM,
            MetricKind.EFTP,
            MetricKind.SUBJECTIVE_FATIGUE,
            MetricKind.SUBJECTIVE_SORENESS,
            MetricKind.SUBJECTIVE_STRESS,
            MetricKind.SUBJECTIVE_MOOD,
            MetricKind.W_PRIME,
            MetricKind.HEIGHT,
            MetricKind.ZONE2_PACE,
            MetricKind.INDOOR_FTP,
        ),
        "Intervals.icu is output-only: stored from its sync, no current value, "
        "load or rating reads it (athlete decision 2026-11-07)",
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
    # Executed strength sets (schema version 22).
    STRENGTH_SETS = "strength_sets"


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
    # Revolutions per minute; for runs one leg (strides per minute, half the
    # steps per minute), as FIT and every provider mapper report it.
    CADENCE_RPM = "cadence_rpm"
    TEMPERATURE_C = "temperature_c"
    # 1 while moving, 0 while paused.
    MOVING = "moving"
    # WGS84 position in degrees (schema-neutral; stored like every channel).
    # Private: see POSITION_CHANNELS.
    LATITUDE_DEG = "latitude_deg"
    LONGITUDE_DEG = "longitude_deg"


# Raw GPS positions stay in storage, backup and export only. They are never
# merged into read models, so no Coach, API, diagnostics or log path can carry
# them; weather and route features derive coarse values from the stored set.
POSITION_CHANNELS: Final = frozenset(
    {StreamChannel.LATITUDE_DEG, StreamChannel.LONGITUDE_DEG}
)


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


class StrengthSetType(StrEnum):
    """Whether a recorded strength set is work or the rest between sets."""

    ACTIVE = "active"
    REST = "rest"


class StrengthSetSource(StrEnum):
    """What produced a strength set list."""

    # Garmin's exercise sets, including the athlete's corrections in Connect.
    GARMIN_EXERCISE_SETS = "garmin_exercise_sets"
    # The ``set`` messages (225) of the original FIT activity file.
    FIT_SET_MESSAGES = "fit_set_messages"


class ExerciseCategory(StrEnum):
    """Exercise categories of the FIT profile (``exercise_category``, 0-32).

    Garmin's exercise sets name the same categories in upper case. A category
    outside this list maps to ``OTHER``; the provider code is kept separately.
    """

    BENCH_PRESS = "bench_press"
    CALF_RAISE = "calf_raise"
    CARDIO = "cardio"
    CARRY = "carry"
    CHOP = "chop"
    CORE = "core"
    CRUNCH = "crunch"
    CURL = "curl"
    DEADLIFT = "deadlift"
    FLYE = "flye"
    HIP_RAISE = "hip_raise"
    HIP_STABILITY = "hip_stability"
    HIP_SWING = "hip_swing"
    HYPEREXTENSION = "hyperextension"
    LATERAL_RAISE = "lateral_raise"
    LEG_CURL = "leg_curl"
    LEG_RAISE = "leg_raise"
    LUNGE = "lunge"
    OLYMPIC_LIFT = "olympic_lift"
    PLANK = "plank"
    PLYO = "plyo"
    PULL_UP = "pull_up"
    PUSH_UP = "push_up"
    ROW = "row"
    SHOULDER_PRESS = "shoulder_press"
    SHOULDER_STABILITY = "shoulder_stability"
    SHRUG = "shrug"
    SIT_UP = "sit_up"
    SQUAT = "squat"
    TOTAL_BODY = "total_body"
    TRICEPS_EXTENSION = "triceps_extension"
    WARM_UP = "warm_up"
    RUN = "run"
    OTHER = "other"


class ZoneBoundarySource(StrEnum):
    """Where the zone boundaries of a time-in-zone distribution came from."""

    PROVIDER_REPORTED = "provider_reported"
    PROFILE = "profile"
    UNKNOWN = "unknown"
