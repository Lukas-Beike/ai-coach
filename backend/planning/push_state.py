"""Which explicit pushes a planned unit still needs, for the calendar sync button.

Read-only projection over stored planned units and their remote links. A unit
still needs Intervals.icu when it was never synced, failed or went missing
remotely; it needs Garmin when it is a strength unit with a structure whose
current payload was not yet pushed there. The payload hash is the one the
``plan_push`` jobs check, so the browser can send it back unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final

from backend.canonical.planning_fields import STRENGTH_STRUCTURE
from backend.canonical.vocabulary import ProviderId, RemoteEntityKind, Sport
from backend.db.remote_links import RemoteLinkRepository
from backend.planning.library import library_payload_hash
from backend.planning.sport import planned_sport_environment

# States from which an explicit Intervals.icu push helps; a conflict needs a
# decision first, and "syncing" is already on its way.
_INTERVALS_PENDING: Final = frozenset({"local", "sync_error", "remote_missing"})
_REMOTE_LINKS = RemoteLinkRepository()


def garmin_baselines(db: Any) -> dict[str, str | None]:
    """Return the pushed payload hash per planned unit linked at Garmin."""
    return {
        link.local_id: link.baseline_hash
        for link in _REMOTE_LINKS.list_for_provider(
            db, ProviderId.GARMIN.value, RemoteEntityKind.PLANNED_UNIT
        )
    }


def _garmin_capable(payload: dict[str, Any]) -> bool:
    structure = payload.get(STRENGTH_STRUCTURE)
    if not isinstance(structure, list) or not structure:
        return False
    sport, _environment = planned_sport_environment(payload)
    return sport is Sport.STRENGTH


def attach_push_state(
    pairs: Iterable[tuple[Any, dict[str, Any]]], baselines: dict[str, str | None]
) -> None:
    """Add ``payload_hash`` and ``push_pending`` to each (row, payload) pair."""
    for row, payload in pairs:
        digest = library_payload_hash(row["payload"])
        pending: dict[str, bool] = {
            ProviderId.INTERVALS.value: str(row["sync_state"] or "local")
            in _INTERVALS_PENDING
        }
        if _garmin_capable(payload):
            pending[ProviderId.GARMIN.value] = (
                baselines.get(str(row["local_id"])) != digest
            )
        payload["payload_hash"] = digest
        payload["push_pending"] = pending
