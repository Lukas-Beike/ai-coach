"""Vocabulary and German label contracts for the canonical package."""

from __future__ import annotations

import re
import unittest

from backend.canonical.labels import SPORT_LABELS_DE, sport_label_de
from backend.canonical.vocabulary import (
    CategoricalDomain,
    Environment,
    LoadModel,
    MetricKind,
    ObservationAggregation,
    ProjectionState,
    ProviderId,
    RecordingOrigin,
    SleepKind,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
    ZonePercentBasis,
)

SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


class CanonicalVocabularyTests(unittest.TestCase):
    def test_provider_identifiers_are_stable(self) -> None:
        self.assertEqual(
            {"INTERVALS": "intervals", "GARMIN": "garmin", "WAHOO": "wahoo"},
            {member.name: member.value for member in ProviderId},
        )

    def test_source_kinds_name_every_provenance_category(self) -> None:
        self.assertEqual(
            [
                "provider_reported",
                "device_measured",
                "derived",
                "ai_estimate",
                "athlete_entered",
                "profile",
            ],
            [member.value for member in SourceKind],
        )

    def test_recording_origins_and_environments_are_snake_case(self) -> None:
        for enum_type in (RecordingOrigin, Environment, LoadModel, Sport):
            for member in enum_type:
                with self.subTest(enum=enum_type.__name__, member=member.name):
                    self.assertRegex(member.value, SNAKE_CASE)

    def test_recording_origins_cover_known_device_apps(self) -> None:
        self.assertEqual(
            {"garmin", "wahoo", "strava", "zwift", "manual", "upload", "unknown"},
            {member.value for member in RecordingOrigin},
        )

    def test_environment_and_load_model_members(self) -> None:
        self.assertEqual(
            {"outdoor", "indoor", "virtual", "unknown"},
            {member.value for member in Environment},
        )
        self.assertEqual(
            {
                "intervals_training_load",
                "garmin_training_load",
                "tss",
                "trimp",
                "unknown",
            },
            {member.value for member in LoadModel},
        )

    def test_every_metric_kind_carries_its_canonical_unit(self) -> None:
        self.assertEqual(
            {
                "weight": "kg",
                "body_fat": "%",
                "ftp": "W",
                "threshold_hr": "bpm",
                "max_hr": "bpm",
                "resting_hr": "bpm",
                "hrv_rmssd": "ms",
                "hrv_sdnn": "ms",
                "hrv_weekly_average": "ms",
                "sleep_duration": "s",
                "sleep_score": "score",
                "vo2max": "ml/kg/min",
                "threshold_pace": "m/s",
                "body_battery": "score",
                "readiness": "score",
                "ctl": "load",
                "atl": "load",
                "training_load": "load",
                "form": "load",
                "eftp": "W",
                "run_threshold_power": "W",
                "daily_energy_total": "kcal",
                "daily_energy_active": "kcal",
                "steps": "count",
                "floors": "count",
                "stress": "score",
                "race_prediction_5k": "s",
                "race_prediction_10k": "s",
                "race_prediction_half": "s",
                "race_prediction_full": "s",
                "endurance_score": "score",
                "daily_energy_resting": "kcal",
                "body_battery_charged": "score",
                "body_battery_drained": "score",
                "acute_load": "load",
                "chronic_load": "load",
                "acute_chronic_ratio": "ratio",
                "load_balance_aerobic_low": "load",
                "load_balance_aerobic_low_target_min": "load",
                "load_balance_aerobic_low_target_max": "load",
                "load_balance_aerobic_high": "load",
                "load_balance_aerobic_high_target_min": "load",
                "load_balance_aerobic_high_target_max": "load",
                "load_balance_anaerobic": "load",
                "load_balance_anaerobic_target_min": "load",
                "load_balance_anaerobic_target_max": "load",
                "running_tolerance": "unknown",
                "endurance_score_group_average": "score",
                "endurance_score_group_max": "score",
                "subjective_fatigue": "rating",
                "subjective_soreness": "rating",
                "subjective_stress": "rating",
                "subjective_mood": "rating",
            },
            {kind.value: kind.unit for kind in MetricKind},
        )

    def test_schema_v15_vocabularies_are_stable(self) -> None:
        expected = {
            ObservationAggregation: ["sample", "total", "mean", "minimum", "maximum"],
            CategoricalDomain: ["training_status", "readiness_level", "hrv_status"],
            SleepKind: ["night", "unknown"],
            ZoneConfigurationMetric: ["heart_rate", "power", "pace"],
            ZonePercentBasis: ["threshold", "maximum", "reserve"],
            ProjectionState: ["active", "retired"],
        }
        for enum_type, values in expected.items():
            with self.subTest(enum=enum_type.__name__):
                self.assertEqual(values, [member.value for member in enum_type])

    def test_metric_kind_identifiers_are_snake_case(self) -> None:
        for kind in MetricKind:
            with self.subTest(kind=kind.name):
                self.assertRegex(kind.value, SNAKE_CASE)

    def test_every_sport_has_a_german_label(self) -> None:
        self.assertEqual(set(Sport), set(SPORT_LABELS_DE))
        for sport in Sport:
            with self.subTest(sport=sport.name):
                self.assertTrue(sport_label_de(sport).strip())

    def test_sport_labels_are_german_display_text(self) -> None:
        self.assertEqual("Radfahren", sport_label_de(Sport.RIDE))
        self.assertEqual("Laufen", sport_label_de(Sport.RUN))
        self.assertEqual("Schwimmen", sport_label_de(Sport.SWIM))
        self.assertEqual("Sonstiges", sport_label_de(Sport.OTHER))

    def test_sport_label_lookup_accepts_stored_text(self) -> None:
        self.assertEqual("Laufen", sport_label_de("run"))

    def test_sport_label_lookup_rejects_unknown_sport(self) -> None:
        with self.assertRaises(ValueError):
            sport_label_de("curling")


if __name__ == "__main__":
    unittest.main()
