"""Bounded, privacy-preserving change-history persistence."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.errors import AppError

RETENTION_DAYS = 180
MAX_ROWS = 1000
ENTITY_TYPES = {
    "profile",
    "workout_library",
    "planned_unit",
    "competition",
    "training_plan",
}
ACTIONS = {"create", "update", "delete", "undo"}

PROFILE_FIELDS = {
    "name",
    "goals",
    "sports",
    "training_background",
    "typical_weekly_volume",
    "availability",
    "constraints",
    "equipment",
    "training_preferences",
    "coaching_style",
    "timezone",
    "weather_location",
    "weight_kg",
    "body_fat_pct",
    "height_cm",
    "performance_notes",
}
LIBRARY_FIELDS = {
    "id",
    "type",
    "name",
    "description",
    "duration_minutes",
    "moving_time",
    "target",
    "date",
    "source",
    "rationale",
    "plan_id",
    "plan_name",
    "archived",
    "local_marked",
    "private_calendar_adjustment",
    "sync_status",
}
PLANNED_UNIT_FIELDS = {
    "id",
    "type",
    "name",
    "description",
    "duration_minutes",
    "moving_time",
    "target",
    "date",
    "source",
    "origin",
    "rationale",
    "plan_id",
    "plan_name",
    "archived",
    "sync_status",
    "remote_event_id",
    "remote_event_external_id",
    "local_deleted",
}
COMPETITION_FIELDS = {
    "id",
    "name",
    "event_date",
    "start_date_local",
    "sport",
    "priority",
    "category",
    "distance",
    "target",
    "course_profile",
    "notes",
    "description",
    "moving_time",
    "sync_state",
}
PLAN_FIELDS = {"id", "name", "goal", "start_date", "end_date", "status"}


def audit_projection_fields(entity_type: str) -> set[str]:
    fields_by_entity = {
        "profile": PROFILE_FIELDS,
        "workout_library": LIBRARY_FIELDS,
        "planned_unit": PLANNED_UNIT_FIELDS,
        "competition": COMPETITION_FIELDS,
        "training_plan": PLAN_FIELDS,
    }
    try:
        return fields_by_entity[entity_type]
    except KeyError as exc:
        raise ValueError("unsupported change-history entity") from exc


def _audit_payload_projection(value: Any) -> Any:
    if not isinstance(value, dict) or not isinstance(value.get("payload"), str):
        return value
    try:
        payload = json.loads(value["payload"])
    except (TypeError, ValueError):
        payload = {}
    return {
        **payload,
        "sync_status": value.get("sync_state") or payload.get("sync_status"),
    }


def audit_projection(entity_type: str, value: Any) -> dict[str, Any] | None:
    """Return the small, local-only representation allowed in change history."""
    if value is None:
        return None
    fields = audit_projection_fields(entity_type)
    if entity_type in {"workout_library", "planned_unit"}:
        value = _audit_payload_projection(value)
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    for field in sorted(fields):
        if field not in value:
            continue
        candidate = value[field]
        try:
            encoded = json.dumps(
                candidate,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
        except (TypeError, ValueError):
            continue
        if len(encoded) > 4000:
            continue
        result[field] = candidate
    return result


def audit_hash(value: dict[str, Any] | None) -> str:
    payload = json.dumps(
        value or {},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit_diff(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> dict[str, Any]:
    before = before or {}
    after = after or {}
    fields: dict[str, dict[str, Any]] = {}
    for field in sorted(set(before) | set(after)):
        old = before.get(field)
        new = after.get(field)
        if old != new:
            fields[field] = {"before": old, "after": new}
    return {
        "fields": fields,
        "before_present": bool(before),
        "after_present": bool(after),
    }


def cleanup(db: Any, *, current_time: datetime | None = None) -> None:
    now = current_time or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat()
    db.execute("DELETE FROM change_history WHERE created_at < ?", (cutoff,))
    db.execute(
        "DELETE FROM change_history WHERE id NOT IN "
        "(SELECT id FROM change_history ORDER BY created_at DESC LIMIT ?)",
        (MAX_ROWS,),
    )


def reserve_capacity(db: Any, required_rows: int) -> None:
    """Make room for one atomic operation without deleting its own audit rows."""
    required = max(0, int(required_rows))
    if required > MAX_ROWS:
        raise AppError(
            400,
            "Die Änderung ist zu groß, um vollständig in der Undo-Historie gespeichert zu werden.",
            reason="change_history_limit",
        )
    keep = max(0, MAX_ROWS - required)
    db.execute(
        "DELETE FROM change_history WHERE id NOT IN "
        "(SELECT id FROM change_history ORDER BY created_at DESC LIMIT ?)",
        (keep,),
    )


def record_change(
    db: Any,
    entity_type: str,
    entity_id: str,
    action: str,
    before: Any,
    after: Any,
    *,
    source: str = "local",
) -> dict[str, str] | None:
    if entity_type not in ENTITY_TYPES or action not in ACTIONS:
        raise ValueError("unsupported change-history record")
    before_projection = audit_projection(entity_type, before)
    after_projection = audit_projection(entity_type, after)
    before_hash = audit_hash(before_projection)
    after_hash = audit_hash(after_projection)
    if before_hash == after_hash and action != "undo":
        return None
    record = {
        "id": str(uuid.uuid4()),
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "action": action,
        "source": str(source)[:40] or "local",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "before_hash": before_hash,
        "after_hash": after_hash,
        "diff": json.dumps(
            audit_diff(before_projection, after_projection),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    if source != "coach_replacement":
        cleanup(db)
    db.execute(
        "INSERT INTO change_history(id, entity_type, entity_id, action, source, created_at, before_hash, after_hash, diff) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        tuple(
            record[key]
            for key in (
                "id",
                "entity_type",
                "entity_id",
                "action",
                "source",
                "created_at",
                "before_hash",
                "after_hash",
                "diff",
            )
        ),
    )
    return record


def public_view(row: dict[str, Any]) -> dict[str, Any]:
    """Remove retained athlete values from the public history representation."""
    try:
        diff = json.loads(row.get("diff") or "{}")
    except (TypeError, ValueError):
        diff = {"fields": {}}
    safe_fields = {
        field: {"changed": True}
        for field in (diff.get("fields") or {})
        if isinstance(field, str) and re.fullmatch(r"[a-z_]+", field)
    }
    return {
        "id": row["id"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "action": row["action"],
        "source": row["source"],
        "created_at": row["created_at"],
        "before_hash": row["before_hash"],
        "after_hash": row["after_hash"],
        "diff": {
            "fields": safe_fields,
            "before_present": bool(diff.get("before_present")),
            "after_present": bool(diff.get("after_present")),
        },
        "remote_sync": "local_only",
    }
