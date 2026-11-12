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
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import TYPE_CHECKING, Any, Final

from backend.canonical.planning_fields import STRENGTH_STRUCTURE
from backend.canonical.vocabulary import ProviderId, RemoteEntityKind, Sport
from backend.db.remote_links import RemoteLinkRepository
from backend.errors import AppError
from backend.planning import strength_structure
from backend.planning.leftovers import nearest_first
from backend.planning.planned_units import plan_push_payload_hash
from backend.planning.sport import planned_sport_environment
from backend.providers.descriptors import WAHOO_ID
from backend.providers.garmin_strength_workout import (
    PAYLOAD_VERSION,
    GarminExercise,
    GarminStrengthMappingError,
    resolve_exercise,
    resolved_exercises,
    suggestions,
)
from backend.providers.intervals_workouts import (
    INTERVALS_EVENT_CATEGORY,
    intervals_event_category,
)

if TYPE_CHECKING:
    from backend.planning.intervals_orphans import IntervalsOrphan
    from backend.planning.leftovers import GarminOrphan
    from backend.planning.wahoo_orphans import WahooOrphan

# States from which an explicit Intervals.icu push helps; "syncing" is already on
# its way.
_INTERVALS_PENDING: Final = frozenset({"local", "sync_error"})
_REMOTE_LINKS = RemoteLinkRepository()


def intervals_event_outdated(payload: Mapping[str, Any]) -> bool:
    """Whether the unit's Intervals.icu event has another category than it gets now.

    A unit sent before the category was recorded counts as a WORKOUT event, the
    category every unit had before strength became a note (#1807): such a strength
    event would keep reaching Garmin as an unstructured copy until it is replaced.
    """
    if not str(payload.get("remote_event_id") or "").strip():
        return False
    sport, _environment = planned_sport_environment(payload)
    sent = str(payload.get("remote_event_category") or INTERVALS_EVENT_CATEGORY)
    return sent != intervals_event_category(sport)


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

    The workout document version is part of it, so a change in how the document
    is built marks units sent in the old form as changed.

    Intervals.icu syncs and focus edits rewrite other payload fields, so the
    Garmin push state compares only this. ``None`` when the unit cannot be
    pushed (not strength, or no valid structure).
    """
    sport, _environment = planned_sport_environment(payload)
    if sport is not Sport.STRENGTH:
        return None
    try:
        exercises = strength_structure.normalize_structure(
            payload.get(STRENGTH_STRUCTURE), stored=True
        )
    except AppError:
        return None
    if not exercises:
        return None
    content = {
        "name": str(payload.get("name") or ""),
        "date": str(payload.get("date") or "")[:10],
        "exercises": exercises,
        "payload_version": PAYLOAD_VERSION,
    }
    serialized = json.dumps(content, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def pushable_fingerprint(
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
            strength_structure.normalize_structure(
                payload.get(STRENGTH_STRUCTURE), stored=True
            )
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
            payload.get(STRENGTH_STRUCTURE), stored=True
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


def _cleanup_lists(
    orphans: Sequence[GarminOrphan],
    intervals_orphans: Sequence[IntervalsOrphan],
    wahoo_orphans: Sequence[WahooOrphan],
) -> dict[str, list[dict[str, str]]]:
    """The leftovers each provider's sync removes, as the calendar receives them."""
    return {
        ProviderId.GARMIN.value: [
            {"id": item.local_id, "name": item.name, "date": item.date}
            for item in orphans
        ],
        ProviderId.INTERVALS.value: [
            {
                "id": item.local_id,
                "name": item.name,
                "date": item.date,
                "hash": item.payload_hash,
            }
            for item in intervals_orphans
        ],
        WAHOO_ID: [
            {"id": item.local_id, "name": item.name, "date": item.date}
            for item in wahoo_orphans
        ],
    }


def _unit_cleanup(
    lists: dict[str, list[dict[str, str]]],
    pending: dict[str, bool],
    payload: dict[str, Any],
    today: date,
) -> dict[str, list[dict[str, str]]]:
    """The leftovers each provider removes with the sync of this upcoming unit.

    Every unit a provider waits for carries them; the calendar collects them
    once and gives each to the week sync button of its own day's week.
    """
    if str(payload.get("date") or "")[:10] < today.isoformat():
        return {}
    return {
        provider: items
        for provider, items in lists.items()
        if items and pending.get(provider)
    }


def attach_push_state(
    pairs: Iterable[tuple[Any, dict[str, Any]]],
    baselines: dict[str, str | None],
    remembered: Mapping[str, GarminExercise] | None = None,
    resync: frozenset[str] | set[str] = frozenset(),
    orphans: Sequence[GarminOrphan] = (),
    intervals_orphans: Sequence[IntervalsOrphan] = (),
    today: date = date.min,
    wahoo_orphans: Sequence[WahooOrphan] = (),
) -> None:
    """Add ``payload_hash``, ``push_pending`` and ``push_blocked`` to each pair.

    An upcoming unit a provider waits for also lists, per provider, the
    leftovers its sync removes (``push_cleanup``): ``orphans`` are Garmin
    workouts, ``intervals_orphans`` Intervals.icu events of deleted or replaced
    units, ``wahoo_orphans`` Wahoo plans of deleted library entries. Leftovers no
    unit waits to carry (no pending unit, and Wahoo never has one) go on the
    unit nearest to ``today``, so the calendar can always offer their removal.

    ``resync`` holds the local ids of synced units whose exported heart-rate range
    moved only with the threshold HR. ``push_blocked`` names why a strength unit cannot reach Garmin, so the
    calendar says so instead of offering only Intervals.icu silently.
    """
    lists = _cleanup_lists(orphans, intervals_orphans, wahoo_orphans)
    payloads: list[dict[str, Any]] = []
    for row, payload in pairs:
        payloads.append(payload)
        digest = plan_push_payload_hash(row["payload"])
        pending: dict[str, bool] = {
            ProviderId.INTERVALS.value: _intervals_pending(row, payload, resync)
        }
        fingerprint, blocked = pushable_fingerprint(payload, remembered or {})
        if fingerprint is not None:
            pending[ProviderId.GARMIN.value] = (
                baselines.get(str(row["local_id"])) != fingerprint
            )
        payload["payload_hash"] = digest
        payload["push_pending"] = pending
        cleanup = _unit_cleanup(lists, pending, payload, today)
        if cleanup:
            payload["push_cleanup"] = cleanup
        payload["push_blocked"] = (
            {ProviderId.GARMIN.value: blocked} if blocked is not None else {}
        )
        payload["push_unmapped"] = (
            unmapped_exercises(payload, remembered or {})
            if blocked == "unmapped"
            else []
        )
    _carry_unclaimed_cleanup(lists, payloads, today)


def _intervals_pending(
    row: Any, payload: dict[str, Any], resync: Iterable[str]
) -> bool:
    """Whether Intervals.icu waits for this unit.

    A synced run unit whose heart-rate range moved with the threshold HR (the bpm
    path of the cap export) is changed too, and so is a unit whose event has
    another category than it gets now.
    """
    return (
        str(row["sync_state"] or "local") in _INTERVALS_PENDING
        or str(row["local_id"]) in resync
        or intervals_event_outdated(payload)
    )


def _carry_unclaimed_cleanup(
    lists: dict[str, list[dict[str, str]]],
    payloads: list[dict[str, Any]],
    today: date,
) -> None:
    """Put each provider's leftovers on one unit when no pending unit carries them.

    Only units the calendar renders qualify: a deleted or archived carrier would
    hide the leftover item.
    """
    visible = [
        p for p in payloads if not p.get("local_deleted") and not p.get("archived")
    ]
    carrier = next(
        iter(nearest_first(visible, today, lambda p: str(p.get("date") or "")[:10])),
        None,
    )
    if carrier is None:
        return
    for provider, items in lists.items():
        if items and not any(provider in p.get("push_cleanup", {}) for p in visible):
            carrier.setdefault("push_cleanup", {})[provider] = items
