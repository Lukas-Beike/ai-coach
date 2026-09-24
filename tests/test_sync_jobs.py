import hashlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend.db.manager import DatabaseManager
from backend.sync.jobs import (
    JobValidationError,
    SyncJobInvalidOperationError,
    SyncJobInvalidStateError,
    SyncJobNotFoundError,
    SyncJobStore,
    aggregate_job_status,
    bounded_progress,
    has_active_job,
    is_retryable_error,
    job_dto,
    list_jobs,
    normalize_sync_job_request,
    read_job,
    retry_delay,
    validate_job_request,
)


class SyncJobContractTests(unittest.TestCase):
    def test_request_contract_normalizes_provider_and_type(self):
        result = validate_job_request(" Garmin ", " REFRESH ", {"days": 30})
        self.assertEqual(
            result, {"provider": "garmin", "type": "refresh", "payload": {"days": 30}}
        )
        with self.assertRaisesRegex(ValueError, "Unsupported job type"):
            validate_job_request("garmin", "body_battery_retry", {})

    def test_status_aggregation_distinguishes_partial_and_running(self):
        self.assertEqual(aggregate_job_status([]), "completed")
        self.assertEqual(aggregate_job_status([{"status": "running"}]), "running")
        self.assertEqual(
            aggregate_job_status([{"status": "completed"}, {"status": "failed"}]),
            "partial",
        )
        self.assertEqual(
            aggregate_job_status([{"status": "failed"}, {"status": "failed"}]), "failed"
        )
        self.assertEqual(
            bounded_progress([{"status": "completed"}, {"status": "queued"}]), (1, 2)
        )

    def test_retry_backoff_is_bounded_and_classified(self):
        self.assertEqual(retry_delay(1, base_seconds=10, max_seconds=25), 10)
        self.assertEqual(retry_delay(4, base_seconds=10, max_seconds=25), 25)
        self.assertTrue(is_retryable_error("network_error"))
        self.assertFalse(is_retryable_error("auth_required"))

    def test_job_dto_decodes_payload_and_bounds_item_projection(self):
        result = job_dto(
            {
                "id": "job-1",
                "provider": "garmin",
                "type": "refresh",
                "payload": '{"days": 7}',
            },
            [
                {
                    "id": 1,
                    "item_key": "activities",
                    "operation": "read",
                    "status": "completed",
                    "attempts": 1,
                }
            ],
        )
        self.assertEqual(result["payload"], {"days": 7})
        self.assertEqual(result["progress"], {"completed": 1, "total": 1})
        self.assertEqual(
            set(result["items"][0]),
            {
                "id",
                "item_key",
                "operation",
                "remote_id",
                "status",
                "attempts",
                "error_class",
                "error_detail",
                "created_at",
                "updated_at",
            },
        )

    def test_persistence_helpers_use_caller_owned_connection(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(
            "CREATE TABLE sync_jobs (id TEXT, provider TEXT, type TEXT, status TEXT, payload TEXT, requested_by TEXT, attempts INTEGER, available_at TEXT, started_at TEXT, finished_at TEXT, error_class TEXT, created_at TEXT, updated_at TEXT);"
            "CREATE TABLE sync_job_items (id INTEGER, job_id TEXT, item_key TEXT, operation TEXT, remote_id TEXT, status TEXT, attempts INTEGER, error_class TEXT, error_detail TEXT, created_at TEXT, updated_at TEXT);"
        )
        db.execute(
            "INSERT INTO sync_jobs VALUES ('j1','garmin','refresh','queued','{}','test',0,NULL,NULL,NULL,NULL,'1','1')"
        )
        db.execute(
            "INSERT INTO sync_job_items VALUES (1,'j1','data','read',NULL,'queued',0,NULL,NULL,'1','1')"
        )
        db.commit()
        job, _items = read_job(db, "j1")
        self.assertEqual(job["id"], "j1")
        self.assertEqual(list_jobs(db, 1)[0]["id"], "j1")
        self.assertTrue(has_active_job(db, "garmin", "refresh"))
        db.close()

    def test_projection_tolerates_malformed_persisted_payload(self):
        result = job_dto(
            {
                "id": "job-2",
                "provider": "weather",
                "type": "refresh",
                "payload": "not-json",
            },
            [],
        )
        self.assertEqual(result["payload"], {})
        self.assertEqual(result["status"], "completed")


class SyncJobRequestNormalizationTests(unittest.TestCase):
    all_sync_days = -1
    workout_id = "123e4567-e89b-12d3-a456-426614174000"
    payload_hash = "a" * 64

    def normalize(self, provider, job_type, payload=None):
        return normalize_sync_job_request(
            provider, job_type, payload, all_sync_days=self.all_sync_days
        )

    def assert_invalid(self, provider, job_type, payload, message):
        with self.assertRaisesRegex(JobValidationError, message):
            self.normalize(provider, job_type, payload)

    def test_allowlists_and_bounded_object_payload(self):
        self.assert_invalid("unknown", "refresh", {}, "Unsupported provider")
        self.assert_invalid("garmin", "unknown", {}, "Unsupported job type")
        self.assert_invalid("garmin", "refresh", [], "payload must be an object")
        self.assert_invalid(
            "garmin",
            "refresh",
            {str(index): index for index in range(33)},
            "too many fields",
        )
        self.assert_invalid(
            "garmin", "refresh", {"days": 7, "credential": "fake"}, "Felder"
        )

    def test_generic_sync_payloads_normalize_values_and_keep_only_allowlisted_fields(
        self,
    ):
        self.assertEqual(
            self.normalize(
                " Garmin ",
                " REFRESH ",
                {
                    "days": "30",
                    "end_date": "2026-09-20T00:00:00",
                    "reason": "  manual  ",
                },
            ),
            {
                "provider": "garmin",
                "type": "refresh",
                "payload": {"days": 30, "end_date": "2026-09-20", "reason": "manual"},
            },
        )
        self.assertEqual(
            self.normalize("weather", "refresh", {"force": False, "reason": " "}),
            {
                "provider": "weather",
                "type": "refresh",
                "payload": {"force": False, "reason": "job"},
            },
        )
        self.assertEqual(
            self.normalize("calendar", "refresh", {"reason": "x" * 100})["payload"][
                "reason"
            ],
            "x" * 80,
        )
        self.assertEqual(self.normalize("calendar", "refresh")["payload"], {})
        self.assert_invalid("weather", "refresh", {"days": 7}, "Felder")
        self.assert_invalid(
            "intervals", "refresh", {"end_date": "not-a-date"}, "Backfill-Enddatum"
        )

    def test_sync_days_accepts_sentinel_and_bounds_regular_ranges(self):
        for value, expected in ((-1, -1), ("-1", -1), (1, 1), (3660, 3660)):
            with self.subTest(value=value):
                self.assertEqual(
                    self.normalize("intervals", "refresh", {"days": value})["payload"][
                        "days"
                    ],
                    expected,
                )
        for value, message in (
            ("invalid", "Synchronisationszeitraum ist ungültig"),
            (0, "Synchronisationszeitraum ist zu groß"),
            (3661, "Synchronisationszeitraum ist zu groß"),
        ):
            with self.subTest(value=value):
                self.assert_invalid("intervals", "refresh", {"days": value}, message)

    def test_refresh_validation_order_and_omitted_reason(self):
        self.assert_invalid(
            "intervals",
            "refresh",
            {"days": "invalid", "unsupported": True},
            "Der Job enthält nicht unterstützte Felder",
        )
        self.assertEqual(
            self.normalize("calendar", "refresh", {"reason": None})["payload"],
            {},
        )

    def test_boolean_fields_require_actual_booleans(self):
        for value in (True, False):
            with self.subTest(value=value):
                self.assertIs(
                    self.normalize("weather", "refresh", {"force": value})["payload"][
                        "force"
                    ],
                    value,
                )
        self.assert_invalid(
            "weather", "refresh", {"force": 1}, "force muss ein Boolean"
        )
        self.assert_invalid(
            "weather", "refresh", {"force": "true"}, "force muss ein Boolean"
        )

    def test_historical_backfill_is_limited_to_activity_providers(self):
        for provider in ("intervals", "garmin"):
            with self.subTest(provider=provider):
                result = self.normalize(provider, "historical_backfill", {"days": -1})
                self.assertEqual(result["provider"], provider)
        for provider in ("calendar", "weather"):
            with self.subTest(provider=provider):
                self.assert_invalid(
                    provider,
                    "historical_backfill",
                    {},
                    "Historischer Backfill ist nur",
                )

    def test_performance_and_competition_jobs_are_intervals_only(self):
        for job_type in ("performance_refresh", "competition_push"):
            with self.subTest(job_type=job_type):
                self.assertEqual(
                    self.normalize("intervals", job_type, {"reason": "  sync  "})[
                        "payload"
                    ],
                    {"reason": "sync"},
                )
                self.assert_invalid(
                    "garmin", job_type, {}, "Dieser Job ist nur für Intervals.icu"
                )
                self.assert_invalid("intervals", job_type, {"days": 7}, "Felder")
        self.assertEqual(
            self.normalize("intervals", "performance_refresh", {"reason": " "})[
                "payload"
            ],
            {"reason": "job"},
        )

    def test_plan_push_normalizes_entries_reason_and_repair(self):
        entry = {
            "library_workout_id": self.workout_id,
            "expected_payload_hash": self.payload_hash.upper(),
        }
        result = self.normalize(
            "intervals",
            "plan_push",
            {"entries": [entry], "reason": "  reviewed  ", "repair": True},
        )
        self.assertEqual(
            result,
            {
                "provider": "intervals",
                "type": "plan_push",
                "payload": {
                    "entries": [
                        {
                            "library_workout_id": self.workout_id,
                            "expected_payload_hash": self.payload_hash,
                        }
                    ],
                    "reason": "reviewed",
                    "repair": True,
                },
            },
        )
        without_repair = self.normalize(
            "intervals", "plan_push", {"entries": [entry], "repair": False}
        )
        self.assertEqual(without_repair["payload"]["reason"], "job")
        self.assertNotIn("repair", without_repair["payload"])

    def test_plan_push_rejects_provider_fields_count_uuid_hash_and_booleans(self):
        self.assert_invalid("garmin", "plan_push", {}, "nur für Intervals.icu")
        self.assert_invalid(
            "intervals", "plan_push", {"entries": [], "unknown": True}, "Felder"
        )
        self.assert_invalid("intervals", "plan_push", {"entries": []}, "1 bis 28")
        entries = [
            {
                "library_workout_id": self.workout_id,
                "expected_payload_hash": self.payload_hash,
            }
        ]
        self.assertEqual(
            len(
                self.normalize("intervals", "plan_push", {"entries": entries * 28})[
                    "payload"
                ]["entries"]
            ),
            28,
        )
        self.assert_invalid(
            "intervals", "plan_push", {"entries": entries * 29}, "1 bis 28"
        )
        self.assert_invalid(
            "intervals", "plan_push", {"entries": [None]}, "lokale UUID"
        )
        self.assert_invalid(
            "intervals",
            "plan_push",
            {
                "entries": [
                    {
                        "library_workout_id": "not-a-uuid",
                        "expected_payload_hash": self.payload_hash,
                    }
                ]
            },
            "lokale UUID",
        )
        self.assert_invalid(
            "intervals",
            "plan_push",
            {
                "entries": [
                    {
                        "library_workout_id": self.workout_id,
                        "expected_payload_hash": "g" * 64,
                    }
                ]
            },
            "aktuellen Payload-Hash",
        )
        self.assert_invalid(
            "intervals",
            "plan_push",
            {
                "entries": [
                    {
                        "library_workout_id": self.workout_id,
                        "expected_payload_hash": self.payload_hash[:-1],
                    }
                ]
            },
            "aktuellen Payload-Hash",
        )
        legacy_entry = {
            "library_workout_id": "a-" * 18,
            "expected_payload_hash": self.payload_hash,
            "credential": "fake",
        }
        normalized = self.normalize(
            "intervals", "plan_push", {"entries": [legacy_entry]}
        )
        self.assertEqual(
            normalized["payload"]["entries"],
            [
                {
                    "library_workout_id": legacy_entry["library_workout_id"],
                    "expected_payload_hash": self.payload_hash,
                }
            ],
        )
        self.assert_invalid(
            "intervals",
            "plan_push",
            {"entries": entries, "repair": 1},
            "repair muss ein Boolean",
        )


class SyncJobStoreTests(unittest.TestCase):
    now = "2026-09-20T12:00:00+00:00"

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "sync-jobs.sqlite",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            db.executescript(
                """
                CREATE TABLE sync_jobs (
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL, type TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL, requested_by TEXT NOT NULL,
                    attempts INTEGER NOT NULL, progress_total INTEGER NOT NULL,
                    progress_completed INTEGER NOT NULL, error_class TEXT,
                    available_at TEXT, started_at TEXT, finished_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE sync_job_items (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, item_key TEXT NOT NULL,
                    operation TEXT NOT NULL, payload_hash TEXT NOT NULL, remote_id TEXT,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL, error_class TEXT,
                    error_detail TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(job_id, item_key),
                    FOREIGN KEY(job_id) REFERENCES sync_jobs(id) ON DELETE CASCADE
                );
                """
            )
        self.current_now = self.now
        self.identifiers = iter(f"job-{index}" for index in range(1, 10000))
        self.store = SyncJobStore(
            self.manager, lambda: self.current_now, lambda: next(self.identifiers)
        )

    def enqueue(
        self,
        provider="garmin",
        job_type="refresh",
        payload=None,
        operations=None,
        available_at=None,
    ):
        return self.store.enqueue(
            {"provider": provider, "type": job_type, "payload": payload or {}},
            "test",
            operations,
            available_at,
        )

    def test_read_list_active_and_pending_performance_job(self):
        performance, created = self.enqueue(
            "intervals", "performance_refresh", {"reason": "manual"}
        )
        self.assertTrue(created)
        self.current_now = "2026-09-20T12:00:01+00:00"
        weather, _ = self.enqueue("weather", "refresh", {"force": True})
        self.assertEqual(self.store.state("missing"), None)
        self.assertEqual(
            self.store.state(performance["id"])["payload"], {"reason": "manual"}
        )
        self.assertEqual([job["id"] for job in self.store.list(1)], [weather["id"]])
        self.assertTrue(self.store.active("weather", "refresh"))
        self.assertFalse(self.store.active("calendar", "refresh"))
        self.assertEqual(self.store.pending_performance_job_id(), performance["id"])

    def test_all_read_methods_reuse_an_outer_unit_of_work_connection(self):
        manager = DatabaseManager(
            self.manager.path,
            sqlite3,
            row_factory=sqlite3.Row,
            persist_connections=False,
        )
        self.addCleanup(manager.close)
        store = SyncJobStore(manager, lambda: self.current_now, lambda: "unused")
        with (
            patch.object(sqlite3, "connect", wraps=sqlite3.connect) as connect,
            manager.unit_of_work(),
        ):
            self.assertIsNone(store.state("missing"))
            self.assertEqual(store.list(10), [])
            self.assertFalse(store.active("garmin", "refresh"))
            self.assertIsNone(store.pending_performance_job_id())
            self.assertEqual(connect.call_count, 1)

    def test_enqueue_persists_compact_utf8_payload_and_server_hash_contract(self):
        operation = {"item_key": "x" * 180, "operation": "sync" * 30}
        envelope = {
            "provider": "garmin",
            "type": "refresh",
            "payload": {"reason": "München"},
        }
        job, created = self.store.enqueue(envelope, " USER ", [operation], None)
        self.assertTrue(created)
        self.assertEqual(job["requested_by"], "user")
        self.assertEqual(len(job["items"][0]["item_key"]), 160)
        self.assertEqual(len(job["items"][0]["operation"]), 80)
        raw = job["items"][0]
        serialized = json.dumps(
            {"operation": raw["operation"], "payload": envelope["payload"]},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self.manager.reader() as db:
            stored_payload = db.execute(
                "SELECT payload FROM sync_jobs WHERE id=?", (job["id"],)
            ).fetchone()[0]
            stored_hash = db.execute(
                "SELECT payload_hash FROM sync_job_items WHERE job_id=?", (job["id"],)
            ).fetchone()[0]
        self.assertEqual(stored_payload, '{"reason":"München"}')
        self.assertEqual(
            stored_hash, hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        )

    def test_enqueue_enforces_operation_bounds_and_schedules_utc(self):
        defaulted, _ = self.enqueue(operations=[])
        self.assertEqual(len(defaulted["items"]), 1)
        with self.assertRaises(SyncJobInvalidOperationError):
            self.enqueue(operations=[{"item_key": "a", "operation": "sync"}] * 1001)
        with self.assertRaises(SyncJobInvalidOperationError):
            self.enqueue(operations=[{"item_key": "   ", "operation": "sync"}])
        job, _ = self.enqueue(available_at="2026-09-20T15:00:00+03:00")
        self.assertEqual(job["available_at"], self.now)

    def test_operation_normalization_keeps_truncation_order_and_exact_errors(self):
        repeated = "k" * 161
        with self.assertRaisesRegex(
            SyncJobInvalidOperationError, r"Job operation keys must be unique\."
        ):
            self.enqueue(
                operations=[
                    {"item_key": repeated, "operation": "sync"},
                    {"item_key": repeated + "x", "operation": "sync"},
                ]
            )
        with self.assertRaisesRegex(
            SyncJobInvalidOperationError, r"Job operations must be objects\."
        ):
            self.enqueue(operations=[{"item_key": "first"}, None])

    def test_operation_hash_rejects_non_json_payload(self):
        with self.assertRaisesRegex(
            SyncJobInvalidOperationError, r"Job payload is not JSON serializable\."
        ):
            self.store._normalize_operations(
                {"type": "refresh", "payload": {"value": object()}},
                [{"item_key": "one", "operation": "read"}],
            )

    def test_performance_refresh_enqueue_is_single_flight(self):
        from threading import Barrier

        barrier = Barrier(2)

        def enqueue(reason):
            barrier.wait()
            return self.enqueue("intervals", "performance_refresh", {"reason": reason})

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(enqueue, ("first", "second")))
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(sorted([first[1], second[1]]), [False, True])
        with self.manager.reader() as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM sync_jobs WHERE type='performance_refresh'"
                ).fetchone()[0],
                1,
            )

    def test_claim_is_conditional_and_increments_job_and_item_once(self):
        job, _ = self.enqueue(operations=[{"item_key": "one", "operation": "read"}])
        self.current_now = "2026-09-20T11:59:00+00:00"
        self.assertIsNone(self.store.claim())
        self.current_now = self.now

        from threading import Barrier

        barrier = Barrier(2)

        def claim():
            barrier.wait()
            return self.store.claim()

        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed = list(pool.map(lambda _: claim(), range(2)))
        winners = [value for value in claimed if value is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]["id"], job["id"])
        self.assertEqual(winners[0]["status"], "running")
        self.assertEqual(winners[0]["attempts"], 1)
        self.assertIsInstance(winners[0]["payload"], str)
        self.assertEqual(self.store.state(job["id"])["items"][0]["attempts"], 1)
        self.assertIsNone(self.store.claim())

    def test_resume_interrupted_resets_running_records_and_claims_again(self):
        job, _ = self.enqueue(
            operations=[
                {"item_key": "running", "operation": "read"},
                {"item_key": "already-done", "operation": "read"},
            ]
        )
        claimed = self.store.claim()
        self.assertEqual(claimed["id"], job["id"])
        self.assertEqual(claimed["status"], "running")
        self.assertIsInstance(claimed["payload"], str)
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE sync_job_items SET status='completed' WHERE job_id=? AND item_key='already-done'",
                (job["id"],),
            )
        self.assertEqual(self.store.resume_interrupted(), 1)
        resumed = self.store.state(job["id"])
        self.assertEqual(resumed["status"], "queued")
        self.assertEqual(resumed["error_class"], "process_interrupted")
        self.assertIsNone(resumed["started_at"])
        items = {item["item_key"]: item for item in resumed["items"]}
        self.assertEqual(items["running"]["status"], "queued")
        self.assertEqual(items["running"]["error_class"], "process_interrupted")
        self.assertIsNone(items["running"]["error_detail"])
        self.assertEqual(items["already-done"]["status"], "completed")
        claimed_again = self.store.claim()
        self.assertEqual(claimed_again["status"], "running")
        self.assertEqual(claimed_again["attempts"], 2)
        self.assertIsInstance(claimed_again["payload"], str)
        items = {
            item["item_key"]: item for item in self.store.state(job["id"])["items"]
        }
        self.assertEqual(items["running"]["attempts"], 2)
        self.assertEqual(items["already-done"]["attempts"], 1)

    def test_update_returns_event_snapshot_and_bounds_details(self):
        job, _ = self.enqueue()
        snapshot = self.store.update(job["id"], "failed", "provider_error", "x" * 700)
        self.assertEqual(
            snapshot,
            {
                "job_id": job["id"],
                "provider": "garmin",
                "type": "refresh",
                "status": "failed",
                "progress": {"completed": 1, "total": 1},
                "error_class": "provider_error",
            },
        )
        self.assertEqual(
            len(self.store.state(job["id"])["items"][0]["error_detail"]), 500
        )
        self.assertIsNone(self.store.update("missing", "failed"))
        with self.assertRaises(SyncJobInvalidOperationError):
            self.store.update(job["id"], "unknown")

    def test_result_mapping_aggregates_and_redacts_item_failures(self):
        job, _ = self.enqueue(
            "intervals",
            "plan_push",
            {"entries": []},
            [
                {"item_key": "workout-a", "operation": "push"},
                {"item_key": "workout-b", "operation": "push"},
                {"item_key": "workout-c", "operation": "push"},
            ],
        )
        snapshot = self.store.update_from_result(
            job["id"],
            {
                "results": [
                    {
                        "library_workout_id": "workout-b",
                        "status": "synced",
                        "remote_id": "remote-b",
                    },
                    {
                        "item_key": "workout-a",
                        "status": "error",
                        "error": "secret " + "e" * 700,
                    },
                    {"item_key": "unknown", "status": "skipped"},
                ]
            },
            "completed",
            lambda value: value.replace("secret", "[redacted]"),
        )
        state = self.store.state(job["id"])
        self.assertEqual(snapshot["status"], "partial")
        self.assertEqual(snapshot["progress"], {"completed": 3, "total": 3})
        self.assertEqual(state["items"][0]["status"], "failed")
        self.assertTrue(state["items"][0]["error_detail"].startswith("[redacted]"))
        self.assertEqual(len(state["items"][0]["error_detail"]), 500)
        self.assertEqual(state["items"][1]["status"], "completed")
        self.assertEqual(state["items"][1]["remote_id"], "remote-b")
        self.assertEqual(state["items"][2]["status"], "completed")
        self.assertEqual(state["error_class"], "plan_push_error")

    def test_result_without_item_results_uses_fallback_status(self):
        job, _ = self.enqueue()
        snapshot = self.store.update_from_result(
            job["id"], {"status": "partial"}, "partial", str
        )
        self.assertEqual(snapshot["status"], "partial")
        self.assertEqual(self.store.state(job["id"])["items"][0]["status"], "partial")

    def test_retry_requeue_respects_class_attempts_and_bounds_detail(self):
        job, _ = self.enqueue()
        claimed = self.store.claim()
        self.assertIsInstance(claimed["payload"], str)
        self.assertEqual(claimed["attempts"], 1)
        available_at = "2026-09-20T15:00:00+03:00"
        self.assertTrue(self.store.requeue(claimed, "timeout", "d" * 700, available_at))
        requeued = self.store.state(job["id"])
        self.assertEqual(requeued["status"], "queued")
        self.assertEqual(requeued["available_at"], self.now)
        self.assertEqual(requeued["attempts"], 1)
        self.assertEqual(requeued["items"][0]["status"], "queued")
        self.assertEqual(requeued["items"][0]["attempts"], 1)
        self.assertEqual(len(requeued["items"][0]["error_detail"]), 500)
        self.assertFalse(
            self.store.requeue(claimed, "auth_required", "safe", available_at)
        )
        self.assertFalse(
            self.store.requeue(
                {"id": job["id"], "attempts": 3}, "timeout", "safe", available_at
            )
        )

    def test_resolve_resets_only_failed_or_partial_items(self):
        job, _ = self.enqueue(
            operations=[
                {"item_key": "done", "operation": "push"},
                {"item_key": "failed", "operation": "push"},
                {"item_key": "partial", "operation": "push"},
            ]
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE sync_jobs SET status='partial', attempts=2, error_class='plan_push_error', "
                "started_at=?, finished_at=?, progress_completed=3 WHERE id=?",
                (self.now, self.now, job["id"]),
            )
            for item_key, status, attempts in (
                ("done", "completed", 4),
                ("failed", "failed", 2),
                ("partial", "partial", 3),
            ):
                db.execute(
                    "UPDATE sync_job_items SET status=?, attempts=?, error_class='old', error_detail='old' "
                    "WHERE job_id=? AND item_key=?",
                    (status, attempts, job["id"], item_key),
                )
        resolved = self.store.resolve(job["id"])
        self.assertEqual(resolved["status"], "queued")
        self.assertEqual(resolved["attempts"], 0)
        items = {item["item_key"]: item for item in resolved["items"]}
        self.assertEqual(items["done"]["status"], "completed")
        self.assertEqual(items["done"]["attempts"], 4)
        self.assertEqual(items["done"]["error_detail"], "old")
        for key in ("failed", "partial"):
            self.assertEqual(items[key]["status"], "queued")
            self.assertEqual(items[key]["attempts"], 0)
            self.assertIsNone(items[key]["error_class"])
            self.assertIsNone(items[key]["error_detail"])

    def test_resolve_rejects_missing_and_nonfailed_jobs(self):
        with self.assertRaises(SyncJobNotFoundError):
            self.store.resolve("missing")
        queued, _ = self.enqueue()
        with self.assertRaises(SyncJobInvalidStateError):
            self.store.resolve(queued["id"])
        self.store.update(queued["id"], "completed")
        with self.assertRaises(SyncJobInvalidStateError):
            self.store.resolve(queued["id"])


if __name__ == "__main__":
    unittest.main()
