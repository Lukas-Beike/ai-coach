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

from canonical_read_support import CanonicalReadFixture, make_selector, populate

from backend.canonical.vocabulary import MetricKind
from backend.performance import chart_history
from backend.performance.canonical_inputs import (
    CanonicalPerformanceInputs,
    read_performance_inputs,
)
from backend.performance.canonical_sections import (
    compact_activity_rows,
    read_wellness_observations,
    row_day,
    wellness_rows,
)
from backend.performance.context import current_performance_context
from backend.performance.training_report import training_report

TODAY = date(2026, 10, 12)
REPORT_START = date(2026, 9, 1)
# Wellness fields without a canonical observation; they stay on the snapshot rows.
SNAPSHOT_ONLY_WELLNESS = (
    "id",
    "tsb",
    "rampRate",
    "fatigue",
    "soreness",
    "stress",
    "mood",
    "sportInfo",
    "sport_info",
)


def _stripped(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The snapshot without the values now served by the canonical ports.

    The activity sections go entirely. The wellness rows keep only the fields that
    have no canonical observation, as the carrier of those fields.
    """
    stripped = {
        key: copy.deepcopy(value)
        for key, value in snapshot.items()
        if key != "recent_activities"
    }
    stripped["recent_wellness"] = [
        {k: v for k, v in row.items() if k in SNAPSHOT_ONLY_WELLNESS}
        for row in snapshot["recent_wellness"]
    ]
    raw = dict(stripped.get("raw_provider_data") or {})
    raw.pop("activities", None)
    raw["wellness"] = [
        {k: v for k, v in row.items() if k in SNAPSHOT_ONLY_WELLNESS}
        for row in raw.get("wellness") or ()
    ]
    stripped["raw_provider_data"] = raw
    return stripped


class SectionHelperTests(unittest.TestCase):
    def test_row_day_accepts_only_strict_iso_dates(self) -> None:
        self.assertEqual(row_day({"id": "2026-10-12"}), TODAY)
        for value in ("2026-10-12T00:00", "20261012", "2026-02-30", 5, None):
            with self.subTest(value=value):
                self.assertIsNone(row_day({"id": value}))
        self.assertIsNone(row_day({}))

    def test_compact_activity_rows_keep_the_planning_fields_only(self) -> None:
        compacted = compact_activity_rows(
            [{"id": "a1", "name": "Ride", "private_note": "drop me"}]
        )
        self.assertEqual(compacted[0]["id"], "a1")
        self.assertNotIn("private_note", compacted[0])

    def test_wellness_rows_without_carrier_or_observations_are_empty(self) -> None:
        self.assertEqual(wellness_rows([], {}), [])

    def test_carrier_rows_keep_non_canonical_fields_and_unmapped_rows(self) -> None:
        carrier: list[dict[str, Any]] = [
            {"id": "2026-10-12", "fatigue": 3, "ctl": 1},
            {"id": "later"},
        ]
        self.assertEqual(wellness_rows(carrier, {}), carrier)


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
    def _start(self, wellness_days: list[str]) -> date | None:
        rows = _StartRecorder()
        snapshot = {"recent_wellness": [{"id": day} for day in wellness_days]}
        read_performance_inputs(
            _NoObservations(), object(), snapshot, activity_reader=rows, as_of=TODAY
        )
        (start,) = rows.starts
        return start

    def test_activities_cover_the_year_before_as_of(self) -> None:
        self.assertEqual(self._start(["2026-09-01"]), TODAY - timedelta(days=364))
        self.assertEqual(self._start([]), TODAY - timedelta(days=364))

    def test_activities_reach_back_to_the_oldest_wellness_row(self) -> None:
        self.assertEqual(self._start(["2025-06-01", "2026-10-12"]), date(2025, 6, 1))


class SectionReadTests(CanonicalReadFixture):
    def _inputs(
        self, snapshot: dict[str, Any]
    ) -> tuple[dict[str, Any], CanonicalPerformanceInputs]:
        selector = make_selector(self)
        with self.manager.reader() as db:
            inputs = read_performance_inputs(
                selector, db, snapshot, activity_reader=selector, as_of=TODAY
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
        self.assertEqual([row["id"] for row in inputs.wellness_rows or ()], legacy_days)

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
        legacy_snapshot, legacy = self._legacy()
        expected = training_report(
            legacy_snapshot,
            start=REPORT_START,
            days=42,
            today=TODAY,
            activity_rows=legacy.activity_rows,
        )
        snapshot, inputs = self._tables()
        actual = training_report(
            snapshot,
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

    def test_observation_days_appear_in_the_rows_of_a_stripped_snapshot(self) -> None:
        _snapshot, inputs = self._tables()
        selector = make_selector(self)
        with self.manager.reader() as db:
            observed = read_wellness_observations(selector, db)
        self.assertTrue(observed[MetricKind.RESTING_HR])
        days = {row["id"] for row in inputs.wellness_rows or ()}
        for observation in observed[MetricKind.RESTING_HR]:
            self.assertIn(observation.observed_on.isoformat(), days)


if __name__ == "__main__":
    unittest.main()
