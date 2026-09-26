"""Tests for explicit Intervals synchronization composition."""

import logging
import unittest
from datetime import date
from unittest.mock import Mock

from backend.sync.intervals_assembly import IntervalsSyncAssembly


class IntervalsSyncAssemblyTests(unittest.TestCase):
    def test_assembly_construction_does_not_resolve_lazy_dependencies(self):
        callbacks = {
            "config": Mock(),
            "database_manager": Mock(),
            "state_repository": Mock(),
            "daily_markers": Mock(),
            "request": Mock(),
            "athlete_clock": Mock(),
            "utc_now": Mock(),
            "operation_observer": Mock(),
            "sync_job_queue": Mock(),
            "remote_planned_unit_reconciler": Mock(),
            "workout_library_refresh_service": Mock(),
            "workout_library_service": Mock(),
        }
        IntervalsSyncAssembly(
            **callbacks,
            key_values=Mock(),
            event_buffer=Mock(),
            redact_text=Mock(),
            logger=logging.getLogger("test.intervals.assembly"),
            intervals_resync_gate=Mock(),
            intervals_sync_lock=Mock(),
            sync_period_defaults={"intervals": 90, "garmin": 30},
            all_sync_days=-1,
            sync_chunk_days=90,
            sync_earliest_date=date(2000, 1, 1),
            calendar_history_days=35,
            calendar_future_days=35,
            performance_wait_seconds=120,
            poll_seconds=1.0,
        )

        for callback in callbacks.values():
            callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
