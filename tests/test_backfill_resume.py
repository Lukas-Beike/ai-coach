"""Backfill chains that stopped before the history floor are queued again."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import Mock

from test_sync_queue import SyncQueueFixtureMixin

from backend.errors import AppError
from backend.sync.backfill_resume import (
    BackfillChainResumer,
    historical_backfill_payload,
)
from backend.sync.daily import DailySyncMarkerService
from backend.sync.executor import HistoricalSyncJobOwner
from backend.sync.job_outcomes import SyncJobOutcomeService
from backend.sync.jobs import STREAM_BACKFILL, STREAM_HISTORY_CURSOR
from backend.sync.scheduler import DailySyncScheduler, DailySyncSchedulerConfig

FLOOR = date(2000, 1, 1)
CHUNK_DAYS = 90
GARMIN = "garmin"
WAHOO = "wahoo"


class _Policy:
    def __init__(self, configured: bool = True, blocked: bool = False) -> None:
        self._configured = configured
        self._blocked = blocked

    def configured(self) -> bool:
        return self._configured

    def blocked(self) -> bool:
        return self._blocked


class _SyncState:
    def __init__(self, cursors: dict[tuple[str, str], str] | None = None) -> None:
        self.cursors = cursors or {}

    def cursor(self, provider: str, stream: str) -> dict[str, Any]:
        return {"cursor": self.cursors.get((provider, stream))}


class _Clock:
    def __init__(self) -> None:
        self.seconds = 1000.0

    def __call__(self) -> float:
        return self.seconds


class BackfillChainResumerTests(SyncQueueFixtureMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.clock = _Clock()
        self.sync_state = _SyncState({(GARMIN, STREAM_HISTORY_CURSOR): "2026-03-01"})
        self.policies: dict[str, Any] = {GARMIN: _Policy(), WAHOO: _Policy()}

    def resumer(self) -> BackfillChainResumer:
        return BackfillChainResumer(
            self.service,
            self.sync_state,  # type: ignore[arg-type]
            self.policies,
            chunk_days=CHUNK_DAYS,
            earliest_date=FLOOR,
            clock=self.clock,
        )

    def jobs(self, job_type: str | None = None) -> list[dict[str, Any]]:
        with self.manager.reader() as db:
            rows = db.execute(
                "SELECT provider, type, status, requested_by, payload FROM sync_jobs "
                "ORDER BY created_at, id"
            ).fetchall()
        return [
            {**dict(row), "payload": json.loads(row["payload"])}
            for row in rows
            if job_type is None or row["type"] == job_type
        ]

    def continuations(self) -> list[dict[str, Any]]:
        with self.manager.reader() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id, provider, type, created_at FROM sync_jobs "
                    "WHERE requested_by='backfill' ORDER BY created_at, id"
                ).fetchall()
            ]

    def fail_last_attempt(self, job_id: str) -> None:
        """Fail the claimed job on its last attempt, as the executor does."""
        claimed = self.store.claim()
        assert claimed is not None and claimed["id"] == job_id
        outcomes = SyncJobOutcomeService(
            self.store,
            Mock(),
            self.wake_event,
            str,
            Mock(),
            lambda: datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
            retry_base_seconds=1,
            retry_max_seconds=2,
        )
        outcomes.record_failure(
            {**claimed, "attempts": 3},
            AppError(503, "synthetic", reason="provider_unavailable"),
        )

    def test_a_chain_that_failed_its_last_attempt_is_queued_again_by_the_scheduler(
        self,
    ) -> None:
        first = self.service.enqueue(
            GARMIN,
            STREAM_BACKFILL,
            {"days": CHUNK_DAYS, "end_date": "2026-03-01"},
            requested_by="startup",
        )
        self.fail_last_attempt(first["id"])
        self.assertEqual(self.store.state(first["id"])["status"], "failed")

        self.resumer().resume()

        streams = [j for j in self.jobs(STREAM_BACKFILL) if j["provider"] == GARMIN]
        self.assertEqual(["failed", "queued"], [job["status"] for job in streams])
        self.assertEqual("scheduler", streams[1]["requested_by"])
        # The walk resumes below the cursor the failed chain left behind.
        self.assertEqual("2026-02-28", streams[1]["payload"]["end_date"])
        self.assertEqual(CHUNK_DAYS, streams[1]["payload"]["days"])

    def test_every_chain_below_the_floor_is_queued_once(self) -> None:
        self.resumer().resume()
        self.resumer().resume()

        self.assertEqual(
            {
                (GARMIN, "historical_backfill"),
                (GARMIN, "wellness_backfill"),
                (GARMIN, "rating_backfill"),
                (GARMIN, STREAM_BACKFILL),
                (WAHOO, STREAM_BACKFILL),
            },
            {(job["provider"], job["type"]) for job in self.jobs()},
        )
        self.assertEqual(5, len(self.jobs()))

    def test_active_finished_unconfigured_and_blocked_chains_are_left_alone(
        self,
    ) -> None:
        self.service.enqueue(
            GARMIN, "wellness_backfill", {"days": CHUNK_DAYS}, requested_by="startup"
        )
        self.sync_state.cursors[(GARMIN, "historical")] = FLOOR.isoformat()
        self.sync_state.cursors[(GARMIN, "rating_history")] = "1999-12-31"
        self.policies[WAHOO] = _Policy(configured=False)
        before = len(self.jobs())

        self.resumer().resume()

        queued = {(job["provider"], job["type"]) for job in self.jobs()[before:]}
        self.assertEqual({(GARMIN, STREAM_BACKFILL)}, queued)

        self.policies[GARMIN] = _Policy(blocked=True)
        self.sync_state.cursors[(GARMIN, STREAM_HISTORY_CURSOR)] = "2026-01-01"
        count = len(self.jobs())
        self.resumer().resume()
        self.assertEqual(count, len(self.jobs()))

    def test_a_chain_is_queued_at_most_once_per_interval(self) -> None:
        resumer = self.resumer()
        resumer.resume()
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE sync_jobs SET status='failed'")
        queued = len(self.jobs())

        self.clock.seconds += timedelta(hours=5, minutes=59).total_seconds()
        resumer.resume()
        self.assertEqual(queued, len(self.jobs()))

        self.clock.seconds += timedelta(minutes=2).total_seconds()
        resumer.resume()
        self.assertEqual(2 * queued, len(self.jobs()))

    def test_connecting_wahoo_queues_its_stream_backfill_at_once(self) -> None:
        resumer = self.resumer()
        resumer.resume()
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE sync_jobs SET status='failed'")
        before = len(self.jobs())

        # Inside the interval, so only the explicit connect path may queue.
        resumer.resume_provider(WAHOO, requested_by="connection")

        added = self.jobs()[before:]
        self.assertEqual(
            [(WAHOO, STREAM_BACKFILL)], [(j["provider"], j["type"]) for j in added]
        )
        self.assertEqual("connection", added[0]["requested_by"])

    def test_connecting_an_unconfigured_provider_queues_nothing(self) -> None:
        self.policies[WAHOO] = _Policy(configured=False)

        self.resumer().resume_provider(WAHOO, requested_by="connection")

        self.assertEqual([], self.jobs())

    def test_connect_does_not_duplicate_an_active_chain(self) -> None:
        self.service.enqueue(
            WAHOO, STREAM_BACKFILL, {"days": CHUNK_DAYS}, requested_by="startup"
        )

        self.resumer().resume_provider(WAHOO, requested_by="connection")
        self.resumer().resume_provider(WAHOO, requested_by="connection")

        self.assertEqual(1, len(self.jobs(STREAM_BACKFILL)))

    def test_a_chunk_that_re_reads_its_own_window_still_queues_its_continuation(
        self,
    ) -> None:
        owner = HistoricalSyncJobOwner(
            sync_state_repository=self.sync_state,  # type: ignore[arg-type]
            queue_service=self.service,
            local_now=lambda: datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
            sync_period_defaults={},
            all_sync_days=-1,
            sync_chunk_days=CHUNK_DAYS,
            sync_earliest_date=FLOOR,
        )
        job = self.service.enqueue(
            WAHOO,
            STREAM_BACKFILL,
            {"days": CHUNK_DAYS, "end_date": "2026-03-01"},
            requested_by="startup",
        )
        window = {"historical_next_end": "2026-03-01"}

        # Each skipped file hands over to a job with the same end day; the
        # second one must not be taken for the first one's successor.
        for expected in (1, 2, 3):
            self.now = f"2026-09-20T12:0{expected}:00+00:00"
            owner.queue_next(job, window, "completed")
            continuations = self.continuations()
            self.assertEqual(expected, len(continuations))
            job = continuations[-1]

    def test_the_daily_scheduler_pass_resumes_chains_after_its_refreshes(self) -> None:
        calls: list[str] = []
        queue = Mock()
        queue.active.return_value = True
        scheduler = DailySyncScheduler(
            Mock(),
            queue,
            Mock(spec=DailySyncMarkerService),
            Mock(),
            self.maintenance_gate,
            config=DailySyncSchedulerConfig(
                calendar_url_enabled=False,
                garmin_automatic_sync_days=7,
                auto_update_label="auto",
            ),
            schedule_policies={},
            backfill_resumer=lambda: calls.append("resume"),
        )

        scheduler.schedule()

        self.assertEqual(["resume"], calls)


class HistoricalBackfillPayloadTests(unittest.TestCase):
    def payload(self, cursor: str | None) -> dict[str, Any] | None:
        state = _SyncState({(GARMIN, STREAM_HISTORY_CURSOR): cursor} if cursor else {})
        return historical_backfill_payload(
            state,  # type: ignore[arg-type]
            GARMIN,
            STREAM_BACKFILL,
            chunk_days=CHUNK_DAYS,
            earliest_date=FLOOR,
            reason="synthetic",
        )

    def test_the_payload_resumes_one_day_below_the_cursor(self) -> None:
        self.assertEqual(
            {"days": 90, "reason": "synthetic", "end_date": "2026-02-28"},
            self.payload("2026-03-01"),
        )

    def test_no_cursor_starts_at_the_newest_end_and_the_floor_ends_the_chain(
        self,
    ) -> None:
        self.assertEqual({"days": 90, "reason": "synthetic"}, self.payload(None))
        self.assertIsNone(self.payload("2000-01-01"))
        self.assertIsNone(self.payload("1999-06-01"))

    def test_an_unreadable_cursor_resumes_without_an_end_date(self) -> None:
        self.assertEqual({"days": 90, "reason": "synthetic"}, self.payload("garbage"))


if __name__ == "__main__":
    unittest.main()
