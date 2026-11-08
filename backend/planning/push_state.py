"""Which explicit pushes a planned unit still needs, for the calendar sync button.

Read-only projection over stored planned units and their remote links. A unit
still needs Intervals.icu when it was never synced, failed or went missing
remotely (strength goes there as a note); it needs Garmin when it is a
strength unit with a valid structure whose Garmin fingerprint differs from the
pushed one. The payload hash is the
one the ``plan_push`` jobs check, so the browser can send it back unchanged.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any, Final

from backend.canonical.planning_fields import STRENGTH_STRUCTURE
from backend.canonical.vocabulary import ProviderId, RemoteEntityKind, Sport
from backend.db.remote_links import RemoteLinkRepository
from backend.errors import AppError
from backend.planning import strength_structure
from backend.planning.library import library_payload_hash
from backend.planning.sport import planned_sport_environment
from backend.providers.garmin_strength_workout import (
    GarminExercise,
    GarminStrengthMappingError,
    resolve_exercise,
    resolved_exercises,
    suggestions,
)

# States from which an explicit Intervals.icu push helps; a conflict needs a
# decision first, and "syncing" is already on its way.
_INTERVALS_PENDING: Final = frozenset({"local", "sync_error", "remote_missing"})
_REMOTE_LINKS = RemoteLinkRepository()


def garmin_baselines(db: Any) -> dict[str, str | None]:
    """Return the pushed Garmin fingerprint per planned unit linked at Garmin."""
    return {
        link.local_id: link.baseline_hash
        for link in _REMOTE_LINKS.list_for_provider(
            db, ProviderId.GARMIN.value, RemoteEntityKind.PLANNED_UNIT
        )
    }


def garmin_fingerprint(payload: dict[str, Any]) -> str | None:
    """Fingerprint of what a Garmin push sends: name, date and the structure.

    Intervals.icu syncs and focus edits rewrite other payload fields, so the
    Garmin push state compares only this. ``None`` when the unit cannot be
    pushed (not strength, or no valid structure).
    """
    sport, _environment = planned_sport_environment(payload)
    if sport is not Sport.STRENGTH:
        return None
    try:
        exercises = strength_structure.normalize_structure(
            payload.get(STRENGTH_STRUCTURE)
        )
    except AppError:
        return None
    if not exercises:
        return None
    content = {
        "name": str(payload.get("name") or ""),
        "date": str(payload.get("date") or "")[:10],
        "exercises": exercises,
    }
    serialized = json.dumps(content, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _pushable_fingerprint(
    payload: dict[str, Any], remembered: Mapping[str, GarminExercise]
) -> tuple[str | None, str | None]:
    """The Garmin fingerprint when every exercise maps, else why Garmin is blocked.

    A strength unit without a valid structure is ``no_structure``; one with an
    unmapped exercise is ``unmapped``, since every push would fail. No button is
    offered either way; the Coach or the job still names the exercise with
    catalogue suggestions. Other sports return ``(None, None)``.
    """
    fingerprint = garmin_fingerprint(payload)
    if fingerprint is None:
        sport, _environment = planned_sport_environment(payload)
        return None, ("no_structure" if sport is Sport.STRENGTH else None)
    try:
        resolved_exercises(
            strength_structure.normalize_structure(payload.get(STRENGTH_STRUCTURE))
            or [],
            remembered,
        )
    except AppError, GarminStrengthMappingError:
        return None, "unmapped"
    return fingerprint, None


def unmapped_exercises(
    payload: dict[str, Any], remembered: Mapping[str, GarminExercise]
) -> list[dict[str, Any]]:
    """Each exercise without a Garmin match: its index, name and suggestions."""
    try:
        exercises = strength_structure.normalize_structure(
            payload.get(STRENGTH_STRUCTURE)
        )
    except AppError:
        return []
    return [
        {
            "index": index,
            "name": item["name"],
            "suggestions": suggestions(item.get("garmin_exercise") or item["name"]),
        }
        for index, item in enumerate(exercises or [])
        if resolve_exercise(item, remembered) is None
    ]


def attach_push_state(
    pairs: Iterable[tuple[Any, dict[str, Any]]],
    baselines: dict[str, str | None],
    remembered: Mapping[str, GarminExercise] | None = None,
) -> None:
    """Add ``payload_hash``, ``push_pending`` and ``push_blocked`` to each pair.

    ``push_blocked`` names why a strength unit cannot reach Garmin, so the
    calendar says so instead of offering only Intervals.icu silently.
    """
    for row, payload in pairs:
        digest = library_payload_hash(row["payload"])
        pending: dict[str, bool] = {
            ProviderId.INTERVALS.value: str(row["sync_state"] or "local")
            in _INTERVALS_PENDING
        }
        # A unit in a sync conflict needs the athlete's decision first; no
        # provider is offered, so the conflicted version never reaches the watch.
        conflicted = str(row["sync_state"] or "") == "conflict"
        fingerprint, blocked = _pushable_fingerprint(payload, remembered or {})
        if fingerprint is not None:
            pending[ProviderId.GARMIN.value] = (
                not conflicted and baselines.get(str(row["local_id"])) != fingerprint
            )
        payload["payload_hash"] = digest
        payload["push_pending"] = pending
        payload["push_blocked"] = (
            {ProviderId.GARMIN.value: blocked} if blocked is not None else {}
        )
        payload["push_unmapped"] = (
            unmapped_exercises(payload, remembered or {})
            if blocked == "unmapped"
            else []
        )
