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
from backend.coach.write_gate import (
    BULK_THRESHOLD,
    DOMAINS,
    WRITE_CAP,
    ImpactVerdict,
)

READ_ONLY = frozenset({"read_profile"})


def verdict(domains=(), delete=False, bulk=False, accepts=False) -> ImpactVerdict:
    listed = frozenset(domains)
    return ImpactVerdict(
        listed,
        listed if delete else frozenset(),
        listed if bulk else frozenset(),
        accepts,
    )


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
    factory = Mock(return_value=classifier or Mock(return_value=verdict()))
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

    def test_reversible_local_writes_pass_without_the_classifier(self) -> None:
        gate, factory = make_gate("Das war gestern lecker")
        self.assertIsNone(gate.denial("save_nutrition_entry", {}))
        self.assertIsNone(gate.denial("update_profile", {}))
        self.assertIsNone(
            gate.denial("apply_training_patch", {"changes": [{"action": "update"}]})
        )
        factory.assert_not_called()

    def test_turn_without_a_stored_athlete_message_writes_nothing(self) -> None:
        gate, _factory = make_gate("Hallo", context(current=0))
        denial = denied(gate, "update_profile", {})
        self.assertEqual(denial["status"], "not_performed")
        self.assertFalse(denial["ok"])
        self.assertEqual(denial["reason"], "write_not_authorized")
        self.assertEqual(denial["gate_reason"], "no_athlete_message")
        self.assertIn("Nothing was saved", denial["message"])

    def test_unknown_non_read_tool_fails_closed(self) -> None:
        gate, _factory = make_gate("Speichere mein Gewicht im Profil")
        denial = denied(gate, "brand_new_write_tool", {})
        self.assertEqual(denial["gate_reason"], "unknown_tool")

    def test_delete_asks_once_unless_the_classifier_confirms_it(self) -> None:
        gate, _factory = make_gate("Weg mit dem Rennen")
        denial = denied(gate, "delete_competition", {})
        self.assertEqual(denial["gate_reason"], "impact_not_confirmed")
        self.assertIn("clarify_coach_request", denial["message"])

        confirmed = Mock(return_value=verdict(["competition"], delete=True))
        gate, _factory = make_gate("Lösch das Rennen in Roth", classifier=confirmed)
        self.assertIsNone(gate.denial("delete_competition", {}))

    def test_classifier_runs_lazily_once_with_turn_model(self) -> None:
        classifier = Mock(return_value=verdict(["nutrition"], delete=True))
        gate, factory = make_gate("Lösch das Frühstück", classifier=classifier)
        self.assertIsNone(gate.denial("save_nutrition_entry", {}))
        factory.assert_not_called()
        self.assertIsNone(gate.denial("delete_nutrition_entry", {}))
        self.assertIsNone(gate.denial("delete_nutrition_template", {}))
        factory.assert_called_once_with("synthetic-model")
        classifier.assert_called_once_with("Lösch das Frühstück", "", "")
        self.assertIsNotNone(gate.denial("delete_competition", {}))
        classifier.assert_called_once()

    def test_classifier_failure_or_missing_model_fails_closed(self) -> None:
        broken = Mock(side_effect=RuntimeError("synthetic transport failure"))
        gate, _factory = make_gate("Lösch das Frühstück", classifier=broken)
        self.assertEqual(
            denied(gate, "delete_nutrition_entry", {})["reason"],
            "write_not_authorized",
        )
        no_model, factory = make_gate("Lösch das Frühstück", model=None)
        self.assertIsNotNone(no_model.denial("delete_nutrition_entry", {}))
        factory.assert_not_called()

    def test_bulk_budget_includes_records_of_resumed_receipts(self) -> None:
        receipts = [
            {"tool": "apply_training_patch", "changes": [{}] * BULK_THRESHOLD},
            {"tool": "read_profile", "changes": [{}] * 50},
        ]
        gate, _factory = make_gate("Verschieb die Woche", receipts=receipts)
        denial = denied(gate, "update_profile", {})
        self.assertEqual(denial["gate_reason"], "impact_not_confirmed")

    def test_remote_writes_need_a_named_sync_and_never_the_classifier(self) -> None:
        classifier = Mock(return_value=verdict(sorted(DOMAINS), True, True))
        gate, factory = make_gate("Passt das so?", classifier=classifier)
        denial = denied(gate, "start_intervals_plan_sync", {})
        self.assertEqual(denial["gate_reason"], "remote_not_requested")
        self.assertIn("offer the sync", denial["message"])
        self.assertIsNotNone(
            gate.denial("apply_adaptive_replan", {"sync_illness_to_intervals": True})
        )
        factory.assert_not_called()

        named, _factory = make_gate("Synchronisier den Plan mit Intervals")
        self.assertIsNone(named.denial("start_intervals_plan_sync", {}))

    def test_negated_sync_wording_never_opens_a_remote_write(self) -> None:
        for message in (
            "Passe die Woche an ohne Intervals zu synchronisieren.",
            "Ich will nicht, dass du mit Intervals synchronisierst.",
            "Ich will nicht, dass du mit Intervals.icu synchronisierst.",
            "Don\u2019t sync it to Intervals.",
            "Bitte keinesfalls zu Intervals hochladen.",
        ):
            with self.subTest(message=message):
                gate, factory = make_gate(message)
                denial = denied(gate, "start_intervals_plan_sync", {})
                self.assertEqual(denial["gate_reason"], "remote_not_requested")
                factory.assert_not_called()
        repair, _factory = make_gate(
            "Korrigiere den Lauf und gleiche alle Einheiten erneut mit Intervals ab, "
            "ohne doppelte Eintraege."
        )
        self.assertIsNone(repair.denial("start_intervals_plan_sync", {}))

    def test_a_reply_to_a_sync_offer_opens_it_only_without_a_negation(self) -> None:
        offer = "Soll ich die drei Einheiten zu Intervals.icu übertragen?"
        for reply, allowed in (
            ("ja, ohne zu synchronisieren", False),
            ("Ja, ohne Upload.", False),
            ("Yes, without uploading.", False),
            ("nein, nicht synchronisieren", False),
            ("Nein danke", False),
            ("ja", True),
            ("Ja, synchronisiere alle", True),
            ("ja, aber synchronisiere", True),
        ):
            with self.subTest(reply=reply):
                messages = [
                    {"id": 9, "role": "assistant", "content": offer},
                    {"id": 10, "role": "user", "content": reply},
                ]
                gate, _factory = make_gate(reply, context(messages))
                denial = gate.denial("start_intervals_plan_sync", {})
                self.assertEqual(denial is None, allowed, denial)

    def test_applying_a_preview_needs_the_classifier_to_confirm_the_request(
        self,
    ) -> None:
        gate, factory = make_gate("danke")
        denial = denied(gate, "apply_adaptive_replan", {})
        self.assertEqual(denial["gate_reason"], "approval_not_confirmed")
        self.assertIn("preview_adaptive_replan", denial["message"])
        factory.assert_called_once_with("synthetic-model")

        classifier = Mock(return_value=verdict(["planning"], accepts=True))
        gate, factory = make_gate("Ja, übernimm die Anpassung", classifier=classifier)
        self.assertIsNone(gate.denial("apply_adaptive_replan", {}))
        self.assertIsNone(gate.denial("update_profile", {}))
        factory.assert_called_once_with("synthetic-model")
        classifier.assert_called_once()

    def test_bare_affirmation_inherits_directly_preceding_sync_offer(self) -> None:
        offer = "Soll ich den Plan zu Intervals synchronisieren?"
        messages = [
            {"id": 8, "role": "user", "content": "Wie sieht meine Woche aus?"},
            {"id": 9, "role": "assistant", "content": offer},
            {"id": 10, "role": "user", "content": "ja"},
        ]
        gate, _factory = make_gate("ja", context(messages))
        self.assertIsNone(gate.denial("start_intervals_plan_sync", {}))

        interrupted = [
            {"id": 8, "role": "assistant", "content": offer},
            {"id": 9, "role": "user", "content": "Moment"},
            {"id": 10, "role": "user", "content": "ja"},
        ]
        gate, _factory = make_gate("ja", context(interrupted))
        self.assertIsNotNone(gate.denial("start_intervals_plan_sync", {}))

    def test_pending_retry_inherits_original_request(self) -> None:
        messages = [
            {"id": 4, "role": "user", "content": "Sync den Plan zu Intervals"},
            {"id": 5, "role": "assistant", "content": "Das hat nicht geklappt."},
            {"id": 10, "role": "user", "content": "nochmal"},
        ]
        pending = {"status": "failed", "source_message_ids": [4]}
        gate, _factory = make_gate("nochmal", context(messages, pending=pending))
        self.assertIsNone(gate.denial("start_intervals_plan_sync", {}))
        unrelated, _factory = make_gate("nochmal", context(messages))
        self.assertIsNotNone(unrelated.denial("start_intervals_plan_sync", {}))

        classifier = Mock(return_value=verdict(["competition"], delete=True))
        messages[0] = {"id": 4, "role": "user", "content": "Lösch das Rennen"}
        gate, _factory = make_gate(
            "nochmal", context(messages, pending=pending), classifier=classifier
        )
        self.assertIsNone(gate.denial("delete_competition", {}))
        classifier.assert_called_once_with(
            "nochmal", "Das hat nicht geklappt.", "Lösch das Rennen"
        )

    def test_cap_counts_allowed_calls_and_resumed_receipts(self) -> None:
        gate, _factory = make_gate("Trainingsplan anpassen")
        for _ in range(WRITE_CAP):
            self.assertIsNone(gate.denial("stage_training_plan", {}))
        capped = denied(gate, "stage_training_plan", {})
        self.assertEqual(capped["reason"], "write_cap_exceeded")

        receipts = [{"tool": "stage_training_plan"} for _ in range(WRITE_CAP - 1)]
        receipts.append({"tool": "read_profile"})
        resumed, _factory = make_gate("Trainingsplan anpassen", receipts=receipts)
        self.assertIsNone(resumed.denial("stage_training_plan", {}))
        self.assertEqual(
            denied(resumed, "stage_training_plan", {})["reason"], "write_cap_exceeded"
        )

    def test_denial_is_logged_with_tool_domain_and_reason_only(self) -> None:
        logger = Mock(spec=logging.Logger)
        gate, _factory = make_gate(
            "Wie war mein Schlaf? synthetic-secret-token", logger=logger
        )
        gate.denial("delete_competition", {"note": "synthetic-secret-token"})
        logger.warning.assert_called_once_with(
            "Coach write denied",
            extra={
                "event": "coach_write_denied",
                "context": {
                    "tool": "delete_competition",
                    "domain": "competition",
                    "reason": "impact_not_confirmed",
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
        self.classifier = Mock(return_value=verdict())
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

        name, call_id, result, _action = self.execute(state, "delete_competition")

        self.assertEqual((name, call_id), ("delete_competition", "call-one"))
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
                    "name": "delete_competition",
                    "call_id": "call-one",
                    "arguments": "{}",
                }
            ],
        }
        with patch(
            "backend.coach.structured_tool_round.structured_tool_call_metadata",
            return_value=self.metadata("delete_competition"),
        ):
            result = self.service.run(
                response, rounds=0, question="", cancelled=False, state=state
            )

        self.assertEqual(result[1:4], (1, "", False))
        followup = self.response.respond.call_args.args[0]
        output = json.loads(followup["input"][0]["output"])
        self.assertEqual(output["status"], "not_performed")
        self.assertEqual(output["gate_reason"], "impact_not_confirmed")
        self.classifier.assert_called_once()
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
