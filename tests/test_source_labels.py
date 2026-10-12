"""Exact legacy source labels for canonical observations."""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from backend.canonical.mapping import MappingResult
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance.source_policy import _is_athlete_level
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.providers.intervals_wellness_mapping import (
    map_intervals_athlete_thresholds,
    map_intervals_wellness,
)
from backend.providers.source_labels import (
    SourceView,
    _is_wellness_record,
    observation_source_label,
    provider_label,
)

OBSERVED_ON = date(2026, 10, 12)
RETRIEVED_AT = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
WELLNESS_RECORD_ID = OBSERVED_ON.isoformat()
ATHLETE_RECORD_ID = "athlete-1"
GARMIN_DAY = "2026-10-12"
ZONE = ZoneInfo("Europe/Berlin")

SAMPLE_VALUES: dict[MetricKind, float] = {
    MetricKind.WEIGHT: 80.0,
    MetricKind.BODY_FAT: 14.0,
    MetricKind.FTP: 250.0,
    MetricKind.THRESHOLD_HR: 165.0,
    MetricKind.MAX_HR: 190.0,
    MetricKind.VO2MAX: 58.0,
    MetricKind.THRESHOLD_PACE: 4.0,
    MetricKind.CTL: 45.0,
}


def _observation(
    kind: MetricKind,
    *,
    record_id: str | None,
    provider: ProviderId = ProviderId.INTERVALS,
    sport: Sport | None = None,
) -> Observation:
    return Observation(
        kind=kind,
        value=MetricValue(SAMPLE_VALUES[kind], kind.unit),
        observed_on=OBSERVED_ON,
        observed_at=None,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=record_id,
            recorded_by=RecordingOrigin.UNKNOWN,
            retrieved_at=RETRIEVED_AT,
            label=None,
        ),
        sport=sport,
    )


def _athlete_entered() -> Observation:
    return Observation(
        kind=MetricKind.WEIGHT,
        value=MetricValue(80.0, MetricKind.WEIGHT.unit),
        observed_on=OBSERVED_ON,
        observed_at=None,
        provenance=Provenance(
            provider=None,
            source_kind=SourceKind.ATHLETE_ENTERED,
            source_record_id=None,
            recorded_by=RecordingOrigin.MANUAL,
            retrieved_at=None,
            label=None,
        ),
    )


def _garmin(
    kind: MetricKind, record_id: str | None, sport: Sport | None = None
) -> Observation:
    return _observation(
        kind, record_id=record_id, provider=ProviderId.GARMIN, sport=sport
    )


def _only(result: MappingResult[Observation], kind: MetricKind) -> Observation:
    matches = [record for record in result.records if record.kind is kind]
    if len(matches) != 1:
        raise AssertionError(f"expected one {kind.value} record, got {len(matches)}")
    return matches[0]


class ProviderLabelTests(unittest.TestCase):
    def test_base_labels_apply_to_views_without_override(self) -> None:
        self.assertEqual(
            provider_label(ProviderId.INTERVALS, SourceView.CURRENT_METRIC),
            "Intervals.icu",
        )
        self.assertEqual(
            provider_label(ProviderId.INTERVALS, SourceView.ACTIVITY_DETAIL),
            "Intervals.icu",
        )
        self.assertEqual(
            provider_label(ProviderId.GARMIN, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect",
        )
        self.assertEqual(
            provider_label(ProviderId.GARMIN, SourceView.DAILY_HEALTH),
            "Garmin Connect",
        )

    def test_view_overrides_replace_the_base_label(self) -> None:
        self.assertEqual(
            provider_label(ProviderId.INTERVALS, SourceView.BODY_HISTORY),
            "Intervals.icu Wellness",
        )
        self.assertEqual(
            provider_label(ProviderId.INTERVALS, SourceView.SEASON_PREPARATION),
            "Intervals.icu recorded wellness",
        )
        self.assertEqual(
            provider_label(
                ProviderId.INTERVALS, SourceView.SEASON_PREPARATION_ACTIVITY
            ),
            "Intervals.icu recorded activities",
        )
        self.assertEqual(
            provider_label(ProviderId.GARMIN, SourceView.DUPLICATE), "Garmin"
        )
        self.assertEqual(
            provider_label(ProviderId.INTERVALS, SourceView.DUPLICATE),
            "Intervals.icu",
        )


class IntervalsSourceLabelTests(unittest.TestCase):
    def test_wellness_row_weight_is_wellness_in_current_metrics(self) -> None:
        observation = _observation(MetricKind.WEIGHT, record_id=WELLNESS_RECORD_ID)
        self.assertEqual(
            observation_source_label(observation, SourceView.CURRENT_METRIC),
            "Intervals.icu Wellness",
        )

    def test_athlete_record_weight_is_intervals_in_current_metrics(self) -> None:
        observation = _observation(MetricKind.WEIGHT, record_id=ATHLETE_RECORD_ID)
        self.assertEqual(
            observation_source_label(observation, SourceView.CURRENT_METRIC),
            "Intervals.icu",
        )

    def test_missing_record_id_is_not_a_wellness_row(self) -> None:
        observation = _observation(MetricKind.BODY_FAT, record_id=None)
        self.assertEqual(
            observation_source_label(observation, SourceView.CURRENT_METRIC),
            "Intervals.icu",
        )

    def test_body_history_labels_all_weight_and_body_fat_as_wellness(self) -> None:
        # Legacy body history reads wellness rows only, so it never splits them.
        for record_id in (WELLNESS_RECORD_ID, ATHLETE_RECORD_ID, None):
            for kind in (MetricKind.WEIGHT, MetricKind.BODY_FAT):
                with self.subTest(kind=kind, record_id=record_id):
                    observation = _observation(kind, record_id=record_id)
                    self.assertEqual(
                        observation_source_label(observation, SourceView.BODY_HISTORY),
                        "Intervals.icu Wellness",
                    )

    def test_split_kinds_use_the_base_label_in_other_views(self) -> None:
        observation = _observation(MetricKind.WEIGHT, record_id=WELLNESS_RECORD_ID)
        self.assertEqual(
            observation_source_label(observation, SourceView.DAILY_HEALTH),
            "Intervals.icu",
        )

    def test_body_history_ftp_is_labelled_as_the_provider(self) -> None:
        observation = _observation(MetricKind.FTP, record_id=ATHLETE_RECORD_ID)
        self.assertEqual(
            observation_source_label(observation, SourceView.BODY_HISTORY),
            "Intervals.icu",
        )

    def test_current_metric_ftp_uses_the_base_label(self) -> None:
        observation = _observation(MetricKind.FTP, record_id=ATHLETE_RECORD_ID)
        self.assertEqual(
            observation_source_label(observation, SourceView.CURRENT_METRIC),
            "Intervals.icu",
        )

    def test_general_threshold_hr_without_sport_is_labelled_allgemein(
        self,
    ) -> None:
        observation = _observation(MetricKind.THRESHOLD_HR, record_id=ATHLETE_RECORD_ID)
        self.assertEqual(
            observation_source_label(observation, SourceView.CURRENT_METRIC),
            "Intervals.icu (allgemein)",
        )

    def test_sport_threshold_hr_uses_the_base_label(self) -> None:
        observation = _observation(
            MetricKind.THRESHOLD_HR,
            record_id=ATHLETE_RECORD_ID,
            sport=Sport.RIDE,
        )
        self.assertEqual(
            observation_source_label(observation, SourceView.CURRENT_METRIC),
            "Intervals.icu",
        )

    def test_general_threshold_hr_outside_current_metrics_is_base(self) -> None:
        observation = _observation(MetricKind.THRESHOLD_HR, record_id=ATHLETE_RECORD_ID)
        self.assertEqual(
            observation_source_label(observation, SourceView.DAILY_HEALTH),
            "Intervals.icu",
        )

    def test_season_preparation_views_label_wellness_rows_as_recorded_wellness(
        self,
    ) -> None:
        observation = _observation(MetricKind.CTL, record_id=WELLNESS_RECORD_ID)
        for view in (
            SourceView.SEASON_PREPARATION,
            SourceView.SEASON_PREPARATION_ACTIVITY,
        ):
            with self.subTest(view=view):
                self.assertEqual(
                    observation_source_label(observation, view),
                    "Intervals.icu recorded wellness",
                )


class GarminSourceLabelTests(unittest.TestCase):
    def test_max_hr_from_heart_rate_zones_is_the_zone_note(self) -> None:
        observation = _garmin(
            MetricKind.MAX_HR, "heart_rate_zones:2026-10-12:0:ride", Sport.RIDE
        )
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect Herzfrequenzzonen",
        )

    def test_vo2max_from_max_metrics_is_the_max_metrics_note(self) -> None:
        observation = _garmin(
            MetricKind.VO2MAX, "max_metrics:2026-10-12:0:run", Sport.RUN
        )
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect max metrics",
        )

    def test_weight_note_has_no_sport(self) -> None:
        observation = _garmin(MetricKind.WEIGHT, "weight:2026-10-12")
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect Körpergewicht",
        )

    def test_cycling_ftp_note(self) -> None:
        observation = _garmin(MetricKind.FTP, "cycling_ftp:2026-10-12", Sport.RIDE)
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect FTP",
        )

    def test_cycling_ftp_history_uses_the_ftp_note(self) -> None:
        # Pinned behaviour: no legacy history label is known, so history rows reuse
        # the current FTP note. The pull request description flags this.
        observation = _garmin(
            MetricKind.FTP, "cycling_ftp_history:2026-10-12", Sport.RIDE
        )
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect FTP",
        )

    def test_running_ftp_note(self) -> None:
        observation = _garmin(
            MetricKind.FTP, "running_threshold:2026-10-12:0", Sport.RUN
        )
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect Lauf-Schwellenleistung",
        )

    def test_running_threshold_pace_note(self) -> None:
        observation = _garmin(
            MetricKind.THRESHOLD_PACE,
            "running_threshold:2026-10-12:0:speed",
            Sport.RUN,
        )
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect Lauf-Schwellenpace",
        )

    def test_running_threshold_heart_rate_note(self) -> None:
        observation = _garmin(
            MetricKind.THRESHOLD_HR,
            "running_threshold:2026-10-12:0:heartRate",
            Sport.RUN,
        )
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect Lauf-Schwellenpuls",
        )

    def test_cycling_threshold_heart_rate_note(self) -> None:
        observation = _garmin(
            MetricKind.THRESHOLD_HR,
            "running_threshold:2026-10-12:0:heartRateCycling",
            Sport.RIDE,
        )
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect Rad-Schwellenpuls",
        )

    def test_ftp_without_sport_has_no_note_and_uses_the_base_label(self) -> None:
        observation = _garmin(MetricKind.FTP, "cycling_ftp:2026-10-12")
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect",
        )

    def test_body_fat_has_no_note(self) -> None:
        observation = _garmin(MetricKind.BODY_FAT, "body_fat:2026-10-12")
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect",
        )

    def test_notes_only_apply_to_the_performance_note_view(self) -> None:
        observation = _garmin(
            MetricKind.MAX_HR, "heart_rate_zones:2026-10-12:0:ride", Sport.RIDE
        )
        self.assertEqual(
            observation_source_label(observation, SourceView.DAILY_HEALTH),
            "Garmin Connect",
        )
        self.assertEqual(
            observation_source_label(observation, SourceView.DUPLICATE),
            "Garmin",
        )

    def test_missing_record_id_has_no_section_note(self) -> None:
        observation = _garmin(MetricKind.MAX_HR, None, Sport.RIDE)
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect",
        )

    def test_unknown_section_falls_back_to_the_base_label(self) -> None:
        observation = _garmin(MetricKind.MAX_HR, "other_section:2026-10-12:0")
        self.assertEqual(
            observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
            "Garmin Connect",
        )

    def test_malformed_record_ids_fall_back_to_the_base_label(self) -> None:
        malformed_ids = (
            "heart_rate_zones",
            "heart_rate_zones:2026-1-1",
            "heart_rate_zones:2026-10-12x",
            "Heart:2026-10-12",
            "heart-rate:2026-10-12",
            ":2026-10-12",
        )
        for record_id in malformed_ids:
            with self.subTest(record_id=record_id):
                observation = _garmin(MetricKind.MAX_HR, record_id, Sport.RIDE)
                self.assertEqual(
                    observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
                    "Garmin Connect",
                )


class SourceRuleParityTests(unittest.TestCase):
    def test_wellness_rule_matches_the_performance_source_policy(self) -> None:
        samples = (
            _observation(MetricKind.WEIGHT, record_id=WELLNESS_RECORD_ID),
            _observation(MetricKind.WEIGHT, record_id=ATHLETE_RECORD_ID),
            _observation(MetricKind.WEIGHT, record_id=None),
        )
        for observation in samples:
            with self.subTest(record_id=observation.provenance.source_record_id):
                self.assertEqual(
                    _is_wellness_record(observation),
                    not _is_athlete_level(observation),
                )


class MapperRoundTripTests(unittest.TestCase):
    def test_intervals_mapper_output_keeps_the_wellness_athlete_split(self) -> None:
        wellness = map_intervals_wellness(
            [{"id": WELLNESS_RECORD_ID, "weight": 80.0}], retrieved_at=RETRIEVED_AT
        )
        athlete = map_intervals_athlete_thresholds(
            {"id": ATHLETE_RECORD_ID, "weight": 80.0},
            observed_on=OBSERVED_ON,
            retrieved_at=RETRIEVED_AT,
        )
        wellness_weight = _only(wellness, MetricKind.WEIGHT)
        athlete_weight = _only(athlete, MetricKind.WEIGHT)
        self.assertEqual(
            wellness_weight.provenance.source_record_id, WELLNESS_RECORD_ID
        )
        self.assertEqual(athlete_weight.provenance.source_record_id, ATHLETE_RECORD_ID)
        self.assertEqual(
            observation_source_label(wellness_weight, SourceView.CURRENT_METRIC),
            "Intervals.icu Wellness",
        )
        self.assertEqual(
            observation_source_label(athlete_weight, SourceView.CURRENT_METRIC),
            "Intervals.icu",
        )

    def test_garmin_mapper_output_gets_its_section_notes(self) -> None:
        result = map_garmin_health(
            {
                "weight": {
                    "calendarDate": GARMIN_DAY,
                    "weight": 72100,
                    "unitKey": "gram",
                },
                "max_metrics": {
                    "calendarDate": GARMIN_DAY,
                    "generic": {"vo2MaxPreciseValue": 58.0},
                },
                "running_threshold": {
                    "calendarDate": GARMIN_DAY,
                    "speed_and_heart_rate": {"speed": 3.6},
                },
            },
            zone=ZONE,
            retrieved_at=RETRIEVED_AT,
        )
        expectations = {
            MetricKind.WEIGHT: ("weight:", "Garmin Connect Körpergewicht"),
            MetricKind.VO2MAX: ("max_metrics:", "Garmin Connect max metrics"),
            MetricKind.THRESHOLD_PACE: (
                "running_threshold:",
                "Garmin Connect Lauf-Schwellenpace",
            ),
        }
        for kind, (prefix, label) in expectations.items():
            with self.subTest(kind=kind):
                observation = _only(result, kind)
                record_id = observation.provenance.source_record_id or ""
                self.assertTrue(record_id.startswith(prefix), record_id)
                self.assertEqual(
                    observation_source_label(observation, SourceView.PERFORMANCE_NOTE),
                    label,
                )


class FallbackTests(unittest.TestCase):
    def test_observation_without_provider_has_no_label(self) -> None:
        observation = _athlete_entered()
        for view in SourceView:
            with self.subTest(view=view):
                self.assertEqual(observation_source_label(observation, view), "")

    def test_every_provider_and_view_pair_yields_a_label(self) -> None:
        samples = (
            _observation(MetricKind.WEIGHT, record_id=WELLNESS_RECORD_ID),
            _garmin(MetricKind.MAX_HR, "heart_rate_zones:2026-10-12:0:ride"),
        )
        for observation in samples:
            for view in SourceView:
                with self.subTest(provider=observation.provenance.provider, view=view):
                    self.assertTrue(observation_source_label(observation, view))


if __name__ == "__main__":
    unittest.main()
