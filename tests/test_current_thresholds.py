"""One source-precedence resolver for thresholds, shared by Coach and plan (#1668)."""

import unittest
from datetime import date, timedelta
from typing import ClassVar

from canonical_domain_support import provenance, zone_configuration
from performance_day_support import (
    SYNCED_AT,
    StubReader,
    garmin_threshold_observations,
)

from backend.activities.zone_settings import zone_two_top
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    Environment,
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
    ZonePercentBasis,
)
from backend.performance.canonical_current import (
    read_current_inputs,
    read_export_thresholds,
)
from backend.performance.current_metrics import (
    coach_thresholds,
    current_performance_metrics,
    first_thresholds,
)
from backend.performance.current_thresholds import (
    configured_thresholds,
    provider_zone_thresholds,
    resolve_current_thresholds,
)
from backend.performance.garmin_canonical import read_garmin_thresholds
from backend.performance.source_policy import (
    Candidate,
    resolve_candidates,
    source_order,
)
from backend.planning.load_checks import load_thresholds
from backend.planning.planned_unit_load import resolve_thresholds
from backend.sync.garmin_payload_metrics import garmin_payload_performance_metrics

AS_OF = SYNCED_AT.date()
GARMIN = ProviderId.GARMIN
INTERVALS = ProviderId.INTERVALS


def _obs(
    kind: MetricKind,
    value: float,
    provider: ProviderId,
    sport: Sport | None,
    day: date = AS_OF,
) -> Observation:
    return Observation(
        kind=kind,
        value=MetricValue(value, kind.unit),
        observed_on=day,
        observed_at=None,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id="athlete-1" if provider is INTERVALS else f"g:{value}",
            recorded_by=RecordingOrigin.GARMIN
            if provider is GARMIN
            else RecordingOrigin.UPLOAD,
            retrieved_at=SYNCED_AT,
            label=None,
        ),
        sport=sport,
    )


class ZoneSource(StubReader):
    """A stub source that also serves zone configurations."""

    def __init__(self, observations, configurations) -> None:
        super().__init__(observations)
        self._configurations = tuple(configurations)

    def zone_configurations(self, _db):
        return self._configurations


def _local_power(threshold: float):
    return zone_configuration(
        metric=ZoneConfigurationMetric.POWER,
        sport=Sport.RIDE,
        threshold=threshold,
        maximum=None,
        resting=None,
        limits=(100.0, 200.0, 300.0, 400.0),
        provenance=provenance(None, provider=None),
    )


class PolicyOrderTests(unittest.TestCase):
    def test_ride_ftp_is_local_then_garmin_then_wahoo(self) -> None:
        self.assertEqual(
            source_order(MetricKind.FTP, Sport.RIDE),
            (None, GARMIN, ProviderId.WAHOO),
        )

    def test_heart_rate_pace_and_run_power_are_local_then_garmin(self) -> None:
        for kind, sport in (
            (MetricKind.THRESHOLD_HR, Sport.RUN),
            (MetricKind.MAX_HR, Sport.RIDE),
            (MetricKind.THRESHOLD_PACE, Sport.RUN),
            (MetricKind.FTP, Sport.RUN),
        ):
            with self.subTest(kind=kind, sport=sport):
                self.assertEqual(source_order(kind, sport), (None, GARMIN))


class ResolverTests(unittest.TestCase):
    def test_ftp_conflict_keeps_both_values_visible(self) -> None:
        resolved = resolve_candidates(
            MetricKind.FTP,
            [
                Candidate(ProviderId.WAHOO, 265.0, AS_OF),
                Candidate(GARMIN, 280.0, AS_OF),
            ],
            as_of=AS_OF,
            sport=Sport.RIDE,
        )
        assert resolved is not None
        self.assertEqual(
            (resolved.winner.source, resolved.winner.value), (GARMIN, 280.0)
        )
        self.assertEqual(
            [(item.source, item.value) for item in resolved.alternatives],
            [(ProviderId.WAHOO, 265.0)],
        )
        self.assertTrue(resolved.conflict)

    def test_an_intervals_candidate_is_never_current(self) -> None:
        resolved = resolve_candidates(
            MetricKind.FTP,
            [Candidate(GARMIN, 270.0, AS_OF), Candidate(INTERVALS, 265.0, AS_OF)],
            as_of=AS_OF,
            sport=Sport.RIDE,
        )
        assert resolved is not None
        self.assertEqual(resolved.winner.source, GARMIN)
        self.assertEqual(resolved.alternatives, ())
        self.assertFalse(resolved.conflict)
        self.assertIsNone(
            resolve_candidates(
                MetricKind.FTP,
                [Candidate(INTERVALS, 265.0, AS_OF)],
                as_of=AS_OF,
                sport=Sport.RIDE,
            )
        )

    def test_old_garmin_threshold_is_not_current(self) -> None:
        old = AS_OF - timedelta(days=181)
        self.assertIsNone(
            resolve_candidates(
                MetricKind.THRESHOLD_HR,
                [Candidate(GARMIN, 170.0, old), Candidate(INTERVALS, 165.0, AS_OF)],
                as_of=AS_OF,
                sport=Sport.RUN,
            )
        )
        fresh = resolve_candidates(
            MetricKind.THRESHOLD_HR,
            [Candidate(GARMIN, 170.0, AS_OF - timedelta(days=180))],
            as_of=AS_OF,
            sport=Sport.RUN,
        )
        assert fresh is not None
        self.assertEqual(fresh.winner.source, GARMIN)

    def test_local_value_wins_and_does_not_age(self) -> None:
        resolved = resolve_candidates(
            MetricKind.FTP,
            [
                Candidate(None, 300.0, AS_OF - timedelta(days=400)),
                Candidate(GARMIN, 265.0, AS_OF),
            ],
            as_of=AS_OF,
            sport=Sport.RIDE,
        )
        assert resolved is not None
        self.assertEqual(resolved.winner.source, None)


class CoachAndPlanParityTests(unittest.TestCase):
    """The Coach and the plan read the same threshold for the same day."""

    def _inputs(self, observations, configurations=()):
        return read_current_inputs(
            ZoneSource(observations, configurations), None, as_of=AS_OF
        )

    def _observations(self):
        return (
            _obs(MetricKind.FTP, 265.0, INTERVALS, Sport.RIDE),
            _obs(MetricKind.THRESHOLD_HR, 165.0, INTERVALS, Sport.RUN),
            _obs(MetricKind.FTP, 280.0, GARMIN, Sport.RIDE),
            _obs(MetricKind.THRESHOLD_HR, 172.0, GARMIN, Sport.RUN),
        )

    def _coach(self, inputs):
        garmin = garmin_payload_performance_metrics(
            {
                "cycling_ftp": {"functionalThresholdPower": 280},
                "running_threshold": {"speed_and_heart_rate": {"heartRate": 172}},
            },
            AS_OF,
        )
        metrics = current_performance_metrics(
            {},
            garmin,
            canonical=inputs,
            activities=[],
            garmin_thresholds=read_garmin_thresholds(
                StubReader(self._observations()), None
            ),
            as_of=AS_OF,
        )
        return coach_thresholds(metrics), metrics

    def test_coach_and_plan_use_the_resolved_thresholds(self) -> None:
        inputs = self._inputs(self._observations())
        coach, metrics = self._coach(inputs)
        plan = load_thresholds(inputs, AS_OF)

        self.assertEqual(coach["ftp_w"], 280)
        self.assertEqual(coach["ftp_source"], "Garmin Connect")
        self.assertNotIn("ftp_alternatives", coach)
        self.assertNotIn("w_prime_j", coach)
        self.assertEqual(plan.for_sport(Sport.RIDE).ftp, coach["ftp_w"])
        self.assertEqual(coach["run_lthr"], 172)
        self.assertEqual(plan.for_sport(Sport.RUN).lthr, coach["run_lthr"])
        self.assertEqual(metrics["run_threshold_hr_bpm"]["source_provider"], "garmin")

    def test_a_local_zone_configuration_leads_both(self) -> None:
        configurations = (_local_power(300.0),)
        inputs = self._inputs(self._observations(), configurations)
        coach, _ = self._coach(inputs)
        plan = load_thresholds(inputs, AS_OF, configurations)

        self.assertEqual(coach["ftp_w"], 300)
        self.assertEqual(coach["ftp_source"], "Lokal")
        self.assertEqual(plan.for_sport(Sport.RIDE).ftp, 300.0)

    def test_plan_thresholds_hold_only_provider_winners(self) -> None:
        winners = provider_zone_thresholds(self._observations(), as_of=AS_OF)
        self.assertEqual(
            {(item.kind, item.sport, item.provenance.provider) for item in winners},
            {
                (MetricKind.FTP, Sport.RIDE, GARMIN),
                (MetricKind.THRESHOLD_HR, Sport.RUN, GARMIN),
            },
        )

    def test_intervals_athlete_wide_lthr_fills_no_sport(self) -> None:
        wide = _obs(MetricKind.THRESHOLD_HR, 168.0, INTERVALS, None)
        resolved = resolve_current_thresholds((wide,), as_of=AS_OF)
        self.assertNotIn((MetricKind.THRESHOLD_HR, Sport.RIDE), resolved)
        self.assertEqual(provider_zone_thresholds((wide,), as_of=AS_OF), ())


class ReviewGuardTests(unittest.TestCase):
    def test_implausible_intervals_max_hr_is_not_current(self) -> None:
        resolved = resolve_current_thresholds(
            (_obs(MetricKind.MAX_HR, 50.0, INTERVALS, Sport.RIDE),), as_of=AS_OF
        )
        self.assertNotIn((MetricKind.MAX_HR, Sport.RIDE), resolved)

    def test_garmin_run_power_is_one_ftp_kind_with_the_legacy_kind_readable(
        self,
    ) -> None:
        # #1672: Garmin health mapper 17 writes FTP/RUN; older rows keep the
        # legacy kind until a replay, and both read as the run FTP.
        for kind in (MetricKind.FTP, MetricKind.RUN_THRESHOLD_POWER):
            with self.subTest(kind=kind):
                power = _obs(kind, 290.0, GARMIN, Sport.RUN)
                (found,) = read_garmin_thresholds(StubReader((power,)), None)
                self.assertEqual(
                    (found.kind, found.sport, found.value.value),
                    (MetricKind.FTP, Sport.RUN, 290.0),
                )

    def test_implausible_garmin_threshold_speed_is_dropped(self) -> None:
        slow = _obs(MetricKind.THRESHOLD_PACE, 0.4, GARMIN, Sport.RUN)
        self.assertEqual(read_garmin_thresholds(StubReader((slow,)), None), ())

    def test_plan_pace_prefers_the_winner_over_a_provider_configuration(self) -> None:
        pace = {
            "metric": ZoneConfigurationMetric.PACE,
            "sport": Sport.RUN,
            "threshold": 4.0,
            "maximum": None,
            "resting": None,
            "limits": (2.0, 3.0, 4.0, 6.0),
        }
        garmin_pace = zone_configuration(
            **pace, provenance=provenance("zones", provider=GARMIN)
        )
        intervals_pace = zone_configuration(**pace)
        winner = _obs(MetricKind.THRESHOLD_PACE, 4.2, GARMIN, Sport.RUN)
        thresholds = resolve_thresholds(
            (winner,), (garmin_pace,), Sport.RUN, Environment.OUTDOOR, AS_OF
        )
        self.assertEqual(thresholds.threshold_pace, 4.2)
        thresholds = resolve_thresholds(
            (), (garmin_pace,), Sport.RUN, Environment.OUTDOOR, AS_OF
        )
        self.assertEqual(thresholds.threshold_pace, 4.0)
        # An Intervals.icu configuration gives its limits, never a pace.
        thresholds = resolve_thresholds(
            (), (intervals_pace,), Sport.RUN, Environment.OUTDOOR, AS_OF
        )
        self.assertIsNone(thresholds.threshold_pace)

    def test_no_values_make_the_thresholds_missing(self) -> None:
        inputs = read_current_inputs(StubReader(()), None, as_of=AS_OF)
        self.assertEqual(
            load_thresholds(inputs, AS_OF).unavailable, "missing_thresholds"
        )

    def test_intervals_values_alone_make_the_thresholds_missing(self) -> None:
        intervals = (
            _obs(MetricKind.FTP, 265.0, INTERVALS, Sport.RIDE),
            _obs(MetricKind.THRESHOLD_HR, 165.0, INTERVALS, Sport.RUN),
        )
        inputs = read_current_inputs(StubReader(intervals), None, as_of=AS_OF)
        self.assertEqual(
            load_thresholds(inputs, AS_OF).unavailable, "missing_thresholds"
        )


class LocalThresholdTests(unittest.TestCase):
    def test_only_athlete_confirmed_configurations_count(self) -> None:
        provider = zone_configuration(
            metric=ZoneConfigurationMetric.POWER,
            sport=Sport.RIDE,
            threshold=290.0,
            maximum=None,
            resting=None,
            limits=(100.0, 200.0, 300.0, 400.0),
        )
        self.assertEqual(configured_thresholds([provider], AS_OF), ())
        (local,) = configured_thresholds([_local_power(300.0)], AS_OF)
        self.assertEqual(
            (local.kind, local.sport, local.value.value),
            (MetricKind.FTP, Sport.RIDE, 300.0),
        )

    def test_test_support_maps_a_garmin_dict_to_observations(self) -> None:
        garmin = garmin_payload_performance_metrics(
            {"cycling_ftp": {"functionalThresholdPower": 280}}, AS_OF
        )
        (ftp,) = garmin_threshold_observations(garmin)
        self.assertEqual((ftp.kind, ftp.value.value), (MetricKind.FTP, 280.0))


class ExportThresholdTests(unittest.TestCase):
    """The thresholds sent to Intervals.icu: local, then Garmin, then Wahoo (#1729)."""

    def _export(self, observations, configurations=()):
        return read_export_thresholds(
            ZoneSource(observations, configurations), None, as_of=AS_OF
        )

    def _ride_ftp(self, observations, configurations=()):
        winner = self._export(observations, configurations).get(
            (MetricKind.FTP, Sport.RIDE)
        )
        return (
            None if winner is None else (winner.provenance.provider, winner.value.value)
        )

    def test_local_then_garmin_then_wahoo_and_never_intervals(self) -> None:
        intervals = _obs(MetricKind.FTP, 265.0, INTERVALS, Sport.RIDE)
        garmin = _obs(MetricKind.FTP, 280.0, GARMIN, Sport.RIDE)
        wahoo = _obs(MetricKind.FTP, 250.0, ProviderId.WAHOO, Sport.RIDE)
        everything = (intervals, garmin, wahoo)
        self.assertEqual(
            self._ride_ftp(everything, [_local_power(300.0)]), (None, 300.0)
        )
        self.assertEqual(self._ride_ftp(everything), (GARMIN, 280.0))
        self.assertEqual(self._ride_ftp((intervals, wahoo)), (ProviderId.WAHOO, 250.0))
        self.assertIsNone(self._ride_ftp((intervals,)))

    def test_given_configurations_count_for_a_reader_without_them(self) -> None:
        # A pending canonical reader serves no zones; the tables' zones still count.
        exported = read_export_thresholds(
            StubReader(()), None, as_of=AS_OF, configurations=[_local_power(300.0)]
        )
        self.assertEqual(exported[(MetricKind.FTP, Sport.RIDE)].value.value, 300.0)

    def test_heart_rate_and_pace_come_from_garmin_not_intervals(self) -> None:
        exported = self._export(
            (
                _obs(MetricKind.THRESHOLD_HR, 165.0, INTERVALS, Sport.RUN),
                _obs(MetricKind.THRESHOLD_HR, 160.0, INTERVALS, None),
                _obs(MetricKind.THRESHOLD_HR, 172.0, GARMIN, Sport.RUN),
            )
        )
        winner = exported[(MetricKind.THRESHOLD_HR, Sport.RUN)]
        self.assertEqual(
            (winner.provenance.provider, winner.value.value), (GARMIN, 172.0)
        )
        self.assertNotIn((MetricKind.THRESHOLD_HR, Sport.RIDE), exported)


class FirstThresholdTests(unittest.TestCase):
    """LT1 per sport (#2427): measured or adopted > zone 2 > fixed share of LT2."""

    METRICS: ClassVar[dict[str, dict[str, float]]] = {
        "run_threshold_hr_bpm": {"value": 172},
        "run_threshold_pace_seconds_per_km": {"value": 270},
        "bike_threshold_hr_bpm": {"value": 160},
        "cycling_ftp_watts": {"value": 280},
    }
    TOPS: ClassVar[dict[str, float]] = {
        "run_hr": 128.0,
        "ride_hr": 131.4,
        "run_pace": 300.4,
        "ride_power": 200.0,
    }

    def test_precedence_of_each_value(self) -> None:
        # Worked examples: 85 % of 172 and 160 bpm is 146 and 136 bpm; 4:30 /km at
        # 88 % speed is 5:07 /km; 75 % of 280 W is 210 W; 86 % of 172 and 160 bpm
        # is 148 and 138 bpm. Own sessions are read at the LT1 heart rate in
        # effect: 128 and 131 bpm from zone 2, 148 and 138 bpm when measured.
        fixed, zone, own = "fixed_share", "zone_2", "own_sessions"
        sessions = {("run", 128): 331.6, ("ride", 131): 187.4,
                    ("run", 148): 296.2, ("ride", 138): 201.0}  # fmt: skip
        at_hr = lambda sport, bpm: sessions.get((sport, bpm))
        for name, pct, origin, tops, at_heart_rate, expected in (
            ("no LT1 value and no zones", None, "", None, None, {
                "run": {"hr_bpm": 146, "hr_origin": fixed,
                        "pace_seconds_per_km": 307, "pace_origin": fixed},
                "ride": {"hr_bpm": 136, "hr_origin": fixed,
                         "watts": 210, "power_origin": fixed}}),
            ("zone 2 of every kind", None, "", self.TOPS, None, {
                "run": {"hr_bpm": 128, "hr_origin": zone,
                        "pace_seconds_per_km": 300, "pace_origin": zone},
                "ride": {"hr_bpm": 131, "hr_origin": zone,
                         "watts": 200, "power_origin": zone}}),
            ("measured wins over zone 2", 86.0, "measured", self.TOPS, None, {
                "run": {"hr_bpm": 148, "hr_origin": "measured",
                        "pace_seconds_per_km": 300, "pace_origin": zone},
                "ride": {"hr_bpm": 138, "hr_origin": "measured",
                         "watts": 200, "power_origin": zone}}),
            ("adopted DFA estimate", 86.0, "estimated", None, None, {
                "run": {"hr_bpm": 148, "hr_origin": "estimated",
                        "pace_seconds_per_km": 307, "pace_origin": fixed},
                "ride": {"hr_bpm": 138, "hr_origin": "estimated",
                         "watts": 210, "power_origin": fixed}}),
            ("own sessions at the zone 2 heart rate win over zone 2", None, "",
             self.TOPS, at_hr, {
                "run": {"hr_bpm": 128, "hr_origin": zone,
                        "pace_seconds_per_km": 332, "pace_origin": own},
                "ride": {"hr_bpm": 131, "hr_origin": zone,
                         "watts": 187, "power_origin": own}}),
            ("own sessions at the measured heart rate", 86.0, "measured", None,
             at_hr, {
                "run": {"hr_bpm": 148, "hr_origin": "measured",
                        "pace_seconds_per_km": 296, "pace_origin": own},
                "ride": {"hr_bpm": 138, "hr_origin": "measured",
                         "watts": 201, "power_origin": own}}),
            ("too few own sessions fall back", None, "", None,
             lambda sport, bpm: None, {
                "run": {"hr_bpm": 146, "hr_origin": fixed,
                        "pace_seconds_per_km": 307, "pace_origin": fixed},
                "ride": {"hr_bpm": 136, "hr_origin": fixed,
                         "watts": 210, "power_origin": fixed}}),
        ):  # fmt: skip
            with self.subTest(name):
                self.assertEqual(
                    expected,
                    first_thresholds(self.METRICS, pct, origin, tops, at_heart_rate),
                )

    def test_a_value_without_its_lt2_or_zone_is_left_out(self) -> None:
        metrics = {"run_threshold_hr_bpm": {"value": 172}}
        self.assertEqual(
            {"run": {"hr_bpm": 146, "hr_origin": "fixed_share"}},
            first_thresholds(metrics, None, ""),
        )
        self.assertEqual({}, first_thresholds({}, 86.0, "measured"))
        # Garmin's all-sport heart-rate zones give no LT1 to a sport without LT2.
        self.assertEqual({}, first_thresholds({}, 86.0, "measured", {"ride_hr": 131.4}))
        # With an FTP but no threshold HR, the heart-rate zone still gives LT1.
        self.assertEqual(
            {"ride": {"hr_bpm": 131, "hr_origin": "zone_2",
                      "watts": 210, "power_origin": "fixed_share"}},
            first_thresholds({"cycling_ftp_watts": {"value": 280}}, None, "",
                             {"ride_hr": 131.4}),
        )  # fmt: skip

    def test_zone_two_top_of_each_zone_kind(self) -> None:
        pace = {
            "metric": ZoneConfigurationMetric.PACE,
            "threshold": None,
            "maximum": None,
            "resting": None,
            "limits": None,
        }
        for name, configuration, threshold_pace, expected in (
            # 4:30 /km at 87.7 % of the threshold speed: 270 * 100 / 87.7.
            ("pace percent of the run threshold", zone_configuration(
                **pace, percent_limits=(77.5, 87.7, 94.3),
                percent_basis=ZonePercentBasis.THRESHOLD), 270.0, 307.87),
            ("pace percent without any threshold", zone_configuration(
                **pace, percent_limits=(77.5, 87.7, 94.3),
                percent_basis=ZonePercentBasis.THRESHOLD), None, None),
            # 3.5 m/s is 285.71 s/km.
            ("absolute pace limits", zone_configuration(
                **{**pace, "limits": (3.0, 3.5, 4.0)}), None, 285.71),
            ("absolute power limits", _local_power(300.0), None, 200.0),
            ("absolute heart-rate limits", zone_configuration(), None, 145.0),
            # 48 + 70 % of the reserve of 192 - 48 bpm.
            ("heart-rate reserve percent", zone_configuration(
                limits=None, percent_limits=(60.0, 70.0, 80.0),
                percent_basis=ZonePercentBasis.RESERVE), None, 148.8),
            ("power percent of the FTP", zone_configuration(
                metric=ZoneConfigurationMetric.POWER, sport=Sport.RIDE,
                threshold=300.0, maximum=None, resting=None, limits=None,
                percent_limits=(55.0, 75.0, 90.0),
                percent_basis=ZonePercentBasis.THRESHOLD), None, 225.0),
        ):  # fmt: skip
            with self.subTest(name):
                top = zone_two_top(configuration, threshold_pace)
                self.assertEqual(expected, None if top is None else round(top, 2))


if __name__ == "__main__":
    unittest.main()
