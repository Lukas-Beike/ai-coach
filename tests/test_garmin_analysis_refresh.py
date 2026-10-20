from __future__ import annotations

import unittest
from contextlib import nullcontext
from datetime import date
from typing import Any, cast
from unittest.mock import Mock, patch

from backend.errors import AppError
from backend.providers.garmin import targeted_analysis_sources
from backend.sync.garmin_assembly import GarminAssembly
from backend.sync.garmin_service import GarminAnalysisRefreshService, GarminRemoteReader


class GarminAnalysisRefreshTests(unittest.TestCase):
    def test_targeted_endpoint_map_uses_pinned_sdk_methods(self) -> None:
        sources = targeted_analysis_sources()

        self.assertEqual(
            sources["recovery"]["readiness"][0], "get_training_readiness_range"
        )
        self.assertEqual(
            sources["performance"]["weekly_training_status"][0],
            "get_weekly_training_status",
        )
        self.assertEqual(
            sources["load"]["daily_training_status"][0],
            "get_daily_training_status",
        )
        self.assertEqual(sources["recovery"]["daily_stats"][0], "get_daily_summaries")

    def test_recovery_keeps_resting_hr_days_after_one_day_fails(self) -> None:
        reader = cast(Any, GarminRemoteReader.__new__(GarminRemoteReader))
        client = Mock(spec=["get_heart_rates"])
        client.get_heart_rates.side_effect = [
            {"restingHeartRate": 48},
            TypeError("invalid daily response"),
            {"restingHeartRate": 50},
        ]
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: (
            lambda _service, _operation, call, _details: call()
        )
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None
        reader._state_service = Mock()
        reader._warn = Mock()

        payload, complete = reader.fetch_analysis_data(
            "recovery", date(2026, 9, 22), date(2026, 9, 24)
        )

        self.assertEqual(
            payload["resting_hr"],
            [
                {"calendarDate": "2026-09-22", "restingHeartRate": 48},
                {"calendarDate": "2026-09-24", "restingHeartRate": 50},
            ],
        )
        self.assertFalse(complete["resting_hr"])
        self.assertEqual(client.get_heart_rates.call_count, 3)
        reader._state_service.record_capability_failure.assert_called_once()

    def test_sessions_reader_requests_only_bounded_activities(self) -> None:
        reader = cast(Any, GarminRemoteReader.__new__(GarminRemoteReader))
        client = Mock(spec=["get_activities_by_date"])
        client.get_activities_by_date.return_value = [
            {"activityId": 1, "startTimeLocal": "2026-09-24 09:00:00"}
        ]
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: (
            lambda _service, _operation, call, _details: call()
        )
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None
        reader._state_service = Mock()

        payload, complete = reader.fetch_analysis_data(
            "sessions", date(2026, 8, 14), date(2026, 9, 24)
        )

        self.assertEqual(set(payload), {"activities"})
        self.assertEqual(complete, {"activities": True})
        client.get_activities_by_date.assert_called_once_with(
            "2026-08-14", "2026-09-24"
        )

    def test_reader_requests_only_the_selected_area_sources(self) -> None:
        reader = cast(Any, GarminRemoteReader.__new__(GarminRemoteReader))
        client = Mock(spec=["get_daily_training_status"])
        client.get_daily_training_status.return_value = {"calendarDate": "2026-09-24"}
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: (
            lambda _service, _operation, call, _details: call()
        )
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None
        reader._state_service = Mock()

        payload, complete = reader.fetch_analysis_data(
            "load", date(2026, 9, 1), date(2026, 9, 24)
        )

        self.assertEqual(set(payload), {"daily_training_status"})
        self.assertEqual(complete["daily_training_status"], True)
        self.assertEqual(
            set(complete),
            {
                "activities",
                "training_load_activities",
                "daily_training_status",
                "training_load_balance",
                "weekly_training_status",
            },
        )
        self.assertFalse(complete["activities"])
        client.get_daily_training_status.assert_called_once_with("2026-09-24")
        self.assertNotIn("activities", payload)

    def make_service(self):
        reader = Mock()
        reader.fetch_analysis_data.return_value = (
            {
                "training_load_balance": {
                    "mostRecentTrainingLoadBalance": {"calendarDate": "2026-09-24"}
                }
            },
            {"training_load_balance": True, "daily_training_status": False},
        )
        manager = Mock()
        manager.unit_of_work.return_value = nullcontext(object())
        writer = Mock()
        payloads = Mock()
        payloads.snapshot.return_value = {
            "synced_at": "2026-09-23T12:00:00Z",
            "sleep": [{"calendarDate": "2026-09-23"}],
            "daily_training_status": {"old": "kept"},
            "source_freshness": {
                "sleep": {"freshness": "current"},
                "daily_training_status": {
                    "freshness": "current",
                    "fetched_at": "2026-09-22T12:00:00Z",
                    "window_start": "2026-09-20",
                    "window_end": "2026-09-22",
                },
            },
        }
        coordination = Mock()
        coordination.operation.return_value = nullcontext()
        coordination.acquire.return_value = True
        service = GarminAnalysisRefreshService(
            reader,
            manager,
            writer,
            payloads,
            coordination,
            lambda: "2026-09-24T12:00:00Z",
            lambda: True,
        )
        return service, reader, writer, coordination

    def test_refresh_updates_only_returned_sources_and_marks_gaps_partial(self) -> None:
        service, reader, writer, coordination = self.make_service()

        result = service.refresh("load", date(2026, 9, 1), date(2026, 9, 24))

        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            result["sources"],
            {"training_load_balance": True, "daily_training_status": False},
        )
        reader.fetch_analysis_data.assert_called_once_with(
            "load", date(2026, 9, 1), date(2026, 9, 24)
        )
        snapshot = writer.write_analysis_refresh.call_args.args[1]
        self.assertEqual(snapshot["sleep"], [{"calendarDate": "2026-09-23"}])
        self.assertEqual(snapshot["daily_training_status"], {"old": "kept"})
        self.assertEqual(snapshot["synced_at"], "2026-09-23T12:00:00Z")
        self.assertEqual(
            snapshot["source_freshness"]["sleep"], {"freshness": "current"}
        )
        self.assertEqual(
            snapshot["source_freshness"]["daily_training_status"]["freshness"], "stale"
        )
        self.assertEqual(
            snapshot["source_freshness"]["daily_training_status"]["fetched_at"],
            "2026-09-22T12:00:00Z",
        )
        self.assertEqual(
            snapshot["source_freshness"]["daily_training_status"]["window_start"],
            "2026-09-20",
        )
        self.assertEqual(
            snapshot["source_freshness"]["daily_training_status"]["window_end"],
            "2026-09-22",
        )
        coordination.release.assert_called_once()

    def test_sessions_refresh_persists_only_activities_and_returns_ok(self) -> None:
        service, reader, writer, _coordination = self.make_service()
        activity = {"activityId": 1, "startTimeLocal": "2026-09-24 09:00:00"}
        reader.fetch_analysis_data.return_value = (
            {"activities": [activity]},
            {"activities": True},
        )

        result = service.refresh("sessions", date(2026, 8, 14), date(2026, 9, 24))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["area"], "sessions")
        self.assertEqual(result["sources"], {"activities": True})
        reader.fetch_analysis_data.assert_called_once_with(
            "sessions", date(2026, 8, 14), date(2026, 9, 24)
        )
        writer.write_analysis_refresh.assert_called_once()
        self.assertEqual(
            writer.write_analysis_refresh.call_args.args[3], {"activities": [activity]}
        )

    def test_refresh_rejects_ranges_over_ninety_days(self) -> None:
        service, reader, writer, _coordination = self.make_service()
        with self.assertRaises(AppError):
            service.refresh("recovery", date(2026, 1, 1), date(2026, 4, 1))
        reader.fetch_analysis_data.assert_not_called()
        writer.write_analysis_refresh.assert_not_called()

    def test_assembly_factory_wires_targeted_service_and_disables_fixtures(
        self,
    ) -> None:
        control = Mock()
        control.resync_gate = None
        control.lock_wait_seconds = 0
        fixture_loader = Mock()
        fixture_loader.path.return_value = "fixture.json"
        reader = Mock()
        reader.configured.return_value = True
        payloads = Mock()
        database = Mock()
        assembly = GarminAssembly(
            dependencies=GarminAssembly.Inputs(
                provider=Mock(),
                persistence=Mock(database_manager=lambda: database),
                telemetry=Mock(),
                control=control,
            )
        )
        with (
            patch.object(assembly, "fixture_loader", return_value=fixture_loader),
            patch.object(assembly, "remote_reader", return_value=reader),
            patch.object(assembly, "payload_service", return_value=payloads),
        ):
            service = assembly.analysis_refresh_service()

        self.assertIsInstance(service, GarminAnalysisRefreshService)
        self.assertIs(service._database_manager, database)
        self.assertIs(service._reader, reader)
        self.assertIs(service._payload_service, payloads)
        self.assertFalse(service._configured())


if __name__ == "__main__":
    unittest.main()
