"""Current sport thresholds and VO2max read from canonical observations.

The threshold heart rate and VO2max values are read from the canonical observations
of the snapshot's own sync. Each comparison is between whole metric dictionaries,
including source labels, so the canonical read must reproduce the legacy output.
All storage is temporary and every provider is mocked by fixtures.
"""

from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any, Final

from canonical_consumer_parity import (
    CASES,
    RETRIEVED_AT,
    TODAY,
    Case,
    _latest_wellness,
    _latest_wellness_day,
    _observations,
)
from canonical_read_support import CanonicalReadFixture, make_selector, populate

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.performance import garmin_metrics as performance_garmin_metrics
from backend.performance.canonical_current import (
    CanonicalCurrentInputs,
    read_current_inputs,
)
from backend.performance.canonical_inputs import read_performance_inputs
from backend.performance.context import current_performance_context
from backend.performance.current_metrics import current_performance_metrics
from backend.providers.source_labels import SourceView, observation_source_label
from backend.runtime.ports import ObservationReader

SYNC_DAY = date(2026, 10, 12)
SENSOR_KINDS = (MetricKind.THRESHOLD_HR, MetricKind.VO2MAX)
SYNC_KINDS = (MetricKind.THRESHOLD_HR, MetricKind.VO2MAX, MetricKind.WEIGHT)


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


def _legacy(case: Case) -> dict[str, Any]:
    garmin = performance_garmin_metrics.garmin_performance_metrics(case.garmin, TODAY)
    return current_performance_metrics(case.intervals, case.profile, garmin)


def _read(
    reader: ObservationStub, snapshot: dict[str, Any] | None
) -> CanonicalCurrentInputs | None:
    """Read a snapshot with its latest wellness day, as the assembly does."""
    latest = _latest_wellness_day(_latest_wellness(snapshot or {}))
    return read_current_inputs(reader, None, latest_wellness_day=latest)


def _canonical(case: Case, observations: tuple[Observation, ...] | None = None) -> Any:
    garmin = performance_garmin_metrics.garmin_performance_metrics(case.garmin, TODAY)
    reader = ObservationStub(
        _observations(case) if observations is None else observations
    )
    inputs = _read(reader, case.intervals)
    return current_performance_metrics(
        case.intervals, case.profile, garmin, canonical=inputs
    )


def _inputs(case: Case) -> CanonicalCurrentInputs:
    inputs = _read(ObservationStub(_observations(case)), case.intervals)
    assert inputs is not None
    return inputs


# (sport, Intervals type, legacy metric key, sport-setting field, kind, value)
SPORT_METRICS: Final = (
    (Sport.RIDE, "Ride", "bike_threshold_hr_bpm", "lthr", MetricKind.THRESHOLD_HR, 175),
    (Sport.RUN, "Run", "run_threshold_hr_bpm", "lthr", MetricKind.THRESHOLD_HR, 180),
    (Sport.RIDE, "Ride", "cycling_vo2max_ml_kg_min", "vo2max", MetricKind.VO2MAX, 55.5),
    (Sport.RUN, "Run", "running_vo2max_ml_kg_min", "vo2max", MetricKind.VO2MAX, 53.5),
)


def _setting(entry_id: int, sport_type: str, **fields: float) -> dict[str, Any]:
    return {"id": entry_id, "types": [sport_type], **fields}


def _with_sport_settings(settings: list[dict[str, Any]]) -> Case:
    case = _case("intervals_only")
    intervals = copy.deepcopy(case.intervals)
    intervals["athlete"]["sport_settings"] = settings
    return replace(case, intervals=intervals)


def _sync_sport_values(case: Case, sport: Sport, kind: MetricKind) -> list[float]:
    """Values of this sync's Intervals observations of ``kind`` for ``sport``."""
    return [
        observation.value.value
        for observation in _observations(case)
        if observation.kind is kind
        and observation.sport is sport
        and observation.provenance.provider is ProviderId.INTERVALS
    ]


def _sensor_rows(case: Case, *, retrieved_at: datetime) -> tuple[Observation, ...]:
    """Intervals threshold and VO2max rows of ``case``, re-stamped to ``retrieved_at``."""
    return tuple(
        replace(
            observation,
            provenance=replace(observation.provenance, retrieved_at=retrieved_at),
        )
        for observation in _observations(case)
        if observation.kind in SENSOR_KINDS
        and observation.provenance.provider is ProviderId.INTERVALS
    )


class CanonicalCurrentParityTests(unittest.TestCase):
    def test_each_consumer_case_matches_the_legacy_current_metrics(self) -> None:
        for case in CASES:
            with self.subTest(case=case.name):
                self.assertEqual(_canonical(case), _legacy(case))

    def test_sport_values_missing_from_the_legacy_snapshot_stay_legacy(self) -> None:
        case = _case("intervals_only")
        without_sport_lthr = copy.deepcopy(case.intervals)
        for setting in without_sport_lthr["athlete"]["sport_settings"]:
            setting.pop("lthr", None)
        variant = replace(case, intervals=without_sport_lthr)
        metrics = _canonical(variant, _observations(case))
        self.assertEqual(metrics, _legacy(variant))

    def test_athlete_wide_threshold_is_the_fallback_with_the_general_label(
        self,
    ) -> None:
        case = _case("intervals_only")
        intervals = copy.deepcopy(case.intervals)
        intervals["athlete"]["lthr"] = 171
        for setting in intervals["athlete"]["sport_settings"]:
            setting.pop("lthr", None)
        variant = replace(case, intervals=intervals)
        metrics = _canonical(variant, _observations(variant))
        self.assertEqual(metrics, _legacy(variant))
        self.assertEqual(metrics["bike_threshold_hr_bpm"]["value"], 171)
        self.assertEqual(
            metrics["bike_threshold_hr_bpm"]["source"], "Intervals.icu (allgemein)"
        )
        inputs = _read(ObservationStub(_observations(variant)), variant.intervals)
        assert inputs is not None and inputs.athlete_threshold_hr is not None
        self.assertIsNone(inputs.athlete_threshold_hr.sport)
        self.assertEqual(
            observation_source_label(
                inputs.athlete_threshold_hr, SourceView.CURRENT_METRIC
            ),
            "Intervals.icu (allgemein)",
        )

    def test_sport_labels_match_the_legacy_view(self) -> None:
        inputs = _inputs(_case("intervals_only"))
        assert inputs.bike_threshold_hr and inputs.cycling_vo2max
        for observation in (inputs.bike_threshold_hr[0], inputs.cycling_vo2max[0]):
            self.assertEqual(
                observation_source_label(observation, SourceView.CURRENT_METRIC),
                "Intervals.icu",
            )

    def test_rows_from_an_earlier_sync_never_change_the_current_values(self) -> None:
        case = _case("intervals_only")
        stale = tuple(
            replace(row, value=replace(row.value, value=row.value.value + 50))
            for row in _sensor_rows(case, retrieved_at=RETRIEVED_AT - timedelta(days=1))
        )
        self.assertEqual(
            _canonical(case, (*_observations(case), *stale)), _legacy(case)
        )

    def test_garmin_rows_never_enter_the_intervals_current_values(self) -> None:
        case = _case("complete")
        garmin_only = tuple(
            observation
            for observation in _observations(case)
            if observation.provenance.provider is ProviderId.GARMIN
        )
        inputs = _read(ObservationStub(garmin_only), case.intervals)
        self.assertIsNone(inputs)


class CanonicalSportMatchTests(unittest.TestCase):
    """A canonical sport value is used only when it equals the legacy-selected value."""

    def test_first_entry_without_the_metric_keeps_the_legacy_value(self) -> None:
        for _sport, sport_type, key, field, _kind, value in SPORT_METRICS:
            with self.subTest(key=key):
                case = _with_sport_settings(
                    [_setting(1, sport_type), _setting(2, sport_type, **{field: value})]
                )
                self.assertEqual(_canonical(case), _legacy(case))

    def test_first_matching_entry_wins_over_a_later_different_value(self) -> None:
        for sport, sport_type, key, field, kind, value in SPORT_METRICS:
            with self.subTest(key=key):
                first, second = value, value + 7
                case = _with_sport_settings(
                    [
                        _setting(1, sport_type, **{field: first}),
                        _setting(2, sport_type, **{field: second}),
                    ]
                )
                metrics = _canonical(case)
                self.assertEqual(metrics, _legacy(case))
                self.assertEqual(metrics[key]["value"], first)
                self.assertEqual(metrics[key]["source"], "Intervals.icu")
                self.assertEqual(
                    sorted(_sync_sport_values(case, sport, kind)), [first, second]
                )

    def test_single_entry_takes_the_canonical_label_and_value(self) -> None:
        for sport, sport_type, key, field, kind, value in SPORT_METRICS:
            with self.subTest(key=key):
                case = _with_sport_settings([_setting(1, sport_type, **{field: value})])
                metrics = _canonical(case)
                self.assertEqual(metrics, _legacy(case))
                self.assertEqual(metrics[key]["value"], value)
                self.assertEqual(metrics[key]["source"], "Intervals.icu")
                self.assertEqual(_sync_sport_values(case, sport, kind), [value])


class CanonicalCurrentInputTests(unittest.TestCase):
    def test_reads_use_the_utc_sync_day_with_one_day_either_side(self) -> None:
        case = _case("intervals_only")
        reader = ObservationStub(_observations(case))
        _read(reader, case.intervals)
        window = (SYNC_DAY - timedelta(days=1), SYNC_DAY + timedelta(days=1))
        # The sync instant is found by one unbounded read per current-metric kind.
        self.assertEqual(
            reader.calls[:3],
            [(kind, None, None, None) for kind in SYNC_KINDS],
        )
        self.assertEqual(
            reader.calls[3:],
            [
                (MetricKind.THRESHOLD_HR, *window, None),
                (MetricKind.VO2MAX, *window, None),
                (MetricKind.WEIGHT, *window, None),
            ],
        )

    def test_weight_window_extends_to_an_older_latest_wellness_day(self) -> None:
        case = _case("intervals_only")
        reader = ObservationStub(_observations(case))
        read_current_inputs(reader, None, latest_wellness_day=date(2026, 10, 1))
        self.assertEqual(
            reader.calls[-1],
            (MetricKind.WEIGHT, date(2026, 10, 1), SYNC_DAY + timedelta(days=1), None),
        )

    def test_observations_without_an_intervals_sync_instant_yield_none(self) -> None:
        case = _case("intervals_only")
        observations = _observations(case)
        unstamped = tuple(
            replace(
                observation,
                provenance=replace(observation.provenance, retrieved_at=None),
            )
            for observation in observations
        )
        reader = ObservationStub(unstamped)
        self.assertIsNone(read_current_inputs(reader, None))
        self.assertEqual({call[1:] for call in reader.calls}, {(None, None, None)})

    def test_sync_without_stored_sport_values_yields_none(self) -> None:
        self.assertIsNone(read_current_inputs(ObservationStub(()), None))


class CanonicalWeightTests(unittest.TestCase):
    def test_wellness_weight_matches_the_legacy_value_and_label(self) -> None:
        case = _case("intervals_only")
        metrics = _canonical(case)
        self.assertEqual(metrics["weight_kg"], _legacy(case)["weight_kg"])
        self.assertEqual(metrics["weight_kg"]["value"], 80.6)
        self.assertEqual(metrics["weight_kg"]["source"], "Intervals.icu Wellness")

    def test_athlete_weight_is_the_fallback_with_the_intervals_label(self) -> None:
        case = _case("sparse_profile")
        intervals = copy.deepcopy(case.intervals)
        del intervals["recent_wellness"][-1]["weight"]
        variant = replace(case, intervals=intervals)
        metrics = _canonical(variant, _observations(variant))
        self.assertEqual(metrics["weight_kg"], _legacy(variant)["weight_kg"])
        self.assertEqual(metrics["weight_kg"]["value"], 79.9)
        self.assertEqual(metrics["weight_kg"]["source"], "Intervals.icu")

    def test_older_wellness_day_weight_is_never_used(self) -> None:
        case = _case("intervals_only")
        intervals = copy.deepcopy(case.intervals)
        del intervals["recent_wellness"][-1]["weight"]
        variant = replace(case, intervals=intervals)
        observations = _observations(variant)
        inputs = _read(ObservationStub(observations), variant.intervals)
        assert inputs is not None
        self.assertIsNone(inputs.wellness_weight)
        metrics = _canonical(variant, observations)
        self.assertEqual(metrics["weight_kg"], _legacy(variant)["weight_kg"])
        self.assertNotEqual(metrics["weight_kg"]["value"], 80.9)

    def test_weight_rows_from_an_earlier_sync_never_change_the_current_weight(
        self,
    ) -> None:
        case = _case("intervals_only")
        earlier = RETRIEVED_AT - timedelta(days=1)
        stale = tuple(
            replace(
                row,
                value=replace(row.value, value=row.value.value + 5),
                provenance=replace(row.provenance, retrieved_at=earlier),
            )
            for row in _observations(case)
            if row.kind is MetricKind.WEIGHT
        )
        self.assertEqual(
            _canonical(case, (*_observations(case), *stale)), _legacy(case)
        )


class CanonicalCurrentFromTablesTests(CanonicalReadFixture):
    def test_populated_tables_reproduce_the_legacy_current_metrics(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        with self.manager.reader() as db:
            inputs = read_performance_inputs(selector, db, self.intervals)
        self.assertIsNotNone(inputs)
        assert inputs is not None
        self.assertIsNotNone(inputs.current)
        legacy = current_performance_context(self.intervals, self.garmin, {}, TODAY)
        canonical = current_performance_context(
            self.intervals, self.garmin, {}, TODAY, canonical=inputs
        )
        self.assertEqual(canonical["metrics"], legacy["metrics"])
