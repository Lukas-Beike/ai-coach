"""7-day resting HR and readiness averages read from canonical observations.

The canonical average replaces the legacy average only when its per-day window
covers the same days and rounds to the same number. Otherwise the legacy average is
kept. The populated temporary database is the end-to-end check: the performance
payload with canonical inputs must equal the legacy payload. Every provider is mocked
by fixtures and all storage is temporary.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import patch

from canonical_consumer_parity import TODAY
from canonical_read_support import CanonicalReadFixture, make_selector, populate

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance import recovery_context
from backend.performance.canonical_inputs import read_performance_inputs
from backend.performance.canonical_recovery_averages import (
    CanonicalRecoveryAverageInputs,
    prefer_canonical_average,
    read_recovery_average_inputs,
)
from backend.performance.context import current_performance_context
from backend.performance.recovery_context import performance_recovery_context

RETRIEVED = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
UNITS = {MetricKind.RESTING_HR: "bpm", MetricKind.READINESS: "score"}
WINDOW_START = date(2026, 10, 6)
WINDOW_DAYS = [date.fromordinal(WINDOW_START.toordinal() + step) for step in range(7)]


def _observation(
    kind: MetricKind,
    value: float,
    day: date,
    provider: ProviderId = ProviderId.GARMIN,
) -> Observation:
    recorded_by = (
        RecordingOrigin.GARMIN
        if provider is ProviderId.GARMIN
        else RecordingOrigin.MANUAL
    )
    return Observation(
        kind=kind,
        value=MetricValue(value, UNITS[kind]),
        observed_on=day,
        observed_at=None,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=f"{kind.value}-{day.isoformat()}",
            recorded_by=recorded_by,
            retrieved_at=RETRIEVED,
            label=None,
        ),
    )


class _FakeReader:
    """Serves fixed observations per kind and records each read."""

    def __init__(self, by_kind: dict[MetricKind, list[Observation]]) -> None:
        self._by_kind = by_kind
        self.calls: list[tuple[MetricKind, date | None, date | None]] = []

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        self.calls.append((kind, start, end))
        return tuple(self._by_kind.get(kind, []))


def _dump(value: Any) -> str:
    return json.dumps(value, default=str)


def _garmin_resting(values: list[float]) -> dict[str, Any]:
    return {
        "resting_hr": [
            {"calendarDate": day.isoformat(), "restingHeartRate": value}
            for day, value in zip(WINDOW_DAYS, values, strict=False)
        ]
    }


def _garmin_observations(values: list[float]) -> list[Observation]:
    return [
        _observation(MetricKind.RESTING_HR, value, day)
        for day, value in zip(WINDOW_DAYS, values, strict=False)
    ]


def _wellness_rows(key: str, values: list[float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {"id": day.isoformat(), key: value}
        for day, value in zip(WINDOW_DAYS, values, strict=False)
    ]
    return rows


def _intervals_observations(kind: MetricKind, values: list[float]) -> list[Observation]:
    return [
        _observation(kind, value, day, ProviderId.INTERVALS)
        for day, value in zip(WINDOW_DAYS, values, strict=False)
    ]


def _legacy_values(values: list[float]) -> list[tuple[date, float]]:
    return [(day, value) for day, value in zip(WINDOW_DAYS, values, strict=False)]


class ReadRecoveryAverageInputsTests(unittest.TestCase):
    def test_both_kinds_are_read_from_the_start_without_an_end_bound(self) -> None:
        reader = _FakeReader({})
        start = WINDOW_START
        inputs = read_recovery_average_inputs(reader, None, start=start)
        self.assertEqual(
            reader.calls,
            [
                (MetricKind.RESTING_HR, start, None),
                (MetricKind.READINESS, start, None),
            ],
        )
        self.assertEqual(inputs, CanonicalRecoveryAverageInputs((), ()))

    def test_read_observations_are_kept_per_kind(self) -> None:
        resting = _observation(MetricKind.RESTING_HR, 50.0, WINDOW_DAYS[0])
        readiness = _observation(
            MetricKind.READINESS, 70.0, WINDOW_DAYS[0], ProviderId.INTERVALS
        )
        reader = _FakeReader(
            {MetricKind.RESTING_HR: [resting], MetricKind.READINESS: [readiness]}
        )
        inputs = read_recovery_average_inputs(reader, None, start=WINDOW_START)
        self.assertEqual(inputs.resting_hr, (resting,))
        self.assertEqual(inputs.readiness, (readiness,))


class PreferCanonicalAverageTests(unittest.TestCase):
    def test_missing_canonical_inputs_keep_the_legacy_average(self) -> None:
        legacy = _legacy_values([50.0, 52.0])
        self.assertEqual(
            prefer_canonical_average(legacy, None, ProviderId.GARMIN, TODAY), 51.0
        )

    def test_no_days_on_either_side_gives_no_average(self) -> None:
        self.assertIsNone(prefer_canonical_average([], (), ProviderId.GARMIN, TODAY))

    def test_garmin_days_that_match_give_the_legacy_average(self) -> None:
        values = [50.0, 52.0, 54.0, 51.0, 53.0, 55.0, 49.0]
        observations = _garmin_observations(values)
        average = prefer_canonical_average(
            _legacy_values(values), observations, ProviderId.GARMIN, TODAY
        )
        self.assertEqual(average, 52.0)

    def test_intervals_days_that_match_give_the_legacy_average(self) -> None:
        values = [48.0, 49.0, 50.0, 51.0, 52.0, 53.0, 54.0]
        observations = _intervals_observations(MetricKind.RESTING_HR, values)
        average = prefer_canonical_average(
            _legacy_values(values), observations, ProviderId.INTERVALS, TODAY
        )
        self.assertEqual(average, 51.0)

    def test_a_missing_day_in_the_window_keeps_the_legacy_average(self) -> None:
        values = [50.0, 52.0, 54.0]
        observations = _garmin_observations(values)[:2]
        average = prefer_canonical_average(
            _legacy_values(values), observations, ProviderId.GARMIN, TODAY
        )
        self.assertEqual(average, 52.0)

    def test_a_canonical_value_that_differs_keeps_the_legacy_average(self) -> None:
        legacy = _legacy_values([50.0, 52.0])
        observations = [
            _observation(MetricKind.RESTING_HR, 50.0, WINDOW_DAYS[0]),
            _observation(MetricKind.RESTING_HR, 60.0, WINDOW_DAYS[1]),
        ]
        average = prefer_canonical_average(
            legacy, observations, ProviderId.GARMIN, TODAY
        )
        self.assertEqual(average, 51.0)

    def test_other_provider_days_do_not_count_for_the_provider(self) -> None:
        legacy = _legacy_values([50.0])
        observations = [
            _observation(
                MetricKind.RESTING_HR, 50.0, WINDOW_DAYS[0], ProviderId.INTERVALS
            )
        ]
        average = prefer_canonical_average(
            legacy, observations, ProviderId.GARMIN, TODAY
        )
        self.assertEqual(average, 50.0)

    def test_days_outside_the_window_are_ignored(self) -> None:
        legacy = _legacy_values([50.0])
        observations = [
            _observation(MetricKind.RESTING_HR, 99.0, WINDOW_START.replace(day=5)),
            _observation(MetricKind.RESTING_HR, 50.0, WINDOW_DAYS[0]),
        ]
        average = prefer_canonical_average(
            legacy, observations, ProviderId.GARMIN, TODAY
        )
        self.assertEqual(average, 50.0)

    def test_the_first_observation_of_a_day_wins(self) -> None:
        legacy = _legacy_values([50.0])
        observations = [
            _observation(MetricKind.RESTING_HR, 50.0, WINDOW_DAYS[0]),
            _observation(MetricKind.RESTING_HR, 70.0, WINDOW_DAYS[0]),
        ]
        average = prefer_canonical_average(
            legacy, observations, ProviderId.GARMIN, TODAY
        )
        self.assertEqual(average, 50.0)

    def test_canonical_days_without_legacy_days_keep_the_legacy_empty_average(
        self,
    ) -> None:
        observations = [
            _observation(
                MetricKind.READINESS, 70.0, WINDOW_DAYS[0], ProviderId.INTERVALS
            )
        ]
        self.assertIsNone(
            prefer_canonical_average([], observations, ProviderId.INTERVALS, TODAY)
        )


class RecoveryContextAverageTests(unittest.TestCase):
    def test_garmin_resting_hr_average_matches_legacy_with_canonical_days(self) -> None:
        values = [50.0, 52.0, 54.0, 51.0, 53.0, 55.0, 49.0]
        garmin = _garmin_resting(values)
        latest = {"id": TODAY.isoformat()}
        averages = CanonicalRecoveryAverageInputs(
            resting_hr=tuple(_garmin_observations(values)), readiness=()
        )
        legacy = performance_recovery_context(garmin, latest, [latest], TODAY)
        served = performance_recovery_context(
            garmin, latest, [latest], TODAY, averages=averages
        )
        self.assertEqual(_dump(served), _dump(legacy))
        self.assertEqual(served["resting_hr_average"], 52.0)

    def test_intervals_resting_hr_average_matches_legacy_with_canonical_days(
        self,
    ) -> None:
        values = [48.0, 49.0, 50.0, 51.0, 52.0, 53.0, 54.0]
        rows = _wellness_rows("restingHR", values)
        latest = rows[-1]
        averages = CanonicalRecoveryAverageInputs(
            resting_hr=tuple(_intervals_observations(MetricKind.RESTING_HR, values)),
            readiness=(),
        )
        legacy = performance_recovery_context({}, latest, rows, TODAY)
        served = performance_recovery_context(
            {}, latest, rows, TODAY, averages=averages
        )
        self.assertEqual(_dump(served), _dump(legacy))
        self.assertEqual(served["resting_hr_average"], 51.0)
        self.assertEqual(served["resting_hr_source"], "Intervals.icu Wellness")

    def test_readiness_average_matches_legacy_with_canonical_days(self) -> None:
        values = [60.0, 62.0, 64.0, 66.0, 68.0, 70.0, 72.0]
        rows = _wellness_rows("readiness", values)
        latest = rows[-1]
        averages = CanonicalRecoveryAverageInputs(
            resting_hr=(),
            readiness=tuple(_intervals_observations(MetricKind.READINESS, values)),
        )
        legacy = performance_recovery_context({}, latest, rows, TODAY)
        served = performance_recovery_context(
            {}, latest, rows, TODAY, averages=averages
        )
        self.assertEqual(_dump(served), _dump(legacy))
        self.assertEqual(served["readiness_average"], 66.0)

    def test_mismatched_canonical_days_keep_the_legacy_averages(self) -> None:
        values = [48.0, 49.0, 50.0, 51.0, 52.0, 53.0, 54.0]
        rows = _wellness_rows("restingHR", values)
        latest = rows[-1]
        short = tuple(_intervals_observations(MetricKind.RESTING_HR, values)[1:])
        averages = CanonicalRecoveryAverageInputs(
            resting_hr=short,
            readiness=tuple(
                _intervals_observations(MetricKind.READINESS, [70.0] * 7)[:3]
            ),
        )
        legacy = performance_recovery_context({}, latest, rows, TODAY)
        served = performance_recovery_context(
            {}, latest, rows, TODAY, averages=averages
        )
        self.assertEqual(_dump(served), _dump(legacy))

    def test_hrv_average_stays_on_the_legacy_path(self) -> None:
        values = [50.0, 52.0, 54.0, 51.0, 53.0, 55.0, 49.0]
        garmin = _garmin_resting(values)
        latest = {"id": TODAY.isoformat()}
        averages = CanonicalRecoveryAverageInputs(
            resting_hr=tuple(_garmin_observations(values)), readiness=()
        )
        with patch.object(
            recovery_context,
            "prefer_canonical_average",
            wraps=recovery_context.prefer_canonical_average,
        ) as spy:
            performance_recovery_context(
                garmin, latest, [latest], TODAY, averages=averages
            )
        offered = [call.args[1] for call in spy.call_args_list]
        self.assertIn(averages.resting_hr, offered)
        self.assertIn(None, offered)


class PopulatedRecoveryAverageTests(CanonicalReadFixture):
    def test_populated_payload_with_canonical_averages_equals_legacy(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        with self.manager.reader() as db:
            inputs = read_performance_inputs(selector, db, self.intervals)
        self.assertIsNotNone(inputs)
        assert inputs is not None
        assert inputs.recovery_averages is not None
        self.assertTrue(inputs.recovery_averages.resting_hr)
        legacy = current_performance_context(self.intervals, self.garmin, {}, TODAY)
        canonical = current_performance_context(
            self.intervals, self.garmin, {}, TODAY, canonical=inputs
        )
        self.assertEqual(_dump(canonical["comparisons"]), _dump(legacy["comparisons"]))
        self.assertEqual(_dump(canonical), _dump(legacy))
