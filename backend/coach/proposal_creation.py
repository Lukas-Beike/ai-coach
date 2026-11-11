"""Create local Coach action previews and approval manifests."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from backend.athlete.local_date import LocalDate
from backend.coach.proposal_models import (
    COACH_ACTION_TTL_SECONDS,
    _preview_nutrient,
    _utc_now,
    coach_action_hash,
    coach_action_view,
    prune_expired_coach_proposals,
)
from backend.coach.proposal_validation import (
    _validate_local_coach_write,
    remote_coach_write_diff,
    remote_write_target,
    validated_coach_action_preview_input,
)
from backend.db.manager import DatabaseManager
from backend.db.repositories import CompetitionRepository, PlanAdjustmentRepository
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.planning import planned_units
from backend.planning.garmin_orphans import find_orphans, removal_entries
from backend.planning.intervals_orphans import find_intervals_orphans, sync_entries
from backend.planning.workout_export import past_export_horizon
from backend.providers.intervals_workouts import intervals_record_type
from backend.sync.authority import competition_push_manifest

_MAX_REMOTE_APPROVAL_DETAILS = 5000
# Entries of one Garmin plan_push job (backend/sync/jobs.py).
_MAX_GARMIN_ENTRIES = 28


def _utc_today() -> date:
    return datetime.now(UTC).date()


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
        *,
        ttl_seconds: int = COACH_ACTION_TTL_SECONDS,
        now: Callable[[], float] = time.time,
        utc_now: Callable[[], str] = _utc_now,
        uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
        nutrition_diary_service: Callable[[], Any] | None = None,
        nutrition_meal_library_service: Callable[[], Any] | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._today = today or _utc_today
        self._database_manager = database_manager
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
        proposal_id = str(self._uuid_factory())
        expires_at = self._now() + self._ttl_seconds
        created_at = self._utc_now()
        with self._database_manager.unit_of_work() as db:
            # Expired authorization artifacts are deleted on the write path only.
            prune_expired_coach_proposals(db, self._now())
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
            nutrition_diary_service=self._nutrition_diary_service,
            today=self._today(),
        )
        payload["intent"] = _card_authorized_intent(
            tool, payload["arguments"], intent, self._database_manager
        )
        targets = sorted(
            value
            for value in payload["intent"].get("authorization_scope", [])
            if isinstance(value, str)
        )
        approval_manifest = payload["arguments"].get("_approval_manifest")
        approval_details = _remote_write_approval_details(
            tool,
            payload["arguments"],
            intent,
            self._database_manager,
            today=self._today(),
        )
        return self.create(
            {
                "action_type": "remote_coach_write",
                "target_system": remote_write_target(tool, payload["intent"]),
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
        elif (
            set(values) & {"kcal", "carbs_g", "protein_g", "fat_g"}
            and self._nutrition_meal_library_service is not None
        ):
            preview_values.update(
                self._nutrition_meal_library_service().prepare_values(preview_values)
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
    nutrition_diary_service: Callable[[], Any] | None,
    today: date,
) -> dict[str, Any]:
    if tool == "start_intervals_plan_sync":
        return _approved_plan_sync_arguments(arguments, intent, database_manager, today)
    if tool == "push_strength_to_garmin":
        return _approved_garmin_arguments(arguments, database_manager, today)
    if tool == "sync_competitions":
        with database_manager.reader() as db:
            return {**arguments, "_approval_manifest": competition_push_manifest(db)}
    if tool == "sync_nutrition":
        return _nutrition_approval_arguments(arguments, nutrition_diary_service)
    if tool == "apply_adaptive_replan":
        return _adaptive_approval_arguments(arguments, database_manager)
    return dict(arguments)


def _adaptive_approval_arguments(
    arguments: dict[str, Any], database_manager: DatabaseManager
) -> dict[str, Any]:
    """Bind the illness sync to the stored preview, never to the model's arguments.

    Only the adjustment id is read from the model; it must name the latest stored
    preview, and every other argument is dropped. The pause that the athlete
    approves is taken from the stored preview as the manifest.
    """
    with database_manager.reader() as db:
        latest = PlanAdjustmentRepository().latest(db)
    try:
        stored = json.loads(latest["payload"]) if latest else {}
    except TypeError, ValueError:
        stored = {}
    pause = stored.get("illness_pause") if isinstance(stored, dict) else None
    if (
        not latest
        or latest["status"] != "preview"
        or str(latest["id"]) != str(arguments.get("adjustment_id") or "").strip()
    ):
        raise AppError(
            409, "Bitte zuerst die aktuelle adaptive Planungsvorschau erstellen."
        )
    if not isinstance(pause, dict) or pause.get("approved"):
        raise AppError(
            409,
            "Die adaptive Vorschau enthält keine Krankheitspause zum Synchronisieren.",
        )
    changes = stored.get("changes")
    return {
        "adjustment_id": str(latest["id"]),
        "sync_illness_to_intervals": True,
        "_approval_manifest": {
            "adjustment_id": str(latest["id"]),
            "changes": len(changes) if isinstance(changes, list) else 0,
            "illness_pause": {
                key: pause.get(key) for key in ("start_date", "end_date")
            },
        },
    }


def _card_authorized_intent(
    tool: str,
    arguments: dict[str, Any],
    intent: dict[str, Any],
    database_manager: DatabaseManager,
) -> dict[str, Any]:
    """Authorize exactly the units an Intervals.icu plan-sync card lists.

    The athlete approves the card, which shows every listed unit. The model's
    unit tokens are not what the athlete sees, so for a selected sync they are
    replaced by tokens for the card entries, each checked against local state.
    The tokens are stored with the hashed card payload and grant nothing else.
    """
    entries = arguments.get("entries")
    if (
        tool != "start_intervals_plan_sync"
        or arguments.get("repair") is True
        or (intent.get("request") or {}).get("sync_scope") != "selected"
        or not isinstance(entries, list)
        or not entries
    ):
        return intent
    # The executor's own entry rules, so the card never lists what it rejects.
    identifiers = sorted(
        entry["library_workout_id"]
        for entry in planning_library.library_bulk_request_entries(
            entries, require_hash=True
        )
    )
    placeholders = ",".join("?" for _ in identifiers)
    tokens: set[str] = set()
    with database_manager.reader() as db:
        for kind, table in (
            ("planned_unit", "planned_units"),
            ("library_workout", "workout_library"),
        ):
            rows = db.execute(
                f"SELECT local_id FROM {table} WHERE local_id IN ({placeholders})",
                tuple(identifiers),
            ).fetchall()
            tokens.update(f"{kind}:{row['local_id']}" for row in rows)
    found = {token.partition(":")[2] for token in tokens}
    if found != set(identifiers):
        raise AppError(
            409,
            "Das ausgewählte Objekt ist nicht mehr verfügbar. Lies den aktuellen Stand erneut.",
            reason="request_object_missing",
        )
    # The card is the only authority over units: the model's own unit tokens go.
    scope = {
        str(value)
        for value in intent.get("authorization_scope", [])
        if value and not str(value).startswith(("planned_unit:", "library_workout:"))
    } | tokens
    return {**intent, "authorization_scope": sorted(scope)}


def _approved_plan_sync_arguments(
    arguments: dict[str, Any],
    intent: dict[str, Any],
    database_manager: DatabaseManager,
    today: date,
) -> dict[str, Any]:
    approved = dict(arguments)
    if approved.get("repair") is True:
        return approved
    if approved.get("entries"):
        return _with_intervals_leftovers(approved, intent, database_manager, today)
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
            "expected_payload_hash": planned_units.plan_push_payload_hash(
                row["payload"]
            ),
        }
        for row in rows
        # A unit before the export horizon can never be pushed: not pending.
        if not (all_pending and past_export_horizon(_payload_date(row), today))
    ]
    return approved


def _payload_date(row: Any) -> str:
    try:
        payload = json.loads(row["payload"] or "{}")
    except TypeError, ValueError:
        return ""
    return str(payload.get("date") or "") if isinstance(payload, dict) else ""


def _with_intervals_leftovers(
    approved: dict[str, Any],
    intent: dict[str, Any],
    database_manager: DatabaseManager,
    today: date,
) -> dict[str, Any]:
    """Add the Intervals.icu events of deleted or replaced units to a selected sync.

    The athlete cannot select a hidden unit, yet its event stays in the
    calendar and keeps reaching Garmin. The card lists these units as removals.
    A sync that must cover exactly the units of one Coach turn gets none.
    """
    if (intent.get("request") or {}).get("sync_scope") != "selected" or any(
        intent.get(key)
        for key in (
            "_replacement_sync_entry_ids",
            "_created_sync_entry_ids",
            "_changed_sync_entry_ids",
            "_sync_all_pending",
        )
    ):
        return approved
    entries = [entry for entry in approved["entries"] if isinstance(entry, dict)]
    chosen = {
        str(entry.get("library_workout_id") or entry.get("local_id") or "")
        for entry in entries
    }
    with database_manager.reader() as db:
        orphans, _total = find_intervals_orphans(db, today)
    room = planning_library.LIBRARY_BULK_MAX_ENTRIES - len(approved["entries"])
    extra = [item for item in orphans if item.local_id not in chosen][: max(room, 0)]
    return {**approved, "entries": [*approved["entries"], *sync_entries(extra)]}


def _remote_write_approval_details(
    tool: str,
    arguments: dict[str, Any],
    intent: dict[str, Any],
    database_manager: DatabaseManager,
    *,
    today: date,
) -> list[dict[str, str]]:
    if tool == "start_intervals_plan_sync":
        return _plan_sync_approval_details(arguments, intent, database_manager, today)
    if tool == "sync_competitions":
        return _competition_approval_details(arguments, database_manager)
    if tool == "push_strength_to_garmin":
        return _garmin_approval_details(arguments, database_manager, today)
    return []


def _approved_garmin_arguments(
    arguments: dict[str, Any], database_manager: DatabaseManager, today: date
) -> dict[str, Any]:
    """Bind each selected unit to its stored payload when the card is created.

    The model names only unit ids and the remove flag; the hash comes from the
    stored unit with the job's own formula, so an edit after the card was shown
    makes the push a conflict.
    """
    raw = arguments.get("entries")
    if not isinstance(raw, list) or not 1 <= len(raw) <= _MAX_GARMIN_ENTRIES:
        raise AppError(
            400, "Wähle 1 bis 28 Krafteinheiten.", reason="invalid_job_request"
        )
    selected = [
        (
            planning_library.workout_library_entry_id(item.get("local_id")),
            item.get("remove") is True,
        )
        for item in raw
        if isinstance(item, dict)
    ]
    if len(selected) != len(raw) or len({i for i, _ in selected}) != len(selected):
        raise AppError(400, "Eine Einheit darf nur einmal ausgewählt werden.")
    rows = _planned_rows([local_id for local_id, _ in selected], database_manager)
    payloads = {str(row["local_id"]): row["payload"] for row in rows}
    if len(payloads) != len(selected):
        raise AppError(
            409,
            "Die ausgewählte Einheit ist nicht mehr verfügbar.",
            reason="request_object_missing",
        )
    entries: list[dict[str, Any]] = [
        {"library_workout_id": local_id, "remove": True}
        if remove
        else {
            "library_workout_id": local_id,
            "expected_payload_hash": planned_units.plan_push_payload_hash(
                payloads[local_id]
            ),
        }
        for local_id, remove in selected
    ]
    # The explicit Garmin sync also removes the workouts it sent for units that
    # no longer exist; the card lists them.
    with database_manager.reader() as db:
        orphans, _total = find_orphans(db, today)
    chosen = {entry["library_workout_id"] for entry in entries}
    room = _MAX_GARMIN_ENTRIES - len(entries)
    entries.extend(
        removal_entries(
            [item for item in orphans if item.local_id not in chosen][:room]
        )
    )
    return {"entries": entries, "reason": str(arguments.get("reason") or "")[:200]}


def _planned_rows(
    identifiers: list[str], database_manager: DatabaseManager
) -> list[Any]:
    placeholders = ",".join("?" for _ in identifiers)
    with database_manager.reader() as db:
        return db.execute(
            "SELECT local_id, payload FROM planned_units WHERE local_id IN ("
            + placeholders
            + ") ORDER BY local_id",
            tuple(identifiers),
        ).fetchall()


def _garmin_approval_details(
    arguments: dict[str, Any], database_manager: DatabaseManager, today: date
) -> list[dict[str, str]]:
    entries = arguments.get("entries") or []
    removals = {
        entry["library_workout_id"] for entry in entries if entry.get("remove") is True
    }
    with database_manager.reader() as db:
        orphans = {
            item.local_id: item for item in find_orphans(db, today, limit=None)[0]
        }
    listed = orphans.keys() & removals
    rows = _planned_rows(
        [
            entry["library_workout_id"]
            for entry in entries
            if entry["library_workout_id"] not in listed
        ],
        database_manager,
    )
    details = _plan_workout_details(rows)
    for detail in details:
        detail["sport"] = (
            "Von Garmin entfernen" if detail["id"] in removals else "Kraft an Garmin"
        )
    details.extend(
        {
            "name": item.name,
            "date": _approval_date(item.date),
            "sport": "Wird bei Garmin entfernt",
            "id": item.local_id,
        }
        for local_id, item in orphans.items()
        if local_id in listed
    )
    return details


def _plan_sync_approval_details(
    arguments: dict[str, Any],
    intent: dict[str, Any],
    database_manager: DatabaseManager,
    today: date,
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
    return _label_intervals_removals(
        _plan_workout_details(rows), database_manager, today
    )


def _label_intervals_removals(
    details: list[dict[str, str]], database_manager: DatabaseManager, today: date
) -> list[dict[str, str]]:
    """Mark the listed units whose Intervals.icu event this sync deletes."""
    with database_manager.reader() as db:
        removed = {
            item.local_id for item in find_intervals_orphans(db, today, limit=None)[0]
        }
    for detail in details:
        if detail["id"] in removed:
            detail["sport"] = "Wird bei Intervals.icu entfernt"
    return details


_COMPETITION_MANIFEST_CHANGED = (
    "Der Wettkampfbestand hat sich vor der Freigabe geändert."
)


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
        _validate_manifest_row(row, item, _COMPETITION_MANIFEST_CHANGED)
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
        raise AppError(409, _COMPETITION_MANIFEST_CHANGED)
    _validate_manifest_row(row, item, _COMPETITION_MANIFEST_CHANGED)
    label = CompetitionRepository.tombstone_label(db, str(row["id"]))
    if label:
        return {
            "name": label["name"][:120],
            "date": _approval_date(label["event_date"]),
            "sport": "Wird bei Intervals.icu entfernt",
            "id": str(row["intervals_event_id"] or row["id"]),
        }
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
                    "sport": intervals_record_type(workout)[:40],
                    "id": str(row["local_id"]),
                }
            )
    return details


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
