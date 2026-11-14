"""Domain rows (sleep, status, zones, gear) through the ingest and the re-projection.

Each test uses a temporary SQLite file with the schema initialized. Provider rows
are synthetic health records of one provider; the domain batches are built here or
come from patched plans. No account, network or real data directory is used.
"""

from __future__ import annotations

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
from support import temp_database

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
PROVIDER = ProviderId.GARMIN
HEALTH = canonical_plans.HEALTH_RECORD_KIND
FIRST_DAY = date(2026, 1, 1)
# The current health mapper, so a backfill does not re-project the records.
VERSION = canonical_plans.GARMIN_HEALTH_VERSION


def day_id(offset: int) -> str:
    return (FIRST_DAY + timedelta(days=offset)).isoformat()


def day_status(source_id: str, code: str = "PRODUCTIVE") -> Any:
    """A status row owned by the health record ``source_id`` on its own day."""
    return status(
        code=code,
        observed_on=date.fromisoformat(source_id),
        provenance=provenance(source_id, provider=PROVIDER),
    )


def batch(source_id: str, *codes: str, version: int = VERSION) -> DomainBatch:
    return DomainBatch(
        source_id,
        version,
        categorical=tuple(day_status(source_id, code) for code in codes),
    )


def raw(source_id: str) -> RawRecord:
    return RawRecord(HEALTH, source_id, {"id": source_id}, VERSION)


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
            provider=PROVIDER,
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
                    gear_item(provenance=provenance(day_id(0), provider=PROVIDER)),
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


def reprojecting(codes: Mapping[str, tuple[str, ...]]) -> Any:
    """Patch the re-projection plan: health record ``id`` emits ``codes[id]``."""

    def plan(raw_row: Mapping[str, Any], **_: Any) -> IngestPlan | None:
        source_id = str(raw_row["source_record_id"])
        result = IngestPlan(provider=PROVIDER)
        if source_id not in codes:
            return result
        return replace(result, domain_batches=(batch(source_id, *codes[source_id]),))

    return patch("backend.sync.canonical_backfill.reprojection_plan", side_effect=plan)


def bumped_health() -> Any:
    key = (PROVIDER.value, HEALTH)
    return patch.dict(
        canonical_plans._MAPPER_VERSIONS,
        {key: canonical_plans._MAPPER_VERSIONS[key] + 1},
    )


def mapped_versions(manager: Any) -> set[int]:
    with manager.reader() as db:
        return {
            int(row["mapped_version"])
            for row in db.execute(
                "SELECT mapped_version FROM provider_records WHERE record_kind = ?",
                (HEALTH,),
            )
        }


class BackfillFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.key_values = KeyValueRepository(lambda: NOW)
        self.manager = self.open_manager("backfill.db")

    def open_manager(self, name: str) -> DatabaseManager:
        return temp_database(self, name, row_factory=row_factory, schema=True)

    def backfill(self, batch_size: int = 200) -> CanonicalBackfill:
        return CanonicalBackfill(
            key_values=self.key_values,
            zone_provider=lambda: ZONE,
            clock=lambda: NOW,
            batch_size=batch_size,
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

    def counters(self, backfill: CanonicalBackfill) -> dict[str, int]:
        with self.manager.reader() as db:
            return dict(backfill.summary(db)["providers"][PROVIDER.value])


class BackfillReprojectionTests(BackfillFixture):
    def populate(self) -> CanonicalBackfill:
        batches = tuple(batch(day_id(i), "PRODUCTIVE") for i in range(3))
        with self.manager.unit_of_work() as db:
            ingest_plan(
                db,
                IngestPlan(
                    provider=PROVIDER,
                    raw_records=tuple(raw(b.source_record_id) for b in batches),
                    domain_batches=batches,
                ),
                retrieved_at=RETRIEVED_AT,
                deletion_window=None,
                zone=ZONE,
            )
        return self.backfill()

    def test_reprojection_replaces_and_retires_rows_of_each_record(self) -> None:
        backfill = self.populate()
        current = VERSION
        # Record 0 changes, record 1 no longer emits a batch, record 2 is unchanged.
        with (
            bumped_health(),
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
        self.assertEqual(mapped_versions(self.manager), {current + 1})
        self.assertEqual(self.counters(backfill)["retired"], 1)

    def test_a_failed_reprojection_rolls_back_rows_and_mapped_version(self) -> None:
        backfill = self.populate()
        before = self.domain_rows()
        with (
            bumped_health(),
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
        self.assertEqual(mapped_versions(self.manager), {VERSION})

    def test_deleted_raw_records_keep_their_rows(self) -> None:
        backfill = self.populate()
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE provider_records SET state = 'deleted' WHERE source_record_id = ?",
                (day_id(0),),
            )
        with bumped_health(), reprojecting({}):
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

        def plan(raw_row: Mapping[str, Any], **_: Any) -> IngestPlan:
            return IngestPlan(
                provider=PROVIDER, domain_batches=(batch(day_id(9), "PRODUCTIVE"),)
            )

        with (
            bumped_health(),
            patch(
                "backend.sync.canonical_backfill.reprojection_plan", side_effect=plan
            ),
            self.assertRaises(ValueError),
            self.manager.unit_of_work() as db,
        ):
            backfill.run_batch(db)


if __name__ == "__main__":
    unittest.main()
