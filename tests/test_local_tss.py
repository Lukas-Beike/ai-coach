"""Local TSS-scale session load (card M6): worked examples and dated thresholds.

Expected values are hand-worked from the card's formulas, not recomputed the way
the code computes them:

* power: NP 230 W, FTP 250 W, 70 min -> IF 0.92, 70/60 × 0.8464 × 100 = 98.75;
* pace: 45 min at 3.5 m/s grade-adjusted, threshold 4.0 m/s -> IF 0.875,
  0.75 × 0.765625 × 100 = 57.42;
* heart rate: rest 50, max 190, threshold 170, average 150 bpm for 90 min ->
  HRr 0.7143 and 0.8571, TRIMP 162.14 vs 170.65 for the threshold hour -> 95.01.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from typing import Any

from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
)
from backend.performance.local_tss import (
    HEART_RATE_BRANCH,
    PACE_BRANCH,
    POWER_BRANCH,
    DatedThresholds,
    LocalLoad,
    SessionThresholds,
    Threshold,
    session_loads,
    session_local_load,
)

DAY = date(2026, 6, 1)


def _threshold(value: float, source: str = "garmin") -> Threshold:
    return Threshold(value, source, DAY)


def _summary(**values: Any) -> dict[str, Any]:
    return {
        "id": "act_1",
        "sport": "ride",
        "started_at": "2026-06-01T06:00:00+00:00",
        "started_at_local": "2026-06-01T08:00:00",
        **values,
    }


def _load(summary: dict[str, Any], thresholds: SessionThresholds) -> LocalLoad:
    result = session_local_load(summary, thresholds)
    assert isinstance(result, LocalLoad), result
    return result


def _observation(
    kind: MetricKind,
    value: float,
    day: date,
    *,
    provider: ProviderId = ProviderId.GARMIN,
    sport: Sport | None = Sport.RIDE,
) -> Observation:
    return Observation(
        kind=kind,
        value=MetricValue(value, kind.unit),
        observed_on=day,
        observed_at=None,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=f"{provider.value}:{kind.value}:{day}",
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=datetime(2026, 6, 1, tzinfo=UTC),
            label=None,
        ),
        sport=sport,
    )


class SessionLoadWorkedExampleTests(unittest.TestCase):
    def test_power_branch_matches_the_card_example(self) -> None:
        load = _load(
            _summary(normalized_power=230.0, moving_duration_s=4200.0),
            SessionThresholds(ftp=_threshold(250.0)),
        )
        self.assertEqual(load.branch, POWER_BRANCH)
        self.assertAlmostEqual(load.load, 98.75, places=2)
        self.assertAlmostEqual(load.intensity_pct or 0, 92.0, places=6)

    def test_one_hour_at_ftp_is_one_hundred(self) -> None:
        load = _load(
            _summary(normalized_power=250.0, moving_duration_s=3600.0),
            SessionThresholds(ftp=_threshold(250.0)),
        )
        self.assertAlmostEqual(load.load, 100.0, places=9)

    def test_pace_branch_uses_grade_adjusted_speed(self) -> None:
        load = _load(
            _summary(
                sport="run",
                moving_duration_s=2700.0,
                grade_adjusted_speed_mps=3.5,
                avg_speed_mps=3.0,
            ),
            SessionThresholds(threshold_pace=_threshold(4.0)),
        )
        self.assertEqual(load.branch, PACE_BRANCH)
        self.assertAlmostEqual(load.load, 57.42, places=2)
        self.assertIsNone(load.intensity_pct)
        self.assertEqual(load.details["inputs"]["pace_basis"], "grade_adjusted_speed")

    def test_pace_branch_marks_flat_average_speed(self) -> None:
        load = _load(
            _summary(sport="run", moving_duration_s=2700.0, avg_speed_mps=3.5),
            SessionThresholds(threshold_pace=_threshold(4.0)),
        )
        self.assertAlmostEqual(load.load, 57.42, places=2)
        self.assertEqual(load.details["inputs"]["pace_basis"], "average_speed")

    def test_heart_rate_branch_matches_the_hand_example(self) -> None:
        load = _load(
            _summary(sport="hike", moving_duration_s=5400.0, avg_hr=150.0),
            SessionThresholds(
                resting_hr=_threshold(50.0),
                threshold_hr=_threshold(170.0),
                max_hr=_threshold(190.0),
            ),
        )
        self.assertEqual(load.branch, HEART_RATE_BRANCH)
        self.assertAlmostEqual(load.load, 95.01, places=2)
        self.assertIsNone(load.intensity_pct)

    def test_one_hour_at_threshold_heart_rate_is_one_hundred(self) -> None:
        load = _load(
            _summary(moving_duration_s=3600.0, avg_hr=170.0),
            SessionThresholds(
                resting_hr=_threshold(50.0),
                threshold_hr=_threshold(170.0),
                max_hr=_threshold(190.0),
            ),
        )
        self.assertAlmostEqual(load.load, 100.0, places=9)

    def test_power_wins_over_heart_rate(self) -> None:
        load = _load(
            _summary(normalized_power=230.0, moving_duration_s=4200.0, avg_hr=150.0),
            SessionThresholds(
                ftp=_threshold(250.0),
                resting_hr=_threshold(50.0),
                threshold_hr=_threshold(170.0),
                max_hr=_threshold(190.0),
            ),
        )
        self.assertEqual(load.branch, POWER_BRANCH)

    def test_missing_ftp_falls_through_to_heart_rate(self) -> None:
        load = _load(
            _summary(normalized_power=230.0, moving_duration_s=3600.0, avg_hr=170.0),
            SessionThresholds(
                resting_hr=_threshold(50.0),
                threshold_hr=_threshold(170.0),
                max_hr=_threshold(190.0),
            ),
        )
        self.assertEqual(load.branch, HEART_RATE_BRANCH)

    def test_provider_load_is_never_used(self) -> None:
        result = session_local_load(
            _summary(
                moving_duration_s=3600.0,
                provider_training_load=80.0,
                training_load=80.0,
                provider_intensity=90.0,
            ),
            SessionThresholds(ftp=_threshold(250.0)),
        )
        self.assertEqual(result, "no_inputs")

    def test_walking_has_no_load(self) -> None:
        result = session_local_load(
            _summary(sport="walk", moving_duration_s=3600.0, avg_hr=110.0),
            SessionThresholds(
                resting_hr=_threshold(50.0),
                threshold_hr=_threshold(170.0),
                max_hr=_threshold(190.0),
            ),
        )
        self.assertEqual(result, "sport_without_load")

    def test_strength_has_no_load(self) -> None:
        result = session_local_load(
            _summary(sport="strength", moving_duration_s=3600.0, avg_hr=120.0),
            SessionThresholds(
                resting_hr=_threshold(50.0),
                threshold_hr=_threshold(170.0),
                max_hr=_threshold(190.0),
            ),
        )
        self.assertEqual(result, "sport_without_load")

    def test_reasons_for_missing_inputs(self) -> None:
        self.assertEqual(
            session_local_load(
                _summary(normalized_power=230.0, moving_duration_s=3600.0),
                SessionThresholds(),
            ),
            "no_ftp",
        )
        self.assertEqual(
            session_local_load(
                _summary(normalized_power=600.0, moving_duration_s=3600.0),
                SessionThresholds(ftp=_threshold(250.0)),
            ),
            "implausible_intensity",
        )
        self.assertEqual(
            session_local_load(
                _summary(avg_hr=200.0, moving_duration_s=3600.0),
                SessionThresholds(
                    resting_hr=_threshold(50.0),
                    threshold_hr=_threshold(170.0),
                    max_hr=_threshold(190.0),
                ),
            ),
            "heart_rate_outside_reserve",
        )
        self.assertEqual(
            session_local_load(_summary(normalized_power=230.0), SessionThresholds()),
            "no_duration",
        )

    def test_fingerprint_follows_inputs_and_thresholds(self) -> None:
        summary = _summary(normalized_power=230.0, moving_duration_s=4200.0)
        first = _load(summary, SessionThresholds(ftp=_threshold(250.0)))
        same = _load(summary, SessionThresholds(ftp=_threshold(250.0)))
        other_ftp = _load(summary, SessionThresholds(ftp=_threshold(260.0)))
        other_source = _load(summary, SessionThresholds(ftp=_threshold(250.0, "local")))
        self.assertEqual(first.fingerprint, same.fingerprint)
        self.assertNotEqual(first.fingerprint, other_ftp.fingerprint)
        self.assertNotEqual(first.fingerprint, other_source.fingerprint)
        self.assertRegex(first.fingerprint, r"^[0-9a-f]{64}$")


def _local_ftp(value: float, valid_from: date) -> ZoneConfiguration:
    return ZoneConfiguration(
        metric=ZoneConfigurationMetric.POWER,
        sport=Sport.RIDE,
        environment=None,
        valid_from=valid_from,
        valid_until=None,
        threshold=value,
        maximum=None,
        resting=None,
        limits=(140.0, 190.0, 225.0, 265.0, 305.0),
        percent_limits=None,
        percent_basis=None,
        provenance=Provenance(
            provider=None,
            source_kind=SourceKind.ATHLETE_ENTERED,
            source_record_id=None,
            recorded_by=RecordingOrigin.MANUAL,
            retrieved_at=None,
            label=None,
        ),
    )


def _found(threshold: Threshold | None) -> Threshold:
    assert threshold is not None
    return threshold


class DatedThresholdTests(unittest.TestCase):
    def test_threshold_in_effect_on_the_session_day(self) -> None:
        thresholds = DatedThresholds(
            [
                _observation(MetricKind.FTP, 240.0, date(2026, 3, 1)),
                _observation(MetricKind.FTP, 260.0, date(2026, 5, 1)),
            ]
        )
        april = _found(
            thresholds.threshold(MetricKind.FTP, Sport.RIDE, date(2026, 4, 1))
        )
        june = _found(
            thresholds.threshold(MetricKind.FTP, Sport.RIDE, date(2026, 6, 1))
        )
        self.assertEqual((april.value, april.after_session), (240.0, False))
        self.assertEqual((june.value, june.observed_on), (260.0, date(2026, 5, 1)))

    def test_session_before_any_threshold_takes_the_earliest_later_one(self) -> None:
        thresholds = DatedThresholds(
            [
                _observation(MetricKind.FTP, 240.0, date(2026, 3, 1)),
                _observation(MetricKind.FTP, 260.0, date(2026, 5, 1)),
            ]
        )
        found = _found(
            thresholds.threshold(MetricKind.FTP, Sport.RIDE, date(2025, 1, 1))
        )
        self.assertEqual(
            (found.value, found.observed_on, found.after_session),
            (240.0, date(2026, 3, 1), True),
        )

    def test_garmin_threshold_older_than_its_age_limit_is_not_current(self) -> None:
        thresholds = DatedThresholds(
            [_observation(MetricKind.FTP, 240.0, date(2025, 1, 1))]
        )
        self.assertIsNone(
            thresholds.threshold(MetricKind.FTP, Sport.RIDE, date(2026, 1, 1))
        )

    def test_local_zone_configuration_wins_from_its_day(self) -> None:
        thresholds = DatedThresholds(
            [_observation(MetricKind.FTP, 240.0, date(2026, 3, 1))],
            [_local_ftp(255.0, date(2026, 4, 15))],
        )
        before = _found(
            thresholds.threshold(MetricKind.FTP, Sport.RIDE, date(2026, 4, 14))
        )
        after = _found(
            thresholds.threshold(MetricKind.FTP, Sport.RIDE, date(2026, 4, 15))
        )
        self.assertEqual((before.value, before.source), (240.0, "garmin"))
        self.assertEqual((after.value, after.source), (255.0, "local"))

    def test_resting_hr_from_the_last_week_garmin_first(self) -> None:
        thresholds = DatedThresholds(
            [],
            resting_hr=[
                _observation(
                    MetricKind.RESTING_HR, 48.0, date(2026, 5, 20), sport=None
                ),
                _observation(
                    MetricKind.RESTING_HR, 50.0, date(2026, 5, 28), sport=None
                ),
                _observation(
                    MetricKind.RESTING_HR,
                    46.0,
                    date(2026, 5, 31),
                    provider=ProviderId.INTERVALS,
                    sport=None,
                ),
            ],
        )
        found = _found(thresholds.resting_hr(date(2026, 6, 1)))
        self.assertEqual((found.value, found.source), (50.0, "garmin"))
        self.assertFalse(found.after_session)
        # Before any stored value: the earliest later one, flagged.
        early = _found(thresholds.resting_hr(date(2026, 5, 1)))
        self.assertEqual(
            (early.value, early.observed_on, early.after_session),
            (48.0, date(2026, 5, 20), True),
        )
        self.assertIsNone(thresholds.resting_hr(date(2026, 6, 10)))

    def test_session_loads_use_the_session_day(self) -> None:
        thresholds = DatedThresholds(
            [
                _observation(MetricKind.FTP, 250.0, date(2026, 3, 1)),
                _observation(MetricKind.FTP, 300.0, date(2026, 7, 1)),
            ]
        )
        loads = session_loads(
            [_summary(normalized_power=250.0, moving_duration_s=3600.0)], thresholds
        )
        load = loads["act_1"]
        assert isinstance(load, LocalLoad)
        self.assertAlmostEqual(load.load, 100.0, places=9)
        self.assertNotIn("threshold_after_session", load.details)


if __name__ == "__main__":
    unittest.main()
