"""Current provider contracts and deterministic destructive-maintenance races."""

import json
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import test_server as fixtures
from backend.providers.garmin import collect_garmin_data, normalize_range_records

server = fixtures.server


class ProviderReviewTests(unittest.TestCase):
    def setUp(self):
        self.log_handlers = list(server.LOGGER.handlers)
        self.log_level = server.LOGGER.level
        self.log_propagate = server.LOGGER.propagate
        self.directory = tempfile.TemporaryDirectory(prefix="provider-review-")
        root = Path(self.directory.name)
        self.patches = [
            patch.object(server, "CONFIG", replace(server.CONFIG, app_password="", garmin_fixture_path="", garmin_email="synthetic@example.invalid")),
            patch.object(server, "DATA_DIR", root),
            patch.object(server, "DB_PATH", root / "fresh.db"),
            patch.object(server, "LOG_PATH", root / "synthetic.log"),
            patch.object(server.LOGGER, "disabled", True),
            patch.object(server, "initialise_logging"),
            patch.object(server, "MAINTENANCE_GATE", server.MaintenanceGate()),
        ]
        for item in self.patches:
            item.start()
        server.initialise_database()

    def tearDown(self):
        for handler in list(server.LOGGER.handlers):
            if handler not in self.log_handlers:
                server.LOGGER.removeHandler(handler)
                handler.close()
        server.LOGGER.setLevel(self.log_level)
        server.LOGGER.propagate = self.log_propagate
        if server.DATABASE_MANAGER:
            server.DATABASE_MANAGER.close()
        server.DATABASE_MANAGER = None
        server.DATABASE_MANAGER_SIGNATURE = None
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def test_performance_commit_merges_latest_full_source_and_historical_wellness(self):
        initial = {
            "synced_at": "2026-09-01T00:00:00+00:00", "athlete": {},
            "recent_activities": [{"id": "first"}], "recent_wellness": [{"id": "2025-01-01", "weight": 70}],
            "upcoming_calendar": [{"id": "calendar"}],
            "raw_provider_data": {"activities": [{"id": "first", "extra": "kept"}], "wellness": [{"id": "2025-01-01", "extra": 1}]},
            "provider_sync": {"calendar_window": {"start": "2025-01-01"}, "pagination": {"activities": {"complete": True}}},
            "historical_sync": {"window": "past"},
        }
        server.save_snapshot(initial)
        entered, release = threading.Event(), threading.Event()
        errors = []

        def fetch(existing):
            entered.set()
            self.assertTrue(release.wait(5))
            return {"synced_at": "2026-09-05T00:00:00+00:00", "athlete": {"weight": 71},
                    "recent_wellness": [{"id": "2026-09-05", "weight": 71}],
                    "recent_activities": existing["recent_activities"], "upcoming_calendar": [],
                    "raw_provider_data": {"athlete": {"provider_extra": 2}, "wellness": [{"id": "2026-09-05", "extra": 2}]}}

        def refresh():
            try:
                server.refresh_current_performance()
            except Exception as exc:
                errors.append(exc)

        with patch.object(server.IntervalsClient, "fetch_performance_snapshot", side_effect=fetch):
            worker = threading.Thread(target=refresh)
            worker.start()
            self.assertTrue(entered.wait(5))
            latest = {**initial, "recent_activities": [{"id": "concurrent"}],
                      "raw_provider_data": {**initial["raw_provider_data"], "activities": [{"id": "concurrent", "extra": "new"}]}}
            server.save_snapshot(latest)
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        saved = server.latest_snapshot()
        self.assertEqual(saved["recent_activities"], latest["recent_activities"])
        self.assertEqual(saved["raw_provider_data"]["activities"], latest["raw_provider_data"]["activities"])
        self.assertEqual(saved["provider_sync"]["calendar_window"], initial["provider_sync"]["calendar_window"])
        self.assertEqual(saved["upcoming_calendar"], initial["upcoming_calendar"])
        self.assertEqual(len(saved["raw_provider_data"]["wellness"]), 2)
        self.assertEqual(len(saved["recent_wellness"]), 2)

    def test_privacy_delete_drains_nested_writer_before_reporting_success(self):
        entered, release, deleted = threading.Event(), threading.Event(), threading.Event()
        errors = []

        @server.maintenance_operation
        def writer():
            try:
                entered.set()
                release.wait(5)
                with server.MAINTENANCE_GATE.operation():
                    server.save_snapshot({"synced_at": "synthetic", "recent_activities": [{"id": "private"}]})
            except Exception as exc:
                errors.append(exc)

        def erase():
            with server.MAINTENANCE_GATE.operation():
                server.delete_local_data()
            deleted.set()

        worker = threading.Thread(target=writer)
        worker.start()
        self.assertTrue(entered.wait(5))
        deletion = threading.Thread(target=erase)
        deletion.start()
        self.assertFalse(deleted.wait(.05))
        release.set()
        worker.join(5)
        deletion.join(5)
        self.assertEqual(errors, [])
        self.assertTrue(deleted.is_set())
        self.assertIsNone(server.latest_snapshot())
        self.assertEqual(server.MAINTENANCE_GATE.state(), {"active": False, "running_operations": 0})

    def test_privacy_delete_discards_queued_and_claimed_provider_payloads(self):
        server.enqueue_sync_job("intervals", "refresh", {"days": 7})
        claimed = server._claim_sync_job()
        server.enqueue_sync_job("garmin", "refresh", {"days": 7})
        server.delete_local_data()
        with patch.object(server, "_execute_sync_job") as execute:
            server._run_claimed_sync_job(claimed)
        execute.assert_not_called()
        self.assertIsNone(server._claim_sync_job())
        self.assertEqual(server.sync_jobs_state(), [])

    def test_privacy_delete_discards_claimed_coach_payload_without_failure_write(self):
        job = {"_maintenance_generation": server.MAINTENANCE_GATE.current_generation()}
        server.delete_local_data()
        with patch.object(server, "chat_with_coach") as coach, patch.object(server, "_persist_structured_command_failure") as failure:
            server._run_background_coach_job(job)
        coach.assert_not_called()
        failure.assert_not_called()

    def test_running_job_failure_cleanup_is_drained_before_deletion(self):
        server.enqueue_sync_job("intervals", "refresh", {"days": 7})
        job = server._claim_sync_job()
        entered, release, deleted = threading.Event(), threading.Event(), threading.Event()

        def execute(_job):
            entered.set()
            release.wait(5)
            server.set_kv("private_after_fetch", "synthetic")
            raise server.AppError(400, "Synthetic provider failure")

        def erase():
            server.delete_local_data()
            deleted.set()

        with patch.object(server, "_execute_sync_job", side_effect=execute):
            worker = threading.Thread(target=server._run_claimed_sync_job, args=(job,))
            worker.start()
            self.assertTrue(entered.wait(5))
            deletion = threading.Thread(target=erase)
            deletion.start()
            self.assertFalse(deleted.wait(.05))
            release.set()
            worker.join(5)
            deletion.join(5)
        self.assertTrue(deleted.is_set())
        self.assertFalse(server.get_kv("private_after_fetch"))
        self.assertEqual(server.sync_jobs_state(), [])

    def test_utf8_login_does_not_normalize_password_or_expose_it(self):
        for password in ("synthetic-ascii-123", "synthetic-\u00e4\u00f6\u00fc-123", "synthetic-\U0001f6b4-123"):
            with self.subTest(kind="utf8"), patch.object(server, "CONFIG", replace(server.CONFIG, app_password=password)), \
                    patch.object(server, "security_configuration_error", return_value=None), \
                    patch.object(server, "allow_rate", return_value=(True, 0)):
                # The storage fixture stays SQLite; login uses the real comparison and session SQL.
                with patch.object(server, "database_manager", return_value=self.manager_for_login()):
                    result = server.login_user(Mock(client_address=("127.0.0.1", 0)), password)
                    self.assertTrue(result["authenticated"])
                    with self.assertRaises(server.AppError) as error:
                        server.login_user(Mock(client_address=("127.0.0.1", 0)), password + "x")
                    self.assertEqual(error.exception.status, 401)
                    self.assertNotIn(password, error.exception.message)

    def manager_for_login(self):
        with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="")):
            return server.database_manager()

    def test_garmin_partial_metrics_and_backfill_keep_last_good_sources_and_cursors(self):
        sources = ("sleep", "hrv", "body_battery", "activities", "daily_stats", "resting_hr",
                   "heart_rate_zones", "readiness", "race_predictions", "max_metrics", "cycling_ftp", "running_threshold", "weight")
        previous = {source: [{"calendarDate": "2026-09-01", "synthetic_metric": 51}] for source in sources}
        previous["source_freshness"] = {source: "2026-09-01T00:00:00+00:00" for source in sources}
        client = Mock()
        client.login.return_value = (False, None)
        for source in sources:
            for historical in (False, True):
                with self.subTest(source=source, historical=historical):
                    server.set_kv("garmin_snapshot", json.dumps(previous))
                    server.update_provider_sync_cursor("garmin", "data", "2026-09-01", "synthetic")
                    server.update_provider_sync_cursor("garmin", "historical", "2026-08-01", "synthetic")
                    payload = {"synced_at": "2026-09-05T00:00:00+00:00", "start": "2026-08-01", "end": "2026-09-05",
                               "errors": [{"source": source, "message": "synthetic outage"}],
                               "provider_sync": {"pagination": {"activities": {"complete": source != "activities"}}}}
                    with patch.object(server, "Garmin", return_value=client), patch.object(server, "collect_garmin_data", return_value=payload):
                        result = server.sync_garmin(days=2, end_date=date(2026, 8, 30) if historical else None)
                    saved = server.garmin_snapshot()
                    self.assertEqual(saved[source], previous[source])
                    self.assertEqual(saved["source_freshness"][source], previous["source_freshness"][source])
                    self.assertEqual(result["status"], "partial")
                    self.assertEqual(server.provider_sync_cursor("garmin", "data")["cursor"], "2026-09-01")
                    self.assertEqual(server.provider_sync_cursor("garmin", "historical")["cursor"], "2026-08-01")

    def test_garmin_raw_duplicate_records_survive_fixture_and_sdk_sync(self):
        original = {"activityId": 123, "activityName": "Synthetic ride", "startTimeLocal": "2026-09-04 10:00:00",
                    "activityType": {"typeKey": "cycling"}, "duration": 3600, "distance": 30000,
                    "garmin_specific": {"sample": "preserved"}}
        intervals = {"id": "canonical", "start_date_local": "2026-09-04T10:00:00", "type": "Ride", "moving_time": 3600, "distance": 30000}
        server.save_snapshot({"synced_at": "synthetic", "recent_activities": [intervals]})
        for fixture in (False, True):
            with self.subTest(fixture=fixture):
                payload = {"synced_at": "2026-09-05T00:00:00+00:00", "start": "2026-09-04", "end": "2026-09-05",
                           "activities": [dict(original)], "errors": [],
                           "provider_sync": {"pagination": {"activities": {"complete": True}}}}
                client = Mock()
                client.login.return_value = (False, None)
                with patch.object(server, "Garmin", return_value=client), \
                        patch.object(server, "garmin_fixture_path", return_value=Path("synthetic.json") if fixture else None), \
                        patch.object(server, "load_garmin_fixture", return_value=payload), \
                        patch.object(server, "collect_garmin_data", return_value=payload):
                    result = server.sync_garmin(days=2)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(server.garmin_snapshot()["activities"], [original])
                self.assertEqual(server.garmin_public_state()["activities"], 0)
                self.assertEqual(server.garmin_snapshot()["activity_matches"], [{"garmin_activity_id": 123, "intervals_activity_id": "canonical"}])
                self.assertEqual(server.provider_sync_cursor("garmin", "data")["cursor"], payload["end"])

    def test_fresh_password_length_boundary_counts_unicode_characters(self):
        for length in (11, 12):
            with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="\U0001f6b4" * length)), \
                    patch.object(server, "SQLCIPHER_AVAILABLE", True):
                self.assertEqual(server.security_configuration_error() is None, length == 12)

    @unittest.skipUnless(server.SQLCIPHER_AVAILABLE, "SQLCipher requires the isolated application container")
    def test_fresh_sqlcipher_unicode_key_login_and_reopen(self):
        server.database_manager().close()
        encrypted_path = Path(self.directory.name) / "encrypted.db"
        configured = replace(server.CONFIG, app_password="synthetic-\u00e4-\U0001f6b4-123")
        with patch.object(server, "DB_PATH", encrypted_path), patch.object(server, "CONFIG", configured), \
                patch.object(server, "allow_rate", return_value=(True, 0)):
            server.initialise_database()
            server.set_kv("marker", "fresh")
            result = server.login_user(Mock(client_address=("127.0.0.1", 0)), configured.app_password)
            self.assertTrue(result["authenticated"])
            server.database_manager().close()
            server.DATABASE_MANAGER = None
            server.DATABASE_MANAGER_SIGNATURE = None
            self.assertEqual(server.get_kv("marker"), "fresh")


class GarminRangeContractTests(unittest.TestCase):
    def collect(self, hrv):
        client = Mock(spec=["get_activities_by_date", "get_sleep_daily", "get_hrv_data_range"])
        client.get_activities_by_date.return_value = []
        client.get_sleep_daily.return_value = []
        client.get_hrv_data_range.side_effect = hrv
        windows = [(date(2026, 9, 1), date(2026, 9, 1)), (date(2026, 9, 2), date(2026, 9, 2))]
        return collect_garmin_data(client, windows, start=windows[0][0], today=windows[-1][1], synced_at="synthetic",
                                   external_call=lambda _p, _s, fn, _d: fn(), redact=lambda value: value,
                                   include_current_metrics=False)

    def test_hrv_dictionary_and_list_windows_all_survive(self):
        result = self.collect([{"hrvSummaries": [{"calendarDate": "2026-09-01", "lastNightAvg": 51}]},
                               [{"calendarDate": "2026-09-02", "lastNightAvg": 52}]])
        self.assertEqual(len(result["hrv"]), 2)
        self.assertTrue(result["provider_sync"]["pagination"]["hrv"]["complete"])
        self.assertEqual(result["provider_sync"]["pagination"]["hrv"]["records"], 2)

    def test_hrv_empty_is_valid_but_unknown_or_failed_window_is_incomplete(self):
        for value in ({"unexpected": []}, None, "bad", RuntimeError("synthetic outage")):
            with self.subTest(shape=type(value).__name__):
                result = self.collect([{"hrvSummaries": [{"calendarDate": "2026-09-01", "lastNightAvg": 51}]}, value])
                self.assertEqual(len(result["hrv"]), 1)
                self.assertFalse(result["provider_sync"]["pagination"]["hrv"]["complete"])
                self.assertFalse(server.garmin_collection_complete(result))
        self.assertEqual(normalize_range_records("hrv", {"hrvSummaries": []}), [])
        self.assertEqual(normalize_range_records("hrv", []), [])


if __name__ == "__main__":
    unittest.main()
