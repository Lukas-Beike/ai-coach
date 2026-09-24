"""Lookup prior structured Coach tool-call results without mutating receipts."""

from __future__ import annotations

from typing import Any

from backend.db.manager import DatabaseManager
from backend.errors import AppError

SELECT_PLANNING_REVISION_SQL = "SELECT revision FROM planning_state WHERE id=1"


class CoachStructuredToolReplayService:
    """Resolve call-ID/effect replays against the current durable plan state."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        database_lock: Any,
        read_only_tools: frozenset[str],
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._read_only_tools = read_only_tools

    def lookup(
        self,
        metadata: dict[str, Any],
        command_receipts: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        call_id = metadata["call_id"]
        name = metadata["name"]
        effect_key = metadata["effect_key"]
        cached = next((entry for entry in command_receipts if entry.get("call_id") == call_id), None)
        if cached and cached.get("effect_key") != effect_key:
            raise AppError(409, "Der wiederholte Werkzeugaufruf wurde verändert.", reason="tool_call_conflict")
        if cached is None and name not in self._read_only_tools:
            cached = next(
                (entry for entry in command_receipts if entry.get("effect_key") == effect_key and entry.get("result", {}).get("ok")),
                None,
            )
        if cached and name == "stage_training_plan" and cached.get("result", {}).get("ok"):
            with self._database_lock, self._database_manager.unit_of_work() as db:
                row = db.execute(
                    "SELECT status, base_revision FROM coach_plan_artifacts WHERE id=?",
                    (cached["result"].get("artifact_id"),),
                ).fetchone()
                revision = db.execute(SELECT_PLANNING_REVISION_SQL).fetchone()["revision"]
            if not row or (row["status"] == "draft" and row["base_revision"] != revision):
                return None
        return cached
