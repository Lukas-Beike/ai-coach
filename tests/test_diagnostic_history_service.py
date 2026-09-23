import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path

from backend.coach.service import command_receipt
from backend.diagnostics.history import CoachDiagnosticHistoryService


class CoachDiagnosticHistoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "commands.sqlite3"
        db = sqlite3.connect(self.database_path)
        try:
            db.execute(
                "CREATE TABLE coach_commands ("
                "client_turn_id TEXT, receipt TEXT, created_at TEXT, updated_at TEXT)"
            )
        finally:
            db.close()
        self.lock = threading.RLock()
        self.redacted_values = []

        @contextmanager
        def database():
            db = sqlite3.connect(self.database_path)
            try:
                db.row_factory = sqlite3.Row
                yield db
            finally:
                db.close()

        def redact(value):
            self.redacted_values.append(value)
            return {**value, "reason": "[REDACTED]"} if "reason" in value else value

        self.service = CoachDiagnosticHistoryService(
            database=database,
            db_lock=self.lock,
            redact=redact,
            receipt_parser=command_receipt,
            allowed_tools={"save_checkin", "sync_intervals"},
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def add_command(self, turn_id, receipt, created_at="2026-09-23T10:00:00+00:00"):
        db = sqlite3.connect(self.database_path)
        try:
            db.execute(
                "INSERT INTO coach_commands VALUES (?, ?, ?, ?)",
                (turn_id, json.dumps(receipt), created_at, created_at),
            )
            db.commit()
        finally:
            db.close()

    def test_projects_only_allowlisted_metadata_and_redacts_it(self):
        self.add_command("private-turn-id", {
            "status": "failed",
            "response_status": "incomplete",
            "awaiting_clarification": True,
            "diagnostic_error": {
                "type": "ProviderError",
                "reason": "athlete_secret",
                "status": 503,
                "provider_error_code": "rate_limit_exceeded",
                "message": "athlete-secret@example.invalid",
                "token": "private-token",
                "frames": [
                    {"file": "backend/coach/service.py", "function": "run", "line": 19},
                    {"file": "C:/private/path.py", "function": "leak", "line": 20},
                ],
            },
            "command_receipts": [{
                "tool": "save_checkin",
                "arguments": {"athlete": "private athlete data"},
                "result": {"ok": True, "body": "private result"},
                "diagnostic_error": {"reason": "private_reason"},
            }, {
                "tool": "attacker_tool",
                "result": {"ok": False},
            }],
        })

        [entry] = self.service.history()

        self.assertEqual(entry["id"], hashlib.sha256(b"private-turn-id").hexdigest()[:12])
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["response_status"], "incomplete")
        self.assertTrue(entry["awaiting_clarification"])
        self.assertEqual(entry["error"]["reason"], "[REDACTED]")
        self.assertEqual(entry["error"]["status"], 503)
        self.assertEqual(entry["error"]["frames"], [{
            "file": "backend/coach/service.py", "function": "run", "line": 19,
        }])
        self.assertEqual(entry["steps"], [
            {"tool": "save_checkin", "ok": True, "error": {"reason": "[REDACTED]"}},
            {"tool": "unknown", "ok": False, "error": None},
        ])
        serialized = json.dumps(entry)
        for secret in (
            "private-turn-id", "athlete-secret@example.invalid", "private-token",
            "private athlete data", "private result", "C:/private/path.py",
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual(len(self.redacted_values), 2)

    def test_limits_to_20_rows_40_steps_and_8_frames(self):
        frames = [
            {"file": "server.py", "function": "handle", "line": index + 1}
            for index in range(10)
        ]
        steps = [{"tool": "sync_intervals", "result": {"ok": True}} for _ in range(42)]
        for index in range(21):
            self.add_command(f"turn-{index + 1:02d}", {}, f"2026-09-23T10:{index + 1:02d}:00+00:00")
        self.add_command("bounded", {
            "diagnostic_error": {"frames": frames}, "command_receipts": steps,
        }, "2026-09-24T10:00:00+00:00")

        history = self.service.history()

        self.assertEqual(len(history), 20)
        bounded = history[0]
        self.assertEqual(bounded["id"], hashlib.sha256(b"bounded").hexdigest()[:12])
        self.assertEqual(len(bounded["steps"]), 40)
        self.assertEqual(len(bounded["error"]["frames"]), 8)

    def test_order_is_deterministic_for_equal_timestamps(self):
        self.add_command("turn-a", {})
        self.add_command("turn-c", {})
        self.add_command("turn-b", {})

        history = self.service.history()

        self.assertEqual(
            [entry["id"] for entry in history],
            [hashlib.sha256(f"turn-{suffix}".encode()).hexdigest()[:12] for suffix in ("c", "b", "a")],
        )

    def test_malformed_receipt_fields_fail_closed(self):
        self.add_command("bad", {
            "status": ["failed"],
            "response_status": {"failed": True},
            "diagnostic_error": {"frames": "not a frame list"},
            "command_receipts": [None, {"tool": [], "result": []}],
        })

        [entry] = self.service.history()

        self.assertEqual(entry["status"], "unknown")
        self.assertIsNone(entry["response_status"])
        self.assertEqual(entry["error"], {})
        self.assertEqual(entry["steps"], [{"tool": "unknown", "ok": False, "error": None}])


if __name__ == "__main__":
    unittest.main()
