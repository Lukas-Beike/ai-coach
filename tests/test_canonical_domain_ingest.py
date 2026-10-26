"""Domain rows (sleep, status, zones, gear) through the ingest and the backfill.

Each test uses a temporary SQLite file with the schema initialized. Provider rows
are synthetic; the domain batches come from patched plans, because no mapper
emits them yet. No account, network or real data directory is used.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

from canonical_domain_support import gear_item, provenance, status

from backend.canonical.vocabulary import ProviderId
from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.providers import canonical_plans
from backend.providers.canonical_plans import DomainBatch, IngestPlan, RawRecord
from backend.sync.canonical_backfill import CanonicalBackfill
from backend.sync.canonical_ingest import ingest_plan

ZONE = ZoneInfo("Europe/Berlin")
NOW = "2026-09-20T08:00:00+00:00"
RETRIEVED_AT = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
INTERVALS = ProviderId.INTERVALS
WELLNESS = canonical_plans.WELLNESS_RECORD_KIND
FIRST_DAY = date(2026, 1, 1)
# The current wellness mapper, so a backfill does not re-project the records.
VERSION = canonical_plans.INTERVALS_WELLNESS_VERSION


def day_id(offset: int) -> str:
    return (FIRST_DAY + timedelta(days=offset)).isoformat()


def day_status(source_id: str, code: str = "PRODUCTIVE") -> Any:
    """A status row owned by the wellness record ``source_id`` on its own day."""
    return status(
        code=code,
        observed_on=date.fromisoformat(source_id),
        provenance=provenance(source_id, provider=INTERVALS),
    )


def batch(source_id: str, *codes: str, version: int = VERSION) -> DomainBatch:
    return DomainBatch(
        source_id,
        version,
        categorical=tuple(day_status(source_id, code) for code in codes),
    )


def raw(source_id: str) -> RawRecord:
    return RawRecord(WELLNESS, source_id, {"id": source_id}, VERSION)


def rows(db: Any, table: str = "categorical_observations") -> list[tuple[Any, ...]]:
    return [
        tuple(row.values() if isinstance(row, dict) else row)
        for row in db.execute(
            f"SELECT source_record_id, code, state FROM {table} "
            "ORDER BY source_record_id, code"
        ).fetchall()
    ]


class IngestFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db = sqlite3.connect(Path(self.temporary.name) / "ingest.db")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)

    def ingest(self, *batches: DomainBatch, raws: tuple[str, ...] | None = None) -> Any:
        sources = (
            raws if raws is not None else tuple(b.source_record_id for b in batches)
        )
        plan = IngestPlan(
            provider=INTERVALS,
            raw_records=tuple(raw(source) for source in sources),
            domain_batches=batches,
        )
        return ingest_plan(
            self.db, plan, retrieved_at=RETRIEVED_AT, deletion_window=None, zone=ZONE
        )


class IngestDomainTests(IngestFixture):
    def test_batches_are_written_then_left_unchanged(self) -> None:
        first = self.ingest(batch(day_id(0), "PRODUCTIVE"), batch(day_id(1), "PEAKING"))
        self.assertEqual((first.written, first.unchanged, first.retired), (2, 0, 0))
        again = self.ingest(batch(day_id(0), "PRODUCTIVE"), batch(day_id(1), "PEAKING"))
        self.assertEqual((again.written, again.unchanged, again.retired), (0, 2, 0))

    def test_a_changed_batch_updates_and_retires_rows_of_its_source_only(self) -> None:
        self.ingest(
            DomainBatch(
                day_id(0),
                VERSION,
                categorical=(day_status(day_id(0)),),
                gear_items=(
                    gear_item(provenance=provenance(day_id(0), provider=INTERVALS)),
                ),
            ),
            batch(day_id(1), "PEAKING"),
        )
        counters = self.ingest(batch(day_id(0), "RECOVERY"))
        self.assertEqual((counters.updated, counters.retired), (1, 1))
        self.assertEqual(
            rows(self.db),
            [(day_id(0), "RECOVERY", "active"), (day_id(1), "PEAKING", "active")],
        )
        self.assertEqual(
            [row["state"] for row in self.db.execute("SELECT state FROM gear_items")],
            ["retired"],
        )

    def test_an_empty_batch_retires_the_rows_of_its_source(self) -> None:
        self.ingest(batch(day_id(0), "PRODUCTIVE"))
        counters = self.ingest(DomainBatch(day_id(0), VERSION))
        self.assertEqual(counters.retired, 1)
        self.assertEqual(rows(self.db), [(day_id(0), "PRODUCTIVE", "retired")])

    def test_a_plan_without_the_raw_record_keeps_its_rows(self) -> None:
        self.ingest(batch(day_id(0), "PRODUCTIVE"))
        counters = self.ingest(raws=(day_id(5),))
        self.assertEqual(counters.retired, 0)
        self.assertEqual(rows(self.db), [(day_id(0), "PRODUCTIVE", "active")])

    def test_a_batch_without_its_raw_record_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.ingest(batch(day_id(0), "PRODUCTIVE"), raws=(day_id(1),))


def wellness_snapshot(days: int, *, synced_at: str = NOW) -> dict[str, Any]:
    return {
        "synced_at": synced_at,
        "upcoming_calendar": [],
        "provider_sync": {"pagination": {}},
        "raw_provider_data": {
            "activities": [],
            "wellness": [{"id": day_id(i)} for i in range(days)],
        },
    }


def with_batches(code: str) -> Any:
    """Patch the snapshot plan so each wellness record also emits one status."""
    real = canonical_plans.intervals_snapshot_ingest_plan

    def plan(snapshot: Mapping[str, Any], *, zone: Any) -> IngestPlan:
        result = real(snapshot, zone=zone)
        return replace(
            result,
            domain_batches=tuple(
                batch(record.source_record_id, code)
                for record in result.raw_records
                if record.record_kind == WELLNESS
            ),
        )

    return patch(
        "backend.sync.canonical_backfill.intervals_snapshot_ingest_plan",
        side_effect=plan,
    )


def reprojecting(codes: Mapping[str, tuple[str, ...]]) -> Any:
    """Patch the re-projection plan: wellness record ``id`` emits ``codes[id]``."""
    real = canonical_plans.reprojection_plan

    def plan(raw_row: Mapping[str, Any], *, zone: Any) -> IngestPlan | None:
        result = real(raw_row, zone=zone)
        source_id = str(raw_row["source_record_id"])
        if result is None or raw_row["record_kind"] != WELLNESS:
            return result
        if source_id not in codes:
            return result
        return replace(result, domain_batches=(batch(source_id, *codes[source_id]),))

    return patch("backend.sync.canonical_backfill.reprojection_plan", side_effect=plan)


def bumped_wellness() -> Any:
    key = (INTERVALS.value, WELLNESS)
    return patch.dict(
        canonical_plans._MAPPER_VERSIONS,
        {key: canonical_plans._MAPPER_VERSIONS[key] + 1},
    )


class BackfillFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.manager = self.open_manager("backfill.db")

    def open_manager(self, name: str) -> DatabaseManager:
        manager = DatabaseManager(
            Path(self.temporary.name) / name, sqlite3, row_factory=row_factory
        )
        self.addCleanup(manager.close)
        with manager.unit_of_work() as db:
            initialize_schema(db)
        return manager

    def backfill(self, batch_size: int = 200) -> CanonicalBackfill:
        return CanonicalBackfill(
            key_values=self.key_values,
            zone_provider=lambda: ZONE,
            clock=lambda: NOW,
            batch_size=batch_size,
        )

    def insert_snapshot(self, payload: dict[str, Any], manager: Any = None) -> None:
        with (manager or self.manager).unit_of_work() as db:
            db.execute(
                "INSERT INTO snapshots(payload, created_at, synced_at, "
                "recent_activity_count) VALUES (?, ?, ?, 0)",
                (json.dumps(payload), NOW, payload["synced_at"]),
            )

    def complete(self, backfill: CanonicalBackfill, manager: Any = None) -> None:
        for _ in range(1000):
            with (manager or self.manager).unit_of_work() as db:
                if backfill.run_batch(db).done:
                    return
        self.fail("backfill did not finish")

    def domain_rows(self, manager: Any = None) -> list[tuple[Any, ...]]:
        with (manager or self.manager).reader() as db:
            return rows(db)

    def mapped_versions(self) -> set[int]:
        with self.manager.reader() as db:
            return {
                int(row["mapped_version"])
                for row in db.execute(
                    "SELECT mapped_version FROM provider_records WHERE record_kind = ?",
                    (WELLNESS,),
                )
            }

    def counters(self, backfill: CanonicalBackfill) -> dict[str, int]:
        with self.manager.reader() as db:
            return dict(backfill.summary(db)["providers"][INTERVALS.value])


class BackfillIngestTests(BackfillFixture):
    def live_ingest(self, *batches: DomainBatch) -> None:
        with self.manager.unit_of_work() as db:
            ingest_plan(
                db,
                IngestPlan(
                    provider=INTERVALS,
                    raw_records=tuple(raw(b.source_record_id) for b in batches),
                    domain_batches=batches,
                ),
                retrieved_at=RETRIEVED_AT,
                deletion_window=None,
                zone=ZONE,
            )

    def test_ingest_inserts_batches_and_never_changes_existing_rows(self) -> None:
        self.live_ingest(batch(day_id(0), "PRODUCTIVE"))
        self.insert_snapshot(wellness_snapshot(2))
        backfill = self.backfill()
        with with_batches("RECOVERY"):
            self.complete(backfill)
        self.assertEqual(
            self.domain_rows(),
            [(day_id(0), "PRODUCTIVE", "active"), (day_id(1), "RECOVERY", "active")],
        )

    def test_a_retired_source_is_not_revived_by_the_backfill(self) -> None:
        self.live_ingest(batch(day_id(0), "PRODUCTIVE"))
        self.live_ingest(DomainBatch(day_id(0), VERSION))
        self.insert_snapshot(wellness_snapshot(1))
        backfill = self.backfill()
        with with_batches("RECOVERY"):
            self.complete(backfill)
        self.assertEqual(self.domain_rows(), [(day_id(0), "PRODUCTIVE", "retired")])

    def test_a_resumed_run_writes_the_same_rows_as_an_uninterrupted_one(self) -> None:
        self.insert_snapshot(wellness_snapshot(180))
        with with_batches("PRODUCTIVE"):
            self.complete(self.backfill(batch_size=250))
            other = self.open_manager("resumed.db")
            self.insert_snapshot(wellness_snapshot(180), other)
            self.complete(self.backfill(batch_size=100), other)
        self.assertEqual(len(self.domain_rows()), 180)
        self.assertEqual(self.domain_rows(other), self.domain_rows())


class BackfillReprojectionTests(BackfillFixture):
    def populate(self) -> CanonicalBackfill:
        self.insert_snapshot(wellness_snapshot(3))
        backfill = self.backfill()
        with with_batches("PRODUCTIVE"):
            self.complete(backfill)
        return backfill

    def test_reprojection_replaces_and_retires_rows_of_each_record(self) -> None:
        backfill = self.populate()
        current = canonical_plans.INTERVALS_WELLNESS_VERSION
        # Record 0 changes, record 1 no longer emits a batch, record 2 is unchanged.
        with (
            bumped_wellness(),
            reprojecting({day_id(0): ("RECOVERY",), day_id(2): ("PRODUCTIVE",)}),
        ):
            self.complete(backfill)
        self.assertEqual(
            self.domain_rows(),
            [
                (day_id(0), "RECOVERY", "active"),
                (day_id(1), "PRODUCTIVE", "retired"),
                (day_id(2), "PRODUCTIVE", "active"),
            ],
        )
        self.assertEqual(self.mapped_versions(), {current + 1})
        self.assertEqual(self.counters(backfill)["retired"], 1)

    def test_a_failed_reprojection_rolls_back_rows_and_mapped_version(self) -> None:
        backfill = self.populate()
        before = self.domain_rows()
        with (
            bumped_wellness(),
            reprojecting({day_id(0): ("RECOVERY",)}),
            patch.object(
                canonical_store,
                "set_mapped_version",
                side_effect=RuntimeError("injected failure"),
            ),
            self.assertRaises(RuntimeError),
            self.manager.unit_of_work() as db,
        ):
            backfill.run_batch(db)
        self.assertEqual(self.domain_rows(), before)
        self.assertEqual(
            self.mapped_versions(), {canonical_plans.INTERVALS_WELLNESS_VERSION}
        )

    def test_deleted_raw_records_keep_their_rows(self) -> None:
        backfill = self.populate()
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE provider_records SET state = 'deleted' WHERE source_record_id = ?",
                (day_id(0),),
            )
        with bumped_wellness(), reprojecting({}):
            self.complete(backfill)
        self.assertEqual(
            self.domain_rows(),
            [
                (day_id(0), "PRODUCTIVE", "active"),
                (day_id(1), "PRODUCTIVE", "retired"),
                (day_id(2), "PRODUCTIVE", "retired"),
            ],
        )

    def test_a_batch_of_another_record_is_rejected(self) -> None:
        backfill = self.populate()

        def plan(raw_row: Mapping[str, Any], *, zone: Any) -> IngestPlan:
            return IngestPlan(
                provider=INTERVALS, domain_batches=(batch(day_id(9), "PRODUCTIVE"),)
            )

        with (
            bumped_wellness(),
            patch(
                "backend.sync.canonical_backfill.reprojection_plan", side_effect=plan
            ),
            self.assertRaises(ValueError),
            self.manager.unit_of_work() as db,
        ):
            backfill.run_batch(db)


if __name__ == "__main__":
    unittest.main()
