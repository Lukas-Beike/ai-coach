"""Canonical read selector: the backfill-gated switch, its diagnostic state and diagnostics."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from canonical_read_support import (
    MAX_BATCHES,
    CanonicalReadFixture,
    first_activity_name,
    intervals_snapshot,
    make_selector,
    new_backfill,
    populate,
)

from backend.activities.detail_store import summary_fingerprint
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.diagnostics.canonical_read import summarize_canonical_read
from backend.providers import canonical_plans
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.canonical_backfill import STATE_KEY as BACKFILL_STATE_KEY
from backend.sync.canonical_backfill import read_status
from backend.sync.canonical_backfill_worker import CanonicalBackfillWorker
from backend.sync.canonical_read_assembly import build_canonical_read
from backend.sync.canonical_read_selector import (
    SOURCE_LEGACY,
    SOURCE_TABLES,
    STATE_KEY,
)
from backend.sync.canonical_table_reader import CanonicalTableReader

SECRET = "sk-test-SECRET-value-123"


def ids(records: tuple[Any, ...]) -> list[tuple[str, str]]:
    return [(r.activity_id, r.provenance.provider.value) for r in records]


class RaisingSnapshots:
    def latest_snapshot(self, db: Any) -> Any:
        raise AssertionError("reads must not touch the provider snapshot")


class SelectorTests(CanonicalReadFixture):
    def test_before_backfill_reads_come_from_legacy(self) -> None:
        selector = make_selector(self)
        summary = self.read(selector.summary)

        self.assertEqual(summary["serving"], "legacy")
        self.assertEqual(summary["reason"], "backfill_pending")
        self.assertFalse(summary["digest_current"])
        self.assertIsNone(summary["parity"])
        self.assertEqual(
            ids(self.read(selector.activities)),
            ids(self.read(self.projection.activities)),
        )

    def test_completed_backfill_serves_tables_without_a_refresh(self) -> None:
        populate(self)
        selector = make_selector(self)

        summary = self.read(selector.summary)
        self.assertEqual(summary["serving"], "tables")
        self.assertEqual(summary["reason"], "backfill_complete")
        self.assertIsNone(summary["parity"])
        self.assertTrue(self.read(selector.serves_tables))
        self.assertEqual(
            ids(self.read(selector.activities)),
            ids(self.read(self.table.activities)),
        )

    def test_refresh_records_parity_counts_and_serves_the_tables(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)

        summary = self.read(selector.summary)
        self.assertEqual(summary["serving"], "tables")
        self.assertEqual(summary["reason"], "backfill_complete")
        self.assertTrue(summary["digest_current"])
        self.assertTrue(summary["parity"]["passed"])
        stored = json.loads(self.read(self.key_values.get, STATE_KEY))
        self.assertEqual(stored["source"], SOURCE_TABLES)
        self.assertEqual(
            ids(self.read(selector.activities)),
            ids(self.read(self.table.activities)),
        )

    def test_backfill_not_complete_stores_incomplete_and_serves_legacy(self) -> None:
        selector = make_selector(self)
        self.write(selector.refresh)

        summary = self.read(selector.summary)
        self.assertEqual(summary["reason"], "backfill_pending")
        self.assertEqual(summary["serving"], "legacy")
        self.assertIsNone(summary["parity"])

    def test_new_snapshot_after_a_pass_keeps_serving_tables(self) -> None:
        # Dual-write keeps the tables in step with each new snapshot, so a sync
        # alone does not switch reads back to legacy.
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)

        self.intervals_version = "row-2"
        summary = self.read(selector.summary)

        self.assertEqual(summary["serving"], "tables")
        self.assertTrue(summary["digest_current"])
        self.assertEqual(
            ids(self.read(selector.activities)),
            ids(self.read(self.table.activities)),
        )

    def test_mapper_version_change_after_a_pass_falls_back_to_legacy(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)

        with (
            patch(
                "backend.sync.canonical_read_selector.current_mapper_versions",
                return_value={"changed": 1},
            ),
            patch(
                "backend.sync.canonical_backfill.current_mapper_versions",
                return_value={"changed": 1},
            ),
        ):
            summary = self.read(selector.summary)
            activities = self.read(selector.activities)

        self.assertEqual(summary["serving"], "legacy")
        self.assertFalse(summary["digest_current"])
        self.assertEqual(ids(activities), ids(self.read(self.projection.activities)))

    def test_intervals_wellness_mapper_bump_after_a_pass_falls_back_to_legacy(
        self,
    ) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)

        bumped = {
            key: version + 1
            if key == (ProviderId.INTERVALS.value, canonical_plans.WELLNESS_RECORD_KIND)
            else version
            for key, version in canonical_plans._MAPPER_VERSIONS.items()
        }
        with patch.dict(canonical_plans._MAPPER_VERSIONS, bumped):
            summary = self.read(selector.summary)
            activities = self.read(selector.activities)

        self.assertEqual(summary["serving"], "legacy")
        self.assertFalse(summary["digest_current"])
        self.assertEqual(ids(activities), ids(self.read(self.projection.activities)))
        restored = self.read(selector.summary)
        self.assertEqual(restored["serving"], "tables")
        self.assertTrue(restored["digest_current"])

    def session_dates(self) -> list[str]:
        return [
            row["local_date"]
            for row in self.rows(
                "SELECT local_date FROM activity_sessions ORDER BY started_at"
            )
        ]

    def test_zone_change_serves_legacy_until_reprojection_finishes(self) -> None:
        backfill = populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)
        before = self.session_dates()
        # Stale dates stand in for rows written in the old zone.
        self.execute("UPDATE activity_sessions SET local_date = '1999-01-01'")

        self.zone = ZoneInfo("America/Los_Angeles")
        summary = self.read(selector.summary)
        self.assertEqual(summary["serving"], "legacy")
        self.assertFalse(summary["digest_current"])
        self.assertIs(self.read(selector.reader_for), self.projection)

        # One batch starts the re-projection; reads stay on legacy until it is done.
        with self.manager.unit_of_work() as db:
            report = backfill.run_batch(db)
        if not report.done:
            self.assertEqual(self.read(selector.summary)["serving"], "legacy")
        for _ in range(MAX_BATCHES):
            if report.done:
                break
            with self.manager.unit_of_work() as db:
                report = backfill.run_batch(db)
        self.assertTrue(report.done)

        self.assertEqual(self.read(selector.summary)["serving"], "tables")
        self.assertEqual(self.session_dates(), before)
        self.assertEqual(
            ids(self.read(selector.activities)),
            ids(self.read(self.projection.activities)),
        )

    def test_state_without_a_stored_zone_reprojects_once(self) -> None:
        backfill = populate(self)
        selector = make_selector(self)
        with self.manager.unit_of_work() as db:
            state = json.loads(self.key_values.get(db, BACKFILL_STATE_KEY) or "{}")
            del state["zone"]
            self.key_values.set(db, BACKFILL_STATE_KEY, json.dumps(state))
        self.assertEqual(self.read(selector.summary)["serving"], "legacy")

        with self.manager.unit_of_work() as db:
            report = backfill.run_batch(db)
        while not report.done:
            with self.manager.unit_of_work() as db:
                report = backfill.run_batch(db)

        self.assertEqual(self.read(selector.summary)["serving"], "tables")
        stored = json.loads(self.read(self.key_values.get, BACKFILL_STATE_KEY))
        self.assertEqual(stored["zone"], str(self.zone))
        self.assertFalse(stored["reproject_all"])
        with self.manager.unit_of_work() as db:
            self.assertEqual(backfill.run_batch(db).items, 0)

    def set_backfill_status(self, status: str) -> None:
        with self.manager.unit_of_work() as db:
            state = json.loads(self.key_values.get(db, BACKFILL_STATE_KEY) or "{}")
            self.key_values.set(
                db, BACKFILL_STATE_KEY, json.dumps({**state, "status": status})
            )

    def test_failed_or_running_backfill_serves_legacy(self) -> None:
        populate(self)
        selector = make_selector(self)
        for status in ("failed", "running", "pending"):
            with self.subTest(status=status):
                self.set_backfill_status(status)
                summary = self.read(selector.summary)
                self.assertEqual(summary["serving"], "legacy")
                self.assertEqual(summary["reason"], "backfill_pending")
                self.assertFalse(self.read(selector.serves_tables))
                self.assertIs(self.read(selector.reader_for), self.projection)
                self.assertEqual(
                    ids(self.read(selector.activities)),
                    ids(self.read(self.projection.activities)),
                )

    def test_corrupt_backfill_status_reads_as_pending_and_keeps_legacy(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)
        self.assertEqual(self.read(selector.summary)["serving"], "tables")

        corrupt_values = ("{not json", "[1, 2]", '{"status": 3}', '{"batches": 1}')
        for raw in corrupt_values:
            with self.subTest(raw=raw):
                self.write(self.key_values.set, BACKFILL_STATE_KEY, raw)
                with self.manager.reader() as db:
                    self.assertEqual(read_status(self.key_values, db), "pending")
                self.assertEqual(self.read(selector.summary)["serving"], "legacy")

    def test_parity_mismatch_does_not_force_legacy_reads(self) -> None:
        # Wellness weight and athlete weight collide on the natural key by design.
        self.intervals = intervals_snapshot(athlete_weight=True)
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)

        summary = self.read(selector.summary)
        self.assertEqual(summary["reason"], "backfill_complete")
        self.assertEqual(summary["serving"], "tables")
        self.assertFalse(summary["parity"]["passed"])
        self.assertEqual(
            ids(self.read(selector.activities)),
            ids(self.read(self.table.activities)),
        )

    def test_recorded_failure_reports_error_and_stores_only_the_error_class(
        self,
    ) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)
        self.write(selector.record_failure, "RuntimeError")

        summary = self.read(selector.summary)
        self.assertEqual(summary["reason"], "backfill_complete")
        self.assertEqual(summary["serving"], "tables")
        stored = self.read(self.key_values.get, STATE_KEY)
        self.assertEqual(json.loads(stored)["error_class"], "RuntimeError")
        self.assertEqual(json.loads(stored)["source"], SOURCE_LEGACY)

    def test_corrupt_switch_state_does_not_change_the_serving_source(self) -> None:
        populate(self)
        self.write(make_selector(self).refresh)
        self.write(self.key_values.set, STATE_KEY, "{not json")

        selector = make_selector(self)
        summary = self.read(selector.summary)
        self.assertEqual(summary["reason"], "backfill_complete")
        self.assertEqual(summary["serving"], "tables")
        self.assertIsNone(summary["parity"])
        self.assertEqual(
            ids(self.read(selector.activities)),
            ids(self.read(self.table.activities)),
        )

    def test_a_new_selector_over_the_same_database_keeps_serving_tables(self) -> None:
        populate(self)
        self.write(make_selector(self).refresh)

        restarted = make_selector(self)
        self.assertEqual(self.read(restarted.summary)["serving"], "tables")
        self.assertEqual(
            ids(self.read(restarted.activities)),
            ids(self.read(self.table.activities)),
        )

    def test_tables_are_readable_without_touching_the_provider_snapshot(self) -> None:
        populate(self)
        self.write(make_selector(self).refresh)

        readable = build_canonical_read(
            legacy=self.projection,
            key_values=self.key_values,
            snapshots=RaisingSnapshots(),
            fingerprint=summary_fingerprint,
        )
        self.assertTrue(self.read(readable.activities))
        self.assertEqual(self.read(readable.summary)["serving"], "tables")

    def test_coverage_without_persisted_summaries_is_the_legacy_projection(
        self,
    ) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)

        self.assertEqual(
            self.read(selector.coverage), self.read(self.projection.coverage)
        )

    def test_reader_for_returns_the_source_that_serves_reads(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.assertIsInstance(self.read(selector.reader_for), CanonicalTableReader)

        with patch(
            "backend.sync.canonical_backfill.current_mapper_versions",
            return_value={"changed": 1},
        ):
            self.assertIs(self.read(selector.reader_for), self.projection)

    def test_observations_switch_with_the_same_source(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)

        for kind in MetricKind:
            with self.subTest(kind=kind):
                self.assertEqual(
                    self.read(selector.observations, kind),
                    self.read(self.table.observations, kind),
                )


class DiagnosticsTests(CanonicalReadFixture):
    def summarize(self, reader: Any) -> dict[str, Any]:
        with self.manager.reader() as db:
            return summarize_canonical_read(reader, db)

    def test_missing_reader_is_unavailable(self) -> None:
        self.assertEqual(self.summarize(None), {"status": "unavailable"})

    def test_raising_reader_is_unavailable_and_keeps_no_exception_text(self) -> None:
        broken = Mock()
        broken.summary.side_effect = RuntimeError(f"leaked {SECRET}")

        result = self.summarize(broken)

        self.assertEqual(result, {"status": "unavailable"})
        self.assertNotIn(SECRET, json.dumps(result))

    def test_malformed_summary_is_unavailable(self) -> None:
        malformed = Mock()
        malformed.summary.return_value = {"serving": "tables"}

        self.assertEqual(self.summarize(malformed), {"status": "unavailable"})

    def test_unchecked_switch_reports_no_parity_counts(self) -> None:
        selector = make_selector(self)
        result = self.summarize(selector)

        self.assertEqual(result["serving"], "legacy")
        self.assertEqual(result["reason"], "backfill_pending")
        self.assertFalse(result["digest_current"])
        self.assertIsNone(result["parity"])

    def test_checked_switch_reports_counts_only(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)

        result = self.summarize(selector)
        text = json.dumps(result, sort_keys=True)

        self.assertEqual(result["serving"], "tables")
        self.assertTrue(result["digest_current"])
        self.assertTrue(result["parity"]["passed"])
        self.assertEqual(result["parity"]["fingerprint_mismatches"], 0)
        self.assertEqual(result["parity"]["activities"]["intervals"]["matched"], 5)
        self.assertNotIn(first_activity_name(self), text)
        self.assertNotIn("i-act-001", text)
        self.assertNotIn("910001", text)


class WorkerParityTests(CanonicalReadFixture):
    class Refresher:
        def __init__(
            self,
            *,
            refresh_error: BaseException | None = None,
            record_error: BaseException | None = None,
        ) -> None:
            self.refresh_error = refresh_error
            self.record_error = record_error
            self.refreshed = 0
            self.failures: list[str] = []

        def refresh(self, db: Any) -> None:
            self.refreshed += 1
            if self.refresh_error is not None:
                raise self.refresh_error

        def record_failure(self, db: Any, error_class: str) -> None:
            self.failures.append(error_class)
            if self.record_error is not None:
                raise self.record_error

    def make_worker(self, parity: Any) -> CanonicalBackfillWorker:
        return CanonicalBackfillWorker(
            backfill=new_backfill(self),
            database=lambda: self.manager,
            maintenance_gate=MaintenanceGate(),
            poll_seconds=0,
            parity=parity,
        )

    def test_completed_backfill_refreshes_parity_once(self) -> None:
        populate(self)
        parity = self.Refresher()
        self.make_worker(parity).run_loop()

        self.assertEqual(parity.refreshed, 1)
        self.assertEqual(parity.failures, [])

    def test_parity_error_is_logged_with_its_class_only(self) -> None:
        populate(self)
        parity = self.Refresher(refresh_error=RuntimeError(f"token {SECRET}"))

        with self.assertLogs(
            "backend.sync.canonical_backfill_worker", level="ERROR"
        ) as captured:
            self.make_worker(parity).run_loop()

        self.assertEqual(parity.failures, ["RuntimeError"])
        record = captured.records[0]
        self.assertEqual(record.__dict__["event"], "canonical_parity_failed")
        self.assertEqual(record.__dict__["error_class"], "RuntimeError")
        self.assertNotIn(SECRET, str(record.__dict__))
        self.assertNotIn(SECRET, record.getMessage())

    def test_status_write_failure_is_logged_with_its_class_only(self) -> None:
        populate(self)
        parity = self.Refresher(
            refresh_error=RuntimeError(f"token {SECRET}"),
            record_error=ValueError(f"disk {SECRET}"),
        )

        with self.assertLogs(
            "backend.sync.canonical_backfill_worker", level="ERROR"
        ) as captured:
            self.make_worker(parity).run_loop()

        events = {record.__dict__["event"]: record for record in captured.records}
        self.assertEqual(
            events["canonical_parity_failed"].__dict__["error_class"], "RuntimeError"
        )
        self.assertEqual(
            events["canonical_parity_status_failed"].__dict__["error_class"],
            "ValueError",
        )
        self.assertNotIn(SECRET, str(captured.records[-1].__dict__))


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
