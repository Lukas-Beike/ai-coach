"""Finalize one structured Coach turn and its pending-request state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from backend.coach.context_selection import infer_coach_domain, select_coach_context
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
from backend.providers.openai_responses import response_text

_READ_ONLY_JOB_TYPES = frozenset(
    {"refresh", "performance_refresh", "activity_details", "historical_backfill"}
)
_READ_ONLY_REFRESH_TOOLS = frozenset(
    {"start_provider_refresh", "refresh_current_performance"}
)


@dataclass(frozen=True)
class _SyncJob:
    status: str
    writes_remote: bool
    started_here: bool

    def reported(self) -> bool:
        """Whether its authoritative status line belongs in the answer."""
        if self.status == "completed":
            return self.writes_remote and self.started_here
        return True

    def replaces_prose(self) -> bool:
        """Whether the model could overstate a remote write it cannot confirm."""
        return self.writes_remote and (self.started_here or self.status != "completed")

    def status_line(self, job_id: str) -> str:
        prefix = f"Synchronisationsauftrag {job_id}: {self.status}."
        if self.writes_remote:
            confirmed = (
                "bestätigt" if self.status == "completed" else "noch nicht bestätigt"
            )
            return f"{prefix} Remote-Abschluss ist {confirmed}."
        if self.status == "partial":
            return f"{prefix} Der Datenabruf war nur teilweise erfolgreich."
        outcome = (
            "läuft noch"
            if self.status in {"queued", "running"}
            else "ist fehlgeschlagen"
        )
        return (
            f"{prefix} Der Datenabruf {outcome}; "
            "die Antwort nutzt die bisher gespeicherten Daten."
        )


def _inspected_jobs(
    command_receipts: list[dict[str, Any]],
) -> dict[str, tuple[str, str | None]]:
    """Latest inspected status per job id, keeping the last reported job type."""
    inspected: dict[str, tuple[str, str | None]] = {}
    for entry in command_receipts:
        job = (entry.get("result") or {}).get("job")
        if not isinstance(job, dict) or not job.get("id"):
            continue
        job_id = str(job["id"])
        previous_type = inspected.get(job_id, ("", None))[1]
        job_type = str(job["type"]) if job.get("type") else previous_type
        inspected[job_id] = (str(job.get("status") or "unknown"), job_type)
    return inspected


def _sync_jobs(
    effects: list[dict[str, Any]], command_receipts: list[dict[str, Any]]
) -> dict[str, _SyncJob]:
    """Fold queue receipts and job inspections; an inspection supersedes the queue.

    Unknown job types count as remote writes, so only known data refreshes keep
    the model's answer.
    """
    inspected = _inspected_jobs(command_receipts)
    jobs = {
        job_id: _SyncJob(
            status=status,
            writes_remote=job_type not in _READ_ONLY_JOB_TYPES,
            started_here=False,
        )
        for job_id, (status, job_type) in inspected.items()
    }
    for entry in effects:
        result = entry.get("result") or {}
        job_id = str(result.get("sync_job_id") or "")
        if result.get("status") != "queued" or not job_id:
            continue
        status, job_type = inspected.get(job_id, ("queued", None))
        # An inspected job type is authoritative over the tool that queued it.
        writes_remote = (
            job_type not in _READ_ONLY_JOB_TYPES
            if job_type
            else entry.get("tool") not in _READ_ONLY_REFRESH_TOOLS
        )
        jobs[job_id] = _SyncJob(
            status=status, writes_remote=writes_remote, started_here=True
        )
    return jobs


def _partial_refresh_note(effects: list[dict[str, Any]]) -> str | None:
    """Flag a waited refresh that finished with missing data."""
    if any(
        entry.get("tool") == "start_provider_refresh"
        and (entry.get("result") or {}).get("partial")
        for entry in effects
    ):
        return "Hinweis: Der Datenabruf war nur teilweise erfolgreich; einzelne Daten können fehlen."
    return None


def _pending_value(
    command_receipts: list[dict[str, Any]],
    effects: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    *,
    incomplete_answer: bool,
    question: str,
    cancelled: bool,
    allow_mutations: bool,
    context: dict[str, Any],
    message: str,
) -> str | None:
    can_update = allow_mutations and not cancelled and not question
    if can_update and (failures or incomplete_answer):
        last_request = next(
            (
                entry.get("request")
                for entry in reversed(command_receipts)
                if entry.get("request")
            ),
            None,
        )
        selection = select_coach_context(message, context)
        pending_request = (
            context.get("pending_request") or {}
            if selection.retain_pending_request
            else {}
        )
        tool_names = [
            entry["tool"]
            for entry in (failures + effects)
            if isinstance(entry, dict) and "tool" in entry
        ]
        request = last_request or pending_request
        summary = request.get("summary") or message
        domain = request.get("domain") or infer_coach_domain(summary, tools=tool_names)
        return json.dumps(
            {
                "summary": summary,
                "source_message_ids": request.get("source_message_ids")
                or [context["current_user_message_id"]],
                "status": "failed",
                "domain": domain,
                "question": None,
                "completed_steps": [
                    {"tool": entry["tool"], "status": entry["result"].get("status")}
                    for entry in effects
                ],
            },
            ensure_ascii=False,
        )
    if can_update and effects and not failures:
        return "null"
    return None


def _may_clear_pending(
    question: str,
    failures: list[dict[str, Any]],
    incomplete_answer: bool,
    missing_answer: bool,
    allow_mutations: bool,
    cancelled: bool,
) -> bool:
    return allow_mutations and not (
        question or failures or incomplete_answer or missing_answer or cancelled
    )


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
    notices: list[str],
    effects: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    incomplete_answer: bool,
    replace_prose: bool,
) -> str:
    """Append sync notices to the answer, or rebuild it around them.

    A clarifying question carries no failure or local-effect lines, so it is
    rebuilt with them, as is an answer that could overstate a remote write.
    """
    if not notices:
        return text
    if text and not replace_prose and not question:
        return "\n".join((text, *notices))
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
    lines.extend(notices)
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
    awaiting_approval: bool,
    effects: list[dict[str, Any]],
    command_receipts: list[dict[str, Any]],
) -> str:
    if not awaiting_approval or question:
        return text
    local_approval = any(
        ((entry.get("result") or {}).get("proposed_action") or {}).get("action_type")
        == "local_coach_write"
        for entry in command_receipts
    )
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
    return prefix + (
        "Die lokale Änderung wartet auf deine ausdrückliche Freigabe. Prüfe den Aktionsvorschlag, bevor sie gespeichert wird."
        if local_approval
        else "Die Remote-Änderung wartet auf deine ausdrückliche Freigabe. Prüfe den Aktionsvorschlag, bevor sie ausgeführt wird."
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
            missing_answer=missing_answer,
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
        jobs = _sync_jobs(effects, command_receipts)
        notices = [
            job.status_line(job_id) for job_id, job in jobs.items() if job.reported()
        ]
        partial_note = _partial_refresh_note(effects)
        if partial_note:
            notices.append(partial_note)
        replace_prose = any(job.replaces_prose() for job in jobs.values())
        awaiting_approval = any(
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
            text, question, notices, effects, failures, incomplete_answer, replace_prose
        )
        text = _approval_message(
            text, question, awaiting_approval, effects, command_receipts
        )
        text = _fallback_message(text, effects)
        return text, incomplete_answer, missing_answer

    def _persist_pending(
        self,
        command_receipts: list[dict[str, Any]],
        effects: list[dict[str, Any]],
        *,
        failures: list[dict[str, Any]],
        incomplete_answer: bool,
        missing_answer: bool = False,
        question: str,
        cancelled: bool,
        allow_mutations: bool,
        context: dict[str, Any],
        message: str,
    ) -> None:
        pending_value = _pending_value(
            command_receipts,
            effects,
            failures,
            incomplete_answer=incomplete_answer,
            question=question,
            cancelled=cancelled,
            allow_mutations=allow_mutations,
            context=context,
            message=message,
        )

        if pending_value is not None:
            with self._database_lock, self._database_manager.unit_of_work() as db:
                self._key_values.set(db, "coach_pending_request", pending_value)
        elif _may_clear_pending(
            question,
            failures,
            incomplete_answer,
            missing_answer,
            allow_mutations,
            cancelled,
        ):
            with self._database_lock, self._database_manager.unit_of_work() as db:
                raw_pending = self._key_values.get(db, "coach_pending_request")
                try:
                    current_pending = json.loads(raw_pending or "null")
                except ValueError, TypeError:
                    current_pending = None
                if isinstance(current_pending, dict):
                    selection = select_coach_context(
                        message, {"pending_request": current_pending}
                    )
                    if current_pending.get("status") == "failed" or (
                        current_pending.get("status") == "needs_clarification"
                        and (
                            not command_receipts or not selection.retain_pending_request
                        )
                    ):
                        self._key_values.set(db, "coach_pending_request", "null")
