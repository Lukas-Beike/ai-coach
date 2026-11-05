"""One source-precedence resolver for thresholds, shared by Coach and plan (#1668)."""

import unittest
from datetime import date, timedelta

from canonical_domain_support import provenance, zone_configuration
from performance_day_support import (
    SYNCED_AT,
    StubReader,
    garmin_threshold_observations,
)

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
)
from backend.performance.canonical_current import read_current_inputs
from backend.performance.current_metrics import (
    coach_thresholds,
    current_performance_metrics,
)
from backend.performance.current_thresholds import (
    local_thresholds,
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
    def test_ride_ftp_is_local_then_intervals_then_garmin_then_wahoo(self) -> None:
        self.assertEqual(
            source_order(MetricKind.FTP, Sport.RIDE),
            (None, INTERVALS, GARMIN, ProviderId.WAHOO),
        )

    def test_heart_rate_pace_and_run_power_are_local_then_garmin(self) -> None:
        for kind, sport in (
            (MetricKind.THRESHOLD_HR, Sport.RUN),
            (MetricKind.MAX_HR, Sport.RIDE),
            (MetricKind.THRESHOLD_PACE, Sport.RUN),
            (MetricKind.FTP, Sport.RUN),
        ):
            with self.subTest(kind=kind, sport=sport):
                self.assertEqual(
                    source_order(kind, sport)[:3], (None, GARMIN, INTERVALS)
                )


class ResolverTests(unittest.TestCase):
    def test_ftp_conflict_keeps_both_values_visible(self) -> None:
        resolved = resolve_candidates(
            MetricKind.FTP,
            [Candidate(GARMIN, 280.0, AS_OF), Candidate(INTERVALS, 265.0, AS_OF)],
            as_of=AS_OF,
            sport=Sport.RIDE,
        )
        assert resolved is not None
        self.assertEqual(
            (resolved.winner.source, resolved.winner.value), (INTERVALS, 265.0)
        )
        self.assertEqual(
            [(item.source, item.value) for item in resolved.alternatives],
            [(GARMIN, 280.0)],
        )
        self.assertTrue(resolved.conflict)

    def test_values_within_tolerance_are_no_conflict(self) -> None:
        resolved = resolve_candidates(
            MetricKind.FTP,
            [Candidate(GARMIN, 270.0, AS_OF), Candidate(INTERVALS, 265.0, AS_OF)],
            as_of=AS_OF,
            sport=Sport.RIDE,
        )
        assert resolved is not None
        self.assertFalse(resolved.conflict)

    def test_old_garmin_threshold_is_not_current(self) -> None:
        old = AS_OF - timedelta(days=181)
        resolved = resolve_candidates(
            MetricKind.THRESHOLD_HR,
            [Candidate(GARMIN, 170.0, old), Candidate(INTERVALS, 165.0, AS_OF)],
            as_of=AS_OF,
            sport=Sport.RUN,
        )
        assert resolved is not None
        self.assertEqual(resolved.winner.source, INTERVALS)
        self.assertEqual(resolved.alternatives, ())

    def test_stale_intervals_sync_yields_to_garmin(self) -> None:
        stale = AS_OF - timedelta(days=31)
        resolved = resolve_candidates(
            MetricKind.FTP,
            [Candidate(INTERVALS, 265.0, stale), Candidate(GARMIN, 280.0, AS_OF)],
            as_of=AS_OF,
            sport=Sport.RIDE,
        )
        assert resolved is not None
        self.assertEqual(resolved.winner.source, GARMIN)

    def test_local_value_wins_and_does_not_age(self) -> None:
        resolved = resolve_candidates(
            MetricKind.FTP,
            [
                Candidate(None, 300.0, AS_OF - timedelta(days=400)),
                Candidate(INTERVALS, 265.0, AS_OF),
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
        return coach_thresholds(metrics, inputs), metrics

    def test_coach_and_plan_use_the_resolved_thresholds(self) -> None:
        inputs = self._inputs(self._observations())
        coach, metrics = self._coach(inputs)
        plan = load_thresholds(inputs, AS_OF)

        self.assertEqual(coach["ftp_w"], 265)
        self.assertEqual(coach["ftp_source"], "Intervals.icu")
        self.assertEqual(
            coach["ftp_alternatives"], [{"source": "Garmin Connect", "value": 280}]
        )
        self.assertTrue(coach["ftp_conflict"])
        self.assertEqual(plan.for_sport(Sport.RIDE).zones.ftp, coach["ftp_w"])
        self.assertEqual(coach["run_lthr"], 172)
        self.assertEqual(plan.for_sport(Sport.RUN).zones.lthr, coach["run_lthr"])
        self.assertEqual(metrics["run_threshold_hr_bpm"]["source_provider"], "garmin")

    def test_a_local_zone_configuration_leads_both(self) -> None:
        configurations = (_local_power(300.0),)
        inputs = self._inputs(self._observations(), configurations)
        coach, _ = self._coach(inputs)
        plan = load_thresholds(inputs, AS_OF, configurations)

        self.assertEqual(coach["ftp_w"], 300)
        self.assertEqual(coach["ftp_source"], "Lokal")
        self.assertEqual(plan.for_sport(Sport.RIDE).zones.ftp, 300.0)

    def test_plan_thresholds_hold_only_provider_winners(self) -> None:
        winners = provider_zone_thresholds(self._observations(), as_of=AS_OF)
        self.assertEqual(
            {(item.kind, item.sport, item.provenance.provider) for item in winners},
            {
                (MetricKind.FTP, Sport.RIDE, INTERVALS),
                (MetricKind.THRESHOLD_HR, Sport.RUN, GARMIN),
            },
        )

    def test_intervals_athlete_wide_lthr_fills_a_sport(self) -> None:
        wide = _obs(MetricKind.THRESHOLD_HR, 168.0, INTERVALS, None)
        resolved = resolve_current_thresholds((wide,), as_of=AS_OF)
        self.assertEqual(
            resolved[(MetricKind.THRESHOLD_HR, Sport.RIDE)].winner.value, 168.0
        )
        self.assertEqual(
            {item.sport for item in provider_zone_thresholds((wide,), as_of=AS_OF)},
            {Sport.RIDE, Sport.RUN},
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
        self.assertEqual(local_thresholds([provider], AS_OF), ())
        (local,) = local_thresholds([_local_power(300.0)], AS_OF)
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


if __name__ == "__main__":
    unittest.main()
