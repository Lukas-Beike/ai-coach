"""Wiring contracts for the Coach write gate at the tool-execution choke point."""

from __future__ import annotations

import json
import logging
import unittest
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from backend.coach.structured_tool_round import (
    CoachStructuredToolRoundLimits,
    CoachStructuredToolRoundService,
    StructuredCoachRoundState,
)
from backend.coach.tool_round_journal import CoachStructuredToolRoundJournal
from backend.coach.turn_write_gate import CoachTurnWriteGate, CoachWriteGateService
from backend.coach.write_gate import WRITE_CAP

READ_ONLY = frozenset({"read_profile"})


def context(
    messages: list[dict[str, object]] | None = None,
    *,
    current: int = 10,
    pending: dict[str, Any] | None = None,
) -> dict[str, object]:
    return {
        "current_user_message_id": current,
        "messages": messages or [],
        "pending_request": pending,
    }


def make_gate(
    message: str,
    ctx: dict[str, object] | None = None,
    *,
    classifier=None,
    model: str | None = "synthetic-model",
    receipts: list[dict[str, Any]] | None = None,
    logger: logging.Logger | None = None,
) -> tuple[CoachTurnWriteGate, Mock]:
    factory = Mock(return_value=classifier or Mock(return_value=frozenset()))
    gate = CoachWriteGateService(
        READ_ONLY, factory, logger or Mock(spec=logging.Logger)
    ).open_turn(
        message=message,
        context=ctx or context(),
        model=model,
        command_receipts=receipts or [],
    )
    return gate, factory


def denied(
    gate: CoachTurnWriteGate, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    denial = gate.denial(tool_name, arguments)
    if denial is None:
        raise AssertionError(f"{tool_name} was unexpectedly allowed")
    return denial


class TurnWriteGateTests(unittest.TestCase):
    def test_read_only_tools_are_never_gated(self) -> None:
        gate, factory = make_gate("Hallo")
        self.assertIsNone(gate.denial("read_profile", {}))
        factory.assert_not_called()

    def test_stem_in_typed_message_allows_and_denies_other_domains(self) -> None:
        gate, _factory = make_gate("Trag meinen Wettkampf am 12.5. ein")
        self.assertIsNone(gate.denial("save_competition", {}))
        denial = denied(gate, "update_profile", {})
        self.assertEqual(denial["status"], "not_performed")
        self.assertFalse(denial["ok"])
        self.assertEqual(denial["reason"], "write_not_authorized")
        self.assertEqual(denial["gate_reason"], "domain_not_requested")
        self.assertIn("Nothing was saved", denial["message"])

    def test_unknown_non_read_tool_fails_closed(self) -> None:
        gate, _factory = make_gate("Speichere mein Gewicht im Profil")
        denial = denied(gate, "brand_new_write_tool", {})
        self.assertEqual(denial["gate_reason"], "unknown_tool")

    def test_bare_affirmation_inherits_directly_preceding_assistant_text(self) -> None:
        messages = [
            {"id": 8, "role": "user", "content": "Wie sieht meine Woche aus?"},
            {
                "id": 9,
                "role": "assistant",
                "content": "Soll ich den Trainingsplan für die Woche anpassen?",
            },
            {"id": 10, "role": "user", "content": "ja"},
        ]
        gate, _factory = make_gate("ja", context(messages))
        self.assertIsNone(gate.denial("apply_training_patch", {}))
        self.assertIsNotNone(gate.denial("update_profile", {}))

    def test_affirmation_after_user_message_has_no_inherited_domain(self) -> None:
        messages = [
            {"id": 8, "role": "assistant", "content": "Soll ich den Plan ändern?"},
            {"id": 9, "role": "user", "content": "Moment"},
            {"id": 10, "role": "user", "content": "ja"},
        ]
        gate, _factory = make_gate("ja", context(messages))
        self.assertIsNotNone(gate.denial("apply_training_patch", {}))

    def test_generic_save_asks_once_instead_of_writing(self) -> None:
        gate, _factory = make_gate("speicher das")
        denial = denied(gate, "save_checkin", {})
        self.assertEqual(denial["gate_reason"], "generic_save_needs_clarification")
        self.assertIn("clarify_coach_request", denial["message"])

    def test_pending_retry_inherits_original_request_domain(self) -> None:
        messages = [
            {
                "id": 4,
                "role": "user",
                "content": "Trag meinen Wettkampf am 12.5. ein",
            },
            {"id": 5, "role": "assistant", "content": "Das hat nicht geklappt."},
            {"id": 10, "role": "user", "content": "nochmal"},
        ]
        pending = {"status": "failed", "source_message_ids": [4]}
        gate, _factory = make_gate("nochmal", context(messages, pending=pending))
        self.assertIsNone(gate.denial("save_competition", {}))
        self.assertIsNotNone(gate.denial("update_profile", {}))
        unrelated, _factory = make_gate("nochmal", context(messages))
        self.assertIsNotNone(unrelated.denial("save_competition", {}))

    def test_classifier_runs_lazily_once_with_turn_model_and_only_on_stem_miss(
        self,
    ) -> None:
        classifier = Mock(return_value=frozenset({"nutrition"}))
        gate, factory = make_gate("Das war gestern lecker", classifier=classifier)
        self.assertIsNone(gate.denial("save_nutrition_entry", {}))
        self.assertIsNone(gate.denial("log_nutrition_template", {}))
        factory.assert_called_once_with("synthetic-model")
        classifier.assert_called_once_with("Das war gestern lecker", "")
        self.assertIsNotNone(gate.denial("update_profile", {}))
        classifier.assert_called_once()

        stem_hit, factory = make_gate("Speichere meine Mahlzeit")
        self.assertIsNone(stem_hit.denial("save_nutrition_entry", {}))
        factory.assert_not_called()

    def test_classifier_failure_or_missing_model_fails_closed(self) -> None:
        broken = Mock(side_effect=RuntimeError("synthetic transport failure"))
        gate, _factory = make_gate("Das war gestern lecker", classifier=broken)
        self.assertEqual(
            denied(gate, "save_nutrition_entry", {})["reason"], "write_not_authorized"
        )
        no_model, factory = make_gate("Das war gestern lecker", model=None)
        self.assertIsNotNone(no_model.denial("save_nutrition_entry", {}))
        factory.assert_not_called()

    def test_classifier_never_grants_remote_intervals_writes(self) -> None:
        classifier = Mock(return_value=frozenset({"planning", "remote_intervals"}))
        gate, _factory = make_gate("Passt das so?", classifier=classifier)
        self.assertIsNotNone(gate.denial("start_intervals_plan_sync", {}))
        self.assertIsNotNone(
            gate.denial("apply_adaptive_replan", {"sync_illness_to_intervals": True})
        )
        self.assertIsNone(gate.denial("apply_adaptive_replan", {}))

    def test_cap_counts_allowed_calls_and_resumed_receipts(self) -> None:
        gate, _factory = make_gate("Trainingsplan anpassen")
        for _ in range(WRITE_CAP):
            self.assertIsNone(gate.denial("apply_training_patch", {}))
        capped = denied(gate, "apply_training_patch", {})
        self.assertEqual(capped["reason"], "write_cap_exceeded")

        receipts = [{"tool": "apply_training_patch"} for _ in range(WRITE_CAP - 1)]
        receipts.append({"tool": "read_profile"})
        resumed, _factory = make_gate("Trainingsplan anpassen", receipts=receipts)
        self.assertIsNone(resumed.denial("apply_training_patch", {}))
        self.assertEqual(
            denied(resumed, "apply_training_patch", {})["reason"], "write_cap_exceeded"
        )

    def test_denial_is_logged_with_tool_domain_and_reason_only(self) -> None:
        logger = Mock(spec=logging.Logger)
        gate, _factory = make_gate(
            "Wie war mein Schlaf? synthetic-secret-token", logger=logger
        )
        gate.denial("update_profile", {"note": "synthetic-secret-token"})
        logger.warning.assert_called_once_with(
            "Coach write denied",
            extra={
                "event": "coach_write_denied",
                "context": {
                    "tool": "update_profile",
                    "domain": "profile",
                    "reason": "domain_not_requested",
                },
            },
        )
        gate.denial("synthetic-secret-token", {})
        self.assertEqual(
            logger.warning.call_args.kwargs["extra"]["context"]["tool"], "unknown"
        )


class ChokePointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = Mock()
        self.manager.unit_of_work.return_value = MagicMock()
        self.lock = MagicMock()
        self.replay = Mock()
        self.replay.lookup.return_value = None
        self.preparation = Mock()
        self.preparation.prepare.return_value = {
            "operation": "save_competition",
            "authorization_scope": [],
            "request": {"remote_write": False},
        }
        self.execution = Mock()
        self.execution.execute.return_value = {"ok": True, "saved": True}
        self.failure = Mock()
        self.jobs = Mock()
        self.response = Mock()
        self.response.respond.return_value = {"output": []}
        self.classifier = Mock(return_value=frozenset())
        self.logger = Mock(spec=logging.Logger)
        self.service = CoachStructuredToolRoundService(
            lambda: self.manager,
            self.lock,
            self.replay,
            self.preparation,
            self.execution,
            self.failure,
            CoachStructuredToolRoundJournal(self.jobs),
            self.jobs,
            Mock(),
            self.response,
            CoachWriteGateService(
                READ_ONLY, lambda _model: self.classifier, self.logger
            ),
            CoachStructuredToolRoundLimits(
                max_rounds=1,
                background_horizon_days=7,
                default_max_output_tokens=6000,
                long_plan_max_output_tokens=32000,
            ),
        )

    @staticmethod
    def state(message: str, **kwargs) -> StructuredCoachRoundState:
        return StructuredCoachRoundState(
            tools=[],
            command_receipts=kwargs.pop("command_receipts", []),
            sync_job_ids=[],
            context=context(),
            allow_mutations=True,
            conversation_id="synthetic-conversation",
            client_turn_id="synthetic-turn",
            session_csrf_hash="synthetic-session",
            cancel_event=None,
            request_payload={"input": [], "model": "synthetic-model"},
            model_instructions="synthetic-instructions",
            message=message,
            attachments=[],
            background_owned=False,
            on_text_delta=None,
            recovery_state={"conversation_recovered": False},
        )

    @staticmethod
    def metadata(name: str = "save_competition") -> dict[str, object]:
        return {
            "name": name,
            "call_id": "call-one",
            "arguments": {"name": "synthetic race"},
            "action": {"operation": name, "authorization_scope": []},
            "effect_key": "effect",
            "step_key": name,
            "repair_key": None,
            "scope_repair_key": None,
            "request_binding_key": None,
            "plan_effect_key": None,
        }

    def execute(self, state: StructuredCoachRoundState, name: str):
        item = {"type": "function_call", "name": name, "call_id": "call-one"}
        with patch(
            "backend.coach.structured_tool_round.structured_tool_call_metadata",
            return_value=self.metadata(name),
        ):
            return self.service._execute_tool_call(
                item, state=state, question="", cancelled=False
            )

    def test_denied_write_does_not_execute_record_or_open_a_transaction(self) -> None:
        state = self.state("Wie war mein Schlaf?")

        name, call_id, result, _action = self.execute(state, "save_competition")

        self.assertEqual((name, call_id), ("save_competition", "call-one"))
        self.assertEqual(result["status"], "not_performed")
        self.assertFalse(result["ok"])
        self.execution.execute.assert_not_called()
        self.manager.unit_of_work.assert_not_called()
        self.lock.__enter__.assert_not_called()
        self.jobs.merge_receipt.assert_not_called()
        self.failure.project.assert_not_called()
        self.assertEqual(state.command_receipts, [])
        self.logger.warning.assert_called_once()

    def test_allowed_write_executes_once_and_records_its_receipt(self) -> None:
        state = self.state("Trag meinen Wettkampf am 12.5. ein")

        result = self.execute(state, "save_competition")[2]

        self.assertEqual(result, {"ok": True, "saved": True})
        self.execution.execute.assert_called_once()
        self.assertEqual(len(state.command_receipts), 1)
        self.logger.warning.assert_not_called()

    def test_gate_sees_request_remote_write_flag_after_preparation(self) -> None:
        self.preparation.prepare.return_value = {
            "operation": "save_competition",
            "authorization_scope": [],
            "request": {"remote_write": True},
        }
        state = self.state("Trag meinen Wettkampf am 12.5. ein")

        result = self.execute(state, "save_competition")[2]

        self.assertEqual(result["status"], "not_performed")
        self.execution.execute.assert_not_called()

    def test_cached_replay_is_returned_without_a_new_decision(self) -> None:
        self.replay.lookup.return_value = {"result": {"ok": True, "cached": True}}
        state = self.state("Wie war mein Schlaf?")

        result = self.execute(state, "save_competition")[2]

        self.assertEqual(result, {"ok": True, "cached": True})
        self.preparation.prepare.assert_not_called()
        self.logger.warning.assert_not_called()

    def test_preparation_failure_keeps_its_existing_failure_path(self) -> None:
        self.preparation.prepare.side_effect = ValueError("synthetic-invalid")
        self.failure.project.return_value = {"ok": False, "reason": "synthetic"}
        state = self.state("Wie war mein Schlaf?")

        result = self.execute(state, "save_competition")[2]

        self.assertEqual(result, {"ok": False, "reason": "synthetic"})
        self.failure.project.assert_called_once()
        self.logger.warning.assert_not_called()

    def test_read_tool_passes_without_domain_words(self) -> None:
        self.preparation.prepare.return_value = {
            "operation": "read_profile",
            "authorization_scope": [],
        }
        state = self.state("Hallo")

        result = self.execute(state, "read_profile")[2]

        self.assertTrue(result["ok"])
        self.classifier.assert_not_called()

    def test_one_gate_per_turn_shares_cap_and_classifier(self) -> None:
        state = self.state("Trag meinen Wettkampf am 12.5. ein")
        self.execute(state, "save_competition")
        gate = state.write_gate
        self.execute(state, "save_competition")
        self.assertIs(state.write_gate, gate)

    def test_denied_round_completes_and_tells_model_nothing_was_saved(self) -> None:
        state = self.state("Wie war mein Schlaf?")
        response = {
            "id": "response-one",
            "output": [
                {
                    "type": "function_call",
                    "name": "save_competition",
                    "call_id": "call-one",
                    "arguments": "{}",
                }
            ],
        }
        with patch(
            "backend.coach.structured_tool_round.structured_tool_call_metadata",
            return_value=self.metadata(),
        ):
            result = self.service.run(
                response, rounds=0, question="", cancelled=False, state=state
            )

        self.assertEqual(result[1:4], (1, "", False))
        followup = self.response.respond.call_args.args[0]
        output = json.loads(followup["input"][0]["output"])
        self.assertEqual(output["status"], "not_performed")
        self.execution.execute.assert_not_called()
        self.assertEqual(state.command_receipts, [])

    def test_resumed_turn_seeds_cap_from_existing_receipts(self) -> None:
        receipts = [{"tool": "save_competition", "result": {"ok": True}}] * WRITE_CAP
        state = self.state(
            "Trag meinen Wettkampf am 12.5. ein", command_receipts=receipts
        )
        self.service.run(
            {"output": []}, rounds=0, question="", cancelled=False, state=state
        )

        result = self.execute(state, "save_competition")[2]

        self.assertEqual(result["reason"], "write_cap_exceeded")


if __name__ == "__main__":
    unittest.main()
