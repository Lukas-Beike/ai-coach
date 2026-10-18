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
    """Model that produced an activity's training load."""

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
}


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
