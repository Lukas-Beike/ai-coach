"""Durable persistence for queued Coach background turns."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from backend.coach.service import command_receipt
from backend.coach.turn_failures import CoachTurnFailureService
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate

SELECT_RECEIPT_SQL = "SELECT receipt FROM coach_commands WHERE client_turn_id=?"


class CoachJobStore:
    """Claim, requeue, and read persisted Coach background jobs."""

    def __init__(
        self,
        database_manager: Callable[[], DatabaseManager],
        database_lock: Any,
        wake_event: Any,
        maintenance_gate: MaintenanceGate,
        utc_now: Callable[[], str],
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._wake_event = wake_event
        self._maintenance_gate = maintenance_gate
        self._utc_now = utc_now

    def claim(self) -> dict[str, Any] | None:
        with (
            self._maintenance_gate.operation(),
            self._database_lock,
            self._database_manager().unit_of_work() as db,
        ):
            rows = db.execute(
                "SELECT * FROM coach_commands WHERE status='queued' "
                "ORDER BY created_at LIMIT 20"
            ).fetchall()
            for row in rows:
                receipt = command_receipt(row.get("receipt"))
                if receipt.get("mode") != "background":
                    continue
                try:
                    retry_after = float(receipt.get("retry_after") or 0)
                except (TypeError, ValueError):
                    retry_after = 0
                if retry_after > time.time():
                    continue
                claimed = db.execute(
                    "UPDATE coach_commands SET status='running', updated_at=? "
                    "WHERE client_turn_id=? AND status='queued'",
                    (self._utc_now(), row["client_turn_id"]),
                ).rowcount
                if claimed == 1:
                    return {
                        **dict(row),
                        "status": "running",
                        "receipt": receipt,
                        "_maintenance_generation": self._maintenance_gate.current_generation(),
                    }
        return None

    def requeue(self, client_turn_id: str, reason: str) -> None:
        with self._database_lock, self._database_manager().unit_of_work() as db:
            row = db.execute(
                SELECT_RECEIPT_SQL,
                (client_turn_id,),
            ).fetchone()
            if not row:
                return
            receipt = command_receipt(row.get("receipt"))
            try:
                attempts = max(0, int(receipt.get("contention_attempts") or 0)) + 1
            except (TypeError, ValueError):
                attempts = 1
            delay = min(60, 2 ** min(attempts, 5))
            receipt.update({
                "status": "queued",
                "phase": "waiting_for_coach_slot",
                "retry_reason": reason,
                "contention_attempts": attempts,
                "retry_after": time.time() + delay,
            })
            db.execute(
                "UPDATE coach_commands SET status='queued', receipt=?, updated_at=? "
                "WHERE client_turn_id=? AND status='running'",
                (
                    json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
                    self._utc_now(),
                    client_turn_id,
                ),
            )
        self._wake_event.set()

    def message(self, job: dict[str, Any]) -> str:
        receipt = job.get("receipt") if isinstance(job.get("receipt"), dict) else {}
        message_id = receipt.get("user_message_id")
        with self._database_lock, self._database_manager().unit_of_work() as db:
            row = db.execute(
                "SELECT content FROM messages WHERE id=? AND role='user'",
                (message_id,),
            ).fetchone()
        if not row or not str(row.get("content") or "").strip():
            raise AppError(
                500,
                "Die gespeicherte Coach-Nachricht fehlt.",
                reason="background_message_missing",
            )
        return str(row["content"])

    def cancel_requested(self, client_turn_id: str) -> bool:
        """Read a persisted cancel flag before a claimed worker resumes."""
        with self._database_lock, self._database_manager().unit_of_work() as db:
            row = db.execute(
                SELECT_RECEIPT_SQL,
                (client_turn_id,),
            ).fetchone()
        return bool(row and command_receipt(row["receipt"]).get("cancel_requested"))

    def merge_receipt(self, client_turn_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Merge progress into a queued/running command in one locked UOW."""
        with self._database_lock, self._database_manager().unit_of_work() as db:
            row = db.execute(
                SELECT_RECEIPT_SQL,
                (client_turn_id,),
            ).fetchone()
            receipt = command_receipt((row or {}).get("receipt"))
            receipt.update(updates)
            db.execute(
                "UPDATE coach_commands SET receipt=?, updated_at=? "
                "WHERE client_turn_id=? AND status IN ('queued', 'running')",
                (
                    json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
                    self._utc_now(),
                    client_turn_id,
                ),
            )
        return receipt

    def resume_interrupted(self, failures: CoachTurnFailureService) -> int:
        """Recover durable turns without replaying an interrupted Gemini turn."""
        with self._database_lock, self._database_manager().unit_of_work() as db:
            interrupted = db.execute(
                "SELECT client_turn_id, intent FROM coach_commands "
                "WHERE status='running' "
                "AND COALESCE(json_extract(receipt, '$.mode'), '') != 'background'"
            ).fetchall()
        for command in interrupted:
            failures.persist(
                command["client_turn_id"],
                json.loads(command["intent"] or "{}"),
                AppError(
                    503,
                    "Die vorherige Verarbeitung wurde durch einen Prozessneustart unterbrochen.",
                    reason="process_interrupted",
                ),
            )

        resumed = 0
        interrupted_gemini: list[tuple[str, dict[str, Any]]] = []
        now = self._utc_now()
        with self._database_lock, self._database_manager().unit_of_work() as db:
            rows = db.execute(
                "SELECT client_turn_id, status, receipt, intent FROM coach_commands "
                "WHERE status IN ('queued', 'running') ORDER BY created_at"
            ).fetchall()
            for row in rows:
                receipt = command_receipt(row.get("receipt"))
                if receipt.get("mode") != "background":
                    continue
                if row.get("status") == "running" and receipt.get("ai_provider") == "gemini":
                    # GenerateContent has no resumable response ID. Replaying a
                    # completed model/tool turn after restart could repeat effects.
                    interrupted_gemini.append(
                        (row["client_turn_id"], json.loads(row.get("intent") or "{}"))
                    )
                    continue
                receipt["status"] = "queued"
                receipt["phase"] = "resuming" if receipt.get("openai_response_id") else "queued"
                db.execute(
                    "UPDATE coach_commands SET status='queued', receipt=?, updated_at=? "
                    "WHERE client_turn_id=?",
                    (
                        json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
                        now,
                        row["client_turn_id"],
                    ),
                )
                resumed += 1

        for client_turn_id, intent in interrupted_gemini:
            failures.persist(
                client_turn_id,
                intent,
                AppError(
                    503,
                    "Die Gemini-Hintergrundverarbeitung wurde durch einen Prozessneustart unterbrochen und nicht erneut ausgeführt.",
                    reason="process_interrupted",
                ),
            )
        if resumed:
            self._wake_event.set()
        return resumed
