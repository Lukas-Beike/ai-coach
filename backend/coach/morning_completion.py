"""Persist the completed morning Coach job and its quick-action receipt."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from backend.coach.service import command_receipt
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository


class MorningCoachJobCompletionService:
    """Own completion markers and quick-action projection for morning jobs."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        database_lock: threading.RLock,
        key_values: KeyValueRepository,
        quick_actions_service: Callable[[], Any],
        local_now: Callable[[], datetime],
        utc_now: Callable[[], str],
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._quick_actions_service = quick_actions_service
        self._local_now = local_now
        self._utc_now = utc_now

    def complete(self, client_turn_id: str) -> dict[str, Any] | None:
        with self._database_lock, self._database_manager.unit_of_work() as db:
            self._key_values.set(
                db, "morning_checkin_date", self._local_now().date().isoformat()
            )
            self._key_values.set(db, "morning_checkin_status", "ready")

        quick_actions = self._quick_actions_service().state()

        with self._database_lock, self._database_manager.unit_of_work() as db:
            row = db.execute(
                "SELECT receipt FROM coach_commands WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            completed_receipt = command_receipt(row["receipt"] if row else None)
            completed_receipt["coach_quick_actions"] = quick_actions
            db.execute(
                "UPDATE coach_commands SET receipt=?, updated_at=? "
                "WHERE client_turn_id=? AND status='completed'",
                (
                    json.dumps(
                        completed_receipt, ensure_ascii=False, separators=(",", ":")
                    ),
                    self._utc_now(),
                    client_turn_id,
                ),
            )
        return completed_receipt
