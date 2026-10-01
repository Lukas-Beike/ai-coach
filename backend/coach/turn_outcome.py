"""Finalize one structured Coach turn and its pending-request state."""

from __future__ import annotations

import json
from typing import Any, NotRequired, TypedDict

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


class ObservedSyncJob(TypedDict):
    id: str
    status: NotRequired[str]


def _failure_message(
    text: str,
    question: str,
    failures: list[dict[str, Any]],
    effects: list[dict[str, Any]],
) -> str:
    if not failures or question:
        return text
    text = (
        "Ein Teil des Auftrags konnte noch nicht ausgeführt werden."
        if effects
        else "Der Auftrag konnte noch nicht ausgeführt werden."
    )
    text += "\n" + coach_failure_lines(failures, {entry["tool"] for entry in failures})
    if effects:
        text += (
            "\nGespeichert beziehungsweise beauftragt: "
            + "; ".join(coach_effect_label(entry) for entry in effects)
            + "."
        )
    return text


def _queued_message(
    text: str,
    question: str,
    queued: list[str],
    effects: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    incomplete_answer: bool,
) -> str:
    if not queued:
        return text
    lines: list[str] = []
    if failures:
        lines.extend(
            (
                "Ein Teil des Auftrags konnte noch nicht ausgeführt werden.",
                coach_failure_lines(failures, {entry["tool"] for entry in failures}),
            )
        )
    local_effects = [
        entry
        for entry in effects
        if not (
            (entry.get("result") or {}).get("status") == "queued"
            and (entry.get("result") or {}).get("sync_job_id")
        )
        and not (entry.get("result") or {}).get("proposed_action")
    ]
    if local_effects:
        lines.append(
            "Lokal gespeichert beziehungsweise ausgeführt: "
            + "; ".join(coach_effect_label(entry) for entry in local_effects)
            + "."
        )
    lines.extend(queued)
    if incomplete_answer:
        lines.append(
            "Die Antwort wurde nicht abgeschlossen. Bitte den Coach um Fortsetzung bitten."
        )
    if question:
        lines.append(question)
    return "\n".join(line for line in lines if line)


def _approval_message(
    text: str,
    question: str,
    awaiting_remote_approval: bool,
    effects: list[dict[str, Any]],
) -> str:
    if not awaiting_remote_approval or question:
        return text
    local_effects = [
        entry
        for entry in effects
        if not (entry.get("result") or {}).get("proposed_action")
    ]
    prefix = ""
    if local_effects:
        prefix = (
            "Lokal gespeichert beziehungsweise ausgeführt: "
            + "; ".join(coach_effect_label(entry) for entry in local_effects)
            + ". "
        )
    return (
        prefix
        + "Die Remote-Änderung wartet auf deine ausdrückliche Freigabe. Prüfe den Aktionsvorschlag, bevor sie ausgeführt wird."
    )


def _fallback_message(text: str, effects: list[dict[str, Any]]) -> str:
    if text:
        return text
    if effects:
        return "Ergebnis: " + "; ".join(coach_effect_label(entry) for entry in effects)
    return "Die Antwort konnte nicht abgeschlossen werden. Bitte versuche es erneut."


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
        self._internal_tools = read_only_tools | {
            "clarify_coach_request",
            "cancel_coach_request",
        }

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
        effects = effects_from_receipts(command_receipts, set(self._internal_tools))
        text, incomplete_answer, missing_answer = self._text(
            response, question, failures, effects, command_receipts
        )
        self._persist_pending(
            command_receipts,
            effects,
            failures=failures,
            incomplete_answer=incomplete_answer,
            question=question,
            cancelled=cancelled,
            allow_mutations=allow_mutations,
            context=context,
            message=message,
        )
        status = outcome_status(
            question=question,
            incomplete_answer=incomplete_answer,
            failures=failures,
            missing_answer=missing_answer,
            effects=effects,
            cancelled=cancelled,
        )
        return status, text, failures

    @staticmethod
    def _text(
        response: dict[str, Any],
        question: str,
        failures: list[dict[str, Any]],
        effects: list[dict[str, Any]],
        command_receipts: list[dict[str, Any]],
    ) -> tuple[str, bool, bool]:
        text = question or response_text(response)
        queued = CoachStructuredOutcomeService._queued_jobs(effects, command_receipts)
        awaiting_remote_approval = any(
            ((entry.get("result") or {}).get("proposed_action") or {}).get(
                "action_type"
            )
            in {"remote_coach_write", "local_coach_write"}
            for entry in command_receipts
        )
        incomplete_answer = response.get("status") == "incomplete"
        missing_answer = not text or incomplete_answer
        if incomplete_answer:
            text += "\nDie Antwort wurde nicht abgeschlossen. Bitte den Coach um Fortsetzung bitten."
        text = _failure_message(text, question, failures, effects)
        text = _queued_message(
            text, question, queued, effects, failures, incomplete_answer
        )
        text = _approval_message(text, question, awaiting_remote_approval, effects)
        text = _fallback_message(text, effects)
        return text, incomplete_answer, missing_answer

    @staticmethod
    def _queued_jobs(
        effects: list[dict[str, Any]], command_receipts: list[dict[str, Any]]
    ) -> list[str]:
        jobs: dict[str, str] = {}
        # Read-only job inspections are excluded from ``effects``. Fold their
        # durable observations too, so a later terminal status supersedes the
        # original queue receipt for the same job.
        for entry in command_receipts:
            result = entry.get("result") or {}
            observed = result.get("job")
            if isinstance(observed, dict) and observed.get("id"):
                job: ObservedSyncJob = {
                    "id": str(observed["id"]),
                    "status": str(observed.get("status") or "unknown"),
                }
                jobs[job["id"]] = job.get("status", "unknown")
        for entry in effects:
            result = entry.get("result") or {}
            if result.get("status") == "queued" and result.get("sync_job_id"):
                jobs.setdefault(str(result["sync_job_id"]), "queued")
        return [
            f"Synchronisationsauftrag {job_id}: {status}. Remote-Abschluss ist "
            f"{'bestätigt' if status == 'completed' else 'noch nicht bestätigt'}."
            for job_id, status in jobs.items()
        ]

    def _persist_pending(
        self,
        command_receipts: list[dict[str, Any]],
        effects: list[dict[str, Any]],
        *,
        failures: list[dict[str, Any]],
        incomplete_answer: bool,
        question: str,
        cancelled: bool,
        allow_mutations: bool,
        context: dict[str, Any],
        message: str,
    ) -> None:
        pending_value: str | None = None
        if (
            (failures or incomplete_answer)
            and allow_mutations
            and not cancelled
            and not question
        ):
            last_request = next(
                (
                    entry.get("request")
                    for entry in reversed(command_receipts)
                    if entry.get("request")
                ),
                None,
            )
            pending_request = context.get("pending_request") or {}
            pending_value = json.dumps(
                {
                    "summary": (last_request or pending_request).get("summary")
                    or message,
                    "source_message_ids": (last_request or {}).get("source_message_ids")
                    or [context["current_user_message_id"]],
                    "status": "failed",
                    "question": None,
                    "completed_steps": [
                        {"tool": entry["tool"], "status": entry["result"].get("status")}
                        for entry in effects
                    ],
                },
                ensure_ascii=False,
            )
        elif (
            effects
            and not question
            and not failures
            and not incomplete_answer
            and allow_mutations
        ):
            pending_value = "null"
        if pending_value is not None:
            with self._database_lock, self._database_manager.unit_of_work() as db:
                self._key_values.set(db, "coach_pending_request", pending_value)
