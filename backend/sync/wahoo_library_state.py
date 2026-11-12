"""Wahoo sync state of library workouts, for the library view (#1769).

Read-only. A workout exported to Wahoo is ``synced`` while the plan it would be
sent as now (its text plus the current athlete references) hashes to the
baseline the last export stored, and ``changed`` otherwise: an edit, a
threshold change behind a relative step, or a workout that no longer maps to a
Wahoo plan. Nothing here writes to Wahoo; the athlete sends from the library
through the existing ``plan_push`` job, which carries the payload hash returned
here.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final

from backend.canonical.vocabulary import WAHOO_ID, RemoteEntityKind, RemoteLinkState
from backend.db import DatabaseManager
from backend.db.remote_links import RemoteLinkRepository
from backend.planning.library import library_payload_hash
from backend.sync.wahoo_plan_push import plan_baseline
from backend.sync.wahoo_workout_export import WahooWorkoutExport

STATE_SYNCED: Final = "synced"
STATE_CHANGED: Final = "changed"
_REMOTE_LINKS = RemoteLinkRepository()


class WahooLibraryState:
    """Compare each exported library workout with what Wahoo last received."""

    def __init__(
        self,
        *,
        configured: Callable[[], bool],
        database_manager: Callable[[], DatabaseManager],
        export: Callable[[], WahooWorkoutExport],
    ) -> None:
        self._configured = configured
        self._database_manager = database_manager
        self._export = export

    def states(self, rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
        """Return ``{local_id: {state, payload_hash}}`` for the exported rows.

        Each row needs ``local_id`` and the raw stored ``payload``. Workouts
        without a delivered Wahoo plan get no entry, and nothing is read from
        the thresholds unless one is linked.
        """
        rows = list(rows)
        if not rows or not self._configured():
            return {}
        with self._database_manager().reader() as db:
            baselines = {
                link.local_id: link.baseline_hash
                for link in _REMOTE_LINKS.list_for_provider(
                    db, WAHOO_ID, RemoteEntityKind.LIBRARY_WORKOUT
                )
                if link.remote_id and link.sync_state is RemoteLinkState.SYNCED
            }
        linked = [row for row in rows if str(row["local_id"]) in baselines]
        if not linked:
            return {}
        export = self._export()
        return {
            str(row["local_id"]): {
                "state": STATE_SYNCED
                if baselines[str(row["local_id"])] == _current_baseline(export, row)
                else STATE_CHANGED,
                "payload_hash": library_payload_hash(row["payload"]),
            }
            for row in linked
        }


def _current_baseline(export: WahooWorkoutExport, row: Mapping[str, Any]) -> str | None:
    """The baseline an export now would store, or ``None`` when it cannot map."""
    try:
        stored = json.loads(row["payload"] or "{}")
        workout = {**stored, "local_id": str(row["local_id"])}
        return plan_baseline(export.serialize_library(workout)["plan"])
    except Exception:  # noqa: BLE001 - a workout Wahoo cannot take counts as changed
        return None
