"""Stored local session load (card M6): reconcile, serve, recompute and retire.

The worked example is the card's: NP 230 W at FTP 250 W for 70 minutes gives
IF 0.92 and 70/60 × 0.8464 × 100 = 98.75 TSS. With FTP 260 W it is
70/60 × (230/260)² × 100 = 91.30 TSS.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, date, datetime
from typing import Any

from backend.activities.activity_summary import activity_summaries
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import canonical_store
from backend.db.repositories import KeyValueRepository
from backend.performance.load import activity_rollup
from backend.providers.garmin_health_mapping import MAPPER_VERSION
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.local_load import (
    LocalLoadStage,
    stored_local_loads,
    with_local_loads,
)
from tests.canonical_detail_support import NOW, ZONE, add_session_record, open_manager


class _Source:
    """The canonical reads of the stage, over the tables directly."""

    def __init__(self) -> None:
        self._reader = CanonicalTableReader()

    def activity_summaries(self, db: Any) -> Any:
        return activity_summaries(self._reader.activity_sessions(db), ZONE)

    def observations(self, db: Any, kind: MetricKind) -> Any:
        return self._reader.observations(db, kind)

    def reader_for(self, db: Any) -> Any:
        return self._reader


def _ftp(db: Any, value: float, day: date) -> None:
    canonical_store.upsert_observation(
        db,
        Observation(
            kind=MetricKind.FTP,
            value=MetricValue(value, "W"),
            observed_on=day,
            observed_at=None,
            provenance=Provenance(
                provider=ProviderId.GARMIN,
                source_kind=SourceKind.PROVIDER_REPORTED,
                source_record_id="garmin-ftp",
                recorded_by=RecordingOrigin.GARMIN,
                retrieved_at=datetime(2026, 9, 1, tzinfo=UTC),
                label=None,
            ),
            sport=Sport.RIDE,
        ),
        mapper_version=MAPPER_VERSION,
        now=NOW,
    )


class LocalLoadStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.stage = LocalLoadStage(
            key_values=self.key_values, zone_provider=lambda: ZONE, clock=lambda: NOW
        )
        # A Garmin-only ride whose Garmin load is EPOC-based, so not TSS-like.
        add_session_record(
            self.manager,
            ProviderId.GARMIN,
            "g1",
            "act_g1",
            normalized_power=230.0,
            moving_duration_s=4200.0,
            load=180.0,
        )

    def _run(self) -> dict[str, Any]:
        with self.manager.unit_of_work() as db:
            self.stage.run_batch(db)
            return self.stage.summary(db)

    def _served(self) -> dict[str, Any]:
        with self.manager.reader() as db:
            summaries = _Source().activity_summaries(db)
            (summary,) = with_local_loads(summaries, stored_local_loads(db))
            return summary

    def test_garmin_only_session_gets_the_local_load(self) -> None:
        with self.manager.unit_of_work() as db:
            _ftp(db, 250.0, date(2026, 9, 1))
        state = self._run()
        self.assertEqual(state["counts"]["branches"], {"power": 1})
        summary = self._served()
        self.assertAlmostEqual(summary["training_load"], 98.75, places=2)
        self.assertAlmostEqual(summary["intensity"], 92.0, places=3)
        self.assertEqual(summary["load_branch"], "power")
        self.assertEqual(summary["sources"]["training_load"], "derived")
        rollup = activity_rollup([summary], 7, date(2026, 9, 10))
        self.assertAlmostEqual(rollup["training_load"], 98.7, places=1)
        self.assertNotIn("load_missing_sessions", rollup)

    def test_unchanged_pass_writes_nothing_and_ftp_change_recomputes(self) -> None:
        with self.manager.unit_of_work() as db:
            _ftp(db, 250.0, date(2026, 9, 1))
        self._run()
        self.assertEqual(self._run()["counts"]["written"], 0)
        with self.manager.unit_of_work() as db:
            _ftp(db, 260.0, date(2026, 9, 1))
        self.assertEqual(self._run()["counts"]["written"], 2)
        self.assertAlmostEqual(self._served()["training_load"], 91.30, places=2)

    def test_threshold_after_session_is_flagged(self) -> None:
        with self.manager.unit_of_work() as db:
            _ftp(db, 250.0, date(2026, 10, 1))
        state = self._run()
        self.assertEqual(state["counts"]["threshold_after_session"], 1)
        self.assertTrue(self._served()["load_threshold_after_session"])

    def test_pass_logs_counts_only(self) -> None:
        with self.manager.unit_of_work() as db:
            _ftp(db, 250.0, date(2026, 9, 1))
        with self.assertLogs("intervals_coach", level="INFO") as logs:
            self._run()
        (record,) = logs.records
        self.assertEqual(record.event, "local_load_reconciled")  # type: ignore[attr-defined]
        self.assertEqual(record.context["branches"], {"power": 1})  # type: ignore[attr-defined]
        self.assertNotIn("98.7", record.getMessage() + repr(record.context))  # type: ignore[attr-defined]

    def test_session_without_inputs_counts_as_missing(self) -> None:
        state = self._run()
        self.assertEqual(state["counts"]["missing"], {"no_ftp": 1})
        summary = self._served()
        self.assertNotIn("training_load", summary)
        rollup = activity_rollup([summary], 7, date(2026, 9, 10))
        self.assertEqual(rollup["load_missing_sessions"], 1)

    def test_deleted_session_retires_its_load(self) -> None:
        with self.manager.unit_of_work() as db:
            _ftp(db, 250.0, date(2026, 9, 1))
        self._run()
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_sessions SET state = 'deleted' "
                "WHERE activity_id = 'act_g1'"
            )
        self.assertEqual(self._run()["counts"]["retired"], 2)
        with self.manager.reader() as db:
            self.assertEqual(stored_local_loads(db), {})


if __name__ == "__main__":
    unittest.main()
