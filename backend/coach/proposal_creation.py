"""Create local Coach action previews and approval manifests."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from typing import Any

from backend.activities.duplicates import (
    latest_wahoo_garmin_duplicate,
    validate_duplicate_delete,
)
from backend.athlete.local_date import LocalDate
from backend.coach.proposal_models import (
    COACH_ACTION_TTL_SECONDS,
    _preview_nutrient,
    _utc_now,
    coach_action_hash,
    coach_action_view,
)
from backend.coach.proposal_validation import (
    _validate_local_coach_write,
    remote_coach_write_diff,
    validated_coach_action_preview_input,
)
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.sync.authority import competition_push_manifest
from backend.sync.state import SyncStateRepository

_MAX_REMOTE_APPROVAL_DETAILS = 5000


def _approval_date(value: Any) -> str:
    if value in (None, ""):
        return "Datum unbekannt"
    try:
        return LocalDate.parse(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise AppError(
            409, "Die Vorschau enthält ein ungültiges Datum.", reason="invalid_date"
        ) from exc


class CoachProposalCreationService:
    def __init__(
        self,
        database_manager: DatabaseManager,
        sync_state_repository: SyncStateRepository,
        *,
        ttl_seconds: int = COACH_ACTION_TTL_SECONDS,
        now: Callable[[], float] = time.time,
        utc_now: Callable[[], str] = _utc_now,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
        nutrition_diary_service: Callable[[], Any] | None = None,
        nutrition_meal_library_service: Callable[[], Any] | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._sync_state_repository = sync_state_repository
        self._ttl_seconds = ttl_seconds
        self._now = now
        self._utc_now = utc_now
        self._uuid_factory = uuid_factory
        self._nutrition_diary_service = nutrition_diary_service
        self._nutrition_meal_library_service = nutrition_meal_library_service

    def create(self, values: Any, session_csrf_hash: str) -> dict[str, Any]:
        action_type, target_system, object_ids, diff, payload = (
            validated_coach_action_preview_input(values)
        )
        if action_type == "delete_duplicate_intervals_activity":
            validate_duplicate_delete(
                payload,
                latest_wahoo_garmin_duplicate(
                    self._sync_state_repository.latest_snapshot() or {}
                ),
            )

        proposal_id = str(self._uuid_factory())
        expires_at = self._now() + self._ttl_seconds
        created_at = self._utc_now()
        with self._database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_action_proposals "
                "(id, session_csrf_hash, action_type, target_system, object_ids, "
                "diff, payload, payload_hash, status, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'preview', ?, ?)",
                (
                    proposal_id,
                    str(session_csrf_hash),
                    action_type,
                    target_system,
                    json.dumps(object_ids, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(diff, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    coach_action_hash(payload),
                    expires_at,
                    created_at,
                ),
            )
            row = db.execute(
                "SELECT * FROM coach_action_proposals WHERE id=?", (proposal_id,)
            ).fetchone()
            result = {
                "status": "preview",
                "proposed_action": coach_action_view(dict(row)),
            }
        return result

    def create_remote_write(
        self,
        tool: str,
        arguments: dict[str, Any],
        intent: dict[str, Any],
        *,
        conversation_id: str,
        client_turn_id: str,
        session_csrf_hash: str,
    ) -> dict[str, Any]:
        """Prepare an independently approved Coach remote-write request."""
        if not conversation_id or not client_turn_id or not session_csrf_hash:
            raise AppError(
                403, "Die Remote-Aktion ist nicht an eine Coach-Sitzung gebunden."
            )
        request = intent.get("request") if isinstance(intent, dict) else None
        source_ids = (
            request.get("source_message_ids") if isinstance(request, dict) else None
        )
        if not isinstance(source_ids, list) or not source_ids:
            raise AppError(403, "Die Remote-Aktion hat keinen gültigen Nutzerauftrag.")
        targets = sorted(
            value
            for value in intent.get("authorization_scope", [])
            if isinstance(value, str)
        )
        payload: dict[str, Any] = {
            "tool": tool,
            "arguments": dict(arguments),
            "intent": intent,
            "conversation_id": str(conversation_id)[:160],
            "client_turn_id": str(client_turn_id)[:160],
        }
        payload["arguments"] = _approved_remote_arguments(
            tool,
            arguments,
            intent,
            database_manager=self._database_manager,
            sync_state_repository=self._sync_state_repository,
            nutrition_diary_service=self._nutrition_diary_service,
        )
        approval_manifest = payload["arguments"].get("_approval_manifest")
        approval_details = _remote_write_approval_details(
            tool, payload["arguments"], intent, self._database_manager
        )
        return self.create(
            {
                "action_type": "remote_coach_write",
                "target_system": "intervals",
                "object_ids": {"operation": tool, "targets": targets},
                "diff": remote_coach_write_diff(
                    tool, arguments, intent, approval_manifest, approval_details
                ),
                "payload": payload,
            },
            session_csrf_hash,
        )

    def create_local_write(
        self,
        tool: str,
        arguments: dict[str, Any],
        intent: dict[str, Any],
        *,
        conversation_id: str,
        client_turn_id: str,
        session_csrf_hash: str,
    ) -> dict[str, Any]:
        if not conversation_id or not client_turn_id or not session_csrf_hash:
            raise AppError(
                403, "Die lokale Aktion ist nicht an eine Coach-Sitzung gebunden."
            )
        payload: dict[str, Any] = {
            "tool": tool,
            "arguments": dict(arguments),
            "intent": intent,
            "conversation_id": str(conversation_id)[:160],
            "client_turn_id": str(client_turn_id)[:160],
        }
        _validate_local_coach_write(payload)
        values = arguments["payload"]
        preview_values = self._local_write_preview_values(values, payload)
        diff = [self._local_write_preview_diff(preview_values)]
        return self.create(
            {
                "action_type": "local_coach_write",
                "target_system": "local",
                "object_ids": {"operation": tool, "template_id": values.get("id")},
                "diff": diff,
                "payload": payload,
            },
            session_csrf_hash,
        )

    def _local_write_preview_values(
        self, values: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        preview_values = dict(values)
        preview_values = self._merge_existing_local_write(
            preview_values, values, payload
        )
        self._calculate_local_write_preview(preview_values, values, payload)
        return preview_values

    def _merge_existing_local_write(
        self,
        preview_values: dict[str, Any],
        values: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        template_id = str(values.get("id") or "").strip()
        if template_id and self._nutrition_meal_library_service:
            nutrition = self._nutrition_meal_library_service()
            if payload.get("tool") == "save_nutrition_product":
                try:
                    existing = nutrition.get_product(template_id)
                except AppError:
                    existing = None
            else:
                existing = next(
                    (
                        template
                        for template in nutrition.list_templates()
                        if template.get("id") == template_id
                    ),
                    None,
                )
            if existing:
                preview_values = {**existing, **preview_values}
        return preview_values

    def _calculate_local_write_preview(
        self,
        preview_values: dict[str, Any],
        values: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        if "components" in values:
            if self._nutrition_meal_library_service is None:
                raise AppError(503, "Lebensmitteldatenbank ist nicht verfügbar.")
            calculation = self._nutrition_meal_library_service().calculate_components(
                values["components"]
            )
            preview_values.update(calculation)
            payload["arguments"]["_food_calculation"] = calculation
        elif "food_ingredients" in values:
            if self._nutrition_meal_library_service is None:
                raise AppError(503, "Lebensmitteldatenbank ist nicht verfügbar.")
            calculation = (
                self._nutrition_meal_library_service().food_database.calculate(
                    values["food_ingredients"]
                )
            )
            preview_values.update(calculation)
            payload["arguments"]["_food_calculation"] = calculation
        elif set(values) & {"kcal", "carbs_g", "protein_g", "fat_g"}:
            if self._nutrition_meal_library_service is not None:
                preview_values.update(
                    self._nutrition_meal_library_service().prepare_values(
                        preview_values
                    )
                )

    @staticmethod
    def _local_write_preview_diff(preview_values: dict[str, Any]) -> dict[str, str]:
        diff = {
            "name": preview_values.get("name", ""),
            "description": str(preview_values.get("description") or "")[:500],
            "kcal": _preview_nutrient(preview_values.get("kcal")),
            "carbs": _preview_nutrient(preview_values.get("carbs_g")),
            "protein": _preview_nutrient(preview_values.get("protein_g")),
            "fat": _preview_nutrient(preview_values.get("fat_g")),
        }
        if preview_values.get("nutrition_basis", {}).get("kind") == "database":
            diff["source"] = "; ".join(
                f"{item['source']}: {item['name']}, {item['amount']:g} {item['unit']} (Basis 100 {item['basis_unit']})"
                for item in preview_values["nutrition_basis"]["ingredients"]
            )
        elif preview_values.get("nutrition_basis", {}).get("kind") == "composite":
            diff["source"] = "; ".join(
                f"{item['kind']}: {item['name']}, {item['amount']:g} {item['unit']}"
                for item in preview_values["nutrition_basis"].get("components", [])
            )
        if preview_values.get("basis_amount") and preview_values.get("source"):
            diff["source"] = str(preview_values["source"])
        if preview_values.get("basis_amount") and preview_values.get("basis_unit"):
            diff["basis"] = (
                f"pro {preview_values['basis_amount']:g} {preview_values['basis_unit']}"
            )
        return diff


def _approved_remote_arguments(
    tool: str,
    arguments: dict[str, Any],
    intent: dict[str, Any],
    *,
    database_manager: DatabaseManager,
    sync_state_repository: Any,
    nutrition_diary_service: Callable[[], Any] | None,
) -> dict[str, Any]:
    if tool == "start_intervals_plan_sync":
        return _approved_plan_sync_arguments(arguments, intent, database_manager)
    if tool == "sync_competitions":
        with database_manager.reader() as db:
            return {**arguments, "_approval_manifest": competition_push_manifest(db)}
    if tool == "delete_duplicate_intervals_activity":
        return _duplicate_approval_arguments(arguments, sync_state_repository)
    if tool == "sync_nutrition":
        return _nutrition_approval_arguments(arguments, nutrition_diary_service)
    return dict(arguments)


def _approved_plan_sync_arguments(
    arguments: dict[str, Any], intent: dict[str, Any], database_manager: DatabaseManager
) -> dict[str, Any]:
    approved = dict(arguments)
    if approved.get("repair") is True or approved.get("entries"):
        return approved
    identifiers = [
        str(value)
        for key in ("_created_sync_entry_ids", "_changed_sync_entry_ids")
        for value in intent.get(key) or []
    ]
    all_pending = bool(
        intent.get("_sync_all_pending")
        or (intent.get("request") or {}).get("sync_scope") == "all_pending"
    )
    if not all_pending and not identifiers:
        return approved
    if all_pending:
        query = (
            "SELECT local_id, payload FROM workout_library "
            "WHERE sync_state IN ('local', 'sync_error', 'remote_missing', 'conflict') "
            "UNION ALL SELECT local_id, payload FROM planned_units "
            "WHERE sync_state IN ('local', 'sync_error', 'remote_missing', 'conflict') "
            f"ORDER BY local_id LIMIT {_MAX_REMOTE_APPROVAL_DETAILS + 1}"
        )
        values: tuple[str, ...] = ()
    else:
        placeholders = ",".join("?" for _ in identifiers)
        query = (
            "SELECT local_id, payload FROM workout_library WHERE local_id IN ("
            + placeholders
            + ") UNION ALL SELECT local_id, payload FROM planned_units WHERE local_id IN ("
            + placeholders
            + f") ORDER BY local_id LIMIT {_MAX_REMOTE_APPROVAL_DETAILS + 1}"
        )
        values = (*identifiers, *identifiers)
    with database_manager.reader() as db:
        rows = db.execute(query, values).fetchall()
    _check_approval_row_limit(rows)
    approved["entries"] = [
        {
            "library_workout_id": str(row["local_id"]),
            "expected_payload_hash": hashlib.sha256(
                str(row["payload"] or "").encode("utf-8")
            ).hexdigest(),
        }
        for row in rows
    ]
    return approved


def _remote_write_approval_details(
    tool: str,
    arguments: dict[str, Any],
    intent: dict[str, Any],
    database_manager: DatabaseManager,
) -> list[dict[str, str]]:
    if tool == "start_intervals_plan_sync":
        return _plan_sync_approval_details(arguments, intent, database_manager)
    if tool == "sync_competitions":
        return _competition_approval_details(arguments, database_manager)
    return []


def _plan_sync_approval_details(
    arguments: dict[str, Any], intent: dict[str, Any], database_manager: DatabaseManager
) -> list[dict[str, str]]:
    repair_period = intent.get("_repair_period")
    if arguments.get("repair") is True and isinstance(repair_period, dict):
        with database_manager.reader() as db:
            rows = db.execute(
                "SELECT local_id, payload FROM planned_units "
                "WHERE substr(COALESCE(json_extract(payload, '$.date'), ''), 1, 10) BETWEEN ? AND ? "
                f"ORDER BY local_id LIMIT {_MAX_REMOTE_APPROVAL_DETAILS + 1}",
                (repair_period.get("start"), repair_period.get("end")),
            ).fetchall()
        _check_approval_row_limit(rows)
        return _plan_workout_details(rows)
    entries = arguments.get("entries") or []
    identifiers = [
        str(item.get("local_id") or item.get("library_workout_id") or "")
        for item in entries
        if isinstance(item, dict)
    ]
    if not identifiers and (
        intent.get("_sync_all_pending")
        or (intent.get("request") or {}).get("sync_scope") == "all_pending"
    ):
        query = (
            "SELECT local_id, payload FROM workout_library "
            "WHERE sync_state IN ('local', 'sync_error', 'remote_missing', 'conflict') "
            "UNION ALL SELECT local_id, payload FROM planned_units "
            "WHERE sync_state IN ('local', 'sync_error', 'remote_missing', 'conflict') "
            f"ORDER BY local_id LIMIT {_MAX_REMOTE_APPROVAL_DETAILS + 1}"
        )
        with database_manager.reader() as db:
            rows = db.execute(query).fetchall()
    else:
        if not identifiers:
            identifiers = [
                str(value)
                for key in ("_created_sync_entry_ids", "_changed_sync_entry_ids")
                for value in intent.get(key) or []
            ]
        if not identifiers:
            return []
        placeholders = ",".join("?" for _ in identifiers)
        query = (
            "SELECT local_id, payload FROM workout_library WHERE local_id IN ("
            + placeholders
            + ") UNION ALL SELECT local_id, payload FROM planned_units WHERE local_id IN ("
            + placeholders
            + f") ORDER BY local_id LIMIT {_MAX_REMOTE_APPROVAL_DETAILS + 1}"
        )
        with database_manager.reader() as db:
            rows = db.execute(query, (*identifiers, *identifiers)).fetchall()
    _check_approval_row_limit(rows)
    return _plan_workout_details(rows)


def _competition_approval_details(
    arguments: dict[str, Any], database_manager: DatabaseManager
) -> list[dict[str, str]]:
    manifest = arguments.get("_approval_manifest") or []
    with database_manager.reader() as db:
        return [
            detail for item in manifest if (detail := _competition_detail(db, item))
        ]


def _competition_detail(db: Any, item: dict[str, Any]) -> dict[str, str]:
    if item["type"] == "competition":
        row = db.execute(
            "SELECT * FROM competitions WHERE id=?", (item["id"],)
        ).fetchone()
        if not row:
            return {}
        _validate_manifest_row(
            row, item, "Der Wettkampfbestand hat sich vor der Freigabe geändert."
        )
        return {
            "name": str(row["name"] or "Wettkampf")[:120],
            "date": _approval_date(row["event_date"]),
            "sport": str(row["sport"] or "")[:40],
            "id": str(row["id"]),
        }
    row = db.execute(
        "SELECT * FROM competition_sync_tombstones WHERE id=?", (item["id"],)
    ).fetchone()
    if not row:
        raise AppError(409, "Competition manifest changed before approval.")
    _validate_manifest_row(row, item, "Competition manifest changed before approval.")
    return {
        "name": "Remote-Wettkampfeintrag l\u00f6schen",
        "date": "Freigegebene L\u00f6schmarkierung",
        "id": str(row["intervals_event_id"] or row["id"]),
    }


def _validate_manifest_row(row: Any, item: dict[str, Any], message: str) -> None:
    digest = hashlib.sha256(
        json.dumps(
            dict(row), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    if digest != item["sha256"]:
        raise AppError(409, message)


def _check_approval_row_limit(rows: list[Any]) -> None:
    if len(rows) > _MAX_REMOTE_APPROVAL_DETAILS:
        raise AppError(
            409, "Der Plan enthält zu viele Sync-Einheiten für eine Freigabe."
        )


def _plan_workout_details(rows: list[Any]) -> list[dict[str, str]]:
    details = []
    for row in rows:
        try:
            workout = json.loads(row["payload"] or "{}")
        except TypeError, ValueError:
            workout = {}
        if isinstance(workout, dict):
            details.append(
                {
                    "name": str(workout.get("name") or "Trainingseinheit")[:120],
                    "date": _approval_date(workout.get("date")),
                    "sport": str(workout.get("sport") or "")[:40],
                    "id": str(row["local_id"]),
                }
            )
    return details


def _duplicate_approval_arguments(
    arguments: dict[str, Any], sync_state_repository: Any
) -> dict[str, Any]:
    snapshot = sync_state_repository.latest_snapshot() or {}
    duplicate = latest_wahoo_garmin_duplicate(snapshot)
    if not duplicate:
        raise AppError(409, "Das Wahoo-/Garmin-Duplikat ist nicht mehr aktuell.")
    for field in ("canonical_id", "duplicate_id"):
        requested = arguments.get(field)
        if requested and str(requested) != str(duplicate[field]):
            raise AppError(
                409, "Das angeforderte Duplikat stimmt nicht mit der Vorschau überein."
            )
    manifest = {
        "canonical_id": duplicate["canonical_id"],
        "duplicate_id": duplicate["duplicate_id"],
        "snapshot_synced_at": duplicate.get("snapshot_synced_at"),
        "date": duplicate.get("start_date_local"),
    }
    return {**arguments, "_approval_manifest": manifest}


def _nutrition_approval_arguments(
    arguments: dict[str, Any], nutrition_diary_service: Callable[[], Any] | None
) -> dict[str, Any]:
    if not nutrition_diary_service:
        raise AppError(503, "Ernährungsvorschau ist nicht verfügbar.")
    date_value = str(arguments.get("date") or "").strip()
    limit = arguments.get("pending_limit")
    if bool(date_value) == (limit is not None):
        raise AppError(400, "Wähle ein Datum oder ausstehende Tage.")
    nutrition = nutrition_diary_service()
    manifest = (
        nutrition.approval_manifest(meal_date=date_value)
        if date_value
        else nutrition.approval_manifest(pending_limit=limit)
    )
    return {**arguments, "_approval_manifest": manifest}
