import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend.coach.proposals import CoachProposalConfirmationService
from backend.db.manager import DatabaseManager
from backend.errors import AppError


PROPOSAL_ID = "abc12345-6789-4abc-8def-0123456789ab"


class CoachProposalConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "coach.sqlite3"
        self.manager = DatabaseManager(
            self.db_path, sqlite3, row_factory=sqlite3.Row, persist_connections=False
        )
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute(
                "CREATE TABLE coach_action_proposals ("
                "id TEXT PRIMARY KEY, session_csrf_hash TEXT NOT NULL, action_type TEXT NOT NULL, "
                "target_system TEXT NOT NULL, object_ids TEXT NOT NULL, diff TEXT NOT NULL, "
                "payload TEXT NOT NULL, payload_hash TEXT NOT NULL, action_token_hash TEXT, "
                "status TEXT NOT NULL, expires_at REAL NOT NULL, used_at TEXT, created_at TEXT)"
            )
            db.commit()
        self.add_proposal()

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    def add_proposal(self, *, proposal_id=PROPOSAL_ID, session="csrf-a", status="preview", expires=200):
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute(
                "INSERT INTO coach_action_proposals "
                "(id, session_csrf_hash, action_type, target_system, object_ids, diff, payload, "
                "payload_hash, action_token_hash, status, expires_at, created_at) "
                "VALUES (?, ?, 'undo_change', 'local', '{\"item\":1}', '{\"x\":1}', "
                "'{\"private\":true}', 'payload-hash', NULL, ?, ?, 'now')",
                (proposal_id, session, status, expires),
            )
            db.commit()

    def proposal_row(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT * FROM coach_action_proposals WHERE id=?", (PROPOSAL_ID,)
            ).fetchone()
            return row

    def service(self, token, now=100):
        return CoachProposalConfirmationService(
            self.manager, now=lambda: now, token_factory=lambda _: token
        )

    def test_confirm_returns_private_token_and_safe_view_with_server_compatible_hash(self):
        result = self.service("first token").confirm(PROPOSAL_ID, "csrf-a")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["action_token"], "first token")
        self.assertEqual(result["proposed_action"]["status"], "ready")
        self.assertNotIn("payload", result["proposed_action"])
        self.assertNotIn("action_token_hash", result["proposed_action"])
        self.assertEqual(
            self.proposal_row()["action_token_hash"],
            hashlib.sha256(b"first token").hexdigest(),
        )

    def test_reconfirm_rotates_unused_token(self):
        first = self.service("first token").confirm(PROPOSAL_ID, "csrf-a")
        second = self.service("second token").confirm(PROPOSAL_ID, "csrf-a")
        self.assertNotEqual(first["action_token"], second["action_token"])
        self.assertEqual(
            self.proposal_row()["action_token_hash"],
            hashlib.sha256(b"second token").hexdigest(),
        )

    def test_foreign_session_does_not_find_or_mutate_proposal(self):
        with self.assertRaises(AppError) as error:
            self.service("unused").confirm(PROPOSAL_ID, "csrf-b")
        self.assertEqual((error.exception.status, error.exception.message), (404, "Aktionsvorschau nicht gefunden."))
        self.assertEqual(self.proposal_row()["status"], "preview")
        self.assertIsNone(self.proposal_row()["action_token_hash"])

    def test_ttl_boundary_is_expired_and_does_not_mutate(self):
        with self.assertRaises(AppError) as error:
            self.service("unused", now=200).confirm(PROPOSAL_ID, "csrf-a")
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.proposal_row()["status"], "preview")
        self.assertIsNone(self.proposal_row()["action_token_hash"])

    def test_used_proposal_cannot_be_confirmed(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("UPDATE coach_action_proposals SET status='used' WHERE id=?", (PROPOSAL_ID,))
            db.commit()
        with self.assertRaises(AppError) as error:
            self.service("unused").confirm(PROPOSAL_ID, "csrf-a")
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.proposal_row()["status"], "used")

    def test_invalid_uuid_format_fails_before_token_creation(self):
        called = []
        service = CoachProposalConfirmationService(
            self.manager, token_factory=lambda length: called.append(length) or "unused"
        )
        with self.assertRaises(AppError) as error:
            service.confirm("bad-id", "csrf-a")
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(called, [])

    def test_view_failure_rolls_back_token_update(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("UPDATE coach_action_proposals SET diff='not-json' WHERE id=?", (PROPOSAL_ID,))
            db.commit()
        with self.assertRaises(ValueError):
            self.service("must-roll-back").confirm(PROPOSAL_ID, "csrf-a")
        row = self.proposal_row()
        self.assertEqual(row["status"], "preview")
        self.assertIsNone(row["action_token_hash"])


if __name__ == "__main__":
    unittest.main()
