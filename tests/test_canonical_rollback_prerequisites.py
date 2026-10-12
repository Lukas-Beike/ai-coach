"""Performance refresh ingest, persisted canonical coverage and the backfill query.

All storage is temporary and the provider client is a mock.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch
from zoneinfo import ZoneInfo

from canonical_read_support import (
    MAX_BATCHES,
    CanonicalReadFixture,
    make_selector,
    new_backfill,
    populate,
)
from support import load_provider_fixture

from backend.canonical.vocabulary import ProviderId
from backend.config import load_config
from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.providers import canonical_plans
from backend.sync.canonical_backfill import STATE_KEY, backfill_complete
from backend.sync.canonical_coverage_store import (
    CANONICAL_COVERAGE_PROVIDERS,
    CanonicalCoverageStore,
    coverage_key,
    garmin_payload_coverage,
    intervals_snapshot_coverage,
)
from backend.sync.canonical_ingest import ingest_intervals_snapshot
from backend.sync.canonical_projection import CanonicalSnapshotProjection
from backend.sync.canonical_read_selector import CanonicalReadSelector
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.performance import PerformanceRefreshService
from backend.sync.state import SyncStateRepository

NOW = "2026-10-10T06:30:00+00:00"
ZONE = ZoneInfo("Europe/Berlin")
OBSERVATION_COLUMNS = (
    "natural_key, metric, value, unit, source_kind, provider, source_record_id, "
    "observed_on, retrieved_at, mapper_version"
)


def performance_response() -> dict[str, Any]:
    wellness = load_provider_fixture("intervals/wellness.json")
    athlete = load_provider_fixture("intervals/athlete.json")
    return {
        "synced_at": NOW,
        "athlete": athlete,
        "recent_wellness": wellness,
        "raw_provider_data": {"athlete": athlete, "wellness": wellness},
    }


class PerformanceCanonicalIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.manager = self.open_database(root / "performance.db")
        self.key_values = KeyValueRepository(lambda: NOW)
        self.sync_state = SyncStateRepository(
            self.manager, self.key_values, SnapshotRepository(), lambda: NOW
        )
        self.provider = Mock()
        self.provider.fetch_performance_snapshot.return_value = performance_response()
        self.service = PerformanceRefreshService(
            load_config(root, root, {"INTERVALS_API_KEY": "fake-key"}),
            self.manager,
            self.sync_state,
            self.key_values,
            self.provider,
            Mock(),
            lambda text: text,
            Mock(),
            MagicMock(),
            MagicMock(),
            threading.Lock(),
            zone_provider=lambda: ZONE,
        )

    def open_database(self, path: Path) -> DatabaseManager:
        manager = DatabaseManager(path, sqlite3, row_factory=row_factory)
        self.addCleanup(manager.close)
        with manager.unit_of_work() as db:
            initialize_schema(db)
        return manager

    def table_rows(self, manager: DatabaseManager, sql: str) -> list[dict[str, Any]]:
        with manager.reader() as db:
            return [dict(row) for row in db.execute(sql).fetchall()]

    def observations(self, manager: DatabaseManager) -> list[dict[str, Any]]:
        return self.table_rows(
            manager,
            f"SELECT {OBSERVATION_COLUMNS} FROM observations ORDER BY natural_key",
        )

    def test_refresh_writes_the_observations_a_full_sync_maps(self) -> None:
        self.service._refresh_inner()

        full = self.open_database(Path(self.temporary.name) / "full.db")
        with full.unit_of_work() as db:
            ingest_intervals_snapshot(
                db,
                performance_response(),
                zone=ZONE,
                activity_days=42,
                all_sync_days=42,
                earliest_date=date(2026, 1, 1),
            )

        refreshed = self.observations(self.manager)
        self.assertGreater(len(refreshed), 0)
        self.assertEqual(refreshed, self.observations(full))
        self.assertEqual(
            self.table_rows(
                self.manager, "SELECT record_kind FROM provider_records ORDER BY 1"
            ),
            self.table_rows(
                full, "SELECT record_kind FROM provider_records ORDER BY 1"
            ),
        )
        self.assertIsNotNone(self.sync_state.latest_snapshot())

    def test_ingest_failure_leaves_neither_the_snapshot_nor_canonical_rows(
        self,
    ) -> None:
        with (
            patch.object(
                canonical_store, "upsert_observation", side_effect=RuntimeError("boom")
            ),
            self.assertRaises(RuntimeError),
        ):
            self.service._refresh_inner()

        self.assertIsNone(self.sync_state.latest_snapshot())
        self.assertEqual(self.observations(self.manager), [])
        self.assertEqual(
            self.table_rows(self.manager, "SELECT 1 FROM provider_records"), []
        )
        with self.manager.reader() as db:
            self.assertIsNone(
                self.key_values.get(db, coverage_key(ProviderId.INTERVALS))
            )

    def test_refresh_never_marks_stored_activities_deleted(self) -> None:
        seed = {
            "synced_at": "2026-10-09T06:00:00+00:00",
            "raw_provider_data": {
                "activities": [
                    {
                        "id": "i-1",
                        "start_date_local": "2026-10-05T07:00:00",
                        "type": "Ride",
                    }
                ]
            },
        }
        with self.manager.unit_of_work() as db:
            ingest_intervals_snapshot(
                db,
                seed,
                zone=ZONE,
                activity_days=None,
                all_sync_days=42,
                earliest_date=date(2026, 1, 1),
            )
        before = self.table_rows(
            self.manager, "SELECT provider_activity_id, state FROM activity_records"
        )
        self.assertEqual(len(before), 1)

        self.service._refresh_inner()

        self.assertEqual(
            self.table_rows(
                self.manager, "SELECT provider_activity_id, state FROM activity_records"
            ),
            before,
        )

    def test_refresh_persists_coverage_equal_to_the_legacy_projection(self) -> None:
        self.service._refresh_inner()
        projection = CanonicalSnapshotProjection(
            intervals_snapshot=lambda db: self.sync_state.latest_snapshot(),
            intervals_version=lambda db: "v",
            garmin_payload=lambda db: {},
            zone=lambda db: ZONE,
            clock=lambda: datetime(2026, 10, 10, tzinfo=UTC),
        )
        with self.manager.reader() as db:
            stored = CanonicalCoverageStore(self.key_values).load(
                db, ProviderId.INTERVALS, zone=ZONE
            )
            legacy = projection.coverage(db)[0]
        self.assertIsNotNone(stored)
        self.assertEqual(stored, legacy)
        self.assertGreater(stored.observation_count, 0)  # type: ignore[union-attr]


class PersistedCoverageTests(CanonicalReadFixture):
    def selector(self) -> CanonicalReadSelector:
        return make_selector(self)

    def store(self, *, zone: ZoneInfo | None = None) -> None:
        use = zone or ZONE
        coverage = CanonicalCoverageStore(self.key_values)
        with self.manager.unit_of_work() as db:
            coverage.persist(
                db, intervals_snapshot_coverage(self.intervals, zone=use), zone=use
            )
            coverage.persist(
                db, garmin_payload_coverage(self.garmin, zone=use), zone=use
            )

    def strip_legacy_inputs(self) -> None:
        synced_at = self.intervals["synced_at"]
        self.intervals.clear()
        self.intervals["synced_at"] = synced_at

    def test_without_persisted_data_coverage_is_the_legacy_computation(self) -> None:
        selector = self.selector()
        self.assertEqual(
            self.read(selector.coverage), self.read(self.projection.coverage)
        )

    def test_persisted_coverage_is_read_instead_of_recomputed(self) -> None:
        expected = self.read(self.projection.coverage)
        self.store()
        # The legacy inputs change, but the persisted summary is what is served.
        self.strip_legacy_inputs()
        self.garmin.clear()
        self.intervals_version = "row-2"

        self.assertEqual(self.read(self.selector().coverage), expected)

    def test_a_provider_without_a_summary_falls_back_for_that_provider(self) -> None:
        expected = self.read(self.projection.coverage)
        coverage = CanonicalCoverageStore(self.key_values)
        with self.manager.unit_of_work() as db:
            coverage.persist(
                db, intervals_snapshot_coverage(self.intervals, zone=ZONE), zone=ZONE
            )

        self.assertEqual(self.read(self.selector().coverage), expected)
        self.assertIsNone(
            self.read(self.key_values.get, coverage_key(ProviderId.GARMIN))
        )

    def test_outdated_or_corrupt_summaries_are_ignored(self) -> None:
        expected = self.read(self.projection.coverage)
        self.store()
        self.strip_legacy_inputs()
        self.intervals_version = "row-2"

        with patch(
            "backend.sync.canonical_coverage_store.current_mapper_versions",
            return_value={"changed": 1},
        ):
            self.assertNotEqual(self.read(self.selector().coverage), expected)

        self.zone = ZoneInfo("America/New_York")
        self.assertNotEqual(self.read(self.selector().coverage), expected)
        self.zone = ZONE

        with self.manager.unit_of_work() as db:
            self.key_values.set(db, coverage_key(ProviderId.INTERVALS), "{not json")
        self.assertNotEqual(self.read(self.selector().coverage)[0], expected[0])

    def test_only_the_ingested_providers_are_consulted(self) -> None:
        self.assertEqual(
            CANONICAL_COVERAGE_PROVIDERS, (ProviderId.INTERVALS, ProviderId.GARMIN)
        )
        expected = self.read(self.projection.coverage)
        self.store()
        self.strip_legacy_inputs()
        self.garmin.clear()

        loaded: list[ProviderId] = []
        original = CanonicalCoverageStore.load

        def spy(
            store: CanonicalCoverageStore, db: Any, provider: ProviderId, **kw: Any
        ) -> Any:
            loaded.append(provider)
            return original(store, db, provider, **kw)

        with patch.object(CanonicalCoverageStore, "load", spy):
            result = self.read(self.selector().coverage)

        self.assertEqual(tuple(loaded), CANONICAL_COVERAGE_PROVIDERS)
        self.assertEqual(result, expected)

    def test_persisted_value_holds_counts_only(self) -> None:
        self.store()
        text = self.read(self.key_values.get, coverage_key(ProviderId.INTERVALS))
        data = json.loads(text)
        self.assertEqual(
            set(data),
            {
                "provider",
                "mapper_versions",
                "zone",
                "retrieved_at",
                "activity_count",
                "observation_count",
                "issue_counts",
                "first_observed_on",
                "last_observed_on",
            },
        )


class BackfillCompleteTests(CanonicalReadFixture):
    def complete(self) -> bool:
        return self.read(
            lambda db: backfill_complete(self.key_values, db, zone=self.zone)
        )

    def test_false_for_another_zone_or_a_state_without_a_zone(self) -> None:
        populate(self)
        self.assertTrue(self.complete())
        self.zone = ZoneInfo("America/Los_Angeles")
        self.assertFalse(self.complete())
        self.zone = ZONE
        with self.manager.unit_of_work() as db:
            state = json.loads(self.key_values.get(db, STATE_KEY) or "{}")
            del state["zone"]
            self.key_values.set(db, STATE_KEY, json.dumps(state))
        self.assertFalse(self.complete())

    def test_false_before_and_true_after_the_backfill(self) -> None:
        self.assertFalse(self.complete())
        populate(self)
        self.assertTrue(self.complete())

    def test_false_for_a_failed_corrupt_or_outdated_record(self) -> None:
        populate(self)
        with self.manager.unit_of_work() as db:
            state = json.loads(self.key_values.get(db, STATE_KEY) or "{}")
            self.key_values.set(
                db, STATE_KEY, json.dumps({**state, "status": "failed"})
            )
        self.assertFalse(self.complete())

        with self.manager.unit_of_work() as db:
            self.key_values.set(db, STATE_KEY, "{not json")
        self.assertFalse(self.complete())

        with self.manager.unit_of_work() as db:
            self.key_values.set(db, STATE_KEY, json.dumps({**state, "versions": {}}))
        self.assertFalse(self.complete())

    def test_false_after_a_mapper_version_bump(self) -> None:
        populate(self)
        bumped = {
            key: version + 1
            for key, version in canonical_plans.current_mapper_versions().items()
        }
        with patch(
            "backend.sync.canonical_backfill.current_mapper_versions",
            return_value=bumped,
        ):
            self.assertFalse(self.complete())


class ReadsAfterBackfillTests(CanonicalReadFixture):
    """Ingest, backfill complete, parity mismatch, then a mapper change."""

    def ids(self, records: Any) -> list[tuple[str, str]]:
        return [(r.activity_id, r.provenance.provider.value) for r in records]

    def test_tables_serve_despite_a_parity_mismatch_until_mappers_change(self) -> None:
        self.assertIs(self.read(make_selector(self).reader_for), self.projection)

        populate(self)  # ingests the snapshots and completes the backfill
        mismatch = {
            "source": "legacy",
            "reason": "parity_failed",
            "digest": "stale",
            "parity": {"passed": False},
        }
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, "canonical_read_state", json.dumps(mismatch))
        selector = make_selector(self)

        self.assertTrue(self.read(selector.serves_tables))
        self.assertIsInstance(self.read(selector.reader_for), CanonicalTableReader)
        self.assertEqual(
            self.ids(self.read(selector.activities)),
            self.ids(self.read(self.table.activities)),
        )

        bumped = {
            key: version + 1
            for key, version in canonical_plans.current_mapper_versions().items()
        }
        with patch(
            "backend.sync.canonical_backfill.current_mapper_versions",
            return_value=bumped,
        ):
            self.assertFalse(self.read(selector.serves_tables))
            self.assertIs(self.read(selector.reader_for), self.projection)
            self.assertEqual(
                self.ids(self.read(selector.activities)),
                self.ids(self.read(self.projection.activities)),
            )

        # A zone change also sends reads back to legacy until re-projection ends.
        self.assertTrue(self.read(selector.serves_tables))
        self.zone = ZoneInfo("America/Los_Angeles")
        self.assertFalse(self.read(selector.serves_tables))
        self.assertIs(self.read(selector.reader_for), self.projection)
        backfill = new_backfill(self)
        for _ in range(MAX_BATCHES):
            with self.manager.unit_of_work() as db:
                if backfill.run_batch(db).done:
                    break
        self.assertTrue(self.read(selector.serves_tables))


if __name__ == "__main__":
    unittest.main()
