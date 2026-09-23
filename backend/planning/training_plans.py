"""Transactional local training-plan metadata use cases."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import date
from typing import Any

from backend import change_history
from backend.errors import AppError

COACH_PLAN_CONSTRAINTS_PREFIX = "coach_plan_constraints:"
TRAINING_PLAN_STATUS_ALIASES = {
    "entwurf": "draft",
    "geplant": "planned",
    "aktiv": "active",
    "abgeschlossen": "completed",
    "archiviert": "archived",
    "abgebrochen": "cancelled",
    "pausiert": "paused",
}
TRAINING_PLAN_STATUSES = frozenset(
    {"draft", "planned", "active", "completed", "archived", "cancelled", "paused"}
)


def _member_dates(db: Any, plan_id: str) -> list[str]:
    rows = db.execute(
        "SELECT payload FROM planned_units "
        "WHERE json_extract(payload, '$.plan_id') = ? "
        "AND COALESCE(json_extract(payload, '$.archived'), 0) = 0 "
        "AND COALESCE(json_extract(payload, '$.local_deleted'), 0) = 0",
        (plan_id,),
    ).fetchall()
    dates: list[str] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError, KeyError):
            payload = {}
        if isinstance(payload, dict) and str(payload.get("date") or "")[:10]:
            dates.append(str(payload["date"])[:10])
    return dates


def _candidate(current: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    status = (
        str(values.get("status") or current.get("status") or "planned")
        .strip()
        .casefold()
    )
    candidate = {
        "id": current["id"],
        "name": str(values.get("name") or current.get("name") or "").strip()[:200],
        "goal": str(values.get("goal") or current.get("goal") or "").strip()[:2000],
        "start_date": str(
            values.get("start_date") or current.get("start_date") or ""
        ).strip(),
        "end_date": str(
            values.get("end_date") or current.get("end_date") or ""
        ).strip(),
        "status": TRAINING_PLAN_STATUS_ALIASES.get(status, status),
    }
    if not candidate["name"]:
        raise AppError(400, "Ein Trainingsplan benötigt einen Namen.")
    if candidate["status"] not in TRAINING_PLAN_STATUSES:
        raise AppError(400, "Ungültiger Trainingsplanstatus.")
    try:
        start = date.fromisoformat(candidate["start_date"])
        end = date.fromisoformat(candidate["end_date"])
    except ValueError as exc:
        raise AppError(
            400, "Start- und Enddatum müssen das Format JJJJ-MM-TT haben."
        ) from exc
    if start > end:
        raise AppError(400, "Das Startdatum darf nicht nach dem Enddatum liegen.")
    return candidate


class TrainingPlanService:
    """Own training-plan metadata reads, writes, bounds, and transactions."""

    def __init__(
        self,
        database_manager: Any,
        repository: Any,
        key_values: Any,
        revisions: Any,
        event_buffer: Any,
        now: Any,
    ):
        self._database_manager = database_manager
        self._repository = repository
        self._key_values = key_values
        self._revisions = revisions
        self._event_buffer = event_buffer
        self._now = now

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._database_manager.unit_of_work() as db:
            plans = self._repository.list(db, limit)
            for plan in plans:
                value = self._key_values.get(
                    db, COACH_PLAN_CONSTRAINTS_PREFIX + plan["id"]
                )
                plan["constraints"] = json.loads(value or "[]")
            return plans

    def update(self, plan_id: Any, values: Any) -> dict[str, Any]:
        normalized_id = self._normalize_id(plan_id)
        if not isinstance(values, dict):
            raise AppError(400, "Der Trainingsplan muss als Objekt gesendet werden.")
        action = str(values.get("action") or "update").strip().casefold()
        with self._database_manager.unit_of_work() as db:
            current = self._repository.get(db, normalized_id)
            if not current:
                raise AppError(404, "Trainingsplan nicht gefunden.")
            if action == "delete":
                self._repository.delete(db, normalized_id)
                change_history.record_change(
                    db, "training_plan", normalized_id, "delete", current, None
                )
                self._revisions.bump(db)
                result = {
                    "status": "deleted",
                    "plan_id": normalized_id,
                    "plan": None,
                }
            elif action == "update":
                result = self._update(db, normalized_id, current, values)
            else:
                raise AppError(400, "Unbekannte Aktion für den Trainingsplan.")
        self._event_buffer.publish("coach", {"status": "changed"})
        return result

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Restore audited plan metadata inside the caller-owned transaction."""
        if target is None:
            self._repository.delete(db, entity_id)
            return None
        if current:
            restored = {**current, **target}
            self._repository.update(
                db,
                entity_id,
                restored["name"],
                restored.get("goal") or "",
                restored["start_date"],
                restored["end_date"],
                restored["status"],
                self._now(),
            )
            return restored
        now = self._now()
        self._repository.create(
            db,
            entity_id,
            target.get("name", ""),
            target.get("goal", ""),
            target.get("start_date", ""),
            target.get("end_date", ""),
            target.get("status", "draft"),
            now,
        )
        return dict(target)

    def _update(
        self,
        db: Any,
        plan_id: str,
        current: dict[str, Any],
        values: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = _candidate(current, values)
        updated_at = self._now()
        self._repository.update(
            db,
            plan_id,
            candidate["name"],
            candidate["goal"],
            candidate["start_date"],
            candidate["end_date"],
            candidate["status"],
            updated_at,
        )
        updated = {**current, **candidate, "updated_at": updated_at}
        change_history.record_change(
            db, "training_plan", plan_id, "update", current, updated
        )
        self._revisions.bump(db)
        return {"status": "updated", "plan_id": plan_id, "plan": updated}

    def update_bounds(self, db: Any, plan_ids: Iterable[str]) -> None:
        for plan_id in sorted(set(plan_ids)):
            plan = self._repository.get(db, plan_id)
            member_dates = _member_dates(db, plan_id)
            if not plan or not member_dates:
                continue
            start, end = min(member_dates), max(member_dates)
            if plan.get("start_date") == start and plan.get("end_date") == end:
                continue
            updated_at = self._now()
            updated_plan = {
                **plan,
                "start_date": start,
                "end_date": end,
                "updated_at": updated_at,
            }
            self._repository.update(
                db,
                plan_id,
                updated_plan["name"],
                updated_plan.get("goal") or "",
                start,
                end,
                updated_plan.get("status") or "planned",
                updated_at,
            )
            change_history.record_change(
                db,
                "training_plan",
                plan_id,
                "update",
                plan,
                updated_plan,
                source="coach_apply",
            )

    @staticmethod
    def _normalize_id(value: Any) -> str:
        try:
            return str(uuid.UUID(str(value or "").strip()))
        except (ValueError, AttributeError) as exc:
            raise AppError(400, "Ungültige Trainingsplan-ID.") from exc
