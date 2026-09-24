"""Import and reconcile remote planned calendar units."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.db import DatabaseManager
from backend.planning import planned_units
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.revision import PlanningRevisionService

_DATE_ONLY_PATTERN = r"\d{4}-\d{2}-\d{2}"
_ROW_COLUMNS = (
    "id",
    "local_id",
    "external_id",
    "payload",
    "sync_dirty",
    "sync_state",
    "sync_error",
    "sync_conflict",
    "baseline_hash",
    "last_synced_at",
    "plan_id",
    "revision",
    "tombstone",
    "command_id",
    "created_at",
    "updated_at",
)


def _update_if_unchanged(db: Any, row: Any, sql: str, params: tuple[Any, ...]) -> bool:
    """Use a single compare-and-swap update so a concurrent edit wins."""
    values = dict(row)
    predicates = " AND ".join(f"{column} IS ?" for column in _ROW_COLUMNS)
    result = db.execute(
        f"{sql} AND " + predicates,
        (*params, *(values.get(column) for column in _ROW_COLUMNS)),
    )
    return result.rowcount == 1


class RemotePlannedUnitReconciler:
    """Own the local transaction for provider planned-unit reconciliation."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        planned_unit_service: PlannedUnitService,
        planning_revision_service: PlanningRevisionService,
        now: Callable[[], str],
        today: Callable[[], date],
    ):
        self._database_manager = database_manager
        self._planned_unit_service = planned_unit_service
        self._planning_revision_service = planning_revision_service
        self._now = now
        self._today = today

    def reconcile(
        self,
        events: list[Any] | None,
        *,
        calendar_start: str | None = None,
        calendar_end: str | None = None,
    ) -> dict[str, int]:
        """Import remote workouts without overwriting pending local edits."""
        seen_ids: set[str] = set()
        incoming_dates: list[str] = []
        imported = updated = conflicts = 0
        mutated = False
        now = self._now()
        today = self._today()

        with self._database_manager.unit_of_work() as db:
            for raw_event in events or []:
                if not isinstance(raw_event, dict):
                    continue
                prepared = planned_units.remote_planned_unit_payload(
                    raw_event, today=today
                )
                if prepared is None:
                    continue
                incoming, remote_id, identity = prepared
                seen_ids.add(remote_id)
                incoming_dates.append(str(incoming.get("date") or "")[:10])
                imported_delta, updated_delta, conflict_delta, mutated_delta = (
                    self._upsert_event(db, incoming, remote_id, identity, now)
                )
                imported += imported_delta
                updated += updated_delta
                conflicts += conflict_delta
                mutated = mutated or mutated_delta

            rows = db.execute(
                "SELECT * FROM planned_units WHERE "
                "json_extract(payload, '$.remote_event_id') IS NOT NULL"
            ).fetchall()
            window_start, window_end = self._calendar_window(
                incoming_dates, calendar_start, calendar_end
            )
            missing_conflicts, missing_mutated = self._mark_missing(
                db, rows, seen_ids, window_start, window_end, now
            )
            conflicts += missing_conflicts
            mutated = mutated or missing_mutated
            if mutated:
                self._planning_revision_service.bump(db)

        return {"imported": imported, "updated": updated, "conflicts": conflicts}

    def _upsert_event(
        self,
        db: Any,
        incoming: dict[str, Any],
        remote_id: str,
        identity: str,
        now: str,
    ) -> tuple[int, int, int, bool]:
        current_row = db.execute(
            "SELECT * FROM planned_units WHERE "
            "json_extract(payload, '$.remote_event_id')=? OR external_id=? LIMIT 1",
            (remote_id, identity),
        ).fetchone()
        incoming_hash = planned_units.planned_unit_payload_hash(incoming)
        if not current_row:
            incoming["sync_status"] = "synced"
            self._planned_unit_service.insert(
                db,
                incoming,
                sync_dirty=0,
                sync_state="synced",
                baseline_hash=incoming_hash,
                last_synced_at=now,
            )
            return 1, 0, 0, True

        current, state = planned_units.remote_planned_unit_existing_state(
            current_row, incoming_hash
        )
        if state == "conflict":
            if self._update_conflict(db, current_row, current, incoming, now):
                return 0, 0, 1, True
            return 0, 0, 0, False
        if state != "update":
            return 0, 0, 0, False
        if self._update_clean(
            db, current_row, current, incoming, identity, incoming_hash, now
        ):
            return 0, 1, 0, True
        return 0, 0, 0, False

    @staticmethod
    def _update_conflict(
        db: Any,
        current_row: Any,
        current: dict[str, Any],
        incoming: dict[str, Any],
        now: str,
    ) -> bool:
        conflict = {"type": "remote_changed", "remote": incoming, "detected_at": now}
        current["sync_status"] = "conflict"
        return _update_if_unchanged(
            db,
            current_row,
            "UPDATE planned_units SET sync_state='conflict', sync_dirty=1, "
            "sync_conflict=?, sync_error=NULL, payload=?, updated_at=? WHERE local_id=?",
            (
                json.dumps(conflict, ensure_ascii=False),
                json.dumps(current, ensure_ascii=False),
                now,
                current_row["local_id"],
            ),
        )

    @staticmethod
    def _update_clean(
        db: Any,
        current_row: Any,
        current: dict[str, Any],
        incoming: dict[str, Any],
        identity: str,
        incoming_hash: str,
        now: str,
    ) -> bool:
        incoming["id"] = str(current_row.get("local_id") or incoming["id"])
        for key in (
            "plan_id",
            "plan_name",
            "rationale",
            "archived",
            "private_calendar_adjustment",
        ):
            if current.get(key) is not None:
                incoming[key] = current[key]
        return _update_if_unchanged(
            db,
            current_row,
            "UPDATE planned_units SET external_id=?, payload=?, sync_dirty=0, "
            "sync_state='synced', sync_error=NULL, sync_conflict='', baseline_hash=?, "
            "last_synced_at=?, updated_at=? WHERE local_id=?",
            (
                identity,
                json.dumps({**incoming, "sync_status": "synced"}, ensure_ascii=False),
                incoming_hash,
                now,
                now,
                current_row["local_id"],
            ),
        )

    @staticmethod
    def _calendar_window(
        incoming_dates: list[str],
        calendar_start: str | None,
        calendar_end: str | None,
    ) -> tuple[str | None, str | None]:
        valid_dates = [
            value for value in incoming_dates if re.fullmatch(_DATE_ONLY_PATTERN, value)
        ]
        start_value = str(calendar_start or "")[:10]
        end_value = str(calendar_end or "")[:10]
        if re.fullmatch(_DATE_ONLY_PATTERN, start_value):
            window_start = start_value
        else:
            window_start = min(valid_dates) if valid_dates else None
        if re.fullmatch(_DATE_ONLY_PATTERN, end_value):
            window_end = end_value
        else:
            window_end = max(valid_dates) if valid_dates else None
        return window_start, window_end

    @staticmethod
    def _mark_missing(
        db: Any,
        rows: list[Any],
        seen_ids: set[str],
        window_start: str | None,
        window_end: str | None,
        now: str,
    ) -> tuple[int, bool]:
        conflicts = 0
        mutated = False
        for row in rows:
            conflict_delta, row_mutated = RemotePlannedUnitReconciler._mark_missing_row(
                db, row, seen_ids, window_start, window_end, now
            )
            conflicts += conflict_delta
            mutated = mutated or row_mutated
        return conflicts, mutated

    @staticmethod
    def _mark_missing_row(
        db: Any,
        row: Any,
        seen_ids: set[str],
        window_start: str | None,
        window_end: str | None,
        now: str,
    ) -> tuple[int, bool]:
        try:
            payload = json.loads(row.get("payload") or "{}")
        except (TypeError, ValueError):
            return 0, False
        remote_id = str(payload.get("remote_event_id") or "")
        row_date = str(payload.get("date") or "")[:10]
        if (
            not remote_id
            or remote_id in seen_ids
            or not window_start
            or not window_end
            or not (window_start <= row_date <= window_end)
        ):
            return 0, False
        state = str(row.get("sync_state") or "synced")
        if state == "synced":
            payload["sync_status"] = "remote_missing"
            updated = _update_if_unchanged(
                db,
                row,
                "UPDATE planned_units SET sync_state='remote_missing', sync_dirty=0, "
                "payload=?, updated_at=? WHERE local_id=?",
                (json.dumps(payload, ensure_ascii=False), now, row["local_id"]),
            )
            return 0, updated
        if state not in {"local", "sync_error"}:
            return 0, False

        payload["sync_status"] = "conflict"
        conflict = {"type": "remote_missing", "detected_at": now}
        updated = _update_if_unchanged(
            db,
            row,
            "UPDATE planned_units SET sync_state='conflict', sync_dirty=1, "
            "sync_conflict=?, payload=?, updated_at=? WHERE local_id=?",
            (
                json.dumps(conflict, ensure_ascii=False),
                json.dumps(payload, ensure_ascii=False),
                now,
                row["local_id"],
            ),
        )
        return int(updated), updated
