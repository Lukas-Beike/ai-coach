import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from backend.coach.job_store import CoachJobStore
from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate


class CoachJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "coach.db"
        self.wake = threading.Event()
        self.gate = MaintenanceGate()
        self.lock = threading.RLock()
        self.manager = self._manager()
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE coach_commands (client_turn_id TEXT PRIMARY KEY, "
                "status TEXT NOT NULL, receipt TEXT NOT NULL, intent TEXT, created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT NOT NULL, "
                "content TEXT NOT NULL)"
            )
        self.store = self._store()

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    def _manager(self):
        return DatabaseManager(self.path, sqlite3, row_factory=row_factory)

    def _store(self):
        return CoachJobStore(
            lambda: self.manager,
            self.lock,
            self.wake,
            self.gate,
            lambda: "2026-09-23T12:00:00+00:00",
        )

    def _insert(
        self, turn_id, receipt, *, status="queued", created_at="2026-09-23", intent=None
    ):
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands VALUES (?, ?, ?, ?, ?, ?)",
                (
                    turn_id,
                    status,
                    json.dumps(receipt),
                    json.dumps(intent or {}),
                    created_at,
                    created_at,
                ),
            )

    def test_claim_skips_non_background_and_future_retry_then_claims_once(self):
        self._insert("interactive", {"mode": "interactive"}, created_at="1")
        self._insert(
            "delayed",
            {"mode": "background", "retry_after": time.time() + 60},
            created_at="2",
        )
        self._insert("ready", {"mode": "background"}, created_at="3")

        job = self.store.claim()

        self.assertEqual(job["client_turn_id"], "ready")
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["_maintenance_generation"], 0)
        self.assertIsNone(self.store.claim())

    def test_claim_preserves_the_twenty_row_candidate_limit(self):
        for index in range(20):
            self._insert(
                f"interactive-{index}",
                {"mode": "interactive"},
                created_at=f"{index:02}",
            )
        self._insert("outside-limit", {"mode": "background"}, created_at="99")

        self.assertIsNone(self.store.claim())

    def test_claim_obeys_maintenance_gate_and_records_its_generation(self):
        self._insert("after-restore", {"mode": "background"})
        with self.gate.restore(), self.assertRaises(AppError) as raised:
            self.store.claim()
        self.assertEqual(raised.exception.reason, "maintenance")
        self.assertEqual(self.store.claim()["_maintenance_generation"], 1)

    def test_requeue_persists_contention_backoff_and_wakes_worker(self):
        self._insert(
            "contended",
            {"mode": "background", "contention_attempts": 100},
            status="running",
        )
        before = time.time()

        self.store.requeue("contended", "chat_queue_full")

        with self.manager.unit_of_work() as db:
            row = db.execute(
                "SELECT status, receipt, updated_at FROM coach_commands WHERE client_turn_id=?",
                ("contended",),
            ).fetchone()
        receipt = json.loads(row["receipt"])
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["updated_at"], "2026-09-23T12:00:00+00:00")
        self.assertEqual(receipt["contention_attempts"], 101)
        self.assertEqual(receipt["retry_reason"], "chat_queue_full")
        self.assertEqual(receipt["phase"], "waiting_for_coach_slot")
        self.assertGreaterEqual(receipt["retry_after"], before + 32)
        self.assertTrue(self.wake.is_set())

    def test_data_wait_requeues_with_fixed_delay_until_its_cap(self):
        self._insert("morning", {"mode": "background"}, status="running")
        before = time.time()

        self.assertTrue(
            self.store.requeue(
                "morning", "garmin_sleep_not_ready", wait_seconds=900, max_waits=2
            )
        )

        with self.manager.unit_of_work() as db:
            row = db.execute(
                "SELECT receipt FROM coach_commands WHERE client_turn_id=?",
                ("morning",),
            ).fetchone()
            receipt = json.loads(row["receipt"])
            self.assertEqual(receipt["data_wait_attempts"], 1)
            self.assertNotIn("contention_attempts", receipt)
            self.assertEqual(receipt["phase"], "waiting_for_data")
            self.assertGreaterEqual(receipt["retry_after"], before + 900)
            receipt["data_wait_attempts"] = 2
            db.execute(
                "UPDATE coach_commands SET status='running', receipt=? "
                "WHERE client_turn_id='morning'",
                (json.dumps(receipt),),
            )

        self.assertFalse(
            self.store.requeue(
                "morning", "garmin_sleep_not_ready", wait_seconds=900, max_waits=2
            )
        )

    def test_cancelled_job_is_not_requeued_for_data_and_is_claimed_at_once(self):
        self._insert(
            "cancelled",
            {"mode": "background", "cancel_requested": True},
            status="running",
        )
        self.assertFalse(
            self.store.requeue(
                "cancelled", "garmin_sleep_not_ready", wait_seconds=900, max_waits=8
            )
        )
        self._insert(
            "waiting",
            {
                "mode": "background",
                "cancel_requested": True,
                "retry_after": time.time() + 900,
            },
        )
        self.assertEqual(self.store.claim()["client_turn_id"], "waiting")

    def test_message_requires_saved_user_content(self):
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO messages(role, content) VALUES ('user', 'Synthetic question')"
            )
        self.assertEqual(
            self.store.message({"receipt": {"user_message_id": 1}}),
            "Synthetic question",
        )
        with self.assertRaises(AppError) as raised:
            self.store.message({"receipt": {"user_message_id": 999}})
        self.assertEqual(raised.exception.reason, "background_message_missing")

    def test_claim_and_saved_message_survive_manager_restart_without_double_claim(self):
        self._insert("restart", {"mode": "background", "user_message_id": 7})
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO messages(id, role, content) VALUES (7, 'user', 'Persisted question')"
            )
        self.manager.close()

        self.manager = self._manager()
        self.store = self._store()
        job = self.store.claim()
        self.assertEqual(self.store.message(job), "Persisted question")
        self.manager.close()

        self.manager = self._manager()
        self.store = self._store()
        self.assertIsNone(self.store.claim())

    def test_receipt_merge_keeps_active_status_guard_and_uses_current_manager(self):
        self._insert("active", {"mode": "background", "phase": "queued"})
        self._insert("done", {"mode": "background"}, status="completed")
        self.manager.close()
        self.manager = self._manager()  # The same store must resolve this manager.

        self.store.merge_receipt("active", {"cancel_requested": True})
        self.store.merge_receipt("done", {"cancel_requested": True})

        active = self._receipt("active")
        self.assertEqual(active["phase"], "queued")
        self.assertTrue(active["cancel_requested"])
        self.assertNotIn("cancel_requested", self._receipt("done"))

    def _receipt(self, turn_id):
        with self.manager.unit_of_work() as db:
            row = db.execute(
                "SELECT receipt FROM coach_commands WHERE client_turn_id=?",
                (turn_id,),
            ).fetchone()
        return json.loads(row["receipt"])

    def test_receipt_merge_changes_only_the_named_keys(self):
        steps = [{"tool": "get_plan", "result": {"ok": True, "text": "keep ä"}}]
        self._insert(
            "active",
            {"mode": "background", "command_receipts": steps, "phase": "queued"},
        )

        self.store.merge_receipt(
            "active", {"phase": "executing_tools", "pending_tool_calls": [{"a": 1}]}
        )

        merged = self._receipt("active")
        self.assertEqual(merged["command_receipts"], steps)
        self.assertEqual(merged["mode"], "background")
        self.assertEqual(merged["phase"], "executing_tools")
        self.assertEqual(merged["pending_tool_calls"], [{"a": 1}])

    def test_receipt_merge_stores_null_and_nested_values_and_replaces_lists(self):
        self._insert(
            "active", {"openai_response_id": "r1", "pending_tool_outputs": [1]}
        )

        self.store.merge_receipt(
            "active",
            {"openai_response_id": None, "pending_tool_outputs": [], "k": {"x": "y"}},
        )

        self.assertEqual(
            self._receipt("active"),
            {"openai_response_id": None, "pending_tool_outputs": [], "k": {"x": "y"}},
        )

    def test_receipt_merge_repairs_a_malformed_receipt_of_an_open_command(self):
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands VALUES ('broken', 'running', 'not json', '{}', '1', '1')"
            )

        self.store.merge_receipt("broken", {"phase": "waiting_openai"})

        self.assertEqual(self._receipt("broken"), {"phase": "waiting_openai"})

    def test_restart_requeues_all_background_jobs(self):
        self._insert(
            "attached",
            {"mode": "interactive"},
            status="running",
            intent={"operation": "save_checkin"},
        )
        self._insert(
            "openai",
            {
                "mode": "background",
                "ai_provider": "openai",
                "openai_response_id": "resp-1",
            },
            status="running",
        )
        self._insert("queued", {"mode": "background", "phase": "preparing"})
        failures = Mock()

        self.assertEqual(self.store.resume_interrupted(failures), 2)

        with self.manager.unit_of_work() as db:
            rows = {
                row["client_turn_id"]: row
                for row in db.execute(
                    "SELECT client_turn_id, status, receipt FROM coach_commands"
                ).fetchall()
            }
        self.assertEqual(rows["openai"]["status"], "queued")
        self.assertEqual(json.loads(rows["openai"]["receipt"])["phase"], "resuming")
        self.assertEqual(rows["queued"]["status"], "queued")
        self.assertEqual(json.loads(rows["queued"]["receipt"])["phase"], "queued")
        self.assertTrue(self.wake.is_set())
        self.assertEqual(failures.persist.call_count, 1)
        self.assertEqual(
            failures.persist.call_args_list[0].args[:2],
            ("attached", {"operation": "save_checkin"}),
        )
        self.assertTrue(
            all(
                call.args[2].reason == "process_interrupted"
                for call in failures.persist.call_args_list
            )
        )

    def test_turn_open_is_true_only_for_queued_or_running_commands(self):
        self._insert("queued", {"mode": "background"}, status="queued")
        self._insert("running", {"mode": "background"}, status="running")
        self._insert("released", {"mode": "background"}, status="completed")

        self.assertTrue(self.store.turn_open("queued"))
        self.assertTrue(self.store.turn_open("running"))
        self.assertFalse(self.store.turn_open("released"))
        self.assertFalse(self.store.turn_open("missing"))

    def test_busy_is_true_only_while_a_turn_is_queued_or_running(self):
        self.assertFalse(self.store.busy())
        self._insert("released", {"mode": "background"}, status="completed")
        self.assertFalse(self.store.busy())
        self._insert("queued", {"mode": "background"}, status="queued")
        self.assertTrue(self.store.busy())
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE coach_commands SET status = 'running'")
        self.assertTrue(self.store.busy())

    def test_record_failed_attempt_counts_only_open_commands(self):
        self._insert("job", {"mode": "background", "phase": "preparing"})
        self._insert("done", {"mode": "background"}, status="completed")

        self.assertEqual(self.store.record_failed_attempt("job"), 1)
        self.assertEqual(self.store.record_failed_attempt("job"), 2)
        self.assertEqual(self.store.record_failed_attempt("missing"), 0)
        self.store.record_failed_attempt("done")

        with self.manager.reader() as db:
            receipts = {
                row["client_turn_id"]: json.loads(row["receipt"])
                for row in db.execute(
                    "SELECT client_turn_id, receipt FROM coach_commands"
                ).fetchall()
            }
        self.assertEqual(receipts["job"]["failed_attempts"], 2)
        self.assertEqual(receipts["job"]["phase"], "preparing")
        self.assertNotIn("failed_attempts", receipts["done"])

    def test_contention_requeue_does_not_count_as_a_failed_attempt(self):
        self._insert("job", {"mode": "background"}, status="running")

        self.store.requeue("job", "chat_queue_full")

        with self.manager.reader() as db:
            receipt = json.loads(
                db.execute("SELECT receipt FROM coach_commands").fetchone()["receipt"]
            )
        self.assertNotIn("failed_attempts", receipt)

    def test_restart_recovery_uses_replaced_manager_and_does_not_wake_without_jobs(
        self,
    ):
        self._insert("done", {"mode": "background"}, status="completed")
        self.manager.close()
        self.manager = self._manager()
        failures = Mock()

        self.assertEqual(self.store.resume_interrupted(failures), 0)

        failures.persist.assert_not_called()
        self.assertFalse(self.wake.is_set())


if __name__ == "__main__":
    unittest.main()
