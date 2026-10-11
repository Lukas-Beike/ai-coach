"""Enumerations that name canonical concepts without provider-specific payloads."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Final


class ProviderId(StrEnum):
    INTERVALS = "intervals"
    GARMIN = "garmin"


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
}
