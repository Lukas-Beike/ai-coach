"""Canonical parity: identity counts, fingerprints, shared order and a content-free report."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

from canonical_read_support import (
    CanonicalReadFixture,
    LatestSnapshot,
    intervals_snapshot,
)

from backend.activities.detail_store import summary_fingerprint
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.sync.canonical_parity import (
    CanonicalParity,
    ComparisonCounts,
    ParityReport,
)


class MappedTable:
    """Wraps the real table reader and rewrites what it serves, to force each outcome."""

    def __init__(
        self,
        base: Any,
        *,
        activities: Callable[[tuple[Any, ...]], tuple[Any, ...]] = lambda rows: rows,
        observations: Callable[[MetricKind, tuple[Any, ...]], tuple[Any, ...]] = (
            lambda kind, rows: rows
        ),
    ) -> None:
        self._base = base
        self._activities = activities
        self._observations = observations

    def activities(self, db: Any, **kwargs: Any) -> tuple[Any, ...]:
        return self._activities(self._base.activities(db, **kwargs))

    def observations(self, db: Any, kind: MetricKind, **kwargs: Any) -> tuple[Any, ...]:
        return self._observations(kind, self._base.observations(db, kind, **kwargs))


class StaticSnapshot:
    def __init__(self, snapshot: Any) -> None:
        self._snapshot = snapshot

    def latest_snapshot(self, db: Any) -> Any:
        return self._snapshot


class FixedReader:
    """Serves fixed activities and observations so one case can be forced exactly."""

    def __init__(
        self,
        *,
        activities: tuple[Any, ...] = (),
        observations: dict[MetricKind, tuple[Any, ...]] | None = None,
    ) -> None:
        self._activities = activities
        self._observations = observations or {}

    def activities(self, db: Any, **kwargs: Any) -> tuple[Any, ...]:
        return self._activities

    def observations(self, db: Any, kind: MetricKind, **kwargs: Any) -> tuple[Any, ...]:
        return self._observations.get(kind, ())


class ParityTests(CanonicalReadFixture):
    def parity(
        self,
        table: Any | None = None,
        *,
        snapshots: Any | None = None,
        fingerprint: Callable[[dict[str, Any]], str] = summary_fingerprint,
    ) -> CanonicalParity:
        return CanonicalParity(
            legacy=self.projection,
            table=table if table is not None else self.table,
            snapshots=snapshots if snapshots is not None else LatestSnapshot(self),
            fingerprint=fingerprint,
            zone=self.projection.zone,
        )

    def check(self, parity: CanonicalParity) -> ParityReport:
        return self.read(parity.check)

    def intervals_activity(self) -> Any:
        """One Intervals.icu activity as the table serves it."""
        return next(
            record
            for record in self.read(self.table.activities)
            if record.provenance.provider is ProviderId.INTERVALS
        )

    def test_populated_clean_fixture_passes_with_identical_served_content(self) -> None:
        self.populate()
        report = self.check(self.make_parity())

        self.assertTrue(report.passed)
        self.assertTrue(report.ordering_equal)
        self.assertEqual(report.fingerprint_mismatches, 0)
        self.assertEqual(report.fingerprint_checked, 5)
        self.assertEqual(report.activities["intervals"].matched, 5)
        self.assertEqual(report.activities["garmin"].matched, 2)
        self.assertEqual(report.observations["weight"].matched, 5)
        self.assertEqual(report.observations["ftp"].differing, 0)

    def test_same_key_value_conflict_fails_and_names_the_weight_metric(self) -> None:
        # Wellness weight and athlete weight share one natural key on one day.
        self.intervals = intervals_snapshot(athlete_weight=True)
        self.populate()
        report = self.check(self.make_parity())

        self.assertFalse(report.passed)
        self.assertEqual(report.observations["weight"].differing, 1)
        self.assertEqual(report.observations["ftp"].differing, 0)

    def test_table_missing_a_legacy_activity_is_counted_as_missing(self) -> None:
        self.populate()
        table = MappedTable(
            self.table,
            activities=lambda rows: tuple(
                r for r in rows if r.activity_id != "i-act-001"
            ),
        )
        report = self.check(self.parity(table))

        self.assertFalse(report.passed)
        self.assertEqual(report.activities["intervals"].missing_in_table, 1)
        self.assertEqual(report.activities["intervals"].matched, 4)

    def test_table_serving_an_activity_absent_from_legacy_is_extra(self) -> None:
        self.populate()
        extra = self.read(self.table.activities)[0]
        table = MappedTable(
            self.table,
            activities=lambda rows: (*rows, replace(extra, activity_id="i-act-999")),
        )
        report = self.check(self.parity(table))

        self.assertFalse(report.passed)
        self.assertEqual(report.activities["intervals"].extra_in_table, 1)

    def test_same_identity_with_different_served_content_is_differing(self) -> None:
        self.populate()
        table = MappedTable(
            self.table,
            activities=lambda rows: tuple(
                replace(r, duration_s=(r.duration_s or 0.0) + 1.0)
                if r.activity_id == "i-act-001"
                else r
                for r in rows
            ),
        )
        report = self.check(self.parity(table))

        self.assertFalse(report.passed)
        self.assertEqual(report.activities["intervals"].differing, 1)
        self.assertEqual(report.activities["intervals"].missing_in_table, 0)
        self.assertEqual(report.activities["intervals"].extra_in_table, 0)

    def test_reversed_activity_order_fails_the_ordering_check(self) -> None:
        self.populate()
        table = MappedTable(self.table, activities=lambda rows: tuple(reversed(rows)))
        report = self.check(self.parity(table))

        self.assertFalse(report.ordering_equal)
        self.assertFalse(report.passed)
        self.assertEqual(report.activities["intervals"].failures, 0)

    def test_table_only_observation_outside_the_legacy_range_is_history(self) -> None:
        self.populate()
        kind = MetricKind.WEIGHT

        def add_old_row(metric: MetricKind, rows: tuple[Any, ...]) -> tuple[Any, ...]:
            if metric is not kind or not rows:
                return rows
            old = replace(rows[0], observed_on=date(2000, 1, 1))
            return (*rows, old)

        table = MappedTable(self.table, observations=add_old_row)
        report = self.check(self.parity(table))

        self.assertEqual(report.observations["weight"].table_history, 1)
        self.assertEqual(report.observations["weight"].extra_in_table, 0)
        self.assertTrue(report.passed)

    def test_table_only_observation_inside_the_legacy_range_is_extra(self) -> None:
        self.populate()
        kind = MetricKind.WEIGHT

        def add_inside_row(
            metric: MetricKind, rows: tuple[Any, ...]
        ) -> tuple[Any, ...]:
            if metric is not kind or not rows:
                return rows
            other = next(s for s in Sport if s is not rows[0].sport)
            return (*rows, replace(rows[0], sport=other))

        table = MappedTable(self.table, observations=add_inside_row)
        report = self.check(self.parity(table))

        self.assertGreaterEqual(report.observations["weight"].extra_in_table, 1)
        self.assertFalse(report.passed)

    def test_legacy_observation_missing_from_the_table_is_counted(self) -> None:
        self.populate()
        kind = MetricKind.RESTING_HR

        def drop_first(metric: MetricKind, rows: tuple[Any, ...]) -> tuple[Any, ...]:
            return rows[1:] if metric is kind else rows

        table = MappedTable(self.table, observations=drop_first)
        report = self.check(self.parity(table))

        self.assertEqual(report.observations["resting_hr"].missing_in_table, 1)
        self.assertFalse(report.passed)

    def test_changed_raw_activity_is_a_fingerprint_mismatch(self) -> None:
        self.populate()
        self.intervals["raw_provider_data"]["activities"][0]["name"] = "Renamed run"
        report = self.check(self.make_parity())

        self.assertEqual(report.fingerprint_mismatches, 1)
        self.assertEqual(report.fingerprint_checked, 5)
        self.assertFalse(report.passed)

    def test_fingerprint_uses_the_injected_function(self) -> None:
        self.populate()
        report = self.check(self.parity(fingerprint=lambda activity: "same"))

        self.assertEqual(report.fingerprint_mismatches, 0)
        self.assertEqual(report.fingerprint_checked, 5)

    def test_missing_or_malformed_snapshots_check_no_fingerprints(self) -> None:
        self.populate()
        shapes: list[Any] = [
            None,
            "not a mapping",
            {"raw_provider_data": None},
            {"raw_provider_data": {"activities": "not a list"}},
            {
                "raw_provider_data": {
                    "activities": [
                        "text row",
                        {"name": "no id"},
                        {"id": None, "name": "null id"},
                    ]
                }
            },
        ]
        for shape in shapes:
            with self.subTest(shape=shape):
                report = self.check(self.parity(snapshots=StaticSnapshot(shape)))
                self.assertEqual(report.fingerprint_checked, 0)
                self.assertEqual(report.fingerprint_mismatches, 0)

    def test_table_only_provider_without_legacy_rows_is_extra_even_when_old(
        self,
    ) -> None:
        self.populate()
        base = self.read(self.table.observations, MetricKind.WEIGHT)[0]
        intervals = replace(
            base, provenance=replace(base.provenance, provider=ProviderId.INTERVALS)
        )
        garmin_old = replace(
            intervals,
            observed_on=date(2000, 1, 1),
            provenance=replace(intervals.provenance, provider=ProviderId.GARMIN),
        )
        parity = CanonicalParity(
            legacy=FixedReader(observations={MetricKind.WEIGHT: (intervals,)}),
            table=FixedReader(
                observations={MetricKind.WEIGHT: (intervals, garmin_old)}
            ),
            snapshots=StaticSnapshot(None),
            fingerprint=summary_fingerprint,
            zone=self.projection.zone,
        )
        report = self.check(parity)

        self.assertEqual(report.observations["weight"].extra_in_table, 1)
        self.assertEqual(report.observations["weight"].table_history, 0)
        self.assertFalse(report.passed)

    def test_aged_out_activity_outside_the_legacy_range_is_history(self) -> None:
        self.populate()
        old = replace(
            self.intervals_activity(),
            activity_id="i-act-old",
            started_at=datetime(2000, 1, 1, tzinfo=UTC),
        )
        table = MappedTable(self.table, activities=lambda rows: (*rows, old))
        report = self.check(self.parity(table))

        self.assertEqual(report.activities["intervals"].table_history, 1)
        self.assertEqual(report.activities["intervals"].extra_in_table, 0)
        self.assertTrue(report.passed)

    def test_activity_provider_without_legacy_rows_is_extra_even_when_old(
        self,
    ) -> None:
        self.populate()
        intervals = self.intervals_activity()
        garmin_old = replace(
            intervals,
            activity_id="g-act-old",
            started_at=datetime(2000, 1, 1, tzinfo=UTC),
            provenance=replace(intervals.provenance, provider=ProviderId.GARMIN),
        )
        parity = CanonicalParity(
            legacy=FixedReader(activities=(intervals,)),
            table=FixedReader(activities=(intervals, garmin_old)),
            snapshots=StaticSnapshot(None),
            fingerprint=summary_fingerprint,
            zone=self.projection.zone,
        )
        report = self.check(parity)

        self.assertEqual(report.activities["garmin"].extra_in_table, 1)
        self.assertEqual(report.activities["garmin"].table_history, 0)
        self.assertEqual(report.activities["intervals"].matched, 1)
        self.assertFalse(report.passed)

    def test_label_only_observation_change_fails_parity(self) -> None:
        self.populate()
        kind = MetricKind.WEIGHT

        def relabel(metric: MetricKind, rows: tuple[Any, ...]) -> tuple[Any, ...]:
            if metric is not kind or not rows:
                return rows
            first = rows[0]
            relabelled = replace(
                first, provenance=replace(first.provenance, label="Relabelled")
            )
            return (relabelled, *rows[1:])

        table = MappedTable(self.table, observations=relabel)
        report = self.check(self.parity(table))

        self.assertEqual(report.observations["weight"].differing, 1)
        self.assertEqual(report.observations["weight"].extra_in_table, 0)
        self.assertFalse(report.passed)

    def test_report_is_content_free(self) -> None:
        self.populate()
        report = self.check(self.make_parity()).as_dict()
        text = json.dumps(report, sort_keys=True)

        self.assertNotIn(self.first_activity_name(), text)
        for identifier in ("i-act-001", "910001", "2026-"):
            self.assertNotIn(identifier, text)
        self.assertTrue(report["passed"])

    def test_report_passes_only_with_no_failures_and_matching_order(self) -> None:
        clean = ComparisonCounts(matched=2, table_history=1)
        failing = ComparisonCounts(differing=1)

        self.assertTrue(ParityReport({"intervals": clean}, {}, True, 0, 0).passed)
        self.assertFalse(ParityReport({"intervals": clean}, {}, False, 0, 0).passed)
        self.assertFalse(ParityReport({"intervals": failing}, {}, True, 0, 0).passed)
        self.assertFalse(ParityReport({}, {"weight": clean}, True, 1, 1).passed)
        self.assertEqual(clean.failures, 0)
        self.assertEqual(
            failing.as_dict(),
            {
                "matched": 0,
                "missing_in_table": 0,
                "extra_in_table": 0,
                "differing": 1,
                "table_history": 0,
            },
        )


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
