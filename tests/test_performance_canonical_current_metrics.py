"""Current metrics read from canonical observations.

Intervals.icu athlete settings, sport thresholds, VO2max, weight and wellness
values are never current inputs (athlete decision 2026-11-07). The current inputs
hold the stored Wahoo fallbacks, the local thresholds and the resolved plan-zone
thresholds; Garmin values come from the Garmin metrics.
All storage is temporary and every provider is mocked by fixtures.
"""

from __future__ import annotations

import contextlib
import unittest
from dataclasses import replace
from datetime import UTC, date, timedelta
from typing import Any, Final

from canonical_consumer_cases import CASES, RETRIEVED_AT, TODAY, Case, _observations
from canonical_read_support import CanonicalReadFixture, make_selector, populate
from performance_day_support import snapshot_metrics

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.coach.context import CoachPerformanceContextReader
from backend.performance.canonical_current import (
    NO_CURRENT_INPUTS,
    CanonicalCurrentInputs,
    read_current_inputs,
)
from backend.performance.canonical_inputs import (
    EMPTY_PERFORMANCE_INPUTS,
    CanonicalPerformanceSource,
    read_performance_inputs,
)
from backend.performance.context import current_performance_context
from backend.performance.freshness import GarminSyncStatus
from backend.providers.wahoo_threshold_mapping import (
    map_wahoo_power_zones,
    map_wahoo_user,
)
from backend.runtime.ports import ObservationReader
from backend.sync import garmin_performance_history

SYNC_DAY = date(2026, 10, 12)


class ObservationStub(ObservationReader):
    """Serves observations by kind, inclusive observed_on window and sport."""

    def __init__(self, observations: tuple[Observation, ...]) -> None:
        self._observations = observations
        self.calls: list[tuple[MetricKind, date | None, date | None, Sport | None]] = []

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        self.calls.append((kind, start, end, sport))
        return tuple(
            observation
            for observation in self._observations
            if observation.kind is kind
            and (start is None or start <= observation.observed_on)
            and (end is None or observation.observed_on <= end)
            and (sport is None or observation.sport is sport)
        )


def _case(name: str) -> Case:
    return next(case for case in CASES if case.name == name)


def _metrics(case: Case) -> dict[str, Any]:
    """Current metrics of a case: stored observations, Garmin metrics, profile."""
    garmin = garmin_performance_history.current_garmin_metrics(case.garmin, TODAY)
    inputs = read_current_inputs(
        ObservationStub(_observations(case)), None, as_of=TODAY
    )
    return snapshot_metrics(case.intervals, case.profile, garmin, canonical=inputs)


def _providers(metrics: dict[str, Any]) -> set[str | None]:
    """Every provider named by a metric or one of its alternatives."""
    found: set[str | None] = set()
    for key, entry in metrics.items():
        # The activity maximum is the activity's own value, not a precedence source.
        if not isinstance(entry, dict) or "max_hr" in key:
            continue
        found.add(entry.get("source_provider"))
        found.update(
            alternative.get("source_provider")
            for alternative in entry.get("alternatives", ())
        )
    return found


class IntervalsValuesAreNotCurrentTests(unittest.TestCase):
    def test_no_current_metric_names_intervals_in_any_consumer_case(self) -> None:
        for case in CASES:
            with self.subTest(case=case.name):
                self.assertNotIn("intervals", _providers(_metrics(case)))

    def test_intervals_only_data_gives_no_threshold_vo2max_or_weight(self) -> None:
        metrics = _metrics(_case("intervals_only"))

        for key in (
            "cycling_ftp_watts",
            "run_threshold_watts",
            "bike_threshold_hr_bpm",
            "run_threshold_hr_bpm",
            "run_threshold_pace_seconds_per_km",
            "cycling_vo2max_ml_kg_min",
            "running_vo2max_ml_kg_min",
            "body_fat_pct",
            "weight_kg",
        ):
            with self.subTest(key=key):
                self.assertIsNone(metrics[key]["value"])
        for key in ("w_prime_j", "run_zone2_pace_seconds_per_km"):
            self.assertNotIn(key, metrics)

    def test_the_ftp_is_garmins_when_both_providers_report_one(self) -> None:
        case = _case("complete")
        garmin_ftp = (
            case.garmin
            and garmin_performance_history.current_garmin_metrics(case.garmin, TODAY)[
                "cycling_ftp_watts"
            ]
        )
        metrics = _metrics(case)

        self.assertIsNotNone(garmin_ftp["value"])
        self.assertEqual(metrics["cycling_ftp_watts"]["value"], garmin_ftp["value"])
        self.assertEqual(metrics["cycling_ftp_watts"]["source_provider"], "garmin")
        self.assertNotIn("alternatives", metrics["cycling_ftp_watts"])

    def test_intervals_observations_are_no_current_inputs(self) -> None:
        for case in CASES:
            intervals_only = tuple(
                row
                for row in _observations(case)
                if row.provenance.provider is ProviderId.INTERVALS
            )
            with self.subTest(case=case.name):
                inputs = read_current_inputs(
                    ObservationStub(intervals_only), None, as_of=TODAY
                )
                self.assertEqual(inputs, NO_CURRENT_INPUTS)

    def test_stored_sport_settings_and_the_indoor_ftp_feed_no_zone_threshold(
        self,
    ) -> None:
        intervals_only = tuple(
            row
            for row in _observations(_case("complete"))
            if row.provenance.provider is ProviderId.INTERVALS
        )
        self.assertTrue(
            any(
                row.kind in (MetricKind.FTP, MetricKind.INDOOR_FTP)
                for row in intervals_only
            )
        )

        inputs = read_current_inputs(ObservationStub(intervals_only), None, as_of=TODAY)

        self.assertEqual(inputs.zone_thresholds, ())
        self.assertEqual(inputs.threshold_candidates, ())

    def test_the_current_inputs_carry_no_intervals_fields(self) -> None:
        names = set(CanonicalCurrentInputs.__dataclass_fields__)

        self.assertEqual(
            names,
            {
                "wahoo_ftp",
                "wahoo_weight",
                "zone_thresholds",
                "threshold_candidates",
                "configured_thresholds",
                "wahoo_activity_max_hr",
                "preferences",
            },
        )


class CanonicalCurrentFromTablesTests(CanonicalReadFixture):
    def test_populated_tables_serve_the_current_metrics(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        with self.manager.reader() as db:
            inputs = read_performance_inputs(
                selector, db, activity_reader=selector, as_of=TODAY
            )
        self.assertIsNotNone(inputs)
        assert inputs is not None
        legacy = current_performance_context(
            GarminSyncStatus.from_state(self.garmin),
            {},
            TODAY,
            canonical=EMPTY_PERFORMANCE_INPUTS,
        )
        canonical = current_performance_context(
            GarminSyncStatus.from_state(self.garmin), {}, TODAY, canonical=inputs
        )
        # Without canonical inputs the context is unavailable (#1416).
        self.assertFalse(legacy["available"])
        self.assertEqual(legacy["metrics"], {})
        self.assertNotIn("cycling_eftp_watts", canonical["metrics"])
        # Garmin values are read from the canonical inputs (#1415); the stored
        # Intervals.icu athlete settings are not a source.
        providers = {
            value.get("source_provider") for value in canonical["metrics"].values()
        }
        self.assertIn("garmin", providers)
        self.assertNotIn("intervals", providers)


def _wahoo_ftp(value: float, sport_family: int = 0) -> Observation:
    (record,) = map_wahoo_power_zones(
        [
            {
                "id": 1,
                "workout_type_family_id": sport_family,
                "ftp": value,
                "updated_at": "2026-10-01T10:00:00Z",
            }
        ],
        zone=UTC,
        retrieved_at=RETRIEVED_AT,
    ).records
    return record


def _wahoo_weight(value: float) -> Observation:
    (record,) = map_wahoo_user(
        {"weight": value}, observed_on=SYNC_DAY, retrieved_at=RETRIEVED_AT
    ).records
    return record


class WahooFallbackReadTests(unittest.TestCase):
    def test_stored_wahoo_ftp_and_weight_are_the_only_current_inputs(self) -> None:
        reader = ObservationStub((_wahoo_ftp(250), _wahoo_weight(78.5)))

        inputs = read_current_inputs(reader, None, as_of=TODAY)

        assert inputs is not None
        assert inputs.wahoo_ftp is not None
        assert inputs.wahoo_weight is not None
        self.assertEqual(250, inputs.wahoo_ftp.value.value)
        self.assertEqual(78.5, inputs.wahoo_weight.value.value)

    def test_only_a_wahoo_ride_ftp_is_read(self) -> None:
        wahoo_ftp = _wahoo_ftp(300)
        intervals_ftp = replace(
            wahoo_ftp,
            provenance=replace(wahoo_ftp.provenance, provider=ProviderId.INTERVALS),
        )
        run_ftp = _wahoo_ftp(280, sport_family=1)

        for observation in (intervals_ftp, run_ftp):
            reader = ObservationStub((observation,))
            self.assertIsNone(read_current_inputs(reader, None, as_of=TODAY).wahoo_ftp)

    def test_no_stored_wahoo_rows_yields_empty_inputs(self) -> None:
        self.assertEqual(
            read_current_inputs(ObservationStub(()), None, as_of=TODAY),
            NO_CURRENT_INPUTS,
        )


AS_OF: Final = TODAY
WAHOO_AGE_LIMIT_DAYS: Final = 90


def _wahoo_ftp_on(value: float, day: date) -> Observation:
    (record,) = map_wahoo_power_zones(
        [
            {
                "id": 1,
                "workout_type_family_id": 0,
                "ftp": value,
                "updated_at": f"{day.isoformat()}T10:00:00Z",
            }
        ],
        zone=UTC,
        retrieved_at=RETRIEVED_AT,
    ).records
    return record


def _wahoo_weight_on(value: float, day: date) -> Observation:
    (record,) = map_wahoo_user(
        {"weight": value}, observed_on=day, retrieved_at=RETRIEVED_AT
    ).records
    return record


class _UnitOfWorkManager:
    """Opens a unit of work without a database; the stub reader needs no connection."""

    def unit_of_work(self) -> contextlib.AbstractContextManager[None]:
        return contextlib.nullcontext()

    read_snapshot = unit_of_work


class WahooAgeLimitProductionReadTests(unittest.TestCase):
    """A Wahoo FTP or weight older than its limit is not current on the read day.

    The stored rows stay readable: history keeps them, and a read on a day within
    the limit still uses them.
    """

    class ActivityReader:
        def activity_summaries(self, _db, *, start=None, end=None, limit=None):
            return ()

        def summary_fingerprints(self, _db, _keys):
            return {}

    def _stored(self, day: date) -> ObservationStub:
        return ObservationStub((_wahoo_ftp_on(250, day), _wahoo_weight_on(78.5, day)))

    def test_a_wahoo_value_91_days_old_is_not_current(self) -> None:
        stale = AS_OF - timedelta(days=WAHOO_AGE_LIMIT_DAYS + 1)
        inputs = read_performance_inputs(
            self._stored(stale),
            None,
            activity_reader=self.ActivityReader(),
            as_of=AS_OF,
        )
        assert inputs is not None
        self.assertEqual(inputs.current, NO_CURRENT_INPUTS)

    def test_a_wahoo_value_90_days_old_is_current(self) -> None:
        limit = AS_OF - timedelta(days=WAHOO_AGE_LIMIT_DAYS)
        inputs = read_performance_inputs(
            self._stored(limit),
            None,
            activity_reader=self.ActivityReader(),
            as_of=AS_OF,
        )
        assert inputs is not None
        assert inputs.current is not None
        assert inputs.current.wahoo_ftp is not None
        assert inputs.current.wahoo_weight is not None
        self.assertEqual(250, inputs.current.wahoo_ftp.value.value)
        self.assertEqual(78.5, inputs.current.wahoo_weight.value.value)

    def test_the_stale_value_stays_stored_and_is_read_within_the_limit(self) -> None:
        stale = AS_OF - timedelta(days=WAHOO_AGE_LIMIT_DAYS + 1)
        reader = self._stored(stale)
        read_performance_inputs(
            reader,
            None,
            activity_reader=self.ActivityReader(),
            as_of=AS_OF,
        )
        # History: the store still returns both stale Wahoo rows.
        self.assertEqual(
            [stale], [o.observed_on for o in reader.observations(None, MetricKind.FTP)]
        )
        self.assertEqual(
            [stale],
            [o.observed_on for o in reader.observations(None, MetricKind.WEIGHT)],
        )
        # Reads: the same rows are used once the read day is within the limit.
        within = stale + timedelta(days=WAHOO_AGE_LIMIT_DAYS)
        inputs = read_performance_inputs(
            reader,
            None,
            activity_reader=self.ActivityReader(),
            as_of=within,
        )
        assert inputs is not None
        assert inputs.current is not None
        assert inputs.current.wahoo_ftp is not None
        self.assertEqual(250, inputs.current.wahoo_ftp.value.value)

    def test_the_coach_context_read_applies_the_athlete_day(self) -> None:
        stale = AS_OF - timedelta(days=WAHOO_AGE_LIMIT_DAYS + 1)
        reader = self._stored(stale)
        source = CanonicalPerformanceSource(
            database_manager=_UnitOfWorkManager,
            observation_reader=lambda: reader,
            activity_summaries=self.ActivityReader,
        )
        context = CoachPerformanceContextReader(
            None, None, None, today=lambda: AS_OF, canonical=source
        )
        inputs = context.read_inputs()
        assert inputs is not None
        self.assertEqual(inputs.current, NO_CURRENT_INPUTS)
