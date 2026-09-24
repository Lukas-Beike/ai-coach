"""Persist a validated Coach clarification request."""

from __future__ import annotations

import json
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError


class CoachClarificationService:
    def __init__(self, database_manager: DatabaseManager, key_values: KeyValueRepository, db_lock: Any) -> None:
        self._database_manager = database_manager
        self._key_values = key_values
        self._db_lock = db_lock

    def save_question(self, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        ids = arguments.get("source_message_ids")
        user_ids = {
            item["id"] for item in context["messages"]
            if item["role"] == "user" and type(item["id"]) is int
        }
        current_user_id = context["current_user_message_id"]
        if (
            not isinstance(ids, list)
            or not 1 <= len(ids) <= 24
            or type(current_user_id) is not int
            or current_user_id not in user_ids
            or current_user_id not in ids
            or any(type(item) is not int or item not in user_ids for item in ids)
        ):
            raise AppError(
                400,
                "Die Rückfrage benötigt den zugehörigen Nutzerauftrag.",
                reason="request_provenance",
            )

        summary, question = arguments.get("summary"), arguments.get("question")
        if (
            not isinstance(summary, str)
            or not summary.strip()
            or len(summary) > 4000
            or not isinstance(question, str)
            or not question.strip()
            or len(question) > 1000
        ):
            raise AppError(
                400,
                "Bitte formuliere eine konkrete Rückfrage zum Auftrag.",
                reason="request_question",
            )

        pending = {
            "summary": summary,
            "question": question,
            "source_message_ids": ids,
            "status": "needs_clarification",
        }
        with self._db_lock, self._database_manager.unit_of_work() as db:
            self._key_values.set(db, "coach_pending_request", json.dumps(pending, ensure_ascii=False))
        return {"ok": True, "status": "needs_clarification", "question": question}
