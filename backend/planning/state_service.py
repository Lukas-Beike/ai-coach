"""Read-only structured training-state projection and cursor paging."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.errors import AppError
from backend.http_api.pagination import (
    api_page_limit,
    decode_page_cursor,
    encode_page_cursor,
)
from backend.planning import library as planning_library

STRUCTURED_TRAINING_STATE_PAGE_LIMIT = 366


class StructuredTrainingStateService:
    """Read local planning state and its bounded, revision-bound page."""

    def __init__(
        self,
        database_manager: Any,
        planning_state_repository: Any,
        competition_service: Any,
        training_plan_service: Any,
        artifact_refs: Callable[[], list[dict[str, Any]]],
        jobs_state: Callable[[], list[dict[str, Any]]],
        today: Callable[[], date],
    ):
        self._database_manager = database_manager
        self._planning_state_repository = planning_state_repository
        self._competition_service = competition_service
        self._training_plan_service = training_plan_service
        self._artifact_refs = artifact_refs
        self._jobs_state = jobs_state
        self._today = today

    @staticmethod
    def _after_key(
        decoded: Any,
        cursor: Any,
        revision_number: int,
        include_inactive: bool,
        today: str,
    ) -> list[str]:
        if cursor and (
            not isinstance(decoded, dict)
            or not isinstance(decoded.get("key"), list)
            or len(decoded["key"]) != 3
            or not all(isinstance(value, str) for value in decoded["key"])
        ):
            raise AppError(
                400, "Ungueltiger Planungscursor.", reason="invalid_page_cursor"
            )
        if decoded and (
            decoded.get("revision") != revision_number
            or decoded.get("include_inactive") != include_inactive
            or decoded.get("today") != today
        ):
            raise AppError(
                409,
                "Die Planung hat sich waehrend des Lesens geaendert. Alle Seiten erneut lesen.",
                reason="planning_revision_conflict",
            )
        return decoded["key"] if decoded else ["", "", ""]

    @staticmethod
    def _target_ref(row: Any, *, planned: bool) -> dict[str, Any] | None:
        try:
            payload = json.loads(row.get("payload") or "{}")
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        return {
            "local_id": str(row.get("local_id") or ""),
            "name": str(payload.get("name") or "")[:200],
            "sport": str(payload.get("sport") or payload.get("type") or "")[:80],
            "date": str(payload.get("date") or "")[:10] or None,
            "archived": bool(payload.get("archived")),
            "local_deleted": bool(payload.get("local_deleted")) if planned else False,
            "sync_status": str(
                row.get("sync_state") or payload.get("sync_status") or "local"
            ),
            "expected_payload_hash": planning_library.library_payload_hash(
                row.get("payload")
            ),
        }

    @staticmethod
    def _page(
        planned_rows: list[Any],
        *,
        page_size: int,
        revision_number: int,
        include_inactive: bool,
        today: str,
    ) -> tuple[list[Any], dict[str, Any]]:
        has_more = len(planned_rows) > page_size
        page_rows = planned_rows[:page_size]
        next_cursor = (
            encode_page_cursor(
                {
                    "revision": revision_number,
                    "include_inactive": include_inactive,
                    "today": today,
                    "key": [
                        page_rows[-1]["plan_date"],
                        page_rows[-1]["sort_name"],
                        page_rows[-1]["local_id"],
                    ],
                }
            )
            if has_more
            else None
        )
        return page_rows, {
            "has_more": has_more,
            "next_cursor": next_cursor,
            "limit": page_size,
        }

    def read(
        self,
        *,
        include_inactive: bool = False,
        cursor: Any = None,
        limit: Any = None,
    ) -> dict[str, Any]:
        today = self._today().isoformat()
        page_size = api_page_limit(
            limit,
            STRUCTURED_TRAINING_STATE_PAGE_LIMIT,
            STRUCTURED_TRAINING_STATE_PAGE_LIMIT,
        )
        decoded = decode_page_cursor(cursor)

        with self._database_manager.unit_of_work() as db:
            revision_number = self._planning_state_repository.read(db)
            after = self._after_key(
                decoded, cursor, revision_number, include_inactive, today
            )
            planned_rows = db.execute(
                "SELECT local_id, sync_state, payload, COALESCE(json_extract(payload, '$.date'), '') AS plan_date, "
                "lower(COALESCE(json_extract(payload, '$.name'), '')) AS sort_name FROM planned_units "
                "WHERE (? OR (COALESCE(json_extract(payload, '$.archived'), 0) = 0 "
                "AND COALESCE(json_extract(payload, '$.local_deleted'), 0) = 0)) "
                "AND substr(COALESCE(json_extract(payload, '$.date'), ''), 1, 10) >= ? "
                "AND (COALESCE(json_extract(payload, '$.date'), ''), lower(COALESCE(json_extract(payload, '$.name'), '')), local_id) > (?, ?, ?) "
                "ORDER BY plan_date, sort_name, local_id LIMIT ?",
                (int(include_inactive), today, *after, page_size + 1),
            ).fetchall()
            template_rows = db.execute(
                "SELECT local_id, sync_state, payload FROM workout_library "
                "WHERE json_extract(payload, '$.date') IS NULL "
                "ORDER BY updated_at DESC LIMIT 100"
            ).fetchall()

        page_rows, page = self._page(
            planned_rows,
            page_size=page_size,
            revision_number=revision_number,
            include_inactive=include_inactive,
            today=today,
        )
        return {
            "planning_revision": revision_number,
            "artifact_refs": self._artifact_refs(),
            "competitions": self._competition_service.list(),
            "training_plans": self._training_plan_service.list(100),
            "planned_units": [
                ref
                for row in page_rows
                if (ref := self._target_ref(row, planned=True)) is not None
            ],
            "planned_units_page": page,
            "training_templates": [
                ref
                for row in template_rows
                if (ref := self._target_ref(row, planned=False)) is not None
            ],
            "jobs": self._jobs_state(),
        }
