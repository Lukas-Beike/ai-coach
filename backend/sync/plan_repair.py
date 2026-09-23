"""Prepare and atomically authorize a complete local plan repair manifest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from typing import Any

from backend.db import DatabaseManager
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.planning import workouts as planning_workouts
from backend.sync.authority import PlanningAuthorityService

_REPAIR_REQUEST_ERROR = (
    "Reparatur-Sync braucht einen vollstaendigen zukuenftigen Zeitraum."
)
_REVISION_CONFLICT = (
    "Lies die aktuelle Planung vor der vollstaendigen Reparatur erneut."
)
_SELECTION_CONFLICT = (
    "Die Reparaturauswahl umfasst nicht den vollstaendigen Zeitraum. Nutze die aktuelle expected_revision ohne entries fuer das komplette serverseitige Manifest."
)
_STALE_SELECTION = (
    "Die ausgewaehlte Planung wurde geaendert. Lies den aktuellen Stand erneut."
)


@dataclass
class PreparedRepairManifest:
    period: dict[str, str]
    entries: list[dict[str, str]]
    expected_revision: Any
    revision_snapshot: int
    supplied_entries: list[dict[str, Any]] | None
    required_scope_groups: tuple[tuple[str, ...], ...]


class PlanRepairManifestService:
    """Own read-only repair selection and its atomic local-authority step."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        planning_authority_service: PlanningAuthorityService,
    ) -> None:
        self._database_manager = database_manager
        self._authority = planning_authority_service

    @staticmethod
    def _period(intent: dict[str, Any]) -> dict[str, str]:
        period = intent.get("_repair_period")
        if not isinstance(period, dict) or intent.get("_sync_all_pending"):
            raise AppError(400, _REPAIR_REQUEST_ERROR, reason="request_sync")
        start, end = period.get("start"), period.get("end")
        try:
            start_day = date.fromisoformat(start)
            end_day = date.fromisoformat(end)
        except (TypeError, ValueError) as exc:
            raise AppError(400, _REPAIR_REQUEST_ERROR, reason="request_sync") from exc
        if start_day.isoformat() != start or end_day.isoformat() != end or start_day > end_day:
            raise AppError(400, _REPAIR_REQUEST_ERROR, reason="request_sync")
        return {"start": start, "end": end}

    @staticmethod
    def _rows(db: Any, period: dict[str, str]) -> list[dict[str, Any]]:
        return db.execute(
            "SELECT local_id, payload FROM planned_units "
            "WHERE substr(COALESCE(json_extract(payload, '$.date'), ''), 1, 10) BETWEEN ? AND ? "
            "ORDER BY local_id",
            (period["start"], period["end"]),
        ).fetchall()

    @staticmethod
    def _entries(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "library_workout_id": row["local_id"],
                "expected_payload_hash": planning_library.library_payload_hash(row["payload"]),
            }
            for row in rows
        ]

    @staticmethod
    def _revision(db: Any) -> int:
        row = db.execute("SELECT revision FROM planning_state WHERE id=1").fetchone()
        return int((row or {}).get("revision") or 0)

    def prepare(
        self, arguments: dict[str, Any], intent: dict[str, Any]
    ) -> PreparedRepairManifest:
        period = self._period(intent)
        with self._database_manager.reader() as db:
            rows = self._rows(db, period)
            entries = self._entries(rows)
            current_revision = self._revision(db)

        supplied = arguments.get("entries")
        if supplied is None:
            expected_revision = arguments.get("expected_revision")
            supplied_entries = None
            groups = (("local_plan",),)
        else:
            selected = planning_library.library_bulk_request_entries(
                supplied, require_hash=True
            )
            if {item["library_workout_id"] for item in selected} != {
                row["local_id"] for row in rows
            }:
                raise AppError(409, _SELECTION_CONFLICT, reason="incomplete_repair_selection")
            supplied_entries = selected
            expected_revision = None
            groups = tuple(
                (f"planned_unit:{entry['library_workout_id']}", f"library_workout:{entry['library_workout_id']}")
                for entry in entries
            )

        return PreparedRepairManifest(
            period, entries, expected_revision, current_revision, supplied_entries, groups
        )

    def execute(self, prepared: PreparedRepairManifest) -> list[dict[str, str]]:
        with self._database_manager.unit_of_work() as db:
            rows = self._rows(db, prepared.period)
            current_entries = self._entries(rows)
            current_revision = self._revision(db)
            if prepared.supplied_entries is None and (
                type(prepared.expected_revision) is not int
                or prepared.expected_revision != current_revision
                or current_revision != prepared.revision_snapshot
            ):
                raise AppError(409, _REVISION_CONFLICT, reason="planning_revision_conflict")
            if current_entries != prepared.entries:
                raise AppError(409, _STALE_SELECTION, reason="planning_revision_conflict")
            if prepared.supplied_entries is not None:
                selected_hashes = {
                    entry["library_workout_id"]: entry["expected_payload_hash"]
                    for entry in prepared.supplied_entries
                }
                if any(
                    selected_hashes.get(entry["library_workout_id"])
                    != entry["expected_payload_hash"]
                    for entry in current_entries
                ):
                    raise AppError(409, _STALE_SELECTION, reason="planning_revision_conflict")

            for row in rows:
                workout = json.loads(row["payload"])
                if not workout.get("archived") and not workout.get("local_deleted"):
                    planning_workouts.validate_workout_description(workout)

            if rows:
                self._authority.mark_planning_authoritative(
                    [row["local_id"] for row in rows]
                )
            refreshed = []
            for entry in prepared.entries:
                row = db.execute(
                    "SELECT payload FROM planned_units WHERE local_id=?",
                    (entry["library_workout_id"],),
                ).fetchone()
                if not row:
                    raise AppError(409, _STALE_SELECTION, reason="planning_revision_conflict")
                refreshed.append(
                    {
                        "library_workout_id": entry["library_workout_id"],
                        "expected_payload_hash": planning_library.library_payload_hash(row["payload"]),
                    }
                )
            return refreshed
