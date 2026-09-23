"""Transactional local competition use cases."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from backend import change_history
from backend.errors import COMPETITION_NOT_FOUND_ERROR, AppError
from backend.planning import competitions

_REQUIRED_FIELDS = ("name", "event_date", "sport", "priority")
_OPTIONAL_FIELDS = (
    "start_date_local",
    "distance",
    "target",
    "course_profile",
    "notes",
    "description",
)
_MAX_COMPETITIONS = 20


def _competition_id(value: Any, *, required: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        if required:
            raise AppError(400, "Eine lokale Wettkampf-ID ist erforderlich.")
        return ""
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError) as exc:
        raise AppError(400, "Ungültige lokale Wettkampf-ID.") from exc


def _coach_payload(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise AppError(400, "Die Wettkampfdaten müssen als Objekt übergeben werden.")
    moving_time = arguments.get("moving_time_seconds")
    if moving_time == -1:
        moving_time = None
    return {
        "id": str(arguments.get("competition_id") or "").strip(),
        "name": arguments.get("name"),
        "event_date": arguments.get("event_date"),
        "start_date_local": arguments.get("start_date_local"),
        "sport": arguments.get("sport"),
        "priority": arguments.get("priority"),
        "distance": arguments.get("distance"),
        "target": arguments.get("target"),
        "course_profile": arguments.get("course_profile"),
        "notes": arguments.get("notes"),
        "description": arguments.get("description"),
        "moving_time": moving_time,
    }


def _merge_update(
    value: dict[str, Any], arguments: dict[str, Any], existing: dict[str, Any] | None
) -> None:
    if not existing:
        return
    for field in _REQUIRED_FIELDS:
        if field not in arguments:
            value[field] = existing.get(field)
    for field in _OPTIONAL_FIELDS:
        if value.get(field) in (None, "") and existing.get(field) not in (None, ""):
            value[field] = existing[field]
    if value.get("moving_time") is None and existing.get("moving_time") is not None:
        value["moving_time"] = existing["moving_time"]


class CompetitionService:
    """Own local competition reads, writes, conflicts, and transactions."""

    def __init__(
        self,
        database_manager: Any,
        repository: Any,
        now: Callable[[], str],
    ):
        self._database_manager = database_manager
        self._repository = repository
        self._now = now

    def list(self, limit: int | None = None) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 500)) if limit is not None else None
        with self._database_manager.unit_of_work() as db:
            return self._repository.list(db, bounded)

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Restore one competition within the caller's transaction."""
        if target is None:
            self._repository.delete(db, entity_id)
            return None

        normalized = competitions.normalize_competition(
            {**(current or {}), **target, "id": entity_id}
        )
        normalized["id"] = entity_id
        if current:
            self._repository.update_local(db, normalized, self._now())
        else:
            self._repository.create_local(db, normalized, self._now())
        return {**normalized, "sync_state": "local"}

    def save(self, arguments: Any) -> dict[str, Any]:
        now = self._now()
        value = _coach_payload(arguments)
        competition_id = _competition_id(value.get("id"))
        with self._database_manager.unit_of_work() as db:
            existing = (
                self._repository.get(db, competition_id) if competition_id else None
            )
            if competition_id and not existing:
                raise AppError(404, COMPETITION_NOT_FOUND_ERROR)
            _merge_update(value, arguments, existing)
            normalized = competitions.normalize_competition(value)
            if competition_id:
                normalized["id"] = competition_id
            if existing:
                self._repository.update_local(db, normalized, now)
                status = "updated"
            else:
                if self._repository.count(db) >= _MAX_COMPETITIONS:
                    raise AppError(
                        400, "Es können maximal 20 Wettkämpfe gespeichert werden."
                    )
                self._repository.create_local(db, normalized, now)
                status = "created"
            change_history.record_change(
                db,
                "competition",
                normalized["id"],
                "create" if status == "created" else "update",
                existing,
                {**normalized, "sync_state": "local"},
            )
            all_competitions = self._repository.list(db)
            saved = next(
                item for item in all_competitions if item["id"] == normalized["id"]
            )
        return {
            "status": status,
            "competition": saved,
            "competitions": all_competitions,
        }

    def delete(self, competition_id: Any) -> dict[str, Any]:
        now = self._now()
        normalized_id = _competition_id(competition_id, required=True)
        with self._database_manager.unit_of_work() as db:
            row = self._repository.get(db, normalized_id)
            if not row:
                raise AppError(404, COMPETITION_NOT_FOUND_ERROR)
            remote_sync_pending = bool(
                row.get("intervals_event_id") or row.get("external_id")
            )
            if remote_sync_pending:
                self._repository.add_tombstone(
                    db,
                    str(uuid.uuid4()),
                    row.get("intervals_event_id"),
                    row.get("external_id"),
                    now,
                )
            self._repository.delete(db, normalized_id)
            self._repository.unlink_public_event_candidate(db, normalized_id, now)
            change_history.record_change(
                db, "competition", normalized_id, "delete", row, None
            )
            all_competitions = self._repository.list(db)
        return {
            "status": "deleted",
            "competition_id": normalized_id,
            "remote_sync_pending": remote_sync_pending,
            "competitions": all_competitions,
        }

    def resolve_conflict(self, competition_id: Any, strategy: Any) -> dict[str, Any]:
        now = self._now()
        normalized_id = _competition_id(competition_id, required=True)
        selected = str(strategy or "").strip().casefold()
        if selected not in {"keep_local", "adopt_remote"}:
            raise AppError(400, "Ungültige Konfliktstrategie.")
        with self._database_manager.unit_of_work() as db:
            row = self._repository.get(db, normalized_id)
            if not row:
                raise AppError(404, COMPETITION_NOT_FOUND_ERROR)
            if row.get("sync_state") != "conflict" or not row.get("sync_conflict"):
                raise AppError(
                    409,
                    "Für diesen Wettkampf liegt kein offener Synchronisierungskonflikt vor.",
                )
            try:
                conflict = json.loads(row["sync_conflict"])
            except (TypeError, ValueError) as exc:
                raise AppError(
                    409,
                    "Der gespeicherte Synchronisierungskonflikt ist nicht mehr gültig.",
                ) from exc
            remote = conflict.get("remote") if isinstance(conflict, dict) else None
            remote = remote if isinstance(remote, dict) else {}
            if selected == "adopt_remote":
                data = competitions.remote_competition_data(remote)
                if not data or not data.get("intervals_event_id"):
                    raise AppError(
                        409, "Das Remote-Event kann nicht übernommen werden."
                    )
                external_id = str(
                    remote.get("external_id")
                    or row.get("external_id")
                    or competitions.competition_external_id(normalized_id)
                )
                self._repository.resolve_adopt_remote(
                    db, normalized_id, data, external_id, now
                )
            else:
                self._repository.resolve_keep_local(db, normalized_id, now)
            all_competitions = self._repository.list(db)
            saved = next(
                item for item in all_competitions if item["id"] == normalized_id
            )
        return {
            "status": "resolved",
            "strategy": selected,
            "competition": saved,
            "competitions": all_competitions,
        }
