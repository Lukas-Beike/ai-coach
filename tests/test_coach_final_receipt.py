"""Direct contracts for atomic final Coach receipts."""

from __future__ import annotations

import json
import sqlite3
import threading
import unittest
from datetime import date
from typing import Any
from unittest.mock import MagicMock, Mock

from support import temp_database

from backend.coach.final_receipt import CoachFinalReceiptService
from backend.coach.receipt_reads import monthly_turn_usage
from backend.db.repositories import ChatRepository, KeyValueRepository
from backend.providers.model_seam import ModelTurn
from backend.providers.state import metered_turn
from backend.runtime.events import StateEventBuffer


class CoachFinalReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.trace: list[str] = []
        self.manager = MagicMock()
        self.db = Mock()
        self.manager.unit_of_work.return_value.__enter__.return_value = self.db
        self.manager.unit_of_work.return_value.__exit__.side_effect = (
            self._close_unit_of_work
        )
        self.chat = Mock()
        self.chat.add.side_effect = self._add_message
        self.keys = Mock()
        self.events = Mock()
        self.events.publish.side_effect = lambda *_: self.trace.append("publish")
        self.service = CoachFinalReceiptService(
            self.manager,
            threading.RLock(),
            self.chat,
            self.keys,
            self.events,
            lambda: "2026-09-24T00:00:00Z",
        )

    def _close_unit_of_work(self, error_type, _error, _traceback):
        self.trace.append("rollback" if error_type else "commit")
        return False

    def _add_message(self, _db, _role, _text, *, client_turn_id):
        self.trace.append("message")
        return {"id": "assistant-1", "client_turn_id": client_turn_id}

    def test_build_projects_outcome_and_removes_open_tool_calls(self) -> None:
        steps = [
            {
                "tool": "preview_adaptive_replan",
                "result": {"proposed_action": {"id": "p1"}},
            }
        ]
        receipt = {
            "openai_reached": True,
            "pending_tool_calls": [2],
            "session_key": "owner",
        }
        final = self.service.build(
            receipt,
            status="awaiting_clarification",
            turn=ModelTurn(stop_reason="max_tokens"),
            client_turn_id="turn-1",
            command_receipts=steps,
            sync_job_ids=["sync-1"],
            intent={"allow_mutations": False},
            rounds=2,
            failures=[{"tool": "z"}, {"tool": "a"}, {"tool": "z"}],
            awaiting_clarification=True,
        )
        self.assertEqual(final["pending_operations"], ["a", "z"])
        self.assertEqual(final["proposed_actions"], [{"id": "p1"}])
        self.assertEqual(final["response_status"], "incomplete")
        self.assertEqual(final["session_key"], "owner")
        self.assertEqual(final["tool_rounds"], 2)
        self.assertNotIn("pending_tool_calls", final)
        self.assertIn("pending_tool_calls", receipt)
        # A re-requested turn keeps the attachment window anchor it had.
        self.assertIs(final["openai_reached"], True)
        self.assertNotIn("usage", final)

    def test_build_keeps_the_usage_of_the_metered_turn(self) -> None:
        options: dict[str, Any] = {
            "status": "completed",
            "turn": ModelTurn(),
            "client_turn_id": "turn-1",
            "command_receipts": [],
            "sync_job_ids": [],
            "intent": {},
            "rounds": 1,
            "failures": [],
            "awaiting_clarification": False,
        }
        with metered_turn({"requests": 3, "input_tokens": 9000}):
            final = self.service.build({"model": "claude-opus"}, **options)
        counts = {
            "requests": 3,
            "input_tokens": 9000,
            "cached_input_tokens": 0,
            "output_tokens": 0,
        }
        self.assertEqual(final["usage"], {**counts, "by_model": {"": counts}})

    def test_completed_command_returns_stored_receipt_without_duplicate_effect(
        self,
    ) -> None:
        self.db.execute.return_value.fetchone.return_value = {
            "status": "completed",
            "receipt": json.dumps({"status": "completed", "message": {"id": "old"}}),
        }
        result = self.service.persist(
            {"text": "new"},
            client_turn_id="turn-1",
            command_receipts=[],
        )
        self.assertEqual(result["message"]["id"], "old")
        self.chat.add.assert_not_called()
        self.keys.set.assert_not_called()
        self.events.publish.assert_not_called()
        self.assertEqual(self.trace, ["commit"])

    def test_persist_commits_message_preview_provider_and_receipt_before_event(
        self,
    ) -> None:
        def execute(sql, _values):
            if sql.startswith("SELECT status, receipt"):
                return Mock(fetchone=lambda: {"status": "running"})
            if sql.startswith("SELECT payload FROM plan_adjustments"):
                return Mock(fetchone=lambda: {"payload": '{"preview":true}'})
            return Mock()

        self.db.execute.side_effect = execute
        steps = [
            {
                "tool": "preview_adaptive_replan",
                "result": {"ok": True, "id": "preview-1"},
            }
        ]
        final = {"status": "completed", "text": "Fertig", "command_receipts": steps}
        result = self.service.persist(
            final,
            client_turn_id="turn-1",
            command_receipts=steps,
        )
        self.assertEqual(self.trace, ["message", "commit", "publish"])
        self.assertNotIn("text", result)
        self.chat.add.assert_called_once_with(
            self.db, "assistant", "Fertig", client_turn_id="turn-1"
        )
        self.keys.set.assert_called_once_with(
            self.db, "last_coach_ai_provider", "openai"
        )
        calls = self.db.execute.call_args_list
        preview = next(
            call for call in calls if call.args[0].startswith("UPDATE plan_adjustments")
        )
        self.assertEqual(
            json.loads(preview.args[1][0])["published_message_id"], "assistant-1"
        )
        update = next(
            call for call in calls if call.args[0].startswith("UPDATE coach_commands")
        )
        self.assertEqual(update.args[1][1], "2026-09-24T00:00:00Z")
        self.assertNotIn("text", json.loads(update.args[1][0]))
        self.events.publish.assert_called_once_with(
            "coach",
            {
                "message_id": "assistant-1",
                "role": "assistant",
                "client_turn_id": "turn-1",
            },
        )

    def test_turn_changes_are_summarized_on_the_receipt_and_the_answer(
        self,
    ) -> None:
        self.db.execute.side_effect = lambda sql, _values: Mock(
            fetchone=lambda: {"status": "running"}
        )
        steps = [
            {
                "tool": "update_profile",
                "result": {"ok": True},
                "changes": [{"id": "change-1"}],
            }
        ]
        final = self.service.build(
            {"text": "Fertig"},
            status="completed",
            turn=ModelTurn(),
            client_turn_id="turn-1",
            command_receipts=steps,
            sync_job_ids=[],
            intent={},
            rounds=1,
            failures=[],
            awaiting_clarification=False,
        )
        summary = {
            "labels": ["Profil aktualisiert"],
            "undoable": True,
            "undone_at": None,
        }
        self.assertEqual(final["change_summary"], summary)

        result = self.service.persist(
            final, client_turn_id="turn-1", command_receipts=steps
        )

        self.assertEqual(result["message"]["coach_changes"], summary)
        update = next(
            call
            for call in self.db.execute.call_args_list
            if call.args[0].startswith("UPDATE coach_commands")
        )
        self.assertEqual(json.loads(update.args[1][0])["change_summary"], summary)

    def test_plan_notes_persist_on_the_message_and_command_receipt(self) -> None:
        self.db.execute.side_effect = lambda sql, _values: Mock(
            fetchone=lambda: {"status": "running"}
        )
        steps = [
            {
                "tool": "apply_training_patch",
                "result": {
                    "ok": True,
                    "plan_check_notes": [
                        {
                            "code": "run_spike",
                            "dates": ["2026-11-02"],
                            "evidence": {"severity": "warning"},
                        }
                    ],
                },
            }
        ]
        final = self.service.build(
            {"text": "Fertig"},
            status="completed",
            turn=ModelTurn(),
            client_turn_id="turn-1",
            command_receipts=steps,
            sync_job_ids=[],
            intent={},
            rounds=1,
            failures=[],
            awaiting_clarification=False,
        )
        result = self.service.persist(
            final, client_turn_id="turn-1", command_receipts=steps
        )
        notes = [{"code": "run_spike", "dates": ["2026-11-02"], "severity": "warning"}]
        self.assertEqual(result["message"]["coach_changes"]["plan_check_notes"], notes)
        update = next(
            call
            for call in self.db.execute.call_args_list
            if call.args[0].startswith("UPDATE coach_commands")
        )
        self.assertEqual(
            json.loads(update.args[1][0])["change_summary"]["plan_check_notes"], notes
        )

    def test_a_turn_without_changes_adds_no_summary_to_the_answer(self) -> None:
        self.db.execute.side_effect = lambda sql, _values: Mock(
            fetchone=lambda: {"status": "running"}
        )
        result = self.service.persist(
            {"text": "Fertig", "change_summary": None},
            client_turn_id="turn-1",
            command_receipts=[],
        )
        self.assertNotIn("coach_changes", result["message"])

    def test_persist_writes_compact_steps_but_returns_the_full_receipt(self) -> None:
        stored: list[str] = []

        def execute(sql, values=()):
            if sql.startswith("SELECT status, receipt"):
                return Mock(fetchone=lambda: {"status": "running"})
            if sql.startswith("UPDATE coach_commands"):
                stored.append(values[0])
            return Mock()

        self.db.execute.side_effect = execute
        bulk = "synthetic tool output " * 500
        steps = [
            {
                "tool": "get_plan",
                "call_id": "c1",
                "result": {"ok": True, "days": [bulk]},
                "changes": [{"id": "change-1"}],
            }
        ]
        final = {"status": "completed", "text": "Fertig", "command_receipts": steps}

        result = self.service.persist(
            final, client_turn_id="turn-1", command_receipts=steps
        )

        (written,) = stored
        step = json.loads(written)["command_receipts"][0]
        self.assertEqual(step["result"], {"ok": True})
        self.assertEqual(step["changes"], [{"id": "change-1"}])
        self.assertNotIn("synthetic tool output", written)
        self.assertEqual(result["command_receipts"][0]["result"]["days"], [bulk])

    def test_failed_command_update_rolls_back_without_event(self) -> None:
        def execute(sql, _values):
            if sql.startswith("SELECT status, receipt"):
                return Mock(fetchone=lambda: {"status": "running"})
            if sql.startswith("UPDATE coach_commands"):
                raise ValueError("synthetic update failure")
            return Mock()

        self.db.execute.side_effect = execute
        with self.assertRaisesRegex(ValueError, "synthetic update failure"):
            self.service.persist(
                {"text": "Fertig"},
                client_turn_id="turn-1",
                command_receipts=[],
            )
        self.assertEqual(self.trace, ["message", "rollback"])
        self.events.publish.assert_not_called()

    def test_real_sqlite_unit_of_work_rolls_back_message_when_provider_state_fails(
        self,
    ) -> None:
        manager = temp_database(
            self,
            "coach.sqlite3",
            row_factory=sqlite3.Row,
            persist_connections=False,
        )
        with manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE coach_commands (client_turn_id TEXT PRIMARY KEY, status TEXT, receipt TEXT, updated_at TEXT)"
            )
            db.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, client_turn_id TEXT, created_at TEXT)"
            )
            db.execute(
                "INSERT INTO coach_commands VALUES ('turn-1', 'running', '{}', '')"
            )
        keys = Mock(spec=KeyValueRepository)
        keys.set.side_effect = ValueError("synthetic KV failure")
        events = StateEventBuffer()
        service = CoachFinalReceiptService(
            manager,
            threading.RLock(),
            ChatRepository(lambda: "now"),
            keys,
            events,
            lambda: "now",
        )
        with self.assertRaisesRegex(ValueError, "synthetic KV failure"):
            service.persist(
                {"text": "Fertig"},
                client_turn_id="turn-1",
                command_receipts=[],
            )
        with manager.unit_of_work() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0
            )
            self.assertEqual(
                db.execute("SELECT status FROM coach_commands").fetchone()[0],
                "running",
            )
        self.assertEqual(events.since()["events"], [])


class MonthlyTurnUsageTests(unittest.TestCase):
    def test_month_sums_turns_with_usage_per_model_in_local_time(self) -> None:
        manager = temp_database(self, "usage.sqlite3", schema=True)
        usage = {
            "requests": 2,
            "input_tokens": 1000,
            "cached_input_tokens": 600,
            "output_tokens": 50,
        }
        opus = {"model": "claude-opus", "usage": usage}
        rows = (
            # 00:30 on 1 November in Berlin is still 31 October in UTC.
            ("a", "completed", opus, "2026-10-31T23:30:00+00:00"),
            ("b", "completed", opus, "2026-11-30T22:59:59.5+00:00"),
            (
                "c",
                "completed",
                {"model": "gpt-6-luna", "usage": usage},
                "2026-11-05T08:00:00+00:00",
            ),
            # A failed turn adds its tokens but no answer.
            (
                "d",
                "completed",
                {**opus, "status": "failed"},
                "2026-11-06T08:00:00+00:00",
            ),
            # A turn on gpt-6-luna whose web search ran on claude-opus (#2638);
            # a request of unknown model counts under the turn's model.
            (
                "j",
                "completed",
                {
                    "model": "gpt-6-luna",
                    "usage": {
                        **usage,
                        "by_model": {
                            "claude-opus": {"input_tokens": 70, "output_tokens": 7},
                            "": {"input_tokens": 30, "cached_input_tokens": 5},
                        },
                    },
                },
                "2026-11-08T08:00:00+00:00",
            ),
            # Older turns without usage, other months and open turns are left out.
            ("e", "completed", {"model": "gpt-6-luna"}, "2026-11-05T08:00:00+00:00"),
            ("f", "completed", opus, "2026-11-30T23:00:00+00:00"),
            ("g", "completed", opus, "2026-10-31T22:59:59+00:00"),
            ("h", "running", opus, "2026-11-06T08:00:00+00:00"),
            ("i", "completed", "not json", "2026-11-07T08:00:00+00:00"),
        )
        with manager.unit_of_work() as db:
            for turn_id, status, receipt, created in rows:
                db.execute(
                    "INSERT INTO coach_commands(id, client_turn_id, intent, target_system, "
                    "status, receipt, created_at, updated_at) VALUES (?, ?, '{}', 'local', ?, ?, ?, ?)",
                    (
                        turn_id,
                        turn_id,
                        status,
                        receipt if isinstance(receipt, str) else json.dumps(receipt),
                        created,
                        created,
                    ),
                )
            result = monthly_turn_usage(db, date(2026, 11, 13), "Europe/Berlin")
        self.assertEqual(
            result,
            {
                "month": "2026-11",
                "models": [
                    {
                        "model": "claude-opus",
                        "answers": 2,
                        "input_tokens": 3070,
                        "cached_input_tokens": 1800,
                        "output_tokens": 157,
                    },
                    {
                        "model": "gpt-6-luna",
                        "answers": 2,
                        "input_tokens": 1030,
                        "cached_input_tokens": 605,
                        "output_tokens": 50,
                    },
                ],
            },
        )
        with manager.unit_of_work() as db:
            december = monthly_turn_usage(db, date(2026, 12, 1), "Europe/Berlin")
        self.assertEqual(december["month"], "2026-12")
        self.assertEqual([entry["answers"] for entry in december["models"]], [1])


if __name__ == "__main__":
    unittest.main()
