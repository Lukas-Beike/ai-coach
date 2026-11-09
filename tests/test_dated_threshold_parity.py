"""One dated precedence for run LTHR and threshold pace across every consumer (#1892).

Precedence for a sport, kind and day: (1) the locally confirmed zone configuration
in effect, (2) the Garmin watch zone set in effect (lactate threshold heart rate),
(3) the stored source-policy observations. Expected values are worked examples:
a watch LTHR of 172 against a stored 168 gives an easy cap (87 % of LTHR) of 150
against 146 bpm, and one hour at 150 bpm scores 60.6 against 66.2 TSS (male
constants, rest 50, max 190).
"""

import re
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from canonical_domain_support import local_zone_configuration, zone_configuration
from canonical_domain_support import provenance as configuration_provenance
from performance_day_support import SYNCED_AT, StubReader

from backend.activities.hr_cap import effective_caps, resolved_range
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
from backend.db import canonical_domain_store
from backend.performance import local_tss
from backend.performance.canonical_current import (
    read_current_inputs,
    read_export_thresholds,
)
from backend.performance.current_metrics import (
    coach_thresholds,
    current_performance_metrics,
)
from backend.performance.current_thresholds import (
    configured_thresholds,
    provider_zone_thresholds,
)
from backend.performance.garmin_canonical import read_garmin_thresholds
from backend.performance.local_tss import (
    DatedThresholds,
    LocalLoad,
    session_local_load,
)
from backend.performance.source_policy import NO_PREFERENCES
from backend.performance.threshold_staleness import ThresholdStalenessService
from backend.planning.load_checks import load_thresholds
from backend.planning.planned_unit_load import resolve_thresholds
from backend.sync.garmin_payload_metrics import garmin_payload_performance_metrics
from backend.sync.wahoo_workout_export import plan_references

GARMIN = ProviderId.GARMIN
DAY = date(2026, 11, 7)
RUN_LTHR = (MetricKind.THRESHOLD_HR, Sport.RUN)
RUN_PACE = (MetricKind.THRESHOLD_PACE, Sport.RUN)
DOCS = Path(__file__).resolve().parents[1] / "docs"


class ZoneSource(StubReader):
    """A stub source that also serves zone configurations."""

    def __init__(self, observations, configurations) -> None:
        super().__init__(observations)
        self._configurations = tuple(configurations)

    def zone_configurations(self, _db):
        return self._configurations


def _obs(
    kind: MetricKind, value: float, provider: ProviderId, sport: Sport | None, day: date
) -> Observation:
    return Observation(
        kind=kind,
        value=MetricValue(value, kind.unit),
        observed_on=day,
        observed_at=None,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=f"g:{kind.value}:{value}",
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=SYNCED_AT,
            label=None,
        ),
        sport=sport,
    )


def _watch(threshold: float, valid_from: date, valid_until: date | None = None):
    """A Garmin watch heart-rate zone set (the dated lactate threshold HR)."""
    return zone_configuration(
        sport=Sport.RUN,
        threshold=threshold,
        valid_from=valid_from,
        valid_until=valid_until,
        provenance=configuration_provenance("zones", provider=GARMIN),
    )


def _local_lthr(threshold: float, valid_from: date):
    return local_zone_configuration(threshold=threshold, valid_from=valid_from)


def _local_pace(threshold: float):
    return local_zone_configuration(
        metric=ZoneConfigurationMetric.PACE,
        sport=Sport.RUN,
        threshold=threshold,
        maximum=None,
        resting=None,
        limits=(3.0, 3.5, 4.0, 4.5, 5.0),
    )


class WatchLthrParityTests(unittest.TestCase):
    """Watch 172 against a stored 168: every consumer reads 172 on the same day."""

    def setUp(self) -> None:
        self.observations = (
            _obs(MetricKind.THRESHOLD_HR, 168.0, GARMIN, Sport.RUN, DAY),
            _obs(MetricKind.MAX_HR, 190.0, GARMIN, Sport.RUN, DAY),
        )
        self.configurations = (_watch(172.0, DAY - timedelta(days=30)),)
        self.reader = ZoneSource(self.observations, self.configurations)

    def _metrics(self):
        inputs = read_current_inputs(self.reader, None, as_of=DAY)
        garmin = garmin_payload_performance_metrics(
            {"running_threshold": {"speed_and_heart_rate": {"heartRate": 168}}}, DAY
        )
        metrics = current_performance_metrics(
            {},
            garmin,
            canonical=inputs,
            activities=[],
            garmin_thresholds=read_garmin_thresholds(self.reader, None),
            as_of=DAY,
        )
        return inputs, metrics

    def test_zones_plan_load_and_the_garmin_export_cap(self) -> None:
        inputs, _ = self._metrics()
        winners = provider_zone_thresholds(
            read_garmin_thresholds(self.reader, None), as_of=DAY
        )
        zones = resolve_thresholds(
            winners, self.configurations, Sport.RUN, Environment.OUTDOOR, DAY
        ).zones
        planned = load_thresholds(inputs, DAY, self.configurations).for_sport(
            Sport.RUN, Environment.OUTDOOR, DAY
        )
        self.assertEqual((zones.lthr, planned.zones.lthr), (172.0, 172.0))
        # The Garmin cap bpm export reads the zones' LTHR: 87 % of 172.
        easy = effective_caps(None)["easy"]
        self.assertEqual(resolved_range(easy, zones.lthr), (112, 150))

    def test_session_load_current_metrics_and_coach_caps(self) -> None:
        _, metrics = self._metrics()
        coach = coach_thresholds(metrics)
        self.assertEqual(coach["run_lthr"], 172)
        self.assertEqual(coach["run_hr_caps"]["easy"]["bpm"], 150)
        self.assertEqual(metrics["run_threshold_hr_bpm"]["source_provider"], "garmin")
        self.assertEqual(metrics["run_threshold_hr_bpm"]["source"], "Garmin Connect")
        thresholds = DatedThresholds(self.observations, self.configurations)
        used = thresholds.for_session(Sport.RUN, DAY).threshold_hr
        assert used is not None
        self.assertEqual((used.value, used.source), (172.0, "garmin"))

    def test_wahoo_header_export_and_staleness_read_the_same_value(self) -> None:
        exported = read_export_thresholds(
            self.reader, None, as_of=DAY, configurations=self.configurations
        )
        self.assertEqual(plan_references(exported, Sport.RUN).threshold_hr, 172)
        self.assertEqual(exported[RUN_LTHR].provenance.provider, GARMIN)

        class Database:
            @contextmanager
            def reader(self):
                yield None

        service = ThresholdStalenessService(
            Database,
            lambda: StubReader(self.observations),
            lambda: DAY,
            zone_configurations=lambda _db: self.configurations,
            preferences=lambda _db: NO_PREFERENCES,
        )
        with mock.patch.object(
            canonical_domain_store, "local_zone_saved_days", return_value={}
        ):
            # Fresh watch zone set (30 days) and a fresh stored value: no warning.
            self.assertIsNone(service.read())
        old_set = (_watch(172.0, DAY - timedelta(days=80)),)
        stale = ThresholdStalenessService(
            Database,
            lambda: StubReader(self.observations),
            lambda: DAY,
            zone_configurations=lambda _db: old_set,
            preferences=lambda _db: NO_PREFERENCES,
        )
        with mock.patch.object(
            canonical_domain_store, "local_zone_saved_days", return_value={}
        ):
            warning = stale.read()
        assert warning is not None
        (item,) = warning["items"]
        # The 172 in effect is dated by the watch set (80 days), not by the 168.
        self.assertEqual(
            (item["metric"], item["value_text"], item["source"], item["age_days"]),
            ("threshold_hr", "172 bpm", "garmin", 80),
        )

    def test_m6_heart_rate_load_uses_the_watch_value(self) -> None:
        resting = _obs(MetricKind.RESTING_HR, 50.0, GARMIN, None, DAY)
        summary = {
            "id": "run_1",
            "sport": "run",
            "started_at": "2026-11-07T06:00:00+00:00",
            "started_at_local": "2026-11-07T07:00:00",
            "moving_duration_s": 3600.0,
            "avg_hr": 150.0,
        }

        def load(configurations):
            thresholds = DatedThresholds(
                self.observations, configurations, [resting]
            ).for_session(Sport.RUN, DAY)
            result = session_local_load(summary, thresholds)
            assert isinstance(result, LocalLoad)
            return result.load

        self.assertAlmostEqual(load(self.configurations), 60.6, places=1)
        self.assertAlmostEqual(load(()), 66.2, places=1)

    def test_local_configuration_leads_the_watch_everywhere(self) -> None:
        configurations = (*self.configurations, _local_lthr(175.0, DAY))
        reader = ZoneSource(self.observations, configurations)
        inputs = read_current_inputs(reader, None, as_of=DAY)
        zones = load_thresholds(inputs, DAY, configurations).for_sport(
            Sport.RUN, Environment.OUTDOOR, DAY
        )
        used = DatedThresholds(self.observations, configurations).for_session(
            Sport.RUN, DAY
        )
        exported = read_export_thresholds(
            reader, None, as_of=DAY, configurations=configurations
        )
        self.assertEqual(zones.zones.lthr, 175.0)
        assert used.threshold_hr is not None
        self.assertEqual(
            (used.threshold_hr.value, used.threshold_hr.source), (175.0, "local")
        )
        self.assertEqual(exported[RUN_LTHR].value.value, 175.0)
        self.assertIsNone(exported[RUN_LTHR].provenance.provider)


class DatedBehaviorTests(unittest.TestCase):
    def test_a_change_on_day_d_affects_sessions_on_or_after_d_only(self) -> None:
        change = DAY
        configurations = (
            _watch(168.0, change - timedelta(days=60), change - timedelta(days=1)),
            _watch(172.0, change),
        )
        observations = (
            _obs(MetricKind.THRESHOLD_HR, 160.0, GARMIN, Sport.RUN, change),
        )
        thresholds = DatedThresholds(observations, configurations)
        for offset, expected in ((-1, 168.0), (0, 172.0), (1, 172.0)):
            day = change + timedelta(days=offset)
            with self.subTest(offset=offset):
                used = thresholds.for_session(Sport.RUN, day).threshold_hr
                assert used is not None
                self.assertEqual(used.value, expected)
                zones = resolve_thresholds(
                    (), configurations, Sport.RUN, Environment.OUTDOOR, day
                )
                self.assertEqual(zones.zones.lthr, expected)
                (configured,) = [
                    item
                    for item in configured_thresholds(configurations, day)
                    if item.kind is MetricKind.THRESHOLD_HR
                ]
                self.assertEqual(configured.value.value, expected)

    def test_a_local_change_on_day_d_leads_the_watch_from_d(self) -> None:
        configurations = (
            _watch(172.0, DAY - timedelta(days=60)),
            _local_lthr(176.0, DAY),
        )
        thresholds = DatedThresholds((), configurations)
        before = thresholds.for_session(Sport.RUN, DAY - timedelta(days=1)).threshold_hr
        after = thresholds.for_session(Sport.RUN, DAY).threshold_hr
        assert before is not None and after is not None
        self.assertEqual((before.value, before.source), (172.0, "garmin"))
        self.assertEqual((after.value, after.source), (176.0, "local"))


class ThresholdPaceParityTests(unittest.TestCase):
    """A local pace (4.0 m/s) leads the stored 3.8 m/s for zones and plan load."""

    def test_zones_plan_load_session_load_and_export_agree(self) -> None:
        observation = _obs(MetricKind.THRESHOLD_PACE, 3.8, GARMIN, Sport.RUN, DAY)
        configurations = (_local_pace(4.0),)
        reader = ZoneSource((observation,), configurations)
        winners = provider_zone_thresholds((observation,), as_of=DAY)
        planned = resolve_thresholds(
            winners, configurations, Sport.RUN, Environment.OUTDOOR, DAY
        )
        used = DatedThresholds((observation,), configurations).for_session(
            Sport.RUN, DAY
        )
        exported = read_export_thresholds(
            reader, None, as_of=DAY, configurations=configurations
        )
        assert used.threshold_pace is not None
        self.assertEqual(planned.threshold_speed_mps, 4.0)
        self.assertEqual(planned.zones.threshold_pace, 4.0)
        self.assertEqual(used.threshold_pace.value, 4.0)
        self.assertEqual(exported[RUN_PACE].value.value, 4.0)
        self.assertEqual(plan_references(exported, Sport.RUN).threshold_speed, 4.0)
        # The absolute 4.0 m/s limit is 100 % of the local threshold, not 105 % of 3.8.
        self.assertAlmostEqual(planned.zones.pace_limits[2], 100.0)

    def test_without_a_local_pace_the_observation_leads(self) -> None:
        observation = _obs(MetricKind.THRESHOLD_PACE, 3.8, GARMIN, Sport.RUN, DAY)
        winners = provider_zone_thresholds((observation,), as_of=DAY)
        planned = resolve_thresholds(winners, (), Sport.RUN, Environment.OUTDOOR, DAY)
        self.assertEqual(planned.threshold_speed_mps, 3.8)


class MethodVersionTests(unittest.TestCase):
    def test_version_constant_card_and_field_map_agree(self) -> None:
        card = (DOCS / "performance-methods" / "m6-local-tss-load.md").read_text(
            "utf-8"
        )
        field_map = (DOCS / "canonical-field-map.md").read_text("utf-8")
        version = local_tss.METHOD_VERSION
        card_version = re.search(r"\*\*Card version:\*\* (\d+)", card)
        method_id = re.search(rf"{local_tss.METHOD_ID} v(\d+)", card)
        stored = re.search(r"`method_version`: (\d+)\.", card)
        mapped = re.search(r"`METHOD_VERSION` = \*\*(\d+)\*\*", field_map)
        for found in (card_version, method_id, stored, mapped):
            assert found is not None
            self.assertEqual(int(found.group(1)), version)

    def test_a_version_bump_changes_the_fingerprint_that_drives_recompute(self) -> None:
        summary = {
            "id": "run_1",
            "sport": "run",
            "started_at": "2026-11-07T06:00:00+00:00",
            "started_at_local": "2026-11-07T07:00:00",
            "moving_duration_s": 3600.0,
            "normalized_power": 250.0,
        }
        thresholds = DatedThresholds(
            [_obs(MetricKind.FTP, 250.0, GARMIN, Sport.RUN, DAY)]
        ).for_session(Sport.RUN, DAY)
        before = session_local_load(summary, thresholds)
        with mock.patch.object(
            local_tss, "METHOD_VERSION", local_tss.METHOD_VERSION + 1
        ):
            after = session_local_load(summary, thresholds)
        assert isinstance(before, LocalLoad) and isinstance(after, LocalLoad)
        self.assertNotEqual(before.fingerprint, after.fingerprint)


if __name__ == "__main__":
    unittest.main()
