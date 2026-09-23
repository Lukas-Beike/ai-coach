"""Validation and normalization for locally owned target competitions."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime
from typing import Any

from backend.errors import AppError

COMPETITION_TEXT_LIMITS = {
    "name": 200,
    "sport": 80,
    "distance": 80,
    "target": 1000,
    "course_profile": 2000,
    "notes": 2000,
    "description": 12000,
    "external_id": 200,
}

COMPETITION_EXTERNAL_PREFIX = "intervals-coach-competition-"
COMPETITION_SPORTS = {
    "cycling": "Ride",
    "rad": "Ride",
    "rad outdoor": "Ride",
    "radfahren": "Ride",
    "ride": "Ride",
    "virtualride": "VirtualRide",
    "virtual ride": "VirtualRide",
    "rad indoor": "VirtualRide",
    "indoor cycling": "VirtualRide",
    "virtual cycling": "VirtualRide",
    "running": "Run",
    "lauf": "Run",
    "laufen": "Run",
    "run": "Run",
    "strength": "WeightTraining",
    "kraft": "WeightTraining",
    "krafttraining": "WeightTraining",
    "weighttraining": "WeightTraining",
}
_ISO_MIDNIGHT_SUFFIX = "T00:00:00"


def supported_competition_sport(value: Any) -> str | None:
    raw = str(value or "").strip().casefold()
    normalized = re.sub(r"[\s_-]+", " ", raw)
    return COMPETITION_SPORTS.get(raw) or COMPETITION_SPORTS.get(normalized)


def intervals_competition_sport(value: Any) -> str:
    raw = str(value or "Cycling").strip()
    return supported_competition_sport(raw) or raw[:80] or "Ride"


def competition_external_id(competition_id: str) -> str:
    return f"{COMPETITION_EXTERNAL_PREFIX}{competition_id}"


def competition_event_optional_payload(competition: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if competition.get("moving_time") is not None:
        payload["moving_time"] = int(competition["moving_time"])
    distance = competition.get("distance")
    if distance not in (None, ""):
        try:
            normalized_distance = float(str(distance).replace(",", "."))
            payload["distance"] = (
                int(normalized_distance)
                if normalized_distance.is_integer()
                else normalized_distance
            )
        except ValueError:
            # Keep free-form values local instead of sending invalid API data.
            pass
    if competition.get("target") not in (None, ""):
        payload["target"] = competition_target(competition.get("target"))
    if competition.get("intervals_event_id"):
        remote_id = str(competition["intervals_event_id"])
        payload["id"] = int(remote_id) if remote_id.isdigit() else remote_id
    return payload


def competition_event_payload(competition: dict[str, Any]) -> dict[str, Any]:
    category = str(competition.get("category") or "").upper()
    if category not in {"RACE_A", "RACE_B", "RACE_C"}:
        category = (
            f"RACE_{competition.get('priority')}"
            if competition.get("priority") in {"A", "B", "C"}
            else "RACE_B"
        )
    payload = {
        "category": category,
        "start_date_local": str(
            competition.get("start_date_local")
            or f"{competition['event_date']}{_ISO_MIDNIGHT_SUFFIX}"
        ),
        "type": intervals_competition_sport(competition.get("sport")),
        "name": str(competition.get("name") or "Zielwettkampf")[:200],
        "description": str(
            competition.get("description") or competition.get("notes") or ""
        )[:12000],
        "external_id": str(
            competition.get("external_id")
            or competition_external_id(str(competition["id"]))
        ),
    }
    payload.update(competition_event_optional_payload(competition))
    return payload


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def remote_competition_date(event: dict[str, Any]) -> str | None:
    raw = _first_present(event, ("start_date_local", "date", "start"))
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw)[:10]).isoformat()
    except ValueError:
        return None


def remote_competition_moving_time(value: Any) -> int | None:
    try:
        return competition_moving_time(value)
    except AppError:
        return None


def remote_competition_distance(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    return competition_distance(value)


def remote_competition_data(event: dict[str, Any]) -> dict[str, Any] | None:
    event_date = remote_competition_date(event)
    name = str(event.get("name") or "").strip()[: COMPETITION_TEXT_LIMITS["name"]]
    sport = supported_competition_sport(
        event.get("type") or event.get("sport") or "Ride"
    )
    if not event_date or not name or not sport:
        return None
    category = str(event.get("category") or "RACE_B").upper()
    suffix = category.rsplit("_", 1)[-1]
    priority = suffix if suffix in {"A", "B", "C"} else "B"
    start_date_local = str(
        event.get("start_date_local") or f"{event_date}{_ISO_MIDNIGHT_SUFFIX}"
    )[:19]
    moving_time = remote_competition_moving_time(event.get("moving_time"))
    distance = remote_competition_distance(event.get("distance"))
    description = str(event.get("description") or "").strip()[
        : COMPETITION_TEXT_LIMITS["description"]
    ]
    return {
        "intervals_event_id": str(
            event.get("id") or event.get("intervals_event_id") or ""
        ).strip()
        or None,
        "name": name,
        "event_date": event_date,
        "start_date_local": start_date_local,
        "sport": sport,
        "priority": priority,
        "category": f"RACE_{priority}",
        "distance": distance,
        "target": competition_target(event.get("target")),
        "description": description,
        "moving_time": moving_time,
        "notes": description[: COMPETITION_TEXT_LIMITS["notes"]],
    }


def competition_conflict_payload(
    remote: dict[str, Any], conflict_type: str, *, detected_at: str
) -> str:
    data = remote_competition_data(remote) or {}
    data["external_id"] = str(
        remote.get("external_id") or data.get("external_id") or ""
    ).strip()[: COMPETITION_TEXT_LIMITS["external_id"]]
    return json.dumps(
        {"type": conflict_type, "remote": data, "detected_at": detected_at},
        ensure_ascii=False,
    )


def is_remote_competition_event(
    event: dict[str, Any], linked_event_ids: set[str]
) -> bool:
    category = str(event.get("category") or "").upper()
    external_id = str(event.get("external_id") or "")
    event_id = str(event.get("id") or "")
    return bool(supported_competition_sport(event.get("type") or "Ride")) and (
        category.startswith("RACE")
        or external_id.startswith(COMPETITION_EXTERNAL_PREFIX)
        or event_id in linked_event_ids
    )


def competition_sync_key(
    value: dict[str, Any],
) -> tuple[str, str, str] | None:
    """Return a conservative identity for matching a local and remote race."""
    name = " ".join(str(value.get("name") or "").split()).casefold()
    event_date = str(value.get("event_date") or remote_competition_date(value) or "")[
        :10
    ]
    sport = supported_competition_sport(
        value.get("sport") or value.get("type") or "Ride"
    )
    if not name or not event_date or not sport:
        return None
    return name, event_date, sport


def competition_remote_indexes(
    remote_events: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[tuple[str, str, str], dict[str, Any]],
]:
    return (
        {
            str(event.get("external_id")): event
            for event in remote_events
            if event.get("external_id")
        },
        {str(event.get("id")): event for event in remote_events if event.get("id")},
        {
            key: event
            for event in remote_events
            if (key := competition_sync_key(event)) is not None
        },
    )


def competition_remote_match(
    row: dict[str, Any],
    remote_by_external: dict[str, dict[str, Any]],
    remote_by_id: dict[str, dict[str, Any]],
    remote_by_identity: dict[tuple[str, str, str], dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    remote = (
        remote_by_id.get(str(row["intervals_event_id"]))
        if row.get("intervals_event_id")
        else None
    )
    if remote is None and row.get("external_id"):
        remote = remote_by_external.get(str(row["external_id"]))
    identity_remote = (
        remote_by_identity.get(competition_sync_key(row))
        if not row.get("intervals_event_id")
        else None
    )
    return remote or identity_remote, identity_remote


def competition_conflict_action(
    row: dict[str, Any],
    remote: dict[str, Any] | None,
    identity_remote: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if identity_remote and row.get("sync_state") != "local_override":
        return {
            "type": "conflict",
            "local_id": str(row["id"]),
            "remote_id": str(identity_remote.get("id") or ""),
            "name": str(row.get("name") or ""),
            "event_date": str(row.get("event_date") or ""),
            "sport": str(row.get("sport") or ""),
            "reason": "remote_identity_changed",
        }
    if row.get("intervals_event_id") and remote is None:
        return {
            "type": "conflict",
            "local_id": str(row["id"]),
            "remote_id": str(row.get("intervals_event_id") or ""),
            "name": str(row.get("name") or ""),
            "event_date": str(row.get("event_date") or ""),
            "sport": str(row.get("sport") or ""),
            "reason": "remote_missing",
        }
    return None


def competition_dirty_row_action(
    row: dict[str, Any],
    remote_by_external: dict[str, dict[str, Any]],
    remote_by_id: dict[str, dict[str, Any]],
    remote_by_identity: dict[tuple[str, str, str], dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not supported_competition_sport(row.get("sport")):
        return None, None
    remote, identity_remote = competition_remote_match(
        row, remote_by_external, remote_by_id, remote_by_identity
    )
    conflict = competition_conflict_action(row, remote, identity_remote)
    if conflict:
        return None, conflict
    payload = competition_event_payload(row)
    action = {
        "type": "change" if remote is not None else "create",
        "local_id": str(row["id"]),
        "remote_id": str(
            (remote or {}).get("id") or row.get("intervals_event_id") or ""
        ),
        "name": str(row.get("name") or ""),
        "event_date": str(row.get("event_date") or ""),
        "sport": str(row.get("sport") or ""),
        "payload_hash": hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
    }
    return payload, action


def competition_delete_identifiers(
    tombstones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {"id": row["intervals_event_id"]}
        if row.get("intervals_event_id")
        else {"external_id": row["external_id"]}
        for row in tombstones
        if row.get("intervals_event_id") or row.get("external_id")
    ]


def competition_remote_signature(
    remote_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fields = (
        "id",
        "external_id",
        "name",
        "start_date_local",
        "type",
        "category",
        "distance",
        "moving_time",
        "target",
        "description",
    )
    return [
        {key: event.get(key) for key in fields}
        for event in sorted(
            remote_events,
            key=lambda item: (
                str(item.get("id") or ""),
                str(item.get("external_id") or ""),
            ),
        )
    ]


def competition_plan_summary(actions: list[dict[str, Any]]) -> dict[str, int]:
    return {
        kind: sum(1 for action in actions if action["type"] == kind)
        for kind in ("create", "change", "delete", "conflict")
    }


def competition_sync_plan(
    local_rows: list[dict[str, Any]],
    tombstones: list[dict[str, Any]],
    remote_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a remote mutation plan without changing local or provider state."""
    remote_by_external, remote_by_id, remote_by_identity = competition_remote_indexes(
        remote_events
    )
    actions: list[dict[str, Any]] = []
    outbound: list[dict[str, Any]] = []
    dirty_rows = [row for row in local_rows if row.get("sync_dirty")]
    for row in dirty_rows:
        payload, action = competition_dirty_row_action(
            row, remote_by_external, remote_by_id, remote_by_identity
        )
        if payload is not None:
            outbound.append(payload)
        if action is not None:
            actions.append(action)
    delete_identifiers = competition_delete_identifiers(tombstones)
    actions.extend(
        {"type": "delete", **{key: str(value) for key, value in identifier.items()}}
        for identifier in delete_identifiers
    )
    remote_signature = competition_remote_signature(remote_events)
    basis = {"actions": actions, "remote": remote_signature}
    fingerprint = hashlib.sha256(
        json.dumps(
            basis,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    summary = competition_plan_summary(actions)
    return {
        "actions": actions,
        "outbound": outbound,
        "delete_identifiers": delete_identifiers,
        "dirty_count": len(dirty_rows),
        "skipped": len(dirty_rows) - len(outbound) - summary["conflict"],
        "summary": summary,
        "fingerprint": fingerprint,
        "remote_events": remote_events,
        "remote_by_external": remote_by_external,
        "remote_by_id": remote_by_id,
        "remote_by_identity": remote_by_identity,
    }


def competition_start(value: Any, fallback_date: Any = None) -> tuple[str, str]:
    raw = str(value or "").strip()
    fallback = str(fallback_date or "").strip()
    if not raw:
        raw = fallback + "T00:00:00"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AppError(
            400, "Der Startzeitpunkt des Wettkampfs muss ein gültiges Datum sein."
        ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    if fallback:
        try:
            fallback_day = date.fromisoformat(fallback)
        except ValueError:
            fallback_day = None
        if fallback_day is not None and parsed.date() != fallback_day:
            parsed = parsed.replace(
                year=fallback_day.year,
                month=fallback_day.month,
                day=fallback_day.day,
            )
    start = parsed.replace(second=0, microsecond=0).isoformat(timespec="seconds")
    return parsed.date().isoformat(), start


def competition_moving_time(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        seconds = int(float(value))
    except (TypeError, ValueError) as exc:
        raise AppError(
            400, "Die Wettkampfdauer muss in Sekunden angegeben werden."
        ) from exc
    if seconds < 0 or seconds > 7 * 24 * 60 * 60:
        raise AppError(
            400,
            "Die Wettkampfdauer muss zwischen 0 und 604800 Sekunden liegen.",
        )
    return seconds


def competition_distance(value: Any) -> str:
    """Keep the existing text field while accepting Intervals' meter value."""
    raw = str(value or "").strip()[: COMPETITION_TEXT_LIMITS["distance"]]
    if not raw:
        return ""
    try:
        number = float(raw.lower().replace("km", "").replace(",", ".").strip())
    except ValueError:
        return raw
    if "km" in raw.lower():
        number *= 1000
    return str(int(number)) if number.is_integer() else str(round(number, 3))


def competition_target(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[
            : COMPETITION_TEXT_LIMITS["target"]
        ]
    return str(value or "").strip()[: COMPETITION_TEXT_LIMITS["target"]]


def competition_category_and_priority(
    value: dict[str, Any], name: str
) -> tuple[str, str]:
    category = str(value.get("category") or "").strip().upper()
    if category in {"RACE_A", "RACE_B", "RACE_C"}:
        return category, category.rsplit("_", 1)[-1]
    priority = str(value.get("priority") or "B").strip().upper()
    if priority not in {"A", "B", "C"}:
        raise AppError(
            400,
            f"Die Kategorie für „{name}“ muss RACE_A, RACE_B oder RACE_C sein.",
        )
    return f"RACE_{priority}", priority


def competition_normalized_id(value: Any) -> str:
    try:
        return str(uuid.UUID(str(value or "").strip()))
    except (ValueError, AttributeError):
        return str(uuid.uuid4())


def competition_normalized_text_fields(value: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field, limit in COMPETITION_TEXT_LIMITS.items():
        if field in {"name", "external_id", "description"}:
            continue
        default = "Cycling" if field == "sport" else ""
        result[field] = (
            competition_target(value.get(field))
            if field == "target"
            else str(value.get(field) or default).strip()[:limit]
        )
    result["distance"] = competition_distance(value.get("distance"))
    result["description"] = str(
        value.get("description") or value.get("notes") or ""
    ).strip()[: COMPETITION_TEXT_LIMITS["description"]]
    result["external_id"] = str(value.get("external_id") or "").strip()[
        : COMPETITION_TEXT_LIMITS["external_id"]
    ]
    return result


def normalize_competition(value: Any) -> dict[str, str | int | None]:
    if not isinstance(value, dict):
        raise AppError(400, "Jeder Wettkampf muss ein Objekt sein.")
    name = str(value.get("name") or "").strip()[: COMPETITION_TEXT_LIMITS["name"]]
    if not name:
        raise AppError(400, "Jeder Wettkampf benötigt einen Namen.")
    event_date, start_date_local = competition_start(
        value.get("start_date_local"), value.get("event_date")
    )
    category, priority = competition_category_and_priority(value, name)
    result: dict[str, str | int | None] = {
        "id": competition_normalized_id(value.get("id")),
        "name": name,
        "event_date": event_date,
        "start_date_local": start_date_local,
        "priority": priority,
        "category": category,
        "moving_time": competition_moving_time(value.get("moving_time")),
    }
    result.update(competition_normalized_text_fields(value))
    return result
