"""Persist the completed morning Coach job and its quick-action receipt."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from backend.coach.service import command_receipt
from backend.db import coach_store
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
            row = coach_store.command_row(db, client_turn_id)
            self._key_values.set(db, "morning_checkin_date", self._checkin_date(row))
            self._key_values.set(db, "morning_checkin_status", "ready")

        quick_actions = self._quick_actions_service().state()

        with self._database_lock, self._database_manager.unit_of_work() as db:
            row = coach_store.command_row(db, client_turn_id)
            completed_receipt = command_receipt(row["receipt"] if row else None)
            completed_receipt["coach_quick_actions"] = quick_actions
            coach_store.write_command(
                db,
                client_turn_id,
                completed_receipt,
                self._utc_now(),
                only=("completed",),
            )
        return completed_receipt

    def _checkin_date(self, row: Any) -> str:
        """The local day the check-in was prepared for; today without one."""
        prepared = command_receipt(row["receipt"] if row else None).get(
            "morning_checkin_date"
        )
        try:
            return date.fromisoformat(str(prepared)).isoformat()
        except ValueError:
            return self._local_now().date().isoformat()
