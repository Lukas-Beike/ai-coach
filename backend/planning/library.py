"""Normalization and matching for local workout-library entries."""

import difflib
import hashlib
import math
import re
import uuid
from datetime import date
from typing import Any

from backend.errors import AppError
from backend.planning import competitions as planning_competitions
from backend.planning import workouts as planning_workouts

PAYLOAD_HASH_PATTERN = r"[0-9a-f]{64}"
LIBRARY_BULK_MAX_ENTRIES = 100

LIBRARY_WORKOUT_FIELDS = {
    "name",
    "description",
    "type",
    "moving_time",
    "duration_minutes",
    "distance",
    "target",
    "workout_doc",
    "icu_training_load",
    "icu_intensity",
    "indoor",
    "tags",
    "folder_id",
    "date",
    "rationale",
    "plan_id",
    "plan_name",
    "source",
    "private_calendar_adjustment",
    "archived",
    "local_marked",
    "local_deleted",
    "remote_event_id",
    "remote_event_external_id",
    "category",
    "paired_event_id",
}


def _library_workout_local_id(workout: dict[str, Any], local_id: str | None) -> str:
    requested_local_id = str(local_id or workout.get("local_id") or "").strip()
    raw_id = str(workout.get("id") or "").strip()
    if not requested_local_id and raw_id:
        try:
            requested_local_id = str(uuid.UUID(raw_id))
        except (ValueError, AttributeError):
            requested_local_id = ""
    if requested_local_id:
        try:
            return str(uuid.UUID(requested_local_id))
        except (ValueError, AttributeError) as exc:
            raise AppError(400, "Bibliothekseinheit ohne gültige lokale UUID.") from exc
    return str(uuid.uuid4())


def _library_workout_external_id(
    workout: dict[str, Any],
    external_id: str | None,
    local_id: str,
) -> str | None:
    raw_id = str(workout.get("id") or "").strip()
    # An explicit stored mapping is authoritative. Otherwise the provider's
    # resource id is the external identity; a local UUID must never become its
    # own external ID.
    resolved_external_id = str(external_id or "").strip()
    if not resolved_external_id:
        try:
            raw_id_is_local = str(uuid.UUID(raw_id)) == local_id
        except (ValueError, AttributeError):
            raw_id_is_local = raw_id == local_id
        resolved_external_id = (
            raw_id
            if raw_id and not raw_id_is_local
            else str(workout.get("external_id") or "").strip()
        )
    return resolved_external_id or None


def _library_workout_ids(
    workout: dict[str, Any],
    local_id: str | None,
    external_id: str | None,
) -> tuple[str, str | None]:
    resolved_local_id = _library_workout_local_id(workout, local_id)
    return resolved_local_id, _library_workout_external_id(
        workout, external_id, resolved_local_id
    )


def _library_workout_projection(workout: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in workout.items() if key in LIBRARY_WORKOUT_FIELDS
    }


def _normalize_library_workout_text_fields(result: dict[str, Any]) -> None:
    result["name"] = str(result.get("name") or "Bibliotheks-Einheit")[:200]
    result["description"] = str(result.get("description") or "")[:12000]
    result["type"] = planning_workouts.intervals_workout_sport(result.get("type"))
    for field, limit in (
        ("date", 10),
        ("rationale", 2000),
        ("plan_name", 200),
        ("source", 40),
    ):
        if result.get(field):
            result[field] = str(result[field])[:limit]


def _normalize_library_workout_duration(result: dict[str, Any]) -> None:
    if result.get("duration_minutes") is not None or result.get("moving_time") is None:
        return
    try:
        result["duration_minutes"] = max(5, round(float(result["moving_time"]) / 60))
    except (TypeError, ValueError):
        pass


def normalize_library_workout(
    workout: Any,
    *,
    local_id: str | None = None,
    external_id: str | None = None,
    sync_status: str = "synced",
) -> dict[str, Any]:
    if not isinstance(workout, dict):
        raise AppError(400, "Jede Bibliothekseinheit muss ein Objekt sein.")
    resolved_local_id, resolved_external_id = _library_workout_ids(
        workout, local_id, external_id
    )
    result = _library_workout_projection(workout)
    result["id"] = resolved_local_id
    result["external_id"] = resolved_external_id
    result["sync_status"] = sync_status
    _normalize_library_workout_text_fields(result)
    _normalize_library_workout_duration(result)
    result["archived"] = bool(result.get("archived"))
    result["local_marked"] = bool(result.get("local_marked"))
    result["local_deleted"] = bool(result.get("local_deleted"))
    return result


def workout_library_type(value: Any) -> str:
    """Return a stable activity type for matching library entries."""
    raw = str(value or "").strip()
    return planning_competitions.supported_competition_sport(raw) or raw.casefold()


def normalized_workout_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9%]+", " ", str(value or "").casefold()).strip()


def library_workout_duration_minutes(workout: dict[str, Any]) -> float | None:
    try:
        duration_minutes = float(workout.get("duration_minutes"))
        if duration_minutes >= 0:
            return duration_minutes
    except (TypeError, ValueError):
        pass
    try:
        moving_time = float(workout.get("moving_time"))
    except (TypeError, ValueError):
        return None
    return moving_time / 60 if moving_time >= 0 else None


def library_workout_matches(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Recognise a remote template after an uncertain create request."""
    if workout_library_type(
        left.get("type") or left.get("sport")
    ) != workout_library_type(right.get("type") or right.get("sport")):
        return False
    if normalized_workout_text(left.get("name")) != normalized_workout_text(
        right.get("name")
    ):
        return False
    if normalized_workout_text(left.get("description")) != normalized_workout_text(
        right.get("description")
    ):
        return False
    left_duration = library_workout_duration_minutes(left)
    right_duration = library_workout_duration_minutes(right)
    return (
        left_duration is None
        or right_duration is None
        or abs(left_duration - right_duration) <= 1
    )


def compatible_workout_duration(
    expected_minutes: int, library_minutes: float | None
) -> bool:
    if library_minutes is None:
        return True
    return abs(expected_minutes - library_minutes) <= max(10, expected_minutes * 0.2)


def _similar_library_workout_inputs(
    workout: dict[str, Any],
) -> tuple[str | None, str, str, int] | None:
    try:
        expected_duration = int(workout.get("duration_minutes"))
    except (TypeError, ValueError):
        return None
    return (
        workout_library_type(workout.get("sport")),
        normalized_workout_text(workout.get("description")),
        normalized_workout_text(workout.get("name")),
        expected_duration,
    )


def _validated_library_candidate(
    candidate: dict[str, Any], expected_duration: int
) -> bool:
    candidate_duration = library_workout_duration_minutes(candidate)
    try:
        planning_workouts.validate_workout_description(
            {
                **candidate,
                "duration_minutes": max(5, round(candidate_duration))
                if candidate_duration is not None
                else expected_duration,
                "target": candidate.get("target")
                if candidate.get("target") in {"AUTO", "POWER", "HR", "PACE"}
                else "AUTO",
            }
        )
    except AppError:
        return False
    return True


def _similar_library_candidate_score(
    candidate: Any,
    expected_type: str | None,
    expected_text: str,
    expected_name: str,
    expected_duration: int,
) -> float | None:
    if (
        not isinstance(candidate, dict)
        or workout_library_type(candidate.get("type") or candidate.get("sport"))
        != expected_type
    ):
        return None
    candidate_text = normalized_workout_text(candidate.get("description"))
    if not candidate_text or not compatible_workout_duration(
        expected_duration, library_workout_duration_minutes(candidate)
    ):
        return None
    if not _validated_library_candidate(candidate, expected_duration):
        return None
    candidate_name = normalized_workout_text(candidate.get("name"))
    description_similarity = difflib.SequenceMatcher(
        None, expected_text, candidate_text
    ).ratio()
    name_similarity = difflib.SequenceMatcher(
        None, expected_name, candidate_name
    ).ratio()
    exact_description = expected_text == candidate_text
    similar_description = description_similarity >= 0.82
    similar_named_workout = name_similarity >= 0.9 and description_similarity >= 0.55
    if not (exact_description or similar_description or similar_named_workout):
        return None
    return (
        1.0
        if exact_description
        else max(description_similarity, (name_similarity + description_similarity) / 2)
    )


def find_similar_library_workout(
    workout: dict[str, Any],
    library: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find an exact or conservative near-match in the injected workout library."""
    inputs = _similar_library_workout_inputs(workout)
    if not inputs:
        return None
    expected_type, expected_text, expected_name, expected_duration = inputs
    best: tuple[float, dict[str, Any]] | None = None
    for candidate in library:
        score = _similar_library_candidate_score(
            candidate, expected_type, expected_text, expected_name, expected_duration
        )
        if score is None or not isinstance(candidate, dict):
            continue
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best else None


def _library_bulk_entry_id(item: Any) -> str:
    if not isinstance(item, dict):
        raise AppError(400, "Jede Bulk-Auswahl muss ein Objekt sein.")
    try:
        return str(
            uuid.UUID(str(item.get("library_workout_id") or item.get("id") or ""))
        )
    except (ValueError, AttributeError) as exc:
        raise AppError(
            400, "Ungültige Bibliothekseinheiten-ID in der Auswahl."
        ) from exc


def _library_bulk_entry_date(item: dict[str, Any]) -> str | None:
    if "date" not in item:
        return None
    plan_date = str(item.get("date") or "").strip()
    try:
        date.fromisoformat(plan_date)
    except (TypeError, ValueError) as exc:
        raise AppError(400, "Das Bulk-Datum muss das Format JJJJ-MM-TT haben.") from exc
    return plan_date[:10]


def _library_bulk_entry_hash(item: dict[str, Any], *, require_hash: bool) -> str | None:
    expected_hash = str(item.get("expected_payload_hash") or "").strip().lower()
    if require_hash and not re.fullmatch(PAYLOAD_HASH_PATTERN, expected_hash):
        raise AppError(400, "Die Bulk-Aktion benötigt aktuelle Payload-Hashes.")
    if expected_hash and not re.fullmatch(PAYLOAD_HASH_PATTERN, expected_hash):
        raise AppError(400, "Ungültiger Payload-Hash in der Bulk-Auswahl.")
    return expected_hash or None


def _library_bulk_request_entry(item: Any, *, require_hash: bool) -> dict[str, Any]:
    local_id = _library_bulk_entry_id(item)
    selected = {"library_workout_id": local_id}
    plan_date = _library_bulk_entry_date(item)
    if plan_date:
        selected["date"] = plan_date
    expected_hash = _library_bulk_entry_hash(item, require_hash=require_hash)
    if expected_hash:
        selected["expected_payload_hash"] = expected_hash
    return selected


def library_bulk_request_entries(
    entries: Any,
    *,
    require_hash: bool = False,
    max_entries: int = LIBRARY_BULK_MAX_ENTRIES,
) -> list[dict[str, Any]]:
    if not isinstance(entries, list) or not entries:
        raise AppError(
            400, "Mindestens eine Bibliothekseinheit muss ausgewählt werden."
        )
    if len(entries) > max_entries:
        raise AppError(
            400,
            f"Es können höchstens {max_entries} Bibliothekseinheiten gleichzeitig ausgewählt werden.",
        )
    result = [
        _library_bulk_request_entry(item, require_hash=require_hash) for item in entries
    ]
    if len({item["library_workout_id"] for item in result}) != len(result):
        raise AppError(
            400, "Eine Bibliothekseinheit darf nur einmal ausgewählt werden."
        )
    return result


def library_payload_hash(raw_payload: Any) -> str:
    return hashlib.sha256(str(raw_payload or "").encode("utf-8")).hexdigest()


def workout_library_entry_id(local_id: Any) -> str:
    try:
        return str(uuid.UUID(str(local_id)))
    except (ValueError, AttributeError) as exc:
        raise AppError(400, "Ungültige Bibliothekseinheiten-ID.") from exc


def workout_library_update_candidate(
    current: dict[str, Any], action: str, values: dict[str, Any]
) -> dict[str, Any]:
    candidate = dict(current)
    if action in {"archive", "restore"}:
        candidate["archived"] = action == "archive"
        return candidate
    if action != "update":
        raise AppError(400, "Unbekannte Aktion für die Bibliothekseinheit.")
    for key in ("name", "description", "duration_minutes", "target"):
        if key in values:
            candidate[key] = values.get(key)
    if "type" in values or "sport" in values:
        candidate["type"] = values.get("type") or values.get("sport")
    return candidate


def _library_workout_as_number(value: Any) -> float | int | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _reconcile_updated_library_workout_content(
    normalized: dict[str, Any], values: dict[str, Any]
) -> None:
    seconds = planning_workouts.validate_workout_description(normalized)
    minutes = _library_workout_as_number(normalized.get("duration_minutes"))
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


def _preserve_library_workout_metadata(
    normalized: dict[str, Any], current: dict[str, Any]
) -> None:
    for key in (
        "source",
        "rationale",
        "plan_id",
        "plan_name",
        "private_calendar_adjustment",
    ):
        if current.get(key) is not None:
            normalized[key] = current[key]


def updated_workout_library_entry(
    current: dict[str, Any],
    row: dict[str, Any],
    local_id: str,
    action: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    normalized = normalize_library_workout(
        workout_library_update_candidate(current, action, values),
        local_id=local_id,
        external_id=str(row.get("external_id") or "") or None,
        sync_status="local",
    )
    if action == "update":
        _reconcile_updated_library_workout_content(normalized, values)
    _preserve_library_workout_metadata(normalized, current)
    return normalized
