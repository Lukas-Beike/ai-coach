"""Persist failed Coach turns without losing confirmed local effects."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend import observability
from backend.coach.authorization import authorized_operations
from backend.coach.outcomes import (
    COACH_ACTION_LABELS,
    coach_effect_label,
    coach_failure_lines,
    coach_observed_sync_lines,
    unresolved_coach_steps,
)
from backend.coach.service import command_receipt
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository, KeyValueRepository
from backend.errors import AppError
from backend.runtime.events import StateEventBuffer


def coach_error_metadata(exc: BaseException, repository_root: Path) -> dict[str, Any]:
    """Keep technical call sites, never exception text, source lines or locals."""
    result = observability.safe_diagnostic_error(exc)
    frames = []
    trace = exc.__traceback__
    while trace is not None:
        filename = Path(trace.tb_frame.f_code.co_filename).resolve()
        if filename == repository_root / "server.py" or filename.is_relative_to(
            repository_root / "backend"
        ):
            frames.append(
                {
                    "file": filename.relative_to(repository_root).as_posix(),
                    "function": trace.tb_frame.f_code.co_name,
                    "line": trace.tb_lineno,
                }
            )
        trace = trace.tb_next
    result["frames"] = frames[-8:]
    return result


@dataclass(frozen=True)
class CoachTurnFailureDependencies:
    database_manager: Callable[[], DatabaseManager]
    database_lock: Any
    chat_repository: ChatRepository
    key_values: KeyValueRepository
    event_buffer: StateEventBuffer
    redactor: observability.Redactor
    utc_now: Callable[[], str]
    repository_root: Path
    read_only_tools: frozenset[str]


class CoachTurnFailureService:
    """Own terminal failure projection, atomic receipt, and committed event."""

    def __init__(self, dependencies: CoachTurnFailureDependencies) -> None:
        self._deps = dependencies

    def persist(
        self, client_turn_id: str, intent: dict[str, Any], error: BaseException
    ) -> dict[str, Any]:
        deps = self._deps
        safe_error = (
            deps.redactor.redact_text(error.message)[:1000]
            if isinstance(error, AppError)
            else "Die Coach-Verarbeitung wurde unterbrochen."
        )
        with deps.database_lock, deps.database_manager().unit_of_work() as db:
            row = db.execute(
                "SELECT receipt, status FROM coach_commands WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            if not row:
                return {}
            receipt = command_receipt(row["receipt"])
            if row["status"] == "completed":
                return receipt
            commands, successes, failures, pending = self._steps(receipt, intent)
            status, text, question, cancelled = self._response(
                error, commands, successes, failures, pending
            )
            self._pending_request(
                db, receipt, question=question, cancelled=cancelled, successes=successes
            )
            receipt.update(
                {
                    "status": status,
                    "awaiting_clarification": bool(question) and not cancelled,
                    "error": safe_error,
                    "diagnostic_error": coach_error_metadata(error, deps.repository_root),
                    "client_turn_id": client_turn_id,
                    "command_receipts": commands,
                    "sync_job_ids": receipt.get("sync_job_ids") or [],
                    "intent": intent,
                    "pending_operations": pending,
                    "proposed_actions": [
                        step["result"]["proposed_action"]
                        for step in commands
                        if step.get("result", {}).get("proposed_action")
                    ],
                }
            )
            # A terminal failure is not resumable and must not retain inline image data.
            for key in (
                "openai_response_id", "pending_tool_outputs", "pending_tool_calls",
                "response_input", "previous_response_id",
            ):
                receipt.pop(key, None)
            receipt["message"] = deps.chat_repository.add(
                db, "assistant", text, client_turn_id=client_turn_id
            )
            db.execute(
                "UPDATE coach_commands SET status='completed', receipt=?, updated_at=? "
                "WHERE client_turn_id=?",
                (json.dumps(receipt, ensure_ascii=False), deps.utc_now(), client_turn_id),
            )
        deps.event_buffer.publish(
            "coach",
            {
                "message_id": receipt["message"]["id"],
                "role": "assistant",
                "client_turn_id": client_turn_id,
            },
        )
        return receipt

    def _steps(
        self, receipt: dict[str, Any], intent: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        commands = list(receipt.get("command_receipts") or [])
        internal = self._deps.read_only_tools | {
            "clarify_coach_request", "cancel_coach_request"
        }
        successes = [
            step for step in commands
            if step.get("result", {}).get("ok") and step["tool"] not in internal
        ]
        failures = unresolved_coach_steps(commands)
        for step in commands:
            if not step.get("result", {}).get("ok"):
                step["resolved"] = not any(step is failure for failure in failures)
        pending = sorted(
            {step["tool"] for step in failures}
            | {
                step["tool"]
                for step in receipt.get("pending_tool_calls", [])
                if step.get("tool")
            }
            | (authorized_operations(intent) - {step["tool"] for step in successes} - {""})
        )
        return commands, successes, failures, pending

    @staticmethod
    def _base_response(
        error: BaseException, commands: list[dict[str, Any]]
    ) -> tuple[str, str, str | None, bool]:
        cancelled = isinstance(error, AppError) and error.reason == "chat_cancelled"
        status = "cancelled" if cancelled else "failed"
        reason = getattr(error, "reason", None)
        explanations = {
            "conversation_state_invalid": "Der KI-Dienst konnte den Gesprächszustand nicht fortsetzen. Bitte versuche es erneut; dein lokaler Chat bleibt erhalten.",
            "conversation_locked": "Der KI-Dienst verarbeitet noch eine andere Anfrage. Bitte warte kurz und versuche es erneut.",
            "authentication_or_permission": "Der KI-Dienst hat den Zugriff abgelehnt. Bitte prüfe den API-Zugang in den Einstellungen.",
            "insufficient_quota": "Das KI-Kontingent ist aufgebraucht. Bitte prüfe Guthaben und Abrechnung beim KI-Anbieter.",
            "credit_balance_exhausted": "Das KI-Guthaben ist aufgebraucht. Bitte prüfe die Abrechnung beim KI-Anbieter.",
            "provider_unavailable": "Der KI-Dienst ist vorübergehend nicht verfügbar. Bitte versuche es in Kürze erneut.",
            "response_error": "Der KI-Dienst konnte die Antwort nicht fertigstellen. Bitte versuche es erneut.",
            "response_failed": "Der KI-Dienst konnte die Antwort nicht fertigstellen. Bitte versuche es erneut.",
        }
        text = (
            "Die Coach-Verarbeitung wurde abgebrochen."
            if cancelled
            else explanations.get(
                reason,
                "Bei der Coach-Verarbeitung ist ein technischer Fehler aufgetreten. Bitte versuche es erneut. Wenn der Fehler wieder auftritt, exportiere die Diagnose in den Einstellungen.",
            )
        )
        question = next(
            (
                step["result"].get("question")
                for step in reversed(commands)
                if step["tool"] == "clarify_coach_request"
                and step.get("result", {}).get("ok")
            ),
            None,
        )
        if question and not cancelled:
            status = "completed"
            text = question
        rate_limited = isinstance(error, AppError) and (
            error.reason == "rate_limit_exceeded"
            or getattr(error, "provider_error_code", None) == "rate_limit_exceeded"
        )
        if rate_limited and not question:
            text = "Der KI-Dienst hat sein Anfragelimit erreicht. Die Antwort konnte noch nicht abgeschlossen werden. Bitte versuche es in Kürze erneut."
        return status, text, question, cancelled

    @staticmethod
    def _effect_text(
        text: str, commands: list[dict[str, Any]], successes: list[dict[str, Any]],
        failures: list[dict[str, Any]], pending: list[str],
    ) -> str:
        if successes:
            text += "\nBereits erfolgreich ausgefuehrt: " + "; ".join(
                coach_effect_label(step) for step in successes
            ) + ". Diese Schritte bleiben gespeichert."
            if any(
                step["tool"] in {"start_intervals_plan_sync", "sync_competitions"}
                and step["result"].get("status") == "queued"
                for step in successes
            ):
                text += "\nDer Sync-Auftrag bleibt bestehen und wird unabhängig vom Coach verarbeitet. Sein Abschluss ist in dieser Antwort noch nicht bestätigt."
        if failures:
            text += "\n" + coach_failure_lines(failures, set(pending))
        observed_sync = coach_observed_sync_lines(commands)
        if observed_sync:
            text += "\n" + observed_sync
        if pending:
            text += "\nNoch offen: " + ", ".join(
                COACH_ACTION_LABELS.get(name, "Angeforderter Schritt") for name in pending
            ) + "."
        return text

    def _response(
        self, error: BaseException, commands: list[dict[str, Any]],
        successes: list[dict[str, Any]], failures: list[dict[str, Any]], pending: list[str],
    ) -> tuple[str, str, str | None, bool]:
        status, text, question, cancelled = self._base_response(error, commands)
        if successes and (cancelled or not question):
            status = "partial"
        return status, self._effect_text(text, commands, successes, failures, pending), question, cancelled

    def _pending_request(
        self, db: Any, receipt: dict[str, Any], *, question: str | None,
        cancelled: bool, successes: list[dict[str, Any]],
    ) -> None:
        if cancelled:
            self._deps.key_values.set(db, "coach_pending_request", "null")
        elif receipt.get("user_message_id") and not question:
            user = db.execute(
                "SELECT content FROM messages WHERE id=? AND role='user'",
                (receipt["user_message_id"],),
            ).fetchone()
            if user:
                self._deps.key_values.set(
                    db,
                    "coach_pending_request",
                    json.dumps(
                        {
                            "summary": user["content"],
                            "source_message_ids": [receipt["user_message_id"]],
                            "status": "failed",
                            "question": None,
                            "completed_steps": [
                                {"tool": step["tool"], "status": step["result"].get("status")}
                                for step in successes
                            ],
                        },
                        ensure_ascii=False,
                    ),
                )
