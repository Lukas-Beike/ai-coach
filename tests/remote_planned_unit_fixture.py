"""Test fixture: the planned-unit payload the retired Intervals.icu import built."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from backend.athlete.local_date import LocalDate
from backend.canonical.vocabulary import ProviderId
from backend.planning.planned_units import (
    normalize_planned_unit,
    planned_unit_payload_hash,
)
from backend.providers.intervals_workouts import (
    INTERVALS_DEFAULT_WORKOUT_TYPE,
    INTERVALS_STRENGTH_TYPE,
    intervals_event_is_coach_note,
)

_ISO_MIDNIGHT_SUFFIX = "T00:00:00"


def _remote_planned_unit_id(event: dict[str, Any]) -> str | None:
    remote_id = str(event.get("id") or "").strip()
    return remote_id or None


def _remote_planned_unit_date(event: dict[str, Any], *, today: date) -> str | None:
    try:
        event_date = LocalDate.parse(
            event.get("starts_at_local") or event.get("date")
        ).isoformat()
    except TypeError, ValueError:
        return None
    try:
        if date.fromisoformat(event_date) < today:
            return None
    except ValueError:
        return None
    return event_date


def _remote_planned_unit_duration(event: dict[str, Any]) -> int:
    planned_duration_s = event.get("planned_duration_s")
    try:
        return (
            max(5, round(float(planned_duration_s) / 60))
            if planned_duration_s not in (None, "")
            else 30
        )
    except TypeError, ValueError:
        return 30


def remote_planned_unit_payload(
    event: dict[str, Any], *, today: date
) -> tuple[dict[str, Any], str, str] | None:
    coach_note = intervals_event_is_coach_note(event)
    if str(event.get("category") or "WORKOUT").upper() != "WORKOUT" and not coach_note:
        return None
    remote_id = _remote_planned_unit_id(event)
    event_date = _remote_planned_unit_date(event, today=today)
    if not remote_id or not event_date:
        return None
    remote_external_id = str(event.get("external_id") or "").strip()
    identity = remote_external_id or f"intervals-event-{remote_id}"
    planned_duration_s = event.get("planned_duration_s")
    sport_type = (
        event.get("type")
        or event.get("sport")
        # A strength note that lost its type stays strength.
        or (INTERVALS_STRENGTH_TYPE if coach_note else INTERVALS_DEFAULT_WORKOUT_TYPE)
    )
    payload = {
        "date": event_date,
        "starts_at_local": event.get("starts_at_local")
        or event.get("start")
        or event_date + _ISO_MIDNIGHT_SUFFIX,
        "sport": sport_type,
        "type": sport_type,
        "name": event.get("name") or "Intervals.icu-Einheit",
        "description": event.get("description") or "",
        "duration_minutes": _remote_planned_unit_duration(event),
        "planned_duration_s": planned_duration_s,
        "target": event.get("target") or "AUTO",
        "source": ProviderId.INTERVALS.value,
        "origin": ProviderId.INTERVALS.value,
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
    except TypeError, ValueError:
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
