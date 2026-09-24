"""Persist progress and collect outputs for one structured Coach tool round."""

from __future__ import annotations

import json
from typing import Any

from backend.coach.job_store import CoachJobStore


class CoachStructuredToolRoundJournal:
    """Keep durable round progress in CoachJobStore and outputs turn-local."""

    def __init__(self, job_store: CoachJobStore) -> None:
        self._job_store = job_store

    def function_calls(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            item
            for item in response.get("output", [])
            if isinstance(item, dict) and item.get("type") == "function_call"
        ]

    def start_round(
        self, client_turn_id: str, calls: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        pending = [
            {
                "call_id": str(item.get("call_id") or ""),
                "tool": str(item.get("name") or ""),
            }
            for item in calls
        ]
        self._job_store.merge_receipt(
            client_turn_id,
            {
                "phase": "executing_tools",
                "pending_tool_calls": pending,
                "pending_tool_outputs": [],
            },
        )
        return pending

    def record_output(
        self,
        *,
        client_turn_id: str,
        name: str,
        call_id: str,
        result: dict[str, Any],
        outputs: list[dict[str, Any]],
        pending: list[dict[str, str]],
        command_receipts: list[dict[str, Any]],
        question: str,
        cancelled: bool,
    ) -> tuple[str, bool, list[dict[str, str]]]:
        outputs.append(
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result, ensure_ascii=False),
            }
        )
        pending = [entry for entry in pending if entry["call_id"] != call_id]
        self._job_store.merge_receipt(
            client_turn_id,
            {
                "command_receipts": command_receipts,
                "pending_tool_calls": pending,
                "phase": "executing_tools" if pending else "waiting_final_response",
                "pending_tool_outputs": outputs if not pending else [],
            },
        )
        if name == "clarify_coach_request" and result.get("ok"):
            question = result["question"]
        if name == "cancel_coach_request" and result.get("ok"):
            cancelled = True
        return question, cancelled, pending

    def finish_round(self, client_turn_id: str, rounds: int) -> None:
        self._job_store.merge_receipt(client_turn_id, {"tool_rounds": rounds})

    def clear_outputs(self, client_turn_id: str) -> None:
        self._job_store.merge_receipt(client_turn_id, {"pending_tool_outputs": []})
