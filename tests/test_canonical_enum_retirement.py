"""Persisted vocabulary values are never removed without a retirement mapping.

Canonical tables store enum values as text, and a stored row keeps its value after
the code changes. This module pins the values of the StrEnum classes in
``backend.canonical.vocabulary`` as they were when the snapshot was taken. A value
may leave an enum only after it is listed in ``RETIRED_VALUES`` with the current
value that replaces it in stored rows. Until then removing it fails the test.
Adding values is always allowed; a new enum must be added to SNAPSHOT.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from backend.canonical import vocabulary

SNAPSHOT: Final[Mapping[str, frozenset[str]]] = {
    "ProviderId": frozenset({"intervals", "garmin", "wahoo"}),
    "SourceKind": frozenset(
        {
            "provider_reported",
            "device_measured",
            "derived",
            "ai_estimate",
            "athlete_entered",
            "profile",
        }
    ),
    "RecordingOrigin": frozenset(
        {"garmin", "wahoo", "strava", "zwift", "manual", "upload", "unknown"}
    ),
    "DeviceType": frozenset({"watch", "bike_computer", "chest_strap", "power_meter"}),
    "Sport": frozenset(
        {
            "ride",
            "run",
            "swim",
            "walk",
            "hike",
            "strength",
            "row",
            "nordic_ski",
            "alpine_ski",
            "yoga",
            "other",
        }
    ),
    "Environment": frozenset({"outdoor", "indoor", "virtual", "unknown"}),
    "LoadModel": frozenset(
        {
            "intervals_training_load",
            "garmin_training_load",
            "trimp",
            "tss",
            "unknown",
        }
    ),
    "MetricKind": frozenset(
        {
            "weight",
            "body_fat",
            "ftp",
            "threshold_hr",
            "max_hr",
            "resting_hr",
            "hrv_rmssd",
            "hrv_sdnn",
            "sleep_duration",
            "sleep_score",
            "vo2max",
            "threshold_pace",
            "body_battery",
            "readiness",
            "ctl",
            "atl",
            "training_load",
            "form",
            "eftp",
            "run_threshold_power",
            "daily_energy_total",
            "daily_energy_active",
            "steps",
            "floors",
            "stress",
            "race_prediction_5k",
            "race_prediction_10k",
            "race_prediction_half",
            "race_prediction_full",
            "endurance_score",
            "daily_energy_resting",
            "body_battery_charged",
            "body_battery_drained",
            "acute_load",
            "chronic_load",
            "acute_chronic_ratio",
            "load_balance_aerobic_low",
            "load_balance_aerobic_low_target_min",
            "load_balance_aerobic_low_target_max",
            "load_balance_aerobic_high",
            "load_balance_aerobic_high_target_min",
            "load_balance_aerobic_high_target_max",
            "load_balance_anaerobic",
            "load_balance_anaerobic_target_min",
            "load_balance_anaerobic_target_max",
            "running_tolerance",
            "endurance_score_group_average",
            "endurance_score_group_max",
            "subjective_fatigue",
            "subjective_soreness",
            "subjective_stress",
            "subjective_mood",
        }
    ),
    "ObservationAggregation": frozenset(
        {"sample", "mean", "minimum", "maximum", "total"}
    ),
    "CategoricalDomain": frozenset(
        {"training_status", "hrv_status", "readiness_level"}
    ),
    "SleepKind": frozenset({"night", "unknown"}),
    "ZoneConfigurationMetric": frozenset({"heart_rate", "power", "pace"}),
    "ZonePercentBasis": frozenset({"threshold", "maximum", "reserve"}),
    "ProjectionState": frozenset({"active", "retired"}),
    "ProviderRecordState": frozenset({"active", "deleted"}),
    "ActivityRecordState": frozenset({"active", "deleted", "invalid"}),
    "ActivityLinkKind": frozenset({"single", "exact", "heuristic", "confirmed"}),
    "ActivitySessionState": frozenset({"active", "hidden", "duplicate", "deleted"}),
    "RemoteEntityKind": frozenset(
        {"library_workout", "planned_unit", "competition", "observation"}
    ),
    "RemoteLinkState": frozenset({"pending", "synced"}),
    "ActivityDetailKind": frozenset(
        {"streams", "laps", "heart_rate_zones", "power_zones"}
    ),
    "ActivityDetailOrigin": frozenset({"fetch", "legacy_backfill"}),
    "StreamChannel": frozenset(
        {
            "time_s",
            "distance_m",
            "altitude_m",
            "grade_pct",
            "speed_mps",
            "power_w",
            "heart_rate_bpm",
            "cadence_rpm",
            "temperature_c",
            "moving",
        }
    ),
    "StreamResolution": frozenset({"full", "downsampled"}),
    "LapKind": frozenset({"lap", "work", "recovery", "warmup", "cooldown"}),
    "LapSource": frozenset({"provider_intervals", "device_laps", "splits"}),
    "ZoneMetric": frozenset({"heart_rate", "power"}),
    "ZoneBoundarySource": frozenset({"provider_reported", "profile", "unknown"}),
}

# Enum name -> {retired value: current value that replaces it in stored rows}.
# Empty: no persisted value has been retired yet.
RETIRED_VALUES: Final[Mapping[str, Mapping[str, str]]] = {}


def _is_string_enum(obj: object) -> bool:
    return isinstance(obj, type) and issubclass(obj, StrEnum)


def _current_values(name: str) -> frozenset[str]:
    enum_class = getattr(vocabulary, name)
    return frozenset(str(member.value) for member in enum_class)


class EnumRetirementTests(unittest.TestCase):
    def test_every_pinned_enum_still_exists(self) -> None:
        for name in SNAPSHOT:
            with self.subTest(enum=name):
                self.assertTrue(_is_string_enum(getattr(vocabulary, name, None)))

    def test_every_vocabulary_enum_is_pinned(self) -> None:
        defined = {
            name
            for name, obj in vars(vocabulary).items()
            if _is_string_enum(obj) and obj.__module__ == vocabulary.__name__
        }
        self.assertEqual(set(), defined - SNAPSHOT.keys())

    def test_stored_values_are_still_members_or_retired(self) -> None:
        for name, stored in SNAPSHOT.items():
            with self.subTest(enum=name):
                retired = frozenset(RETIRED_VALUES.get(name, {}))
                missing = stored - retired - _current_values(name)
                self.assertEqual(
                    frozenset(), missing, "stored values were removed without a mapping"
                )

    def test_retired_values_map_to_current_members(self) -> None:
        for name, retired in RETIRED_VALUES.items():
            with self.subTest(enum=name):
                self.assertIn(name, SNAPSHOT)
                current = _current_values(name)
                for old, new in retired.items():
                    with self.subTest(retired=old):
                        self.assertIn(old, SNAPSHOT[name])
                        self.assertNotIn(old, current)
                        self.assertIn(new, current)


if __name__ == "__main__":
    unittest.main()
