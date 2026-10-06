"""Session-owned Coach action proposal projection and expiration cleanup."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from backend.activities.duplicate_service import DuplicateActivityService
from backend.activities.duplicates import (
    latest_wahoo_garmin_duplicate,
    validate_duplicate_delete,
)
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.history.undo_service import HistoryUndoService
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.authority import competition_push_manifest
from backend.sync.state import SyncStateRepository

COACH_ACTION_TYPES = {
    "undo_change",
    "delete_duplicate_intervals_activity",
    "remote_coach_write",
    "local_coach_write",
}
REMOTE_COACH_WRITE_TOOLS = frozenset(
    {
        "start_intervals_plan_sync",
        "sync_competitions",
        "delete_duplicate_intervals_activity",
        "sync_nutrition",
        "resolve_training_sync_conflict",
        "apply_adaptive_replan",
    }
)
LOCAL_COACH_WRITE_TOOLS = frozenset(
    {"save_nutrition_template", "save_nutrition_product"}
)
COACH_ACTION_TTL_SECONDS = 600
LOGGER = logging.getLogger("intervals_coach")
_MAX_REMOTE_APPROVAL_DETAILS = 5000


def _preview_nutrient(value: Any) -> str:
    return str(value) if value is not None else "unbekannt"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validated_coach_action_preview_input(
    values: Any,
) -> tuple[
    str, str, dict[str, Any] | list[Any], dict[str, Any] | list[Any], dict[str, Any]
]:
    """Validate proposal input shape, supported action, target, and visible diff."""
    if not isinstance(values, dict):
        raise AppError(400, "Die Aktionsvorschau muss ein Objekt sein.")
    action_type = str(values.get("action_type") or "").strip()
    if action_type not in COACH_ACTION_TYPES:
        raise AppError(400, "Unbekannter Coach-Aktionstyp.")
    target_system = str(values.get("target_system") or "").strip()
    if target_system not in {"local", "intervals", "local+intervals"}:
        raise AppError(400, "Die Aktionsvorschau benötigt ein gültiges Zielsystem.")
    object_ids = values.get("object_ids")
    diff = values.get("diff")
    payload = values.get("payload")
    if (
        not isinstance(object_ids, (dict, list))
        or not isinstance(diff, (dict, list))
        or not isinstance(payload, dict)
    ):
        raise AppError(
            400, "Die Aktionsvorschau benötigt Objekt-IDs, Diff und Payload."
        )
    expected_target = (
        "intervals"
        if action_type
        in {
            "delete_duplicate_intervals_activity",
            "remote_coach_write",
        }
        else "local"
    )
    if action_type == "local_coach_write":
        if target_system != "local" or not diff:
            raise AppError(
                400, "Die lokale Coach-Aktion benÃ¶tigt einen sichtbaren Diff."
            )
        _validate_local_coach_write(payload)
    elif target_system != expected_target or not diff:
        raise AppError(
            400,
            "Die geschuetzte Aktion benoetigt das passende Ziel und einen sichtbaren Diff.",
        )
    if action_type == "remote_coach_write":
        _validate_remote_coach_write(payload)
    return action_type, target_system, object_ids, diff, payload


def _validate_remote_coach_write(payload: dict[str, Any]) -> None:
    tool = payload.get("tool")
    arguments = payload.get("arguments")
    intent = payload.get("intent")
    request = intent.get("request") if isinstance(intent, dict) else None
    scope = intent.get("authorization_scope") if isinstance(intent, dict) else None
    scope_ok = isinstance(scope, list) and "intervals_sync" in scope
    source_ids = (
        request.get("source_message_ids") if isinstance(request, dict) else None
    )
    source_ids_ok = (
        isinstance(source_ids, list)
        and 1 <= len(source_ids) <= 24
        and all(type(value) is int and value > 0 for value in source_ids)
        and len(source_ids) == len(set(source_ids))
    )
    if (
        tool not in REMOTE_COACH_WRITE_TOOLS
        or not isinstance(arguments, dict)
        or not isinstance(intent, dict)
        or intent.get("operation") != tool
        or intent.get("target_system") != "intervals"
        or not isinstance(request, dict)
        or request.get("remote_write") is not True
        or not source_ids_ok
        or not scope_ok
    ):
        raise AppError(
            400, "Die Coach-Aktion ist keine gültige Intervals.icu-Änderung."
        )


def _validate_local_coach_write(payload: dict[str, Any]) -> None:
    tool = payload.get("tool")
    arguments = payload.get("arguments")
    intent = payload.get("intent")
    request = intent.get("request") if isinstance(intent, dict) else None
    scope = intent.get("authorization_scope") if isinstance(intent, dict) else None
    source_ids = (
        request.get("source_message_ids") if isinstance(request, dict) else None
    )
    values = arguments.get("payload") if isinstance(arguments, dict) else None
    product_write = tool == "save_nutrition_product"
    valid_payload = (
        isinstance(values, dict)
        and isinstance(values.get("name"), str)
        and (
            values.get("basis_unit") in {"g", "ml", "portion"}
            if product_write
            else isinstance(values.get("description"), str)
        )
    )
    source_ids_ok = (
        isinstance(source_ids, list)
        and 1 <= len(source_ids) <= 24
        and all(type(value) is int and value > 0 for value in source_ids)
        and len(source_ids) == len(set(source_ids))
    )
    if (
        tool not in LOCAL_COACH_WRITE_TOOLS
        or not isinstance(intent, dict)
        or intent.get("operation") != tool
        or intent.get("target_system") != "local"
        or not isinstance(request, dict)
        or not source_ids_ok
        or not isinstance(scope, list)
        or not ({"local_nutrition", "local_nutrition_product"} & set(scope))
        or (
            product_write
            and isinstance(values, dict)
            and values.get("id")
            and f"nutrition_product:{values.get('id')}" not in scope
        )
        or not valid_payload
    ):
        raise AppError(400, "Die lokale Coach-Aktion ist ungÃ¼ltig.")


REMOTE_WRITE_LABELS = {
    "start_intervals_plan_sync": "Trainingseinheiten mit Intervals.icu synchronisieren",
    "sync_competitions": "Bestätigte Wettkämpfe mit Intervals.icu synchronisieren",
    "delete_duplicate_intervals_activity": "Garmin-Duplikat mit Intervals.icu löschen",
    "sync_nutrition": "Ernährungsdaten mit Intervals.icu synchronisieren",
    "resolve_training_sync_conflict": "Fehlgeschlagenen Intervals.icu-Sync wiederholen",
    "apply_adaptive_replan": "Adaptive Änderung anwenden und Krankheitspause synchronisieren",
}


def remote_coach_write_diff(
    tool: str,
    arguments: dict[str, Any],
    intent: dict[str, Any],
    approval_manifest: Any = None,
    approval_details: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Project the remote effect into a compact, non-sensitive approval summary."""
    name = REMOTE_WRITE_LABELS[tool]
    if tool == "sync_nutrition":
        return _nutrition_approval_diff(name, approval_manifest)
    if tool == "start_intervals_plan_sync":
        return _plan_sync_write_diff(
            {"name": name}, arguments, intent, approval_details or []
        )
    if tool == "sync_competitions" and approval_details:
        return approval_details
    return _remote_write_summary(tool, name, arguments, approval_manifest)


def _remote_write_summary(
    tool: str, name: str, arguments: dict[str, Any], approval_manifest: Any
) -> list[dict[str, str]]:
    entry: dict[str, str] = {"name": name}
    if tool == "resolve_training_sync_conflict":
        entry["date"] = (
            "Synchronisationsauftrag " + str(arguments.get("job_id") or "")[:36]
        )
    elif tool == "delete_duplicate_intervals_activity":
        manifest = approval_manifest if isinstance(approval_manifest, dict) else {}
        entry.update(
            date=str(manifest.get("date") or "")[:10],
            keep=str(manifest.get("canonical_id") or "")[:80],
            delete=str(manifest.get("duplicate_id") or "")[:80],
        )
    elif tool == "apply_adaptive_replan":
        entry["date"] = (
            "Adaptive Vorschau " + str(arguments.get("adjustment_id") or "")[:36]
        )
    return [entry]


def _nutrition_approval_diff(name: str, approval_manifest: Any) -> list[dict[str, str]]:
    entries = approval_manifest if isinstance(approval_manifest, list) else []
    if entries:
        return _nutrition_write_diff(name, entries)
    return [{"name": name, "date": "Keine ausstehenden Tage"}]


def _nutrition_write_diff(
    name: str, manifest: list[dict[str, Any]]
) -> list[dict[str, str]]:
    return [
        {
            "name": name,
            "date": str(item["date"]),
            "kcal": f"{item['total_kcal']} kcal",
            "entries": str(item["entry_count"]),
            **{
                field: f"{item[key]} g"
                for field, key in (
                    ("carbs", "total_carbs_g"),
                    ("protein", "total_protein_g"),
                    ("fat", "total_fat_g"),
                )
                if item.get(key) is not None
            },
        }
        for item in manifest
    ]


def _plan_sync_write_diff(
    entry: dict[str, str],
    arguments: dict[str, Any],
    intent: dict[str, Any],
    details: list[dict[str, str]],
) -> list[dict[str, str]]:
    scope = str((intent.get("request") or {}).get("sync_scope") or "selected")
    entries = arguments.get("entries") or []
    count = len(entries)
    entry["scope"] = scope
    entry["units"] = f"{count} konkret ausgewählte Einheit(en)"
    labels = {
        "selected": entry["units"],
        "all_pending": f"{count} derzeit ausstehende Einheit(en)",
    }
    entry["sport"] = labels.get(
        scope, f"{count} in diesem Auftrag erstellte Einheit(en)"
    )
    dates = sorted(
        {
            str(item["date"])
            for item in entries
            if isinstance(item, dict) and item.get("date")
        }
    )
    if dates:
        entry["date"] = dates[0]
        if len(dates) > 1:
            entry["date"] = f"{dates[0]} bis {dates[-1]}"
    return details or [entry]


def coach_action_hash(payload: Any) -> str:
    """Return the canonical SHA-256 identity used for Coach action payloads."""
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def coach_action_view(row: dict[str, Any]) -> dict[str, Any]:
    """Expose proposal metadata without returning its private action payload."""
    return {
        "id": row["id"],
        "action_type": row["action_type"],
        "target_system": row["target_system"],
        "object_ids": json.loads(row["object_ids"]),
        "diff": json.loads(row["diff"]),
        "payload_hash": row["payload_hash"],
        "expires_at": row["expires_at"],
        "status": row["status"],
    }


def prune_expired_coach_proposals(db: Any, now: float) -> int:
    """Delete expired authorization artifacts, leaving durable plan drafts alone."""
    return db.execute(
        "DELETE FROM coach_action_proposals WHERE expires_at<=?", (now,)
    ).rowcount


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
        nutrition_service: Callable[[], Any] | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._sync_state_repository = sync_state_repository
        self._ttl_seconds = ttl_seconds
        self._now = now
        self._utc_now = utc_now
        self._uuid_factory = uuid_factory
        self._nutrition_service = nutrition_service

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
            nutrition_service=self._nutrition_service,
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
        if template_id and self._nutrition_service:
            nutrition = self._nutrition_service()
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
            if self._nutrition_service is None:
                raise AppError(503, "Lebensmitteldatenbank ist nicht verfuegbar.")
            calculation = self._nutrition_service().calculate_components(
                values["components"]
            )
            preview_values.update(calculation)
            payload["arguments"]["_food_calculation"] = calculation
        elif "food_ingredients" in values:
            if self._nutrition_service is None:
                raise AppError(503, "Lebensmitteldatenbank ist nicht verfügbar.")
            calculation = self._nutrition_service().food_database.calculate(
                values["food_ingredients"]
            )
            preview_values.update(calculation)
            payload["arguments"]["_food_calculation"] = calculation
        elif set(values) & {"kcal", "carbs_g", "protein_g", "fat_g"}:
            if self._nutrition_service is not None:
                preview_values.update(
                    self._nutrition_service()._prepare_values(preview_values)
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
    nutrition_service: Callable[[], Any] | None,
) -> dict[str, Any]:
    if tool == "start_intervals_plan_sync":
        return _approved_plan_sync_arguments(arguments, intent, database_manager)
    if tool == "sync_competitions":
        with database_manager.reader() as db:
            return {**arguments, "_approval_manifest": competition_push_manifest(db)}
    if tool == "delete_duplicate_intervals_activity":
        return _duplicate_approval_arguments(arguments, sync_state_repository)
    if tool == "sync_nutrition":
        return _nutrition_approval_arguments(arguments, nutrition_service)
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
            row, item, "Der Wettkampfbestand hat sich vor der Freigabe geaendert."
        )
        return {
            "name": str(row["name"] or "Wettkampf")[:120],
            "date": str(row["event_date"] or "Datum unbekannt")[:10],
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
            409, "Der Plan enthaelt zu viele Sync-Einheiten fuer eine Freigabe."
        )


def _plan_workout_details(rows: list[Any]) -> list[dict[str, str]]:
    details = []
    for row in rows:
        try:
            workout = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            workout = {}
        if isinstance(workout, dict):
            details.append(
                {
                    "name": str(workout.get("name") or "Trainingseinheit")[:120],
                    "date": str(workout.get("date") or "Datum unbekannt")[:10],
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
                409, "Das angeforderte Duplikat stimmt nicht mit der Vorschau ueberein."
            )
    manifest = {
        "canonical_id": duplicate["canonical_id"],
        "duplicate_id": duplicate["duplicate_id"],
        "snapshot_synced_at": duplicate.get("snapshot_synced_at"),
        "date": duplicate.get("start_date_local"),
    }
    return {**arguments, "_approval_manifest": manifest}


def _nutrition_approval_arguments(
    arguments: dict[str, Any], nutrition_service: Callable[[], Any] | None
) -> dict[str, Any]:
    if not nutrition_service:
        raise AppError(503, "Ernährungsvorschau ist nicht verfügbar.")
    date_value = str(arguments.get("date") or "").strip()
    limit = arguments.get("pending_limit")
    if bool(date_value) == (limit is not None):
        raise AppError(400, "Wähle ein Datum oder ausstehende Tage.")
    nutrition = nutrition_service()
    manifest = (
        nutrition.approval_manifest(meal_date=date_value)
        if date_value
        else nutrition.approval_manifest(pending_limit=limit)
    )
    return {**arguments, "_approval_manifest": manifest}


def _remote_source_message_status(
    message: Any, client_turn_id: str, conversation_id: str, session_key: str
) -> tuple[bool, bool]:
    receipt = json.loads(message["receipt"] or "{}")
    belongs = (
        message["conversation_id"] == conversation_id
        and receipt.get("session_key") == session_key
    )
    return belongs, belongs and message["client_turn_id"] == client_turn_id


class CoachProposalReadService:
    def __init__(
        self,
        database_manager: DatabaseManager,
        *,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._database_manager = database_manager
        self._now = now

    def current(self, session_csrf_hash: str) -> list[dict[str, Any]]:
        if not session_csrf_hash:
            return []
        with self._database_manager.unit_of_work() as db:
            prune_expired_coach_proposals(db, self._now())
            rows = db.execute(
                "SELECT * FROM coach_action_proposals "
                "WHERE session_csrf_hash=? AND status IN ('preview', 'ready') "
                "AND expires_at>? ORDER BY created_at DESC LIMIT 30",
                (session_csrf_hash, self._now()),
            ).fetchall()
            return [coach_action_view(row) for row in rows]


class CoachProposalConfirmationService:
    def __init__(
        self,
        database_manager: DatabaseManager,
        *,
        now: Callable[[], float] = time.time,
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        self._database_manager = database_manager
        self._now = now
        self._token_factory = token_factory

    def confirm(self, proposal_id: Any, session_csrf_hash: str) -> dict[str, Any]:
        normalized_id = str(proposal_id or "").strip()
        if not re.fullmatch(r"[0-9a-f-]{36}", normalized_id):
            raise AppError(400, "Ungültige Aktionsvorschau.")
        token = self._token_factory(32)
        now = self._now()
        with self._database_manager.unit_of_work() as db:
            row = db.execute(
                "SELECT * FROM coach_action_proposals WHERE id=? AND session_csrf_hash=?",
                (normalized_id, str(session_csrf_hash)),
            ).fetchone()
            if not row:
                raise AppError(404, "Aktionsvorschau nicht gefunden.")
            if (
                row["status"] not in {"preview", "ready"}
                or float(row["expires_at"]) <= now
            ):
                raise AppError(
                    409,
                    "Die Aktionsvorschau ist abgelaufen oder wurde bereits bestätigt.",
                )
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            confirmed = db.execute(
                "UPDATE coach_action_proposals SET action_token_hash=?, status='ready' "
                "WHERE id=? AND status IN ('preview', 'ready')",
                (token_hash, normalized_id),
            ).rowcount
            if confirmed != 1:
                raise AppError(409, "Die Aktionsvorschau wurde bereits bestÃ¤tigt.")
            updated = db.execute(
                "SELECT * FROM coach_action_proposals WHERE id=?", (normalized_id,)
            ).fetchone()
            result = {
                "status": "ready",
                "action_token": token,
                "proposed_action": coach_action_view(dict(updated)),
            }
        return result

    def cancel(self, proposal_id: Any, session_csrf_hash: str) -> dict[str, Any]:
        """Revoke an unexecuted approval proposal owned by this session."""
        normalized_id = str(proposal_id or "").strip()
        if not re.fullmatch(r"[0-9a-f-]{36}", normalized_id):
            raise AppError(400, "Ungültige Aktionsvorschau.")
        with self._database_manager.unit_of_work() as db:
            changed = db.execute(
                "UPDATE coach_action_proposals SET status='cancelled', action_token_hash=NULL "
                "WHERE id=? AND session_csrf_hash=? AND status IN ('preview', 'ready')",
                (normalized_id, str(session_csrf_hash)),
            ).rowcount
            if changed != 1:
                raise AppError(409, "Die Aktionsvorschau ist nicht mehr offen.")
        return {"status": "cancelled", "proposal_id": normalized_id}


class CoachProposalExecutionService:
    """Consume a confirmed, session-bound token before dispatching its action."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        duplicate_activity_service: DuplicateActivityService,
        history_undo_service: HistoryUndoService,
        intervals_client_factory: Callable[[], Any],
        maintenance_gate: MaintenanceGate,
        tool_dispatch_service: Callable[[], Any] | None = None,
        *,
        now: Callable[[], float] = time.time,
        utc_now: Callable[[], str] = _utc_now,
    ) -> None:
        self._database_manager = database_manager
        self._duplicate_activity_service = duplicate_activity_service
        self._history_undo_service = history_undo_service
        self._intervals_client_factory = intervals_client_factory
        self._maintenance_gate = maintenance_gate
        self._tool_dispatch_service = tool_dispatch_service
        self._now = now
        self._utc_now = utc_now

    def execute(
        self,
        token: Any,
        session_csrf_hash: str,
        payload_hash: Any = None,
    ) -> dict[str, Any]:
        with self._maintenance_gate.operation():
            return self._execute(token, session_csrf_hash, payload_hash)

    def _execute(
        self,
        token: Any,
        session_csrf_hash: str,
        payload_hash: Any,
    ) -> dict[str, Any]:
        row, action_type, payload = self._load_ready_action(
            token, session_csrf_hash, payload_hash
        )
        validated_context = self._validate_action_before_consume(
            action_type, payload, session_csrf_hash
        )
        self._consume_action(row["id"])
        return self._dispatch_action(
            row, action_type, payload, session_csrf_hash, validated_context
        )

    def _load_ready_action(
        self, token: Any, session_csrf_hash: str, payload_hash: Any
    ) -> tuple[Any, str, dict[str, Any]]:
        raw_token = str(token or "").strip()
        if len(raw_token) < 32:
            raise AppError(400, "Ungültiges Coach-Aktionstoken.")
        now = self._now()
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        with self._database_manager.unit_of_work() as db:
            row = db.execute(
                "SELECT * FROM coach_action_proposals "
                "WHERE action_token_hash=? AND session_csrf_hash=? AND status='ready'",
                (token_hash, str(session_csrf_hash)),
            ).fetchone()
            if not row:
                raise AppError(
                    409,
                    "Das Coach-Aktionstoken ist ungültig, abgelaufen oder bereits verwendet.",
                    reason="proposal_invalid",
                )
            if float(row["expires_at"]) <= now:
                raise AppError(
                    409,
                    "Das Coach-Aktionstoken ist abgelaufen.",
                    reason="proposal_expired",
                )
            if payload_hash is not None and str(payload_hash) != str(
                row["payload_hash"]
            ):
                raise AppError(
                    409,
                    "Der bestätigte Aktions-Payload wurde verändert.",
                    reason="proposal_payload_changed",
                )
            action_type = str(row["action_type"])
            payload = json.loads(row["payload"])
        return row, action_type, payload

    def _validate_action_before_consume(
        self, action_type: str, payload: dict[str, Any], session_csrf_hash: str
    ) -> tuple[str, dict[str, Any], dict[str, Any], str, str] | None:
        """Reject stale provenance before consuming the one-shot token."""
        if action_type in {"remote_coach_write", "local_coach_write"}:
            return self._validate_remote_write_context(payload, session_csrf_hash)
        if action_type not in {"delete_duplicate_intervals_activity", "undo_change"}:
            raise AppError(
                400, "Unbekannte Coach-Aktion.", reason="unknown_coach_action"
            )
        return None

    def _consume_action(self, proposal_id: str) -> None:
        with self._database_manager.unit_of_work() as db:
            consumed = db.execute(
                "UPDATE coach_action_proposals SET status='used', used_at=? WHERE id=? AND status='ready'",
                (self._utc_now(), proposal_id),
            ).rowcount
            if consumed != 1:
                raise AppError(
                    409,
                    "Das Coach-Aktionstoken wurde bereits verwendet.",
                    reason="proposal_used",
                )

    def _dispatch_action(
        self,
        row: Any,
        action_type: str,
        payload: dict[str, Any],
        session_csrf_hash: str,
        validated_context: tuple[str, dict[str, Any], dict[str, Any], str, str] | None,
    ) -> dict[str, Any]:
        if action_type == "delete_duplicate_intervals_activity":
            result = {
                "ok": True,
                **self._duplicate_activity_service.delete(
                    payload, self._intervals_client_factory()
                ),
            }
        elif action_type == "undo_change":
            result = self._history_undo_service.apply(payload)
        elif action_type in {"remote_coach_write", "local_coach_write"}:
            assert validated_context is not None
            try:
                result = self._execute_coach_write(session_csrf_hash, validated_context)
            except AppError:
                if action_type == "local_coach_write":
                    # Local nutrition validation failures have no durable
                    # effect. Keep their proposal available so a conflict is
                    # not misreported as an expired confirmation.
                    with self._database_manager.unit_of_work() as db:
                        db.execute(
                            "UPDATE coach_action_proposals SET status='ready', used_at=NULL "
                            "WHERE id=? AND status='used'",
                            (row["id"],),
                        )
                raise
        else:
            raise AppError(400, "Unbekannte Coach-Aktion.")
        LOGGER.info(
            "Coach action executed",
            extra={
                "event": "coach_action_executed",
                "context": {
                    "action_type": action_type,
                    "target_system": row["target_system"],
                    "proposal_id": row["id"],
                },
            },
        )
        return result

    def _execute_coach_write(
        self,
        session_csrf_hash: str,
        validated_context: tuple[str, dict[str, Any], dict[str, Any], str, str],
    ) -> dict[str, Any]:
        if not self._tool_dispatch_service:
            raise AppError(503, "Die Coach-Aktionsausführung ist nicht verfügbar.")
        tool, arguments, intent, conversation_id, client_turn_id = validated_context
        if tool in LOCAL_COACH_WRITE_TOOLS:
            result = self._tool_dispatch_service().execute(
                tool,
                arguments,
                intent=intent,
                conversation_id=conversation_id,
                client_turn_id=client_turn_id,
                session_csrf_hash=session_csrf_hash,
                sync_job_ids=[],
            )
            return {**result, "ok": True, "status": "applied"}
        sync_job_ids: list[str] = []
        result = self._tool_dispatch_service().execute(
            tool,
            arguments,
            intent=intent,
            conversation_id=conversation_id,
            client_turn_id=client_turn_id,
            session_csrf_hash=session_csrf_hash,
            sync_job_ids=sync_job_ids,
        )
        if sync_job_ids:
            result["sync_job_ids"] = sync_job_ids
        return result

    def _validate_remote_write_context(
        self, payload: dict[str, Any], session_csrf_hash: str
    ) -> tuple[str, dict[str, Any], dict[str, Any], str, str]:
        tool = payload.get("tool")
        arguments = payload.get("arguments")
        intent = payload.get("intent")
        local_write = tool in LOCAL_COACH_WRITE_TOOLS
        if (
            not isinstance(tool, str)
            or (tool not in REMOTE_COACH_WRITE_TOOLS and not local_write)
            or not isinstance(arguments, dict)
            or not isinstance(intent, dict)
        ):
            raise AppError(409, "Der freigegebene Coach-Auftrag ist ung\u00fcltig.")
        if local_write:
            _validate_local_coach_write(payload)
        else:
            _validate_remote_coach_write(payload)
        client_turn_id = str(payload.get("client_turn_id") or "")
        conversation_id = str(payload.get("conversation_id") or "")
        if not client_turn_id or not conversation_id:
            raise AppError(
                409, "Der freigegebene Coach-Auftrag ist nicht mehr g\u00fcltig."
            )
        self._validate_remote_write_provenance(
            intent, client_turn_id, conversation_id, session_csrf_hash
        )
        return tool, arguments, intent, conversation_id, client_turn_id

    def _validate_remote_write_provenance(
        self,
        intent: dict[str, Any],
        client_turn_id: str,
        conversation_id: str,
        session_csrf_hash: str,
    ) -> None:
        source_ids = intent["request"].get("source_message_ids") or []
        session_key = hashlib.sha256(str(session_csrf_hash).encode("utf-8")).hexdigest()
        with self._database_manager.unit_of_work() as db:
            bound = db.execute(
                "SELECT conversation_id, receipt FROM coach_commands WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            receipt = json.loads(bound["receipt"] or "{}") if bound else {}
            if (
                not bound
                or bound["conversation_id"] != conversation_id
                or receipt.get("session_key") != session_key
            ):
                raise AppError(
                    409,
                    "Der freigegebene Coach-Auftrag geh\u00f6rt nicht mehr zu dieser Sitzung.",
                )
            placeholders = ",".join("?" for _ in source_ids)
            existing = db.execute(
                "SELECT m.id, m.client_turn_id, c.conversation_id, c.receipt "
                "FROM messages m LEFT JOIN coach_commands c "
                "ON c.client_turn_id=m.client_turn_id "
                f"WHERE m.role='user' AND m.id IN ({placeholders})",
                tuple(source_ids),
            ).fetchall()
            valid_ids = set()
            current_turn_ids = set()
            for message in existing:
                belongs, current_turn = _remote_source_message_status(
                    message, client_turn_id, conversation_id, session_key
                )
                if belongs:
                    message_id = int(message["id"])
                    valid_ids.add(message_id)
                    if current_turn:
                        current_turn_ids.add(message_id)
            if valid_ids != set(source_ids) or not current_turn_ids:
                raise AppError(
                    409,
                    "Der urspr\u00fcngliche Nutzerauftrag ist nicht mehr verf\u00fcgbar.",
                )
