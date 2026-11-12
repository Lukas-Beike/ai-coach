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
# A job whose failure escapes its own error handling is retried this many times in
# total, then ended; contention requeues are counted separately and never end a job.
MAX_FAILED_ATTEMPTS = 3
# Resume checkpoints that releases up to 2.1.1 wrote into a running job's receipt.
LEGACY_RESUME_KEYS = (
    "openai_response_id",
    "response_input",
    "previous_response_id",
    "pending_tool_outputs",
)


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

    def busy(self) -> bool:
        """Report whether a Coach turn is queued or running."""
        with self._database_manager().reader() as db:
            return (
                db.execute(
                    "SELECT 1 FROM coach_commands "
                    "WHERE status IN ('queued', 'running') LIMIT 1"
                ).fetchone()
                is not None
            )

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
                except TypeError, ValueError:
                    retry_after = 0
                # A cancelled job is due at once, so it ends instead of waiting.
                if retry_after > time.time() and not receipt.get("cancel_requested"):
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

    def requeue(
        self,
        client_turn_id: str,
        reason: str,
        *,
        wait_seconds: int | None = None,
        max_waits: int | None = None,
    ) -> bool:
        """Queue a running job again; contention backs off up to a minute.

        A fixed ``wait_seconds`` waits for outside data instead and gives up
        (returns ``False``) once ``max_waits`` such waits were used.
        """
        counter = (
            "contention_attempts" if wait_seconds is None else "data_wait_attempts"
        )
        with self._database_lock, self._database_manager().unit_of_work() as db:
            row = db.execute(
                SELECT_RECEIPT_SQL,
                (client_turn_id,),
            ).fetchone()
            if not row:
                return False
            receipt = command_receipt(row.get("receipt"))
            try:
                attempts = max(0, int(receipt.get(counter) or 0)) + 1
            except TypeError, ValueError:
                attempts = 1
            if wait_seconds is not None and receipt.get("cancel_requested"):
                return False
            if max_waits is not None and attempts > max_waits:
                return False
            delay = (
                min(60, 2 ** min(attempts, 5)) if wait_seconds is None else wait_seconds
            )
            receipt.update(
                {
                    "status": "queued",
                    "phase": "waiting_for_coach_slot"
                    if wait_seconds is None
                    else "waiting_for_data",
                    "retry_reason": reason,
                    counter: attempts,
                    "retry_after": time.time() + delay,
                }
            )
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
        return True

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

    def turn_open(self, client_turn_id: str) -> bool:
        """Report whether the turn may still act: its command is queued or running.

        A turn released as stale (or finished by recovery) is `completed`; a worker
        that is still running it must stop executing tools.
        """
        with self._database_lock, self._database_manager().unit_of_work() as db:
            row = db.execute(
                "SELECT status FROM coach_commands WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
        return bool(row and row["status"] in {"queued", "running"})

    def record_failed_attempt(self, client_turn_id: str) -> int:
        """Count a failure that escaped the job's own error handling."""
        with self._database_lock, self._database_manager().unit_of_work() as db:
            row = db.execute(
                SELECT_RECEIPT_SQL,
                (client_turn_id,),
            ).fetchone()
            if not row:
                return 0
            receipt = command_receipt(row.get("receipt"))
            try:
                attempts = max(0, int(receipt.get("failed_attempts") or 0)) + 1
            except TypeError, ValueError:
                attempts = 1
            receipt["failed_attempts"] = attempts
            db.execute(
                "UPDATE coach_commands SET receipt=?, updated_at=? "
                "WHERE client_turn_id=? AND status IN ('queued', 'running')",
                (
                    json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
                    self._utc_now(),
                    client_turn_id,
                ),
            )
        return attempts

    def cancel_requested(self, client_turn_id: str) -> bool:
        """Read a persisted cancel flag before a claimed worker resumes."""
        with self._database_lock, self._database_manager().unit_of_work() as db:
            row = db.execute(
                SELECT_RECEIPT_SQL,
                (client_turn_id,),
            ).fetchone()
        return bool(row and command_receipt(row["receipt"]).get("cancel_requested"))

    def merge_receipt(self, client_turn_id: str, updates: dict[str, Any]) -> None:
        """Write only the changed top-level keys of a queued/running command.

        ``json_set`` stores each key in place, so a progress step does not decode
        and re-encode the receipt's other, possibly large, values.
        """
        if not updates:
            return
        paths = ", ".join("?, json(?)" for _ in updates)
        values: list[str] = []
        for key, value in updates.items():
            values.append("$." + json.dumps(str(key)))
            values.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        with self._database_lock, self._database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE coach_commands SET receipt=json_set("
                "CASE WHEN json_valid(receipt) AND json_type(receipt)='object' "
                f"THEN receipt ELSE '{{}}' END, {paths}), updated_at=? "
                "WHERE client_turn_id=? AND status IN ('queued', 'running')",
                (*values, self._utc_now(), client_turn_id),
            )

    def resume_interrupted(self, failures: CoachTurnFailureService) -> int:
        """Recover durable turns after a process restart."""
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
                receipt["status"] = "queued"
                receipt["phase"] = "queued"
                # An older release resumed the provider response; the job is now
                # requested again and only keeps that it had reached OpenAI.
                if receipt.get("openai_response_id"):
                    receipt["openai_reached"] = True
                for key in LEGACY_RESUME_KEYS:
                    receipt.pop(key, None)
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

        if resumed:
            self._wake_event.set()
        return resumed
