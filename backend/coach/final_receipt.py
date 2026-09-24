"""Atomic final receipt and assistant-message persistence for Coach turns."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend.coach.service import command_receipt
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository, KeyValueRepository
from backend.runtime.events import StateEventBuffer


class CoachFinalReceiptService:
    """Finish a turn once, then publish its state event after the DB commit."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        database_lock: Any,
        chat_repository: ChatRepository,
        key_values: KeyValueRepository,
        events: StateEventBuffer,
        now: Callable[[], str],
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._chat_repository = chat_repository
        self._key_values = key_values
        self._events = events
        self._now = now

    def build(
        self,
        receipt: dict[str, Any],
        *,
        status: str,
        response: dict[str, Any],
        client_turn_id: str,
        command_receipts: list[dict[str, Any]],
        sync_job_ids: list[str],
        intent: dict[str, Any],
        rounds: int,
        failures: list[dict[str, Any]],
        awaiting_clarification: bool,
    ) -> dict[str, Any]:
        final_receipt = {
            **receipt,
            "status": status,
            "awaiting_clarification": awaiting_clarification,
            "response_status": response.get("status") if response.get("status") in {"completed", "incomplete", "failed", "cancelled"} else None,
            "client_turn_id": client_turn_id,
            "command_receipts": command_receipts,
            "sync_job_ids": sync_job_ids,
            "intent": intent,
            "tool_rounds": rounds,
            "pending_operations": sorted({entry["tool"] for entry in failures}),
            "proposed_actions": [entry["result"]["proposed_action"] for entry in command_receipts if entry.get("result", {}).get("proposed_action")],
        }
        for key in (
            "openai_response_id", "pending_tool_outputs", "pending_tool_calls",
            "response_input", "previous_response_id",
        ):
            final_receipt.pop(key, None)
        return final_receipt

    def persist(
        self,
        final_receipt: dict[str, Any],
        *,
        client_turn_id: str,
        command_receipts: list[dict[str, Any]],
        ai_provider: str,
    ) -> dict[str, Any]:
        with self._database_lock, self._database_manager.unit_of_work() as db:
            current_command = db.execute(
                "SELECT status, receipt FROM coach_commands WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            if current_command and current_command["status"] == "completed":
                return command_receipt(current_command["receipt"])

            final_receipt["message"] = self._chat_repository.add(
                db, "assistant", final_receipt["text"], client_turn_id=client_turn_id,
            )
            for step in command_receipts:
                if step["tool"] == "preview_adaptive_replan" and step.get("result", {}).get("ok"):
                    preview_id = step["result"].get("id")
                    preview_row = db.execute(
                        "SELECT payload FROM plan_adjustments WHERE id=? AND status='preview'",
                        (preview_id,),
                    ).fetchone()
                    if preview_row:
                        preview_payload = json.loads(preview_row["payload"])
                        preview_payload["published_message_id"] = final_receipt["message"]["id"]
                        db.execute(
                            "UPDATE plan_adjustments SET payload=? WHERE id=?",
                            (json.dumps(preview_payload, ensure_ascii=False), preview_id),
                        )
            self._key_values.set(db, "last_coach_ai_provider", ai_provider)
            db.execute(
                "UPDATE coach_commands SET status='completed', receipt=?, updated_at=? WHERE client_turn_id=?",
                (
                    json.dumps(
                        {key: value for key, value in final_receipt.items() if key != "text"},
                        ensure_ascii=False,
                    ),
                    self._now(),
                    client_turn_id,
                ),
            )
        final_receipt.pop("text", None)
        self._events.publish(
            "coach",
            {
                "message_id": final_receipt["message"]["id"],
                "role": "assistant",
                "client_turn_id": client_turn_id,
            },
        )
        return final_receipt
