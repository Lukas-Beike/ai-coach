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
    daily_local_loads,
    refresh_after_job,
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
        # Before the next pass retires the row, the day sums already drop it.
        with self.manager.reader() as db:
            self.assertEqual(daily_local_loads(db), {})
        self.assertEqual(self._run()["counts"]["retired"], 2)
        with self.manager.reader() as db:
            self.assertEqual(stored_local_loads(db), {})


if __name__ == "__main__":
    unittest.main()


class LocalLoadReviewRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        self.stage = LocalLoadStage(
            key_values=KeyValueRepository(lambda: NOW),
            zone_provider=lambda: ZONE,
            clock=lambda: NOW,
        )
        with self.manager.unit_of_work() as db:
            _ftp(db, 250.0, date(2026, 9, 1))

    def _run(self) -> dict[str, Any]:
        with self.manager.unit_of_work() as db:
            self.stage.run_batch(db)
            return self.stage.summary(db)["counts"]

    def test_two_sessions_with_the_same_start_keep_their_own_load(self) -> None:
        # A split leaves two live sessions with the same sport and start.
        for provider_id, session in (("g1", "act_g1"), ("g2", "act_g2")):
            add_session_record(
                self.manager,
                ProviderId.GARMIN,
                provider_id,
                session,
                normalized_power=230.0 if session == "act_g1" else 250.0,
                moving_duration_s=4200.0 if session == "act_g1" else 3600.0,
            )
        self._run()
        self.assertEqual(self._run()["written"], 0)
        with self.manager.reader() as db:
            stored = stored_local_loads(db)
        self.assertAlmostEqual(stored["act_g1"]["session_load"]["value"], 98.75, 2)
        self.assertAlmostEqual(stored["act_g2"]["session_load"]["value"], 100.0, 6)
        # The day sum counts each session's load once, never its intensity factor.
        with self.manager.reader() as db:
            days = daily_local_loads(db)
        self.assertEqual(list(days), [stored["act_g1"]["session_load"]["observed_on"]])
        self.assertAlmostEqual(next(iter(days.values())), 198.75, 2)

    def test_one_value_outside_the_bounds_does_not_stop_the_pass(self) -> None:
        # 150,000 s at IF 1.6 is 41.7 h × 2.56 × 100 = 10,667 TSS > 10,000.
        add_session_record(
            self.manager,
            ProviderId.GARMIN,
            "g1",
            "act_g1",
            normalized_power=400.0,
            moving_duration_s=150_000.0,
        )
        add_session_record(
            self.manager,
            ProviderId.GARMIN,
            "g2",
            "act_g2",
            normalized_power=250.0,
            moving_duration_s=3600.0,
        )
        counts = self._run()
        self.assertEqual(counts["missing"], {"invalid_value": 1})
        self.assertEqual(counts["branches"], {"power": 1})

    def test_stored_loads_can_be_read_for_some_sessions_only(self) -> None:
        add_session_record(
            self.manager,
            ProviderId.GARMIN,
            "g1",
            "act_g1",
            normalized_power=250.0,
            moving_duration_s=3600.0,
        )
        self._run()
        with self.manager.reader() as db:
            self.assertEqual(set(stored_local_loads(db, ["act_g1"])), {"act_g1"})
            self.assertEqual(stored_local_loads(db, ["act_other"]), {})


class RefreshAfterJobTests(unittest.TestCase):
    def test_only_input_provider_jobs_request_a_pass(self) -> None:
        calls: list[bool] = []
        hook = refresh_after_job(lambda: calls.append(True))
        for provider in ("intervals", "garmin", "wahoo", "weather", "calendar"):
            hook({"provider": provider})
        self.assertEqual(calls, [True, True, True])
