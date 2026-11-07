"""The Intervals.icu ingest switch: off by default, gates every ingest read."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import nullcontext
from datetime import UTC
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from canonical_detail_support import open_manager

from backend.activities.duplicate_inspection import DuplicateInspector
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.http_api.settings_put import SettingsPutRoutes
from backend.sync.intervals import IntervalsSyncService
from backend.sync.intervals_ingest import INGEST_ENABLED_KEY, IntervalsIngestSwitch
from backend.sync.jobs import JobValidationError, normalize_sync_job_request
from backend.sync.provider_resync_assembly import IntervalsFullResync

NOW = "2026-11-07T08:00:00+00:00"
OFF = {"status": "skipped", "reason": "intervals_ingest_off"}


class IngestSwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.switch = IntervalsIngestSwitch(self.manager, self.key_values)

    def test_missing_key_means_off_and_save_round_trips(self) -> None:
        self.assertFalse(self.switch.enabled())

        self.assertEqual(
            self.switch.save({"enabled": True}), {"status": "ok", "enabled": True}
        )
        self.assertTrue(self.switch.enabled())
        self.switch.save({"enabled": False})
        self.assertFalse(self.switch.enabled())

    def test_save_rejects_anything_but_a_boolean(self) -> None:
        for values in ({}, {"enabled": "1"}, {"enabled": 1}, None):
            with self.subTest(values=values), self.assertRaises(AppError):
                self.switch.save(values)
        with self.manager.unit_of_work() as db:
            self.assertIsNone(self.key_values.get(db, INGEST_ENABLED_KEY))


class IngestGateTests(unittest.TestCase):
    def sync_service(
        self, enabled: bool
    ) -> tuple[IntervalsSyncService, MagicMock, Mock]:
        workflow = Mock()
        workflow.synchronize.return_value = {"status": "ok"}
        runtime = MagicMock()
        followup = Mock()
        followup.enqueue_after_sync.return_value = None
        service = IntervalsSyncService(
            SimpleNamespace(intervals_api_key="configured"),
            workflow,
            followup,
            Mock(),
            Mock(),
            runtime,
            ingest_enabled=lambda: enabled,
        )
        return service, runtime, followup

    def test_sync_reads_nothing_while_off(self) -> None:
        service, runtime, _followup = self.sync_service(False)

        self.assertEqual(service.sync("automatic"), OFF)
        runtime.operation.assert_not_called()

    def test_one_off_sync_runs_while_off_without_a_performance_follow_up(
        self,
    ) -> None:
        service, runtime, followup = self.sync_service(False)

        service.sync("manual", activity_days=42, one_off=True)

        runtime.operation.assert_called_once()
        followup.enqueue_after_sync.assert_not_called()

    def test_unconfigured_sync_still_reports_not_configured(self) -> None:
        service = IntervalsSyncService(
            SimpleNamespace(intervals_api_key=""),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            MagicMock(),
            ingest_enabled=lambda: False,
        )

        with self.assertRaises(AppError) as raised:
            service.sync("automatic")

        self.assertEqual(raised.exception.status, 503)

    def test_duplicate_inspector_finds_nothing_while_off(self) -> None:
        manager = Mock()
        inspector = DuplicateInspector(
            manager, Mock(), lambda: UTC, Mock(), ingest_enabled=lambda: False
        )

        self.assertIsNone(inspector.latest())
        manager.read_snapshot.assert_not_called()

    def test_full_resync_is_refused_while_off(self) -> None:
        service = Mock()
        resync = IntervalsFullResync(
            config=SimpleNamespace(intervals_api_key="configured"),
            intervals_service=service,
            competition_service=Mock(),
            gate=SimpleNamespace(operation=nullcontext),
            all_sync_days=-1,
            ingest_enabled=lambda: False,
        )

        with self.assertRaises(AppError) as raised:
            resync.run("operation-1", Mock())

        self.assertEqual(raised.exception.status, 409)
        service.sync.assert_not_called()

    def test_settings_route_stores_the_switch(self) -> None:
        switch = Mock()
        switch.save.return_value = {"status": "ok", "enabled": True}
        handler = Mock()
        handler.read_json.return_value = {"enabled": True}
        resumed: list[str] = []
        routes = SettingsPutRoutes(
            Mock(),
            intervals_ingest=lambda: switch,
            resume_provider_schedule=resumed.append,
        )

        self.assertTrue(routes.handle(handler, "/api/settings/intervals-ingest"))

        switch.save.assert_called_once_with({"enabled": True})
        self.assertEqual(resumed, ["intervals"])
        handler.send_json.assert_called_once_with(
            200, {"status": "ok", "enabled": True}
        )

    def test_turning_the_ingest_off_resumes_nothing(self) -> None:
        switch = Mock()
        switch.save.return_value = {"status": "ok", "enabled": False}
        handler = Mock()
        handler.read_json.return_value = {"enabled": False}
        resumed: list[str] = []
        routes = SettingsPutRoutes(
            Mock(),
            intervals_ingest=lambda: switch,
            resume_provider_schedule=resumed.append,
        )

        routes.handle(handler, "/api/settings/intervals-ingest")

        self.assertEqual(resumed, [])

    def test_one_off_is_an_intervals_refresh_flag_only(self) -> None:
        job = normalize_sync_job_request(
            "intervals", "refresh", {"days": 42, "one_off": True}, all_sync_days=-1
        )
        self.assertEqual(job["payload"], {"days": 42, "one_off": True})
        with self.assertRaises(JobValidationError):
            normalize_sync_job_request(
                "garmin", "refresh", {"one_off": True}, all_sync_days=-1
            )
        with self.assertRaises(JobValidationError):
            normalize_sync_job_request(
                "intervals", "refresh", {"one_off": "yes"}, all_sync_days=-1
            )


if __name__ == "__main__":
    unittest.main()
