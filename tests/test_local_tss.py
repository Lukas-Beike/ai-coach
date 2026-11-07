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
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    Environment,
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
    CalibrationPair,
    DatedThresholds,
    LocalLoad,
    RpeCalibration,
    RpeCalibrations,
    SessionRating,
    SessionThresholds,
    Threshold,
    rated_sessions,
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


def _load(
    summary: dict[str, Any], thresholds: SessionThresholds, sex: str | None = None
) -> LocalLoad:
    result = session_local_load(summary, thresholds, sex=sex)
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

    def test_heart_rate_branch_uses_the_profile_sex_constants(self) -> None:
        # Card M6 v3: 90 min at HR 150 (rest 50, threshold 170, max 190).
        summary = _summary(sport="hike", moving_duration_s=5400.0, avg_hr=150.0)
        thresholds = SessionThresholds(
            resting_hr=_threshold(50.0),
            threshold_hr=_threshold(170.0),
            max_hr=_threshold(190.0),
        )
        male = _load(summary, thresholds, "male")
        female = _load(summary, thresholds, "female")
        unset = _load(summary, thresholds)
        self.assertAlmostEqual(male.load, 95.01, places=2)
        self.assertAlmostEqual(female.load, 98.47, places=2)
        self.assertAlmostEqual(unset.load, male.load, places=12)
        self.assertEqual(female.details["inputs"]["sex"], "female")
        self.assertNotIn("sex_assumed", male.details["inputs"])
        self.assertEqual(unset.details["inputs"]["sex"], "male")
        self.assertTrue(unset.details["inputs"]["sex_assumed"])
        # A changed or newly saved sex changes the fingerprint, so the
        # backfill recomputes the stored value.
        self.assertEqual(
            len({male.fingerprint, female.fingerprint, unset.fingerprint}), 3
        )

    def test_unknown_sex_takes_the_assumed_male_constants(self) -> None:
        load = _load(
            _summary(moving_duration_s=3600.0, avg_hr=170.0),
            SessionThresholds(
                resting_hr=_threshold(50.0),
                threshold_hr=_threshold(170.0),
                max_hr=_threshold(190.0),
            ),
            "",
        )
        self.assertTrue(load.details["inputs"]["sex_assumed"])

    def test_power_branch_ignores_the_sex(self) -> None:
        summary = _summary(normalized_power=230.0, moving_duration_s=4200.0)
        thresholds = SessionThresholds(ftp=_threshold(250.0))
        self.assertEqual(
            _load(summary, thresholds, "female").fingerprint,
            _load(summary, thresholds).fingerprint,
        )

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

    def test_walking_uses_the_heart_rate_branch(self) -> None:
        # HRr 60/140, threshold HRr 120/140: 50 x e^(-1.92 x 60/140) = 21.96.
        load = _load(
            _summary(sport="walk", moving_duration_s=3600.0, avg_hr=110.0),
            SessionThresholds(
                resting_hr=_threshold(50.0),
                threshold_hr=_threshold(170.0),
                max_hr=_threshold(190.0),
            ),
        )
        self.assertEqual(load.branch, "heart_rate")
        self.assertAlmostEqual(load.load, 21.9588, places=3)

    def test_strength_reads_only_the_session_rpe_branch(self) -> None:
        heart_rate = SessionThresholds(
            resting_hr=_threshold(50.0),
            threshold_hr=_threshold(170.0),
            max_hr=_threshold(190.0),
        )
        strength = _summary(sport="strength", moving_duration_s=3600.0, avg_hr=120.0)
        self.assertEqual(session_local_load(strength, heart_rate), "no_rating")
        rating = SessionRating(au=300.0, rpe=5.0, rpe_scale="garmin_rpe")
        self.assertEqual(
            session_local_load(strength, heart_rate, rating=rating), "not_calibrated"
        )
        calibration = RpeCalibration(
            0.2, 20, date(2025, 6, 2), DAY, (4.0, 6.0), {"garmin": 20}
        )
        load = session_local_load(
            strength, heart_rate, rating=rating, calibration=calibration
        )
        assert isinstance(load, LocalLoad)
        self.assertEqual((load.branch, load.load), ("session_rpe", 60.0))
        self.assertIsNone(load.intensity_pct)
        self.assertEqual(load.details["calibration"]["pairs"], 20)

    def test_yoga_and_alpine_ski_have_no_load(self) -> None:
        for sport in ("yoga", "alpine_ski"):
            self.assertEqual(
                session_local_load(
                    _summary(sport=sport, moving_duration_s=3600.0, avg_hr=120.0),
                    SessionThresholds(),
                ),
                "sport_without_load",
            )

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


def _local_ftp(
    value: float, valid_from: date, environment: Environment | None = None
) -> ZoneConfiguration:
    return ZoneConfiguration(
        metric=ZoneConfigurationMetric.POWER,
        sport=Sport.RIDE,
        environment=environment,
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

    def test_intervals_thresholds_are_ignored_for_every_session_day(self) -> None:
        thresholds = DatedThresholds(
            [
                _observation(
                    MetricKind.FTP,
                    300.0,
                    date(2026, 5, 1),
                    provider=ProviderId.INTERVALS,
                ),
                _observation(MetricKind.FTP, 240.0, date(2026, 3, 1)),
                _observation(
                    MetricKind.THRESHOLD_HR,
                    170.0,
                    date(2026, 5, 1),
                    provider=ProviderId.INTERVALS,
                ),
            ]
        )
        june = _found(
            thresholds.threshold(MetricKind.FTP, Sport.RIDE, date(2026, 6, 1))
        )
        early = _found(
            thresholds.threshold(MetricKind.FTP, Sport.RIDE, date(2025, 1, 1))
        )
        self.assertEqual((june.value, june.source), (240.0, "garmin"))
        self.assertEqual((early.value, early.after_session), (240.0, True))
        self.assertIsNone(
            thresholds.threshold(MetricKind.THRESHOLD_HR, Sport.RIDE, date(2026, 6, 1))
        )

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

    def test_indoor_ride_uses_the_local_indoor_ftp(self) -> None:
        # FTP 280 W outdoors, 260 W indoors: 1 h at NP 260 W indoors is 100 TSS.
        thresholds = DatedThresholds(
            [],
            [
                _local_ftp(280.0, date(2026, 1, 1)),
                _local_ftp(260.0, date(2026, 1, 1), Environment.INDOOR),
            ],
        )
        summary = _summary(
            normalized_power=260.0, moving_duration_s=3600.0, environment="virtual"
        )
        loads = session_loads([summary], thresholds)
        load = loads["act_1"]
        assert isinstance(load, LocalLoad)
        self.assertAlmostEqual(load.load, 100.0, places=9)
        outdoor = session_loads([{**summary, "environment": "outdoor"}], thresholds)
        outdoor_load = outdoor["act_1"]
        assert isinstance(outdoor_load, LocalLoad)
        # 260/280 = 0.9286, squared 0.8622 -> 86.22 TSS.
        self.assertAlmostEqual(outdoor_load.load, 86.22, places=2)

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


def _pair(day: date, rpe: float, ratio: float) -> CalibrationPair:
    return CalibrationPair(day, rpe, ratio, "garmin")


def _ride(
    index: int,
    day: date,
    *,
    rpe_label: str = "Garmin Connect",
    rpe: float = 5.0,
    np: float = 250.0,
    minutes: float = 60.0,
) -> dict:
    """By default a 60-min ride at NP 250 W (100 TSS at FTP 250), RPE 5 (300 AU)."""
    return {
        "id": f"act_r{index}",
        "sport": "ride",
        "started_at": f"{day.isoformat()}T06:00:00+00:00",
        "started_at_local": f"{day.isoformat()}T08:00:00",
        "moving_duration_s": minutes * 60,
        "elapsed_duration_s": minutes * 60,
        "normalized_power": np,
        "rpe": rpe,
        "sources": {"rpe": rpe_label},
    }


def _strength(day: date, rpe: float | None = 6.0) -> dict[str, Any]:
    """45 min of strength; with RPE 6 that is 270 AU."""
    value: dict[str, Any] = {
        "id": "act_gym",
        "sport": "strength",
        "started_at": f"{day.isoformat()}T17:00:00+00:00",
        "started_at_local": f"{day.isoformat()}T19:00:00",
        "elapsed_duration_s": 2700.0,
        "sources": {},
    }
    if rpe is not None:
        value.update(rpe=rpe, sources={"rpe": "Garmin Connect"})
    return value


class SessionRpeCalibrationTests(unittest.TestCase):
    """Strength TSS = sRPE AU x median TSS/AU of 365 days of rated rides (v2)."""

    def setUp(self) -> None:
        self.thresholds = DatedThresholds(
            [_observation(MetricKind.FTP, 250.0, date(2026, 5, 1))]
        )

    def _loads(self, rides: list[dict[str, Any]], gym: dict[str, Any]) -> Any:
        return session_loads([*rides, gym], self.thresholds)

    def test_twenty_garmin_rated_rides_calibrate_strength(self) -> None:
        rides = [_ride(i, DAY - timedelta(days=i)) for i in range(20)]
        load = self._loads(rides, _strength(DAY))["act_gym"]
        assert isinstance(load, LocalLoad), load
        # 100 TSS / 300 AU per ride; 270 AU x 1/3 = 90 TSS.
        self.assertAlmostEqual(load.load, 90.0, places=6)
        self.assertEqual(load.branch, "session_rpe")
        self.assertEqual(load.details["calibration"]["pairs"], 20)

    def test_fewer_than_twenty_pairs_are_not_calibrated(self) -> None:
        rides = [_ride(i, DAY - timedelta(days=i)) for i in range(19)]
        self.assertEqual(
            self._loads(rides, _strength(DAY))["act_gym"], "not_calibrated"
        )

    def test_intervals_relayed_ratings_do_not_calibrate(self) -> None:
        rides = [
            _ride(i, DAY - timedelta(days=i), rpe_label="Intervals.icu")
            for i in range(25)
        ]
        self.assertEqual(
            self._loads(rides, _strength(DAY))["act_gym"], "not_calibrated"
        )

    def test_local_feedback_calibrates_and_rates(self) -> None:
        rides = [_ride(i, DAY - timedelta(days=i)) for i in range(20)]
        for ride in rides:
            ride.pop("rpe")
        feedback = {ride["id"]: {"session_rpe": 4.0} for ride in rides}
        feedback["act_gym"] = {"session_rpe": 5.0}
        loads = session_loads(
            [*rides, _strength(DAY, rpe=None)], self.thresholds, feedback
        )
        load = loads["act_gym"]
        assert isinstance(load, LocalLoad), load
        # 100 TSS / 240 AU; 45 min x RPE 5 = 225 AU -> 93.75 TSS.
        self.assertAlmostEqual(load.load, 93.75, places=6)
        self.assertEqual(load.details["calibration"]["pairs_by_source"], {"local": 20})

    def test_pairs_older_than_365_days_drop_out(self) -> None:
        rides = [_ride(i, DAY - timedelta(days=365 + i)) for i in range(20)]
        self.assertEqual(
            self._loads(rides, _strength(DAY))["act_gym"], "not_calibrated"
        )
        calibrations = RpeCalibrations(
            [_pair(DAY - timedelta(days=364), 5.0, 0.5)] * 20
        )
        found = calibrations.on(DAY, 5.0)
        assert found is not None
        self.assertEqual(
            (found.factor, found.window_start), (0.5, DAY - timedelta(days=364))
        )

    def test_median_resists_an_outlier(self) -> None:
        pairs = [_pair(DAY, 5.0, 0.3)] * 20 + [_pair(DAY, 5.0, 5.0)]
        found = RpeCalibrations(pairs).on(DAY, 5.0)
        assert found is not None
        self.assertEqual(found.factor, 0.3)

    def test_rpe_zero_gives_zero_and_unbounded_rides_do_not_calibrate(self) -> None:
        rides = [_ride(i, DAY - timedelta(days=i)) for i in range(20)]
        load = self._loads(rides, _strength(DAY, rpe=0.0))["act_gym"]
        assert isinstance(load, LocalLoad), load
        self.assertEqual(load.load, 0.0)
        # A 200 h unstopped recording is rejected by the store, so it never counts.
        rides[0]["moving_duration_s"] = 720_000.0
        self.assertEqual(
            self._loads(rides, _strength(DAY))["act_gym"], "not_calibrated"
        )

    def test_easy_pairs_no_longer_inflate_hard_strength(self) -> None:
        # Card M6 v4 worked example: 30 easy rides (60 min, IF 0.65, RPE 2)
        # and 22 threshold rides (50 min, IF 0.90, RPE 7).
        easy = [_ride(i, DAY - timedelta(days=i), rpe=2.0, np=162.5) for i in range(30)]
        hard = [
            _ride(100 + i, DAY - timedelta(days=i), rpe=7.0, np=225.0, minutes=50)
            for i in range(22)
        ]
        gym = {**_strength(DAY, rpe=7.0), "elapsed_duration_s": 3600.0}
        load = self._loads([*easy, *hard], gym)["act_gym"]
        assert isinstance(load, LocalLoad), load
        # 67.5 TSS / 350 AU per threshold ride; 420 AU -> 81 TSS (v3: 147.9).
        self.assertAlmostEqual(load.load, 420 * 67.5 / 350, places=6)
        calibration = load.details["calibration"]
        self.assertEqual(calibration["rpe_band"], [6.0, 8.0])
        self.assertEqual(calibration["pairs"], 22)
        table = {row["rpe"]: row for row in calibration["by_rpe"]}
        self.assertAlmostEqual(table[2]["tss_per_au"], 42.25 / 120, places=6)
        self.assertNotIn(4, table)
        self.assertEqual(table[7]["pairs"], 22)

    def test_band_widens_to_two_then_gives_no_value(self) -> None:
        rides = [_ride(i, DAY - timedelta(days=i), rpe=3.0) for i in range(20)]
        load = self._loads(rides, _strength(DAY, rpe=5.0))["act_gym"]
        assert isinstance(load, LocalLoad), load
        self.assertEqual(load.details["calibration"]["rpe_band"], [3.0, 7.0])
        self.assertEqual(
            self._loads(rides, _strength(DAY, rpe=6.0))["act_gym"], "not_calibrated"
        )

    def test_pair_au_uses_the_tss_duration(self) -> None:
        # 60 min moving inside 90 min elapsed: 100 TSS over 60 min x RPE 5.
        rides = [
            {**_ride(i, DAY - timedelta(days=i)), "elapsed_duration_s": 5400.0}
            for i in range(20)
        ]
        load = self._loads(rides, _strength(DAY, rpe=5.0))["act_gym"]
        assert isinstance(load, LocalLoad), load
        self.assertAlmostEqual(load.details["calibration"]["tss_per_au"], 1 / 3)

    def test_rated_sessions_only_with_strength(self) -> None:
        rides = [_ride(i, DAY) for i in range(3)]
        walk = {**_ride(9, DAY), "id": "act_walk", "sport": "walk"}
        self.assertEqual(rated_sessions([*rides, walk]), [])
        gym = _strength(DAY)
        self.assertEqual(
            [item["id"] for item in rated_sessions([*rides, walk, gym])],
            ["act_r0", "act_r1", "act_r2", "act_gym"],
        )

    def test_unrated_strength_has_no_load(self) -> None:
        rides = [_ride(i, DAY - timedelta(days=i)) for i in range(20)]
        self.assertEqual(
            self._loads(rides, _strength(DAY, rpe=None))["act_gym"], "no_rating"
        )


if __name__ == "__main__":
    unittest.main()
