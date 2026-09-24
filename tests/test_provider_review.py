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
from backend.http_api.rate_limit import RateLimiter
from backend.performance import context as performance_context
from backend.performance import garmin_metrics as performance_garmin_metrics
from backend.performance import history as performance_history
from backend.providers.garmin import (
    GarminCollectionOptions,
    collect_garmin_data,
    normalize_range_records,
)
from backend.runtime import maintenance as runtime_maintenance
from backend.sync import garmin as garmin_sync
from backend.sync import garmin_service
from backend.sync.intervals import IntervalsSnapshotReader
from backend.sync.worker import SyncJobWorker

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
            patch.object(server.observability, "configure_logging"),
            patch.object(runtime_maintenance, "MAINTENANCE_GATE", runtime_maintenance.MaintenanceGate()),
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
        server.sync_state_repository().save_snapshot(initial)
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
                server.performance_refresh_service().refresh()
            except Exception as exc:
                errors.append(exc)

        with patch.object(IntervalsSnapshotReader, "fetch_performance_snapshot", side_effect=fetch):
            worker = threading.Thread(target=refresh)
            worker.start()
            self.assertTrue(entered.wait(5))
            latest = {**initial, "recent_activities": [{"id": "concurrent"}],
                      "raw_provider_data": {**initial["raw_provider_data"], "activities": [{"id": "concurrent", "extra": "new"}]}}
            server.sync_state_repository().save_snapshot(latest)
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        saved = server.sync_state_repository().latest_snapshot()
        self.assertEqual(saved["recent_activities"], latest["recent_activities"])
        self.assertEqual(saved["raw_provider_data"]["activities"], latest["raw_provider_data"]["activities"])
        self.assertEqual(saved["provider_sync"]["calendar_window"], initial["provider_sync"]["calendar_window"])
        self.assertEqual(saved["upcoming_calendar"], initial["upcoming_calendar"])
        self.assertEqual(len(saved["raw_provider_data"]["wellness"]), 2)
        self.assertEqual(len(saved["recent_wellness"]), 2)

    def test_privacy_delete_drains_nested_writer_before_reporting_success(self):
        entered, release, deleted = threading.Event(), threading.Event(), threading.Event()
        errors = []

        @runtime_maintenance.maintenance_operation
        def writer():
            try:
                entered.set()
                release.wait(5)
                with runtime_maintenance.MAINTENANCE_GATE.operation():
                    server.sync_state_repository().save_snapshot({"synced_at": "synthetic", "recent_activities": [{"id": "private"}]})
            except Exception as exc:
                errors.append(exc)

        def erase():
            with runtime_maintenance.MAINTENANCE_GATE.operation():
                server.privacy_delete_service().delete()
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
        self.assertIsNone(server.sync_state_repository().latest_snapshot())
        self.assertEqual(runtime_maintenance.MAINTENANCE_GATE.state(), {"active": False, "running_operations": 0})

    def test_privacy_delete_discards_queued_provider_payloads(self):
        server.sync_job_queue_service().enqueue("intervals", "refresh", {"days": 7})
        server.sync_job_queue_service().enqueue("garmin", "refresh", {"days": 7})
        server.privacy_delete_service().delete()
        self.assertIsNone(server.sync_job_store().claim())
        self.assertEqual(server.sync_job_queue_service().list(), [])

    def test_privacy_delete_discards_claimed_coach_payload_without_failure_write(self):
        job = {"_maintenance_generation": runtime_maintenance.MAINTENANCE_GATE.current_generation()}
        server.privacy_delete_service().delete()
        with patch("backend.coach.chat_turn.CoachChatTurnService.run") as coach, patch("backend.coach.turn_failures.CoachTurnFailureService.persist") as failure:
            server._run_background_coach_job(job)
        coach.assert_not_called()
        failure.assert_not_called()

    def test_running_job_failure_cleanup_is_drained_before_deletion(self):
        server.sync_job_queue_service().enqueue("intervals", "refresh", {"days": 7})
        entered, release, deleted = threading.Event(), threading.Event(), threading.Event()

        def execute(_job):
            entered.set()
            release.wait(5)
            server.set_kv("private_after_fetch", "synthetic")
            raise server.AppError(400, "Synthetic provider failure")

        def erase():
            server.privacy_delete_service().delete()
            deleted.set()

        executor = server.sync_job_executor()
        sync_worker = SyncJobWorker(
            server.sync_job_store(),
            executor,
            runtime_maintenance.MAINTENANCE_GATE,
            0.01,
        )
        with patch.object(executor, "execute", side_effect=execute):
            worker = threading.Thread(target=sync_worker.run_loop)
            worker.start()
            self.assertTrue(entered.wait(5))
            deletion = threading.Thread(target=erase)
            deletion.start()
            self.assertFalse(deleted.wait(.05))
            release.set()
            sync_worker.stop()
            worker.join(5)
            deletion.join(5)
        self.assertFalse(worker.is_alive())
        self.assertTrue(deleted.is_set())
        self.assertFalse(server.get_kv("private_after_fetch"))
        self.assertEqual(server.sync_job_queue_service().list(), [])

    def test_utf8_login_does_not_normalize_password_or_expose_it(self):
        for password in ("synthetic-ascii-123", "synthetic-\u00e4\u00f6\u00fc-123", "synthetic-\U0001f6b4-123"):
            with self.subTest(kind="utf8"), patch.object(server, "CONFIG", replace(server.CONFIG, app_password=password)), \
                    patch.object(server.app_config, "security_configuration_error", return_value=None), \
                    patch.object(RateLimiter, "allow", autospec=True, return_value=(True, 0)) as rate_limit:
                # The storage fixture stays SQLite; login uses the real comparison and session SQL.
                with patch.object(server, "database_manager", return_value=self.manager_for_login()):
                    result = server.session_auth_service().login_user(Mock(client_address=("127.0.0.1", 0)), password)
                    self.assertTrue(result["authenticated"])
                    rate_limit.assert_called_with(server.RATE_LIMITER, "login:127.0.0.1", 5, 900)
                    with self.assertRaises(server.AppError) as error:
                        server.session_auth_service().login_user(Mock(client_address=("127.0.0.1", 0)), password + "x")
                    self.assertEqual(error.exception.status, 401)
                    self.assertNotIn(password, error.exception.message)

    def manager_for_login(self):
        with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="")):
            return server.database_manager()

    def test_garmin_partial_metrics_and_backfill_keep_last_good_sources_and_cursors(self):
        sources = ("sleep", "hrv", "body_battery", "activities", "daily_stats", "resting_hr",
                   "heart_rate_zones", "readiness", "race_predictions", "max_metrics", "cycling_ftp", "running_threshold", "weight")
        previous = {source: [{"calendarDate": "2026-09-01", "synthetic_metric": 51}] for source in sources}
        previous["source_freshness"] = {source: {"fetched_at": "2026-09-01T00:00:00+00:00", "observed_at": "2026-09-01", "freshness": "current"} for source in sources}
        client = Mock()
        client.login.return_value = (False, None)
        for source in sources:
            for historical in (False, True):
                with self.subTest(source=source, historical=historical):
                    server.set_kv("garmin_snapshot", json.dumps(previous))
                    server.sync_state_repository().update_cursor("garmin", "data", "2026-09-01", "synthetic")
                    server.sync_state_repository().update_cursor("garmin", "historical", "2026-08-01", "synthetic")
                    payload = {"synced_at": "2026-09-05T00:00:00+00:00", "start": "2026-08-01", "end": "2026-09-05",
                               "errors": [{"source": source, "message": "synthetic outage"}],
                               "provider_sync": {"pagination": {"activities": {"complete": source != "activities"}}}}
                    with patch.object(
                        server.GarminClientFactory, "available", return_value=True
                    ), patch.object(
                        server.GarminClientFactory, "create", return_value=client
                    ), patch.object(
                        garmin_service, "collect_garmin_data", return_value=payload
                    ):
                        result = server.garmin_sync_service().sync(
                            days=2,
                            end_date=date(2026, 8, 30) if historical else None,
                        )
                    saved = server.garmin_payload_service().snapshot()
                    self.assertEqual(saved[source], previous[source])
                    self.assertEqual(saved["source_freshness"][source]["fetched_at"], previous["source_freshness"][source]["fetched_at"])
                    self.assertEqual(saved["source_freshness"][source]["freshness"], "stale")
                    self.assertEqual(result["status"], "partial")
                    self.assertEqual(server.sync_state_repository().cursor("garmin", "data")["cursor"], "2026-09-01")
                    self.assertEqual(server.sync_state_repository().cursor("garmin", "historical")["cursor"], "2026-08-01")

    def test_garmin_raw_duplicate_records_survive_fixture_and_sdk_sync(self):
        original = {"activityId": 123, "activityName": "Synthetic ride", "startTimeLocal": "2026-09-04 10:00:00",
                    "activityType": {"typeKey": "cycling"}, "duration": 3600, "distance": 30000,
                    "garmin_specific": {"sample": "preserved"}}
        intervals = {"id": "canonical", "start_date_local": "2026-09-04T10:00:00", "type": "Ride", "moving_time": 3600, "distance": 30000}
        server.sync_state_repository().save_snapshot({"synced_at": "synthetic", "recent_activities": [intervals]})
        for fixture in (False, True):
            with self.subTest(fixture=fixture):
                payload = {"synced_at": "2026-09-05T00:00:00+00:00", "start": "2026-09-04", "end": date.today().isoformat(),
                           "activities": [dict(original)], "errors": [],
                           "provider_sync": {"pagination": {"activities": {"complete": True}}}}
                client = Mock()
                client.login.return_value = (False, None)
                with patch.object(server.GarminClientFactory, "available", return_value=True), \
                        patch.object(server.GarminClientFactory, "create", return_value=client), \
                        patch.object(garmin_sync.GarminFixtureLoader, "path", return_value=Path("synthetic.json") if fixture else None), \
                        patch.object(garmin_sync.GarminFixtureLoader, "load", return_value=payload), \
                        patch.object(garmin_service, "collect_garmin_data", return_value=payload):
                    result = server.garmin_sync_service().sync(days=2)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(server.garmin_payload_service().snapshot()["activities"], [original])
                self.assertEqual(server.garmin_projection_service().public_state()["activities"], 0)
                self.assertEqual(server.garmin_payload_service().snapshot()["activity_matches"], [{"garmin_activity_id": 123, "intervals_activity_id": "canonical"}])
                self.assertEqual(server.sync_state_repository().cursor("garmin", "data")["cursor"], payload["end"])
                context = server.coach_training_context_service().build()
                self.assertNotIn("garmin_specific", context)
                self.assertEqual(context.count('"id":"canonical"'), 1)

    def test_retained_metric_freshness_reaches_coach_and_public_without_new_history(self):
        first = {"synced_at": "2026-09-01T09:00:00+00:00", "errors": [],
                 "cycling_ftp": {"calendarDate": "2026-08-30", "functionalThresholdPower": 302},
                 "readiness": {"calendarDate": "2026-09-01", "score": 73},
                 "weight": {"calendarDate": "2026-08-31", "weight": 72}}
        garmin_sync.merge_sources(first, {})
        performance_history.append_garmin_performance_history(
            first, {}, server.local_now().date()
        )
        history = first["performance_history"]
        self.assertEqual([row["date"] for row in history], ["2026-08-30", "2026-08-31", "2026-09-01"])
        for failed in (True, False):
            second = {"synced_at": "2026-09-05T09:00:00+00:00", "errors": [
                {"source": source, "message": "synthetic outage"} for source in ("cycling_ftp", "readiness", "weight")
            ] if failed else [], "activities": [{"activityId": 8, "startTimeLocal": "2025-02-01T12:00:00"}]}
            garmin_sync.merge_sources(second, first)
            performance_history.append_garmin_performance_history(
                second, first, server.local_now().date()
            )
            server.set_kv("garmin_snapshot", json.dumps(second))
            server.sync_state_repository().save_snapshot({"synced_at": second["synced_at"], "athlete": {}, "recent_wellness": [], "recent_activities": []})
            public = performance_context.current_performance_context(
                server.sync_state_repository().latest_snapshot(),
                server.garmin_payload_service().snapshot(),
                server.profile_service().get(),
                server.local_now().date(),
            )
            for key in ("cycling_ftp_watts", "weight_kg"):
                data = public["metrics"][key]
                self.assertEqual(data["freshness"], "stale")
                self.assertEqual(data["fetched_at"], first["synced_at"])
                self.assertIn("Letzter guter Wert", data["note"])
            self.assertEqual(public["metrics"]["cycling_ftp_watts"]["observed_at"], "2026-08-30")
            readiness = public["recovery"]["source_freshness"]["readiness"]
            self.assertEqual(readiness["freshness"], "stale")
            self.assertEqual(readiness["observed_at"], "2026-09-01")
            self.assertEqual(server.garmin_projection_service().public_state()["source_freshness"]["readiness"]["fetched_at"], first["synced_at"])
            coach = server.garmin_projection_service().coach_context(include_performance=True)
            self.assertEqual(coach["performance"]["thresholds"]["cycling_ftp_watts"]["freshness"], "stale")
            context = server.coach_training_context_service().build()
            self.assertIn('"freshness":"stale"', context)
            self.assertIn('"observed_at":"2026-08-30"', context)
            self.assertEqual(second["performance_history"], history)

    def test_undated_successful_metrics_do_not_fabricate_observation_history(self):
        payload = {"synced_at": "2026-09-05T09:00:00+00:00", "errors": [],
                   "cycling_ftp": {"functionalThresholdPower": 300}}
        garmin_sync.merge_sources(payload, {})
        performance_history.append_garmin_performance_history(
            payload, {}, server.local_now().date()
        )
        metric = performance_garmin_metrics.garmin_performance_metrics(
            payload, server.local_now().date()
        )["cycling_ftp_watts"]
        self.assertEqual(metric["freshness"], "current")
        self.assertIsNone(metric["observed_at"])
        self.assertEqual(metric["fetched_at"], payload["synced_at"])
        self.assertEqual(payload["performance_history"], [])

    def test_backfill_does_not_redate_retained_activity_maximum(self):
        first = {"synced_at": "2026-09-01T09:00:00+00:00", "errors": [],
                 "activities": [{"activityId": 1, "startTimeLocal": "2026-08-31T12:00:00", "activityType": "cycling", "maxHR": 180}]}
        garmin_sync.merge_sources(first, {})
        performance_history.append_garmin_performance_history(
            first, {}, server.local_now().date()
        )
        second = {"synced_at": "2026-09-05T09:00:00+00:00", "errors": [],
                  "activities": [{"activityId": 2, "startTimeLocal": "2025-02-01T12:00:00", "activityType": "cycling", "maxHR": 150}]}
        garmin_sync.merge_sources(second, first)
        performance_history.append_garmin_performance_history(
            second, first, server.local_now().date()
        )
        metric = performance_garmin_metrics.garmin_performance_metrics(
            second, server.local_now().date()
        )["cycling_max_hr_bpm"]
        self.assertEqual(metric["value"], 180)
        self.assertEqual(metric["observed_at"], "2026-08-31")
        self.assertEqual(second["performance_history"], first["performance_history"])

    def test_fresh_password_length_boundary_counts_unicode_characters(self):
        for length in (11, 12):
            with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="\U0001f6b4" * length)), \
                    patch.object(server, "SQLCIPHER_AVAILABLE", True):
                self.assertEqual(
                    server.app_config.security_configuration_error(
                        server.CONFIG, sqlcipher_available=server.SQLCIPHER_AVAILABLE
                    ) is None,
                    length == 12,
                )

    @unittest.skipUnless(server.SQLCIPHER_AVAILABLE, "SQLCipher requires the isolated application container")
    def test_fresh_sqlcipher_unicode_key_login_and_reopen(self):
        server.database_manager().close()
        encrypted_path = Path(self.directory.name) / "encrypted.db"
        configured = replace(server.CONFIG, app_password="synthetic-\u00e4-\U0001f6b4-123")
        with patch.object(server, "DB_PATH", encrypted_path), patch.object(server, "CONFIG", configured), \
                patch.object(RateLimiter, "allow", autospec=True, return_value=(True, 0)) as rate_limit:
            server.initialise_database()
            server.set_kv("marker", "fresh")
            result = server.session_auth_service().login_user(Mock(client_address=("127.0.0.1", 0)), configured.app_password)
            self.assertTrue(result["authenticated"])
            rate_limit.assert_called_with(server.RATE_LIMITER, "login:127.0.0.1", 5, 900)
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
                                   options=GarminCollectionOptions(include_current_metrics=False))

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
                self.assertFalse(garmin_sync.collection_complete(result))
        self.assertEqual(normalize_range_records("hrv", {"hrvSummaries": []}), [])
        self.assertEqual(normalize_range_records("hrv", []), [])


if __name__ == "__main__":
    unittest.main()
