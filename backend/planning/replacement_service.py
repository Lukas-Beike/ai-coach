"""Atomic local replacement of a complete structured training plan."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from backend import change_history
from backend.errors import STALE_PLANNING_REVISION_ERROR, AppError
from backend.planning import replacement
from backend.planning.training_plans import COACH_PLAN_CONSTRAINTS_PREFIX


class StructuredTrainingPlanReplacementService:
    """Replace selected local planning rows and plan metadata atomically."""

    def __init__(
        self,
        database_manager: Any,
        planning_state_repository: Any,
        revision_service: Any,
        training_plan_repository: Any,
        key_value_repository: Any,
        calendar_conflict_service: Any,
        planned_unit_service: Any,
        today: Callable[[], date],
        now: Callable[[], str],
        id_factory: Callable[[], Any],
    ) -> None:
        self._database_manager = database_manager
        self._planning_state_repository = planning_state_repository
        self._revision_service = revision_service
        self._training_plan_repository = training_plan_repository
        self._key_value_repository = key_value_repository
        self._calendar_conflict_service = calendar_conflict_service
        self._planned_unit_service = planned_unit_service
        self._today = today
        self._now = now
        self._id_factory = id_factory

    @staticmethod
    def _selected_rows(
        db: Any,
        selected_plan_id: str | None,
        period: dict[str, str],
    ) -> list[dict[str, Any]]:
        return db.execute(
            "SELECT local_id, payload FROM planned_units "
            "WHERE COALESCE(json_extract(payload, '$.archived'), 0) = 0 "
            "AND COALESCE(json_extract(payload, '$.local_deleted'), 0) = 0 "
            "AND (? = '' OR json_extract(payload, '$.plan_id') = ?) "
            "AND (? <> '' OR COALESCE(json_extract(payload, '$.source'), 'coach') IN ('coach', 'library')) "
            "AND substr(COALESCE(json_extract(payload, '$.date'), ''), 1, 10) BETWEEN ? AND ?",
            (
                selected_plan_id or "",
                selected_plan_id or "",
                selected_plan_id or "",
                period["start"],
                period["end"],
            ),
        ).fetchall()

    @staticmethod
    def _archived_or_deleted_unit_ids(db: Any) -> set[str]:
        rows = db.execute(
            "SELECT local_id FROM planned_units "
            "WHERE COALESCE(json_extract(payload, '$.local_deleted'), 0) = 1 "
            "OR (COALESCE(json_extract(payload, '$.archived'), 0) = 1 "
            "AND (external_id IS NULL OR external_id = ''))"
        ).fetchall()
        return {str(row.get("local_id") or "") for row in rows if row.get("local_id")}

    @staticmethod
    def _superseded_plan_ids(
        db: Any,
        arguments: dict[str, Any],
        selected_plan_id: str | None,
        today: str,
    ) -> set[str]:
        plan_ids = {selected_plan_id} if selected_plan_id else set()
        if selected_plan_id or arguments.get("period"):
            return plan_ids
        rows = db.execute(
            "SELECT id FROM training_plans WHERE status <> 'archived' AND end_date >= ?",
            (today,),
        ).fetchall()
        plan_ids.update(str(row.get("id") or "") for row in rows if row.get("id"))
        return plan_ids

    @staticmethod
    def _parse_existing_entries(
        rows: list[dict[str, Any]],
    ) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], set[str]]:
        entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
        plan_ids: set[str] = set()
        for row in rows:
            try:
                current = json.loads(row.get("payload") or "{}")
            except (TypeError, ValueError) as exc:
                raise AppError(
                    409,
                    "Eine bestehende lokale Planung ist beschädigt.",
                    reason="invalid_plan",
                ) from exc
            if not isinstance(current, dict):
                raise AppError(
                    409,
                    "Eine bestehende lokale Planung ist beschädigt.",
                    reason="invalid_plan",
                )
            entries.append((dict(row), current))
            plan_id = str(current.get("plan_id") or "").strip()
            if plan_id:
                plan_ids.add(plan_id)
        return entries, plan_ids

    @staticmethod
    def _existing_state(
        db: Any,
        arguments: dict[str, Any],
        selected_plan_id: str | None,
        period: dict[str, str],
        today: str,
    ) -> tuple[
        list[dict[str, Any]],
        set[str],
        set[str],
        list[tuple[dict[str, Any], dict[str, Any]]],
    ]:
        rows = StructuredTrainingPlanReplacementService._selected_rows(
            db, selected_plan_id, period
        )
        replace_ids = {
            str(row.get("local_id") or "") for row in rows if row.get("local_id")
        }
        ignored_calendar_ids = replace_ids | (
            StructuredTrainingPlanReplacementService._archived_or_deleted_unit_ids(db)
        )
        superseded_plan_ids = (
            StructuredTrainingPlanReplacementService._superseded_plan_ids(
                db, arguments, selected_plan_id, today
            )
        )
        existing_entries, existing_plan_ids = (
            StructuredTrainingPlanReplacementService._parse_existing_entries(rows)
        )
        superseded_plan_ids.update(existing_plan_ids)
        return rows, ignored_calendar_ids, superseded_plan_ids, existing_entries

    def _validate_calendar(
        self, workouts: list[dict[str, Any]], ignored_calendar_ids: set[str]
    ) -> None:
        for workout in workouts:
            if self._calendar_conflict_service.conflicts(
                {"date": workout["date"]}, ignored_calendar_ids
            ):
                raise AppError(
                    409,
                    f"Für den {workout['date']} existiert bereits eine lokale Kalendereinheit.",
                    reason="plan_date_conflict",
                )

    @staticmethod
    def _archive_entries(
        db: Any,
        existing_entries: list[tuple[dict[str, Any], dict[str, Any]]],
        now: str,
    ) -> None:
        for row, current in existing_entries:
            before = {**current, "sync_status": "local"}
            current.update(
                {"local_deleted": True, "archived": True, "sync_status": "local"}
            )
            db.execute(
                "UPDATE planned_units SET payload=?, sync_state='local', sync_dirty=1, "
                "sync_error=NULL, sync_conflict='', updated_at=? WHERE local_id=?",
                (json.dumps(current, ensure_ascii=False), now, row["local_id"]),
            )
            change_history.record_change(
                db,
                "planned_unit",
                row["local_id"],
                "delete",
                before,
                current,
                source="coach_replacement",
            )

    def _archive_superseded_plans(self, db: Any, plan_ids: set[str], now: str) -> None:
        for plan_id in plan_ids:
            plan = self._training_plan_repository.get(db, plan_id)
            remaining = db.execute(
                "SELECT 1 FROM planned_units WHERE json_extract(payload, '$.plan_id')=? "
                "AND COALESCE(json_extract(payload, '$.archived'), 0)=0 "
                "AND COALESCE(json_extract(payload, '$.local_deleted'), 0)=0 LIMIT 1",
                (plan_id,),
            ).fetchone()
            if remaining or not plan or plan.get("status") == "archived":
                continue
            archived_plan = {**plan, "status": "archived"}
            self._training_plan_repository.update(
                db,
                plan_id,
                archived_plan["name"],
                archived_plan["goal"],
                archived_plan["start_date"],
                archived_plan["end_date"],
                "archived",
                now,
            )
            change_history.record_change(
                db,
                "training_plan",
                plan_id,
                "update",
                plan,
                archived_plan,
                source="coach_replacement",
            )

    def _create_plan(
        self, db: Any, payload: dict[str, Any], plan_name: str, now: str
    ) -> str:
        goal = str(payload.get("goal") or "").strip()[:2000]
        plan_id = str(self._id_factory()) if plan_name else ""
        if not plan_id:
            return plan_id
        sorted_dates = sorted(workout["date"] for workout in payload["workouts"])
        self._training_plan_repository.create(
            db,
            plan_id,
            plan_name,
            goal,
            sorted_dates[0],
            sorted_dates[-1],
            "planned",
            now,
        )
        change_history.record_change(
            db,
            "training_plan",
            plan_id,
            "create",
            None,
            {
                "id": plan_id,
                "name": plan_name,
                "goal": goal,
                "start_date": sorted_dates[0],
                "end_date": sorted_dates[-1],
                "status": "planned",
            },
            source="coach_replacement",
        )
        return plan_id

    def _copy_constraints(
        self,
        db: Any,
        arguments: dict[str, Any],
        plan_id: str,
        superseded_plan_ids: set[str],
    ) -> None:
        if not plan_id:
            return
        constraints = arguments.get("constraints") or list(
            dict.fromkeys(
                item
                for old_id in sorted(superseded_plan_ids)
                for item in json.loads(
                    self._key_value_repository.get(
                        db, COACH_PLAN_CONSTRAINTS_PREFIX + old_id
                    )
                    or "[]"
                )
            )
        )
        if constraints:
            self._key_value_repository.set(
                db,
                COACH_PLAN_CONSTRAINTS_PREFIX + plan_id,
                json.dumps(constraints, ensure_ascii=False),
            )

    def _create_units(
        self,
        db: Any,
        workouts: list[dict[str, Any]],
        plan_id: str,
        plan_name: str,
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        for workout in workouts:
            entry_payload = {**workout, "source": "coach"}
            if plan_id:
                entry_payload.update({"plan_id": plan_id, "plan_name": plan_name})
            created.append(
                self._planned_unit_service.create(
                    entry_payload,
                    db=db,
                    bump_planning_revision=False,
                    change_source="coach_replacement",
                )
            )
        return created

    def replace(
        self, arguments: dict[str, Any], *, selected_plan_id: str | None = None
    ) -> dict[str, Any]:
        payload, expected_revision, workouts, plan_name, today, period = (
            replacement.prepare_structured_plan_replacement(
                arguments, today=self._today()
            )
        )
        with self._database_manager.unit_of_work() as db:
            current_revision = self._planning_state_repository.read(db)
            if expected_revision != current_revision:
                raise AppError(
                    409,
                    STALE_PLANNING_REVISION_ERROR,
                    reason="planning_revision_conflict",
                )
            rows, ignored_calendar_ids, superseded_plan_ids, existing_entries = (
                self._existing_state(db, arguments, selected_plan_id, period, today)
            )
            change_history.reserve_capacity(
                db, len(rows) + len(superseded_plan_ids) + len(workouts) + 1
            )
            self._validate_calendar(workouts, ignored_calendar_ids)
            now = self._now()
            self._archive_entries(db, existing_entries, now)
            self._archive_superseded_plans(db, superseded_plan_ids, now)
            replacement_payload = {**payload, "workouts": workouts}
            plan_id = self._create_plan(db, replacement_payload, plan_name, now)
            self._copy_constraints(db, arguments, plan_id, superseded_plan_ids)
            created = self._create_units(db, workouts, plan_id, plan_name)
            if rows or created or plan_id:
                self._revision_service.bump(db)
            revision = self._revision_service.read(db)
        return {
            "ok": True,
            "status": "replaced",
            "planning_revision": int(revision or current_revision),
            "archived_count": len(rows),
            "created_count": len(created),
            "plan_id": plan_id or None,
            "library_entry_ids": [entry["id"] for entry in created],
        }
