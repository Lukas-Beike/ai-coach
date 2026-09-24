"""Execute structured Coach tool rounds with durable replay and follow-up."""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from backend.coach.authorization import coach_execution_scope
from backend.coach.context import CoachTrainingContextService
from backend.coach.dialogue import INSTRUCTIONS as COACH_DIALOGUE_INSTRUCTIONS
from backend.coach.job_store import CoachJobStore
from backend.coach.proposals import coach_action_hash
from backend.coach.response_transport import raise_if_chat_cancelled
from backend.coach.structured_response import CoachStructuredResponseService
from backend.coach.tool_call_metadata import structured_tool_call_metadata
from backend.coach.tool_execution_service import CoachStructuredToolExecutionService
from backend.coach.tool_failures import CoachStructuredToolFailureService
from backend.coach.tool_preparation import CoachStructuredToolPreparationService
from backend.coach.tool_replay import CoachStructuredToolReplayService
from backend.coach.tool_round_journal import CoachStructuredToolRoundJournal
from backend.db.manager import DatabaseManager
from backend.errors import AppError


@dataclass
class StructuredCoachRoundState:
    tools: list[dict[str, Any]]
    command_receipts: list[dict[str, Any]]
    sync_job_ids: list[str]
    context: dict[str, Any]
    allow_mutations: bool
    conversation_id: str
    client_turn_id: str
    session_csrf_hash: str
    cancel_event: threading.Event | None
    ai_provider: str
    request_payload: dict[str, Any]
    model_instructions: str
    message: str
    attachments: list[dict[str, Any]]
    background_owned: bool
    on_text_delta: Callable[[str], None] | None
    recovery_state: dict[str, bool]


class CoachStructuredToolRoundService:
    """Own tool execution, durable round progress, and provider follow-up."""

    def __init__(
        self,
        database_manager: Callable[[], DatabaseManager],
        database_lock: Any,
        replay: CoachStructuredToolReplayService,
        preparation: CoachStructuredToolPreparationService,
        execution: CoachStructuredToolExecutionService,
        failure: CoachStructuredToolFailureService,
        journal: CoachStructuredToolRoundJournal,
        jobs: CoachJobStore,
        training_context: CoachTrainingContextService,
        response: CoachStructuredResponseService,
        *,
        max_rounds: int,
        background_horizon_days: int,
        default_max_output_tokens: int,
        long_plan_max_output_tokens: int,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._replay = replay
        self._preparation = preparation
        self._execution = execution
        self._failure = failure
        self._journal = journal
        self._jobs = jobs
        self._training_context = training_context
        self._response = response
        self._max_rounds = max_rounds
        self._background_horizon_days = background_horizon_days
        self._default_max_output_tokens = default_max_output_tokens
        self._long_plan_max_output_tokens = long_plan_max_output_tokens

    def _execute_tool_call(
        self, item: dict[str, Any], *, state: StructuredCoachRoundState, question: str, cancelled: bool,
    ) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        name = str(item.get("name") or "")
        call_id = str(item.get("call_id") or "")
        action = {"operation": name, "authorization_scope": []}
        effect_key = coach_action_hash({"tool": name, "arguments": item.get("arguments")})
        step_key = name
        repair_key = scope_repair_key = request_binding_key = plan_effect_key = None
        model_instructions = state.model_instructions
        try:
            metadata = structured_tool_call_metadata(item, state.tools, state.command_receipts)
            name, call_id = metadata["name"], metadata["call_id"]
            action = metadata["action"]
            effect_key, step_key = metadata["effect_key"], metadata["step_key"]
            repair_key = metadata["repair_key"]
            scope_repair_key = metadata["scope_repair_key"]
            request_binding_key = metadata["request_binding_key"]
            plan_effect_key = metadata["plan_effect_key"]
            cached = self._replay.lookup(metadata, state.command_receipts)
            if cached:
                result = cached["result"]
            else:
                action = self._preparation.prepare(
                    metadata, state.command_receipts, question=question, cancelled=cancelled,
                    context=state.context, allow_mutations=state.allow_mutations,
                )
                local_transaction = name not in {"start_provider_refresh", "apply_adaptive_replan"}
                with (
                    self._database_lock if local_transaction else nullcontext(),
                    self._database_manager().unit_of_work() if local_transaction else nullcontext(),
                ):
                    result = self._execution.execute(
                        metadata, action=action, context=state.context, conversation_id=state.conversation_id,
                        client_turn_id=state.client_turn_id, session_csrf_hash=state.session_csrf_hash,
                        sync_job_ids=state.sync_job_ids, cancel_event=state.cancel_event,
                    )
                    state.command_receipts.append({
                        "call_id": call_id, "tool": name, "effect_key": effect_key, "step_key": step_key,
                        "repair_key": repair_key, "scope_repair_key": scope_repair_key,
                        "request_binding_key": request_binding_key, "plan_effect_key": plan_effect_key,
                        "request": action.get("request"), "result": result,
                    })
                    self._jobs.merge_receipt(state.client_turn_id, {
                        "command_receipts": state.command_receipts, "sync_job_ids": state.sync_job_ids,
                    })
            if result.get("synchronous_refresh") or (name == "get_sync_job" and result.get("ok")):
                model_instructions = self._training_context.build() + "\n\n" + COACH_DIALOGUE_INSTRUCTIONS
            if action.get("period"):
                scope = coach_execution_scope(action, background_horizon_days=self._background_horizon_days)
                state.request_payload["max_output_tokens"] = (
                    self._long_plan_max_output_tokens if scope["planning"] else self._default_max_output_tokens
                )
                self._jobs.merge_receipt(state.client_turn_id, {"plan_scope": scope})
        except (AppError, ValueError, TypeError, KeyError) as exc:
            result = self._failure.project(
                exc, name=name, call_id=call_id, effect_key=effect_key, step_key=step_key,
                repair_key=repair_key, scope_repair_key=scope_repair_key,
                request_binding_key=request_binding_key, plan_effect_key=plan_effect_key,
                action=action, command_receipts=state.command_receipts,
            )
        state.model_instructions = model_instructions
        return name, call_id, result, action

    def _followup_response(
        self, response: dict[str, Any], *, outputs: list[dict[str, Any]], state: StructuredCoachRoundState,
        question: str, cancelled: bool, rounds: int,
    ) -> dict[str, Any]:
        followup = {
            **state.request_payload, "instructions": state.model_instructions, "input": outputs,
            "tool_choice": "none" if question or cancelled or rounds >= self._max_rounds else "auto",
        }
        if state.ai_provider == "openai" and response.get("id") and not followup.get("conversation"):
            followup["previous_response_id"] = response["id"]
        return self._response.respond(
            followup, request_payload=state.request_payload, context=state.context, message=state.message,
            command_receipts=state.command_receipts, attachments=state.attachments,
            client_turn_id=state.client_turn_id, ai_provider=state.ai_provider,
            background_owned=state.background_owned, on_text_delta=state.on_text_delta,
            cancel_event=state.cancel_event, recovery_state=state.recovery_state,
        )

    def run(
        self, response: dict[str, Any], *, rounds: int, question: str, cancelled: bool,
        state: StructuredCoachRoundState,
    ) -> tuple[dict[str, Any], int, str, bool, str]:
        """Run bounded tool rounds while preserving durable replay checkpoints."""
        while rounds < self._max_rounds:
            calls = self._journal.function_calls(response)
            if not calls:
                break
            pending = self._journal.start_round(state.client_turn_id, calls)
            outputs = []
            for item in calls:
                raise_if_chat_cancelled(state.cancel_event)
                name, call_id, result, _ = self._execute_tool_call(
                    item, state=state, question=question, cancelled=cancelled,
                )
                question, cancelled, pending = self._journal.record_output(
                    client_turn_id=state.client_turn_id, name=name, call_id=call_id,
                    result=result, outputs=outputs, pending=pending,
                    command_receipts=state.command_receipts,
                    question=question, cancelled=cancelled,
                )
            rounds += 1
            self._journal.finish_round(state.client_turn_id, rounds)
            response = self._followup_response(
                response, outputs=outputs, state=state, question=question, cancelled=cancelled, rounds=rounds,
            )
            self._journal.clear_outputs(state.client_turn_id)
            if question or cancelled:
                break
        return response, rounds, question, cancelled, state.model_instructions
