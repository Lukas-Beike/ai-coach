"""Pure projections and normalization for concrete planned units."""

import hashlib
import json
import math
import uuid
from datetime import date
from typing import Any

from backend.errors import (
    CORRUPT_PLANNING_ERROR,
    INVALID_PLANNING_DATE_ERROR,
    INVALID_PLANNING_ID_ERROR,
    AppError,
)
from backend.planning import library as planning_library
from backend.planning import workouts as planning_workouts
from backend.providers.workout_text import canonical_workout_zones

_ISO_MIDNIGHT_SUFFIX = "T00:00:00"


def planned_unit_payload_hash(payload: Any) -> str:
    if not isinstance(payload, dict):
        payload = {}
    comparable = {
        key: value
        for key, value in payload.items()
        if key not in {"id", "sync_status", "sync_conflict", "origin", "local_marked"}
    }
    serialized = json.dumps(
        comparable,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _planned_unit_metadata(
    workout: dict[str, Any], normalized: dict[str, Any]
) -> dict[str, Any]:
    metadata = {
        "sport": normalized.get("type")
        or planning_workouts.intervals_workout_sport(
            workout.get("sport") or workout.get("type")
        ),
        "origin": str(workout.get("origin") or workout.get("source") or "coach")[:40],
    }
    metadata["source"] = str(workout.get("source") or metadata["origin"])[:40]
    if workout.get("start_date_local"):
        metadata["start_date_local"] = str(workout["start_date_local"])[:40]
    for field, limit in (
        ("status", 80),
        ("remote_event_id", 120),
        ("remote_event_external_id", 200),
    ):
        if workout.get(field) is not None:
            metadata[field] = str(workout.get(field) or "")[:limit]
    if workout.get("sync_conflict") is not None:
        metadata["sync_conflict"] = workout["sync_conflict"]
    return metadata


def normalize_planned_unit(
    workout: dict[str, Any],
    *,
    local_id: str | None = None,
    external_id: str | None = None,
    sync_status: str = "local",
) -> dict[str, Any]:
    """Normalize one concrete local calendar unit independently of templates."""
    if (
        not isinstance(workout, dict)
        or not isinstance(workout.get("sport"), str)
        or not workout["sport"].strip()
    ):
        raise AppError(
            400,
            "Eine geplante Einheit benoetigt ihre Sportart.",
            reason="invalid_workout",
        )
    normalized = planning_library.normalize_library_workout(
        {
            **workout,
            "type": planning_workouts.intervals_workout_sport(workout["sport"]),
            "date": str(workout.get("date") or workout.get("start_date_local") or "")[
                :10
            ],
        },
        local_id=local_id,
        external_id=external_id,
        sync_status=sync_status,
    )
    normalized.update(_planned_unit_metadata(workout, normalized))
    if normalized.get("moving_time") in (None, "") and normalized.get(
        "duration_minutes"
    ) not in (None, ""):
        normalized["moving_time"] = int(normalized["duration_minutes"]) * 60
    return normalized


def planned_workout_update_request(
    local_id: str, values: Any
) -> tuple[str, dict[str, Any], str]:
    try:
        normalized_id = str(uuid.UUID(str(local_id)))
    except (ValueError, AttributeError) as exc:
        raise AppError(400, INVALID_PLANNING_ID_ERROR) from exc
    if not isinstance(values, dict):
        raise AppError(400, "Die lokale Planung muss als Objekt gesendet werden.")
    action = str(values.get("action") or "update").strip().casefold()
    return normalized_id, values, action


def planned_workout_update_candidate(
    current: dict[str, Any], action: str, values: dict[str, Any]
) -> dict[str, Any]:
    candidate = dict(current)
    if action in {"archive", "restore"}:
        candidate["archived"] = action == "archive"
        if action == "restore":
            candidate["local_deleted"] = False
    elif action == "update":
        for key in ("date", "name", "description", "duration_minutes", "target"):
            if key in values:
                candidate[key] = values.get(key)
        if "type" in values or "sport" in values:
            candidate["sport"] = values.get("sport") or values.get("type")
    else:
        raise AppError(400, "Unbekannte Aktion für lokale Planung.")
    return candidate


def prepare_planned_workout_date(
    candidate: dict[str, Any], current: dict[str, Any]
) -> bool:
    candidate["date"] = str(candidate.get("date") or "").strip()
    try:
        date.fromisoformat(candidate["date"])
    except (TypeError, ValueError) as exc:
        raise AppError(400, INVALID_PLANNING_DATE_ERROR) from exc
    date_changed = candidate["date"][:10] != str(current.get("date") or "")[:10]
    if date_changed:
        old_start = str(current.get("start_date_local") or "")
        time_suffix = (
            old_start[10:]
            if len(old_start) > 10 and old_start[10] == "T"
            else _ISO_MIDNIGHT_SUFFIX
        )
        candidate["start_date_local"] = candidate["date"][:10] + time_suffix
    return date_changed


def planned_conflict_resolution_request(
    local_id: Any, strategy: Any
) -> tuple[str, str]:
    try:
        normalized_id = str(uuid.UUID(str(local_id)))
    except (ValueError, AttributeError) as exc:
        raise AppError(400, INVALID_PLANNING_ID_ERROR) from exc
    selected = str(strategy or "").strip().casefold()
    if selected not in {"keep_local", "adopt_remote"}:
        raise AppError(400, "Ungültige Konfliktstrategie.")
    return normalized_id, selected


def planned_conflict_payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError) as exc:
        raise AppError(409, CORRUPT_PLANNING_ERROR) from exc
    if not isinstance(payload, dict):
        raise AppError(409, CORRUPT_PLANNING_ERROR)
    return payload


def _as_number(value: Any) -> float | int | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _reconcile_updated_planned_workout_content(
    normalized: dict[str, Any], values: dict[str, Any]
) -> None:
    if "description" in values:
        normalized["description"] = canonical_workout_zones(
            normalized["description"],
            endurance=planning_workouts.intervals_workout_sport(normalized.get("sport"))
            in planning_workouts.INTERVALS_ENDURANCE_WORKOUT_TYPES,
        )
    seconds = planning_workouts.validate_workout_description(normalized)
    minutes = _as_number(normalized.get("duration_minutes"))
    if seconds is not None or minutes is not None:
        normalized["moving_time"] = round(
            seconds if seconds is not None else minutes * 60
        )
    if any(
        key in values
        for key in ("description", "duration_minutes", "target", "type", "sport")
    ):
        for key in ("workout_doc", "icu_training_load", "icu_intensity"):
            normalized.pop(key, None)


def _preserve_local_planned_workout_metadata(
    normalized: dict[str, Any], current: dict[str, Any]
) -> None:
    for key in (
        "plan_id",
        "plan_name",
        "rationale",
        "remote_event_id",
        "remote_event_external_id",
        "private_calendar_adjustment",
        "local_deleted",
    ):
        if current.get(key) is not None:
            normalized[key] = current[key]


def normalized_planned_workout_update(
    candidate: dict[str, Any],
    current: dict[str, Any],
    row: dict[str, Any],
    local_id: str,
    action: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    normalized = normalize_planned_unit(
        candidate,
        local_id=local_id,
        external_id=str(row.get("external_id") or current.get("external_id") or "")
        or None,
        sync_status="local",
    )
    normalized["source"] = str(current.get("source") or "library")[:40]
    if action == "update":
        _reconcile_updated_planned_workout_content(normalized, values)
    _preserve_local_planned_workout_metadata(normalized, current)
    return normalized


def _remote_planned_unit_id(event: dict[str, Any]) -> str | None:
    remote_id = str(event.get("id") or "").strip()
    return remote_id or None


def _remote_planned_unit_date(event: dict[str, Any], *, today: date) -> str | None:
    event_date = str(event.get("start_date_local") or event.get("date") or "")[:10]
    try:
        if date.fromisoformat(event_date) < today:
            return None
    except ValueError:
        return None
    return event_date


def _remote_planned_unit_duration(event: dict[str, Any]) -> int:
    moving_time = event.get("moving_time")
    try:
        return (
            max(5, round(float(moving_time) / 60))
            if moving_time not in (None, "")
            else 30
        )
    except (TypeError, ValueError):
        return 30


def remote_planned_unit_payload(
    event: dict[str, Any], *, today: date
) -> tuple[dict[str, Any], str, str] | None:
    if str(event.get("category") or "WORKOUT").upper() != "WORKOUT":
        return None
    remote_id = _remote_planned_unit_id(event)
    event_date = _remote_planned_unit_date(event, today=today)
    if not remote_id or not event_date:
        return None
    remote_external_id = str(event.get("external_id") or "").strip()
    identity = remote_external_id or f"intervals-event-{remote_id}"
    moving_time = event.get("moving_time")
    payload = {
        "date": event_date,
        "start_date_local": event.get("start_date_local")
        or event.get("start")
        or event_date + _ISO_MIDNIGHT_SUFFIX,
        "sport": event.get("type") or event.get("sport") or "Ride",
        "type": event.get("type") or event.get("sport") or "Ride",
        "name": event.get("name") or "Intervals.icu-Einheit",
        "description": event.get("description") or "",
        "duration_minutes": _remote_planned_unit_duration(event),
        "moving_time": moving_time,
        "target": event.get("target") or "AUTO",
        "source": "intervals",
        "origin": "intervals",
        "category": "WORKOUT",
        "paired_event_id": event.get("paired_event_id") or event.get("pairedEventId"),
        "remote_event_id": remote_id,
        "remote_event_external_id": remote_external_id,
    }
    normalized = normalize_planned_unit(
        payload, local_id=None, external_id=identity, sync_status="synced"
    )
    return normalized, remote_id, identity


def remote_planned_unit_existing_state(
    current_row: Any, incoming_hash: str
) -> tuple[dict[str, Any], str]:
    try:
        current = json.loads(current_row.get("payload") or "{}")
    except (TypeError, ValueError):
        current = {}
    if not isinstance(current, dict):
        current = {}
    state = str(current_row.get("sync_state") or "synced")
    baseline = str(current_row.get("baseline_hash") or "")
    local_changed = bool(int(current_row.get("sync_dirty") or 0)) or state in {
        "local",
        "sync_error",
        "conflict",
    }
    remote_changed = bool(baseline and baseline != incoming_hash) or (
        not baseline and planned_unit_payload_hash(current) != incoming_hash
    )
    if local_changed and remote_changed:
        return current, "conflict"
    if local_changed:
        return current, "preserve"
    if state == "synced" and not remote_changed:
        return current, "unchanged"
    return current, "update"
