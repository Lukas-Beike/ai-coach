"""Canonical read selector: legacy before the first backfill, tables from then on."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from canonical_read_support import (
    MAX_BATCHES,
    CanonicalReadFixture,
    first_activity_name,
    make_selector,
    new_backfill,
    populate,
)

from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.diagnostics.canonical_read import summarize_canonical_read
from backend.providers import canonical_plans
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.canonical_backfill import STATE_KEY as BACKFILL_STATE_KEY
from backend.sync.canonical_backfill import (
    CanonicalBackfill,
    completed_observation_versions,
    read_status,
)
from backend.sync.canonical_backfill_worker import CanonicalBackfillWorker
from backend.sync.canonical_coverage_store import (
    CanonicalCoverageStore,
    intervals_snapshot_coverage,
)
from backend.sync.canonical_table_reader import CanonicalTableReader

SECRET = "sk-test-SECRET-value-123"
LEGACY_STATE_KEY = "canonical_read_state"
TABLES = "tables"
LEGACY = "legacy"
STATUS = "status"
COMPLETED_ONCE = "completed_once"
FIRST_COMPLETED_AT = "first_completed_at"
UNAVAILABLE = {STATUS: "unavailable"}
NOT_COMPLETE_STATUSES = ("failed", "running", "pending")
SERVING = "serving"
REASON = "reason"
DIGEST_CURRENT = "digest_current"
BACKFILL_COMPLETE = "backfill_complete"
BACKFILL_PENDING = "backfill_pending"


def ids(records: tuple[Any, ...]) -> list[tuple[str, str]]:
    return [(r.activity_id, r.provenance.provider.value) for r in records]


@contextmanager
def bumped_intervals_mappers() -> Iterator[None]:
    """Raise the Intervals.icu wellness and athlete mapper version by one.

    The version is both the expected one (the lookup table) and the one the
    re-projection stamps on the rows it writes (the module constant).
    """
    observation_kinds = (
        canonical_plans.WELLNESS_RECORD_KIND,
        canonical_plans.ATHLETE_RECORD_KIND,
    )
    next_version = canonical_plans.INTERVALS_WELLNESS_VERSION + 1
    bumped = {
        key: next_version
        if key[0] == ProviderId.INTERVALS.value and key[1] in observation_kinds
        else version
        for key, version in canonical_plans._MAPPER_VERSIONS.items()
    }
    with (
        patch.dict(canonical_plans._MAPPER_VERSIONS, bumped),
        patch.object(canonical_plans, "INTERVALS_WELLNESS_VERSION", next_version),
    ):
        yield


class SelectorTests(CanonicalReadFixture):
    def _all_observations(self, reader: Any) -> dict[MetricKind, tuple[Any, ...]]:
        return {kind: self.read(reader.observations, kind) for kind in MetricKind}

    def _run_to_completion(self, backfill: CanonicalBackfill) -> None:
        for _ in range(MAX_BATCHES):
            with self.manager.unit_of_work() as db:
                if backfill.run_batch(db).done:
                    return
        self.fail("backfill did not finish")

    def _session_dates(self) -> list[str]:
        return [
            row["local_date"]
            for row in self.rows(
                "SELECT local_date FROM activity_sessions ORDER BY started_at"
            )
        ]

    def _backfill_state(self) -> dict[str, Any]:
        return json.loads(self.read(self.key_values.get, BACKFILL_STATE_KEY))

    def _store_backfill_state(self, state: dict[str, Any]) -> None:
        self.write(self.key_values.set, BACKFILL_STATE_KEY, json.dumps(state))

    def _assert_serves_tables(self, selector: Any) -> None:
        summary = self.read(selector.summary)
        self.assertEqual(summary[SERVING], TABLES)
        self.assertEqual(summary[REASON], BACKFILL_COMPLETE)
        self.assertTrue(self.read(selector.serves_tables))
        self.assertIsInstance(self.read(selector.reader_for), CanonicalTableReader)
        self.assertEqual(
            ids(self.read(selector.activities)),
            ids(self.read(self.table.activities)),
        )

    def _assert_serves_legacy(self, selector: Any) -> None:
        summary = self.read(selector.summary)
        self.assertEqual(summary[SERVING], LEGACY)
        self.assertEqual(summary[REASON], BACKFILL_PENDING)
        self.assertFalse(summary[DIGEST_CURRENT])
        self.assertFalse(self.read(selector.serves_tables))
        self.assertIs(self.read(selector.reader_for), self.projection)
        self.assertEqual(
            ids(self.read(selector.activities)),
            ids(self.read(self.projection.activities)),
        )

    def test_before_the_first_backfill_reads_come_from_legacy(self) -> None:
        self._assert_serves_legacy(make_selector(self))

    def test_completed_backfill_serves_tables_without_any_refresh(self) -> None:
        populate(self)
        selector = make_selector(self)

        self._assert_serves_tables(selector)
        self.assertTrue(self.read(selector.summary)[DIGEST_CURRENT])
        self.assertTrue(self._backfill_state()[COMPLETED_ONCE])
        self.assertIsNotNone(self._backfill_state()[FIRST_COMPLETED_AT])

    def test_first_completion_marker_is_written_with_the_completion(self) -> None:
        backfill = new_backfill(self)
        with self.manager.unit_of_work() as db:
            self.assertFalse(backfill.run_batch(db).done)
        state = self._backfill_state()
        self.assertFalse(state[COMPLETED_ONCE])
        self.assertIsNone(state[FIRST_COMPLETED_AT])
        self._assert_serves_legacy(make_selector(self))

        self._run_to_completion(backfill)
        self.assertTrue(self._backfill_state()[COMPLETED_ONCE])

    def test_first_backfill_not_complete_serves_legacy(self) -> None:
        populate(self)
        state = self._backfill_state()
        selector = make_selector(self)
        for status in NOT_COMPLETE_STATUSES:
            with self.subTest(status=status):
                self._store_backfill_state(
                    {**state, STATUS: status, COMPLETED_ONCE: False}
                )
                self._assert_serves_legacy(selector)

    def test_new_snapshot_after_completion_keeps_serving_tables(self) -> None:
        # Dual-write keeps the tables in step with each new snapshot.
        populate(self)
        selector = make_selector(self)

        self.intervals_version = "row-2"

        self._assert_serves_tables(selector)
        self.assertTrue(self.read(selector.summary)[DIGEST_CURRENT])

    def test_a_state_complete_without_the_marker_counts_as_completed_once(
        self,
    ) -> None:
        backfill = populate(self)
        state = self._backfill_state()
        del state[COMPLETED_ONCE]
        del state[FIRST_COMPLETED_AT]
        self._store_backfill_state(state)
        selector = make_selector(self)

        self._assert_serves_tables(selector)

        with bumped_intervals_mappers():
            self._assert_reprojecting_tables(selector)
            with self.manager.unit_of_work() as db:
                backfill.run_batch(db)
            self.assertTrue(self._backfill_state()[COMPLETED_ONCE])
            self._run_to_completion(backfill)
        self._assert_serves_tables(selector)

    def test_a_failure_keeps_a_completion_that_predates_the_marker(self) -> None:
        backfill = populate(self)
        state = self._backfill_state()
        del state[COMPLETED_ONCE]
        del state[FIRST_COMPLETED_AT]
        self._store_backfill_state(state)

        with self.manager.unit_of_work() as db:
            backfill.mark_failed(db)

        self.assertEqual(self._backfill_state()[STATUS], "failed")
        self._assert_serves_tables(make_selector(self))

    def test_failed_or_running_state_after_completion_keeps_serving_tables(
        self,
    ) -> None:
        populate(self)
        state = self._backfill_state()
        selector = make_selector(self)
        for status in NOT_COMPLETE_STATUSES:
            with self.subTest(status=status):
                self._store_backfill_state({**state, STATUS: status})
                self._assert_serves_tables(selector)

    def _assert_reprojecting_tables(self, selector: Any) -> None:
        summary = self.read(selector.summary)
        self.assertEqual(summary[SERVING], TABLES)
        self.assertFalse(summary[DIGEST_CURRENT])
        self.assertTrue(self.read(selector.serves_tables))
        self.assertIsNot(self.read(selector.reader_for), self.projection)
        self.assertEqual(
            ids(self.read(selector.activities)),
            ids(self.read(self.table.activities)),
        )

    def test_mapper_version_change_keeps_serving_tables(self) -> None:
        populate(self)
        selector = make_selector(self)

        with patch(
            "backend.sync.canonical_backfill.current_mapper_versions",
            return_value={"changed": 1},
        ):
            self._assert_reprojecting_tables(selector)

    def test_observations_stay_available_until_the_reprojection_completes(
        self,
    ) -> None:
        backfill = populate(self)
        selector = make_selector(self)
        before = self._all_observations(selector)
        self.assertTrue(any(before.values()))

        with bumped_intervals_mappers():
            strict = self._all_observations(self.table)
            self.assertNotEqual(strict, before)
            self._assert_reprojecting_tables(selector)
            self.assertEqual(self._all_observations(selector), before)

            with self.manager.unit_of_work() as db:
                report = backfill.run_batch(db)
            for _ in range(MAX_BATCHES):
                if report.done:
                    break
                self._assert_reprojecting_tables(selector)
                self.assertEqual(self._all_observations(selector), before)
                with self.manager.unit_of_work() as db:
                    report = backfill.run_batch(db)
            self.assertTrue(report.done)

            self._assert_serves_tables(selector)
            self.assertTrue(self.read(selector.summary)[DIGEST_CURRENT])
            after = self._all_observations(selector)
            self.assertEqual(after, self._all_observations(self.table))
            self.assertEqual(after, before)

    def test_observations_of_the_current_version_win_during_a_reprojection(
        self,
    ) -> None:
        backfill = populate(self)
        selector = make_selector(self)
        weight = MetricKind.WEIGHT

        with bumped_intervals_mappers():
            with self.manager.unit_of_work() as db:
                backfill.run_batch(db)
            served = self.read(selector.observations, weight)
            versions = {
                row["mapper_version"]
                for row in self.rows("SELECT mapper_version FROM observations")
            }
            self.assertGreater(len(versions), 1)
            self.assertEqual(
                len({(o.observed_on, o.sport, o.provenance.provider) for o in served}),
                len(served),
            )

    def _insert_retired_observation(self) -> None:
        """Copy one Intervals.icu observation under a new key at an older version.

        It stands in for a measurement that an earlier mapper stopped emitting
        before the last completed run.
        """
        columns = (
            "metric, value, unit, method, aggregation, source_kind, recorded_by, "
            "provider, source_record_id, sport, observed_on, observed_at, "
            "retrieved_at, label, details, created_at, updated_at"
        )
        self.execute(
            f"INSERT INTO observations (natural_key, mapper_version, {columns}) "
            f"SELECT natural_key || ':retired', mapper_version - 1, {columns} "
            "FROM observations WHERE provider = ? ORDER BY id LIMIT 1",
            (ProviderId.INTERVALS.value,),
        )

    def test_observations_retired_before_the_last_completion_stay_hidden(
        self,
    ) -> None:
        backfill = populate(self)
        selector = make_selector(self)
        before = self._all_observations(selector)
        self._insert_retired_observation()
        self.assertEqual(self._all_observations(selector), before)

        with bumped_intervals_mappers():
            self._assert_reprojecting_tables(selector)
            self.assertEqual(self._all_observations(selector), before)
            with self.manager.unit_of_work() as db:
                backfill.mark_failed(db)
            self._assert_reprojecting_tables(selector)
            self.assertEqual(self._all_observations(selector), before)

    def _completed_versions(self) -> dict[str, int]:
        with self.manager.reader() as db:
            return completed_observation_versions(self.key_values, db)

    def test_completed_observation_versions_ignore_other_kinds_and_bad_values(
        self,
    ) -> None:
        populate(self)
        intervals = ProviderId.INTERVALS.value
        self.assertEqual(
            self._completed_versions()[intervals],
            canonical_plans.INTERVALS_WELLNESS_VERSION,
        )
        self._store_backfill_state(
            {
                **self._backfill_state(),
                "versions": {
                    f"{intervals}.{canonical_plans.WELLNESS_RECORD_KIND}": "2",
                    f"{intervals}.{canonical_plans.ATHLETE_RECORD_KIND}": True,
                    f"{intervals}.{canonical_plans.ACTIVITY_RECORD_KIND}": 7,
                },
            }
        )
        self.assertEqual(self._completed_versions(), {})
        self._store_backfill_state({**self._backfill_state(), "versions": []})
        self.assertEqual(self._completed_versions(), {})

    def test_zone_change_keeps_serving_tables_until_reprojection_finishes(
        self,
    ) -> None:
        backfill = populate(self)
        selector = make_selector(self)
        before = self._session_dates()
        # Stale dates stand in for rows written in the old zone.
        self.execute("UPDATE activity_sessions SET local_date = '1999-01-01'")

        self.zone = ZoneInfo("America/Los_Angeles")
        self._assert_reprojecting_tables(selector)

        # One batch starts the re-projection; reads stay on the tables until done.
        with self.manager.unit_of_work() as db:
            report = backfill.run_batch(db)
        for _ in range(MAX_BATCHES):
            if report.done:
                break
            self._assert_reprojecting_tables(selector)
            with self.manager.unit_of_work() as db:
                report = backfill.run_batch(db)
        self.assertTrue(report.done)

        self._assert_serves_tables(selector)
        self.assertEqual(self._session_dates(), before)
        self.assertEqual(
            ids(self.read(selector.activities)),
            ids(self.read(self.projection.activities)),
        )

    def test_state_without_a_stored_zone_reprojects_once_on_the_tables(self) -> None:
        backfill = populate(self)
        selector = make_selector(self)
        state = self._backfill_state()
        del state["zone"]
        self._store_backfill_state(state)
        self._assert_reprojecting_tables(selector)

        self._run_to_completion(backfill)

        self._assert_serves_tables(selector)
        stored = self._backfill_state()
        self.assertEqual(stored["zone"], str(self.zone))
        self.assertFalse(stored["reproject_all"])
        with self.manager.unit_of_work() as db:
            self.assertEqual(backfill.run_batch(db).items, 0)

    def test_corrupt_backfill_status_reads_as_never_completed(self) -> None:
        populate(self)
        selector = make_selector(self)
        self._assert_serves_tables(selector)

        corrupt_values = ("{not json", "[1, 2]", "{STATUS: 3}", '{"batches": 1}')
        for raw in corrupt_values:
            with self.subTest(raw=raw):
                self.write(self.key_values.set, BACKFILL_STATE_KEY, raw)
                with self.manager.reader() as db:
                    self.assertEqual(read_status(self.key_values, db), "pending")
                self._assert_serves_legacy(selector)

    def test_an_old_read_state_with_parity_counts_is_ignored_and_kept(self) -> None:
        populate(self)
        old = json.dumps(
            {
                "source": LEGACY,
                "reason": "error",
                "digest": "0" * 64,
                "error_class": "RuntimeError",
                "parity": {"passed": False, "ordering_equal": False},
            }
        )
        self.write(self.key_values.set, LEGACY_STATE_KEY, old)
        selector = make_selector(self)

        self._assert_serves_tables(selector)
        self.assertTrue(self.read(selector.summary)[DIGEST_CURRENT])
        self.assertNotIn("parity", self.read(selector.summary))
        self.assertEqual(self.read(self.key_values.get, LEGACY_STATE_KEY), old)

        self.write(self.key_values.set, LEGACY_STATE_KEY, "{not json")
        self._assert_serves_tables(make_selector(self))

    def test_a_new_selector_over_the_same_database_keeps_serving_tables(self) -> None:
        populate(self)

        self._assert_serves_tables(make_selector(self))

    def test_tables_are_readable_without_touching_the_provider_snapshot(self) -> None:
        populate(self)
        readable = make_selector(self)

        self.assertTrue(self.read(readable.activities))
        self.assertEqual(self.read(readable.summary)[SERVING], TABLES)

    def test_coverage_before_completion_is_the_legacy_projection(self) -> None:
        selector = make_selector(self)

        self.assertEqual(
            self.read(selector.coverage), self.read(self.projection.coverage)
        )

    def test_coverage_after_completion_has_no_legacy_fallback(self) -> None:
        populate(self)
        selector = make_selector(self)

        # Garmin coverage is persisted by its writer; only Intervals.icu could fall back.
        self.assertEqual(self._intervals_coverage(selector), ())

    def test_persisted_coverage_is_kept_after_a_mapper_bump(self) -> None:
        populate(self)
        selector = make_selector(self)
        summary = intervals_snapshot_coverage(self.intervals, zone=self.zone)
        self.assertIsNotNone(summary)
        self.write(
            lambda db: CanonicalCoverageStore(self.key_values).persist(
                db, summary, zone=self.zone
            )
        )
        self.assertEqual(self._intervals_coverage(selector), (summary,))

        with bumped_intervals_mappers():
            self.assertEqual(self._intervals_coverage(selector), (summary,))

    def _intervals_coverage(self, selector: Any) -> tuple[Any, ...]:
        return tuple(
            item
            for item in self.read(selector.coverage)
            if item.provider is ProviderId.INTERVALS
        )

    def test_reader_for_returns_the_source_that_serves_reads(self) -> None:
        selector = make_selector(self)
        self.assertIs(self.read(selector.reader_for), self.projection)

        populate(self)
        self.assertIsInstance(self.read(selector.reader_for), CanonicalTableReader)

    def test_observations_come_from_the_same_source(self) -> None:
        selector = make_selector(self)
        for kind in MetricKind:
            with self.subTest(phase=LEGACY, kind=kind):
                self.assertEqual(
                    self.read(selector.observations, kind),
                    self.read(self.projection.observations, kind),
                )
        populate(self)
        for kind in MetricKind:
            with self.subTest(phase=TABLES, kind=kind):
                self.assertEqual(
                    self.read(selector.observations, kind),
                    self.read(self.table.observations, kind),
                )

    def test_metric_windows_are_empty_before_the_first_backfill(self) -> None:
        self.assertEqual(self.read(make_selector(self).metric_windows), ())

    def test_metric_windows_come_from_the_tables_after_completion(self) -> None:
        populate(self)
        selector = make_selector(self)

        self.assertTrue(self.read(selector.metric_windows))
        self.assertEqual(
            self.read(selector.metric_windows),
            self.read(self.table.metric_windows),
        )


class DiagnosticsTests(CanonicalReadFixture):
    def _summarize(self, reader: Any) -> dict[str, Any]:
        with self.manager.reader() as db:
            return summarize_canonical_read(reader, db)

    def test_missing_reader_is_unavailable(self) -> None:
        self.assertEqual(self._summarize(None), UNAVAILABLE)

    def test_raising_reader_is_unavailable_and_keeps_no_exception_text(self) -> None:
        broken = Mock()
        broken.summary.side_effect = RuntimeError(f"leaked {SECRET}")

        result = self._summarize(broken)

        self.assertEqual(result, UNAVAILABLE)
        self.assertNotIn(SECRET, json.dumps(result))

    def test_malformed_summary_is_unavailable(self) -> None:
        malformed = Mock()
        malformed.summary.return_value = {SERVING: TABLES}

        self.assertEqual(self._summarize(malformed), UNAVAILABLE)

    def test_before_the_first_backfill_the_summary_names_legacy(self) -> None:
        result = self._summarize(make_selector(self))

        self.assertEqual(
            result,
            {SERVING: LEGACY, REASON: BACKFILL_PENDING, DIGEST_CURRENT: False},
        )

    def test_summary_has_no_parity_field_and_no_content(self) -> None:
        populate(self)
        selector = make_selector(self)

        result = self._summarize(selector)
        text = json.dumps(result, sort_keys=True)

        self.assertEqual(
            result,
            {SERVING: TABLES, REASON: BACKFILL_COMPLETE, DIGEST_CURRENT: True},
        )
        self.assertNotIn(first_activity_name(self), text)
        self.assertNotIn("i-act-001", text)
        self.assertNotIn("910001", text)

    def test_summary_reports_a_pending_reprojection_without_leaving_tables(
        self,
    ) -> None:
        populate(self)
        selector = make_selector(self)

        with bumped_intervals_mappers():
            result = self._summarize(selector)

        self.assertEqual(
            result,
            {SERVING: TABLES, REASON: BACKFILL_COMPLETE, DIGEST_CURRENT: False},
        )


class WorkerTests(CanonicalReadFixture):
    def test_the_worker_runs_the_backfill_to_completion_and_stops(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO snapshots(payload, created_at, synced_at, "
                "recent_activity_count) VALUES (?, ?, ?, 0)",
                ("{}", "2026-09-20T08:00:00+00:00", "2026-09-20T08:00:00+00:00"),
            )
        worker = CanonicalBackfillWorker(
            backfill=new_backfill(self),
            database=lambda: self.manager,
            maintenance_gate=MaintenanceGate(),
            poll_seconds=0,
        )

        worker.run_loop()

        self.assertEqual(read_status_of(self), "complete")
        self.assertTrue(json.loads(self._state_text())[COMPLETED_ONCE])

    def _state_text(self) -> str:
        return self.read(self.key_values.get, BACKFILL_STATE_KEY)


def read_status_of(case: CanonicalReadFixture) -> str:
    with case.manager.reader() as db:
        return read_status(case.key_values, db)


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
