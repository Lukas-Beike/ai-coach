"""Performance readers take activities and wellness from the canonical ports.

The readers no longer need the snapshot sections ``recent_activities``,
``raw_provider_data.activities`` and ``recent_wellness``. A populated database that
finished its backfill serves the same output from the tables when those sections
are stripped from the stored snapshot. Storage is temporary.
"""

from __future__ import annotations

import copy
import unittest
from datetime import date, timedelta
from typing import Any
from unittest.mock import Mock

from canonical_read_support import CanonicalReadFixture, make_selector, populate

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance import chart_history
from backend.performance.canonical_inputs import (
    CanonicalPerformanceInputs,
    ReadOnceObservationReader,
    read_performance_inputs,
)
from backend.performance.canonical_sections import compact_activity_rows
from backend.performance.context import current_performance_context
from backend.performance.garmin_canonical import read_garmin_state
from backend.performance.training_report import training_report
from backend.performance.wellness_days import read_wellness_days, wellness_day_values

TODAY = date(2026, 10, 12)
REPORT_START = date(2026, 9, 1)


def _stripped(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Strip activity and wellness sections served by canonical ports."""
    stripped = {
        key: copy.deepcopy(value)
        for key, value in snapshot.items()
        if key != "recent_activities"
    }
    stripped["recent_wellness"] = []
    raw = dict(stripped.get("raw_provider_data") or {})
    raw.pop("activities", None)
    raw.pop("wellness", None)
    stripped["raw_provider_data"] = raw
    return stripped


class SectionHelperTests(unittest.TestCase):
    def test_empty_observations_have_no_wellness_days(self) -> None:
        self.assertEqual(read_wellness_days(_NoObservations(), object()), ())

    def test_compact_activity_rows_keep_the_planning_fields_only(self) -> None:
        compacted = compact_activity_rows(
            [{"id": "a1", "name": "Ride", "private_note": "drop me"}]
        )
        self.assertEqual(compacted[0]["id"], "a1")
        self.assertNotIn("private_note", compacted[0])

    def test_wellness_days_keep_observation_provenance(self) -> None:
        observation = _observation(MetricKind.CTL, TODAY, 55, record=TODAY.isoformat())
        reader = Mock(spec=["observations"])
        reader.observations.side_effect = lambda _db, kind: (
            (observation,) if kind is MetricKind.CTL else ()
        )
        (day,) = read_wellness_days(reader, object())
        self.assertIs(day.observations[MetricKind.CTL], observation)

    def test_subjective_ratings_are_rebuilt_from_their_observations(self) -> None:
        provenance = Provenance(
            provider=ProviderId.INTERVALS,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=TODAY.isoformat(),
            recorded_by=RecordingOrigin.MANUAL,
            retrieved_at=None,
            label="Intervals.icu",
        )
        observed = {
            kind: (
                Observation(
                    kind=kind,
                    value=MetricValue(value, kind.unit),
                    observed_on=TODAY,
                    observed_at=None,
                    provenance=provenance,
                ),
            )
            for kind, value in (
                (MetricKind.SUBJECTIVE_FATIGUE, 3.0),
                (MetricKind.SUBJECTIVE_SORENESS, 1.0),
                (MetricKind.SUBJECTIVE_STRESS, 2.0),
                (MetricKind.SUBJECTIVE_MOOD, 4.0),
            )
        }
        reader = Mock(spec=["observations"])
        reader.observations.side_effect = lambda _db, kind: observed.get(kind, ())
        (day,) = read_wellness_days(reader, object())
        self.assertEqual([day.value(kind) for kind in observed], [3, 1, 2, 4])

    def test_snapshot_carrier_fields_do_not_create_wellness_days(self) -> None:
        carrier: list[dict[str, Any]] = [
            {"id": "2026-10-12", "fatigue": 3, "ctl": 1},
            {"id": "later"},
        ]
        self.assertEqual(read_wellness_days(_NoObservations(), carrier), ())

    def test_wellness_day_values_keep_wellness_days_of_one_scope_only(self) -> None:
        wellness_form = _observation(
            MetricKind.FORM, TODAY, 3.5, record=TODAY.isoformat()
        )
        ride_eftp = _observation(
            MetricKind.EFTP, TODAY, 258, record=TODAY.isoformat(), sport=Sport.RIDE
        )
        athlete_eftp = _observation(
            MetricKind.EFTP, TODAY, 262, record="athlete-1", sport=Sport.RIDE
        )
        garmin = _observation(
            MetricKind.FORM, TODAY, 9, record=TODAY.isoformat(), garmin=True
        )
        self.assertEqual(wellness_day_values([wellness_form, garmin]), {TODAY: 3.5})
        self.assertEqual(
            wellness_day_values([ride_eftp, athlete_eftp], sport=Sport.RIDE),
            {TODAY: 258},
        )
        # A sport-scoped observation is not a sport-less wellness value.
        self.assertEqual(wellness_day_values([ride_eftp]), {})
        self.assertEqual(wellness_day_values([]), {})


def _observation(
    kind: MetricKind,
    day: date,
    value: float,
    *,
    record: str,
    sport: Sport | None = None,
    garmin: bool = False,
) -> Observation:
    return Observation(
        kind=kind,
        value=MetricValue(value, kind.unit),
        observed_on=day,
        observed_at=None,
        provenance=Provenance(
            provider=ProviderId.GARMIN if garmin else ProviderId.INTERVALS,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=record,
            recorded_by=RecordingOrigin.UNKNOWN,
            retrieved_at=None,
            label=None,
        ),
        sport=sport,
    )


class _NoObservations:
    def observations(self, _db, _kind, *, start=None, end=None, sport=None):
        return ()


class _StartRecorder:
    def __init__(self) -> None:
        self.starts: list[date | None] = []

    def activity_rows(
        self, _db: Any, *, start: date | None = None, end=None, limit=None
    ) -> tuple[dict[str, Any], ...]:
        self.starts.append(start)
        return ()


class ActivityWindowTests(unittest.TestCase):
    def test_performance_and_garmin_status_share_one_read_per_metric(self) -> None:
        source = Mock(spec=["observations"])
        source.observations.return_value = ()
        reader = ReadOnceObservationReader(source)
        db = object()

        read_performance_inputs(
            reader, db, activity_reader=_StartRecorder(), as_of=TODAY
        )
        reads = source.observations.call_count
        read_garmin_state(reader, db)
        reader.observations(db, MetricKind.WEIGHT, start=TODAY - timedelta(days=7))
        reader.observations(db, MetricKind.BODY_FAT, end=TODAY)

        self.assertGreater(reads, 0)
        self.assertEqual(source.observations.call_count, reads)
        kinds = [call.args[1] for call in source.observations.call_args_list]
        self.assertEqual(len(kinds), len(set(kinds)))

    def _start(self) -> date | None:
        rows = _StartRecorder()
        read_performance_inputs(
            _NoObservations(), object(), activity_reader=rows, as_of=TODAY
        )
        (start,) = rows.starts
        return start

    def test_activities_cover_the_year_before_as_of_without_wellness_days(
        self,
    ) -> None:
        self.assertEqual(self._start(), TODAY - timedelta(days=364))


class SectionReadTests(CanonicalReadFixture):
    def _inputs(
        self, snapshot: dict[str, Any]
    ) -> tuple[dict[str, Any], CanonicalPerformanceInputs]:
        selector = make_selector(self)
        with self.manager.reader() as db:
            inputs = read_performance_inputs(
                selector, db, activity_reader=selector, as_of=TODAY
            )
        self.assertIsNotNone(inputs)
        assert inputs is not None
        return snapshot, inputs

    def _legacy(self) -> tuple[dict[str, Any], CanonicalPerformanceInputs]:
        return self._inputs(copy.deepcopy(self.intervals))

    def _tables(self) -> tuple[dict[str, Any], CanonicalPerformanceInputs]:
        """Complete the backfill, then read with the sections stripped."""
        populate(self)
        selector = make_selector(self)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        stripped = _stripped(self.intervals)
        return self._inputs(stripped)

    def test_legacy_rows_reproduce_the_snapshot_sections(self) -> None:
        snapshot, inputs = self._legacy()
        self.assertEqual(list(inputs.activities or ()), snapshot["recent_activities"])
        legacy_days = [row["id"] for row in snapshot["recent_wellness"]]
        self.assertEqual(
            [day.day.isoformat() for day in inputs.wellness_days or ()], legacy_days
        )

    def test_tables_serve_the_same_performance_context_without_the_sections(
        self,
    ) -> None:
        legacy_snapshot, legacy = self._legacy()
        expected = current_performance_context(
            legacy_snapshot, self.garmin, {}, TODAY, canonical=legacy
        )
        snapshot, inputs = self._tables()
        self.assertNotIn("recent_activities", snapshot)
        actual = current_performance_context(
            snapshot, self.garmin, {}, TODAY, canonical=inputs
        )
        self.assertEqual(actual, expected)

    def test_tables_serve_the_same_training_report_without_the_sections(self) -> None:
        _legacy_snapshot, legacy = self._legacy()
        assert legacy.activity_rows is not None
        expected = training_report(
            start=REPORT_START,
            days=42,
            today=TODAY,
            activity_rows=legacy.activity_rows,
        )
        _snapshot, inputs = self._tables()
        assert inputs.activity_rows is not None
        actual = training_report(
            start=REPORT_START,
            days=42,
            today=TODAY,
            activity_rows=inputs.activity_rows,
        )
        self.assertEqual(actual, expected)

    def test_tables_serve_the_same_analysis_history_without_the_sections(self) -> None:
        legacy_snapshot, legacy = self._legacy()
        expected = chart_history.analysis_history(
            legacy_snapshot, self.garmin, TODAY, canonical=legacy
        )
        snapshot, inputs = self._tables()
        actual = chart_history.analysis_history(
            snapshot, self.garmin, TODAY, canonical=inputs
        )
        self.assertEqual(actual, expected)

    def test_observation_days_appear_in_a_stripped_snapshot(self) -> None:
        _snapshot, inputs = self._tables()
        selector = make_selector(self)
        with self.manager.reader() as db:
            observed = read_wellness_days(selector, db)
        self.assertTrue(observed)
        days = {day.day for day in inputs.wellness_days or ()}
        for day in observed:
            self.assertIn(day.day, days)


if __name__ == "__main__":
    unittest.main()
