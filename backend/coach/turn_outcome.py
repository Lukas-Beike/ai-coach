"""Finalize one structured Coach turn and its pending-request state."""

from __future__ import annotations

import json
from typing import Any

from backend.coach.outcomes import (
    coach_effect_label,
    coach_failure_lines,
    unresolved_coach_steps,
)
from backend.coach.service import (
    effects_from_receipts,
    mark_resolved_receipts,
    outcome_status,
)
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.providers.openai import response_text


class CoachStructuredOutcomeService:
    """Own final text/status projection and durable pending-request updates."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        database_lock: Any,
        key_values: KeyValueRepository,
        read_only_tools: frozenset[str],
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._internal_tools = read_only_tools | {"clarify_coach_request", "cancel_coach_request"}

    def finalize(
        self,
        response: dict[str, Any],
        command_receipts: list[dict[str, Any]],
        *,
        question: str,
        cancelled: bool,
        allow_mutations: bool,
        context: dict[str, Any],
        message: str,
    ) -> tuple[str, str, list[dict[str, Any]]]:
        failures = unresolved_coach_steps(command_receipts)
        mark_resolved_receipts(command_receipts, failures)
        effects = effects_from_receipts(command_receipts, self._internal_tools)
        text, incomplete_answer, missing_answer = self._text(response, question, failures, effects)
        self._persist_pending(
            command_receipts, effects, failures=failures, incomplete_answer=incomplete_answer,
            question=question, cancelled=cancelled, allow_mutations=allow_mutations,
            context=context, message=message,
        )
        status = outcome_status(
            question=question, incomplete_answer=incomplete_answer, failures=failures,
            missing_answer=missing_answer, effects=effects, cancelled=cancelled,
        )
        return status, text, failures

    @staticmethod
    def _text(
        response: dict[str, Any], question: str,
        failures: list[dict[str, Any]], effects: list[dict[str, Any]],
    ) -> tuple[str, bool, bool]:
        text = question or response_text(response)
        incomplete_answer = response.get("status") == "incomplete"
        missing_answer = not text or incomplete_answer
        if incomplete_answer:
            text += "\nDie Antwort wurde nicht abgeschlossen. Bitte den Coach um Fortsetzung bitten."
        if failures and not question:
            text = "Ein Teil des Auftrags konnte noch nicht ausgeführt werden." if effects else "Der Auftrag konnte noch nicht ausgeführt werden."
            text += "\n" + coach_failure_lines(failures, {entry["tool"] for entry in failures})
            if effects:
                text += "\nGespeichert beziehungsweise beauftragt: " + "; ".join(coach_effect_label(entry) for entry in effects) + "."
        if not text:
            text = "Ergebnis: " + "; ".join(coach_effect_label(entry) for entry in effects) if effects else "Die Antwort konnte nicht abgeschlossen werden. Bitte versuche es erneut."
        return text, incomplete_answer, missing_answer

    def _persist_pending(
        self,
        command_receipts: list[dict[str, Any]], effects: list[dict[str, Any]], *,
        failures: list[dict[str, Any]], incomplete_answer: bool, question: str,
        cancelled: bool, allow_mutations: bool, context: dict[str, Any], message: str,
    ) -> None:
        pending_value: str | None = None
        if (failures or incomplete_answer) and allow_mutations and not cancelled and not question:
            last_request = next((entry.get("request") for entry in reversed(command_receipts) if entry.get("request")), None)
            pending_request = context.get("pending_request") or {}
            pending_value = json.dumps({
                "summary": (last_request or pending_request).get("summary") or message,
                "source_message_ids": (last_request or {}).get("source_message_ids") or [context["current_user_message_id"]],
                "status": "failed",
                "question": None,
                "completed_steps": [{"tool": entry["tool"], "status": entry["result"].get("status")} for entry in effects],
            }, ensure_ascii=False)
        elif effects and not question and not failures and not incomplete_answer and allow_mutations:
            pending_value = "null"
        if pending_value is not None:
            with self._database_lock, self._database_manager.unit_of_work() as db:
                self._key_values.set(db, "coach_pending_request", pending_value)
