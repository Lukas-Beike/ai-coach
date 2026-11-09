"""One-time backfill of the session focus of future planned units (#1849).

``SessionFocusBackfill`` is a follow-up stage of the canonical backfill worker.
Once per ``VERSION`` it stores, on every **future** local planned unit that lacks
it, the focus (and for strength the intensity) that ``unambiguous_values``
derives without doubt. Past units, archived units and anything contested stay
untouched, and the stage never invents strength exercises. The stored value
equals what the calendar chip already shows as a derived suggestion.

Each write is a focus-only edit: it keeps the sync state, is recorded in the
change history and never reaches a provider. The stage keeps the references of
its changes in its state row, so ``undo`` restores all of them in one
transaction (or none, when one unit was edited since). The state holds counts
and change references only, never names or dates.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from typing import Any, Final

from backend import change_history
from backend.activities.workout_load import WorkoutEstimate
from backend.canonical.vocabulary import Sport
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.history.undo_service import HistoryUndoService
from backend.planning.session_focus import (
    FOCUS_KEY,
    allowed_foci,
    unambiguous_values,
)
from backend.planning.sport import planned_sport_environment
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.canonical_backfill import BatchReport

STAGE: Final = "session_focus_backfill"
STATE_KEY: Final = "session_focus_backfill_state"
# Bump to run the step once more after the derivation rules change.
VERSION: Final = 1
# The repository never returns more future units than this; every plan check
# sees the same window.
MAX_UNITS: Final = 1000
_ESTIMATED = frozenset({Sport.RUN, Sport.RIDE})


class SessionFocusBackfill:
    """Fill unambiguous derived focus values on future units, once per version."""

    stage = STAGE

    def __init__(
        self,
        *,
        key_values: KeyValueRepository,
        clock: Callable[[], str],
        future_units: Callable[[int], list[dict[str, Any]]],
        estimator: Callable[[], Callable[[Mapping[str, Any]], WorkoutEstimate]],
        update_unit: Callable[..., Any],
        bump_planning_revision: Callable[[Any], None],
        database_manager: Callable[[], Any],
        history_undo: Callable[[], HistoryUndoService],
        database_lock: threading.RLock,
        maintenance_gate: MaintenanceGate,
        publish_change: Callable[[], object],
    ) -> None:
        self._key_values = key_values
        self._clock = clock
        self._future_units = future_units
        self._estimator = estimator
        self._update_unit = update_unit
        self._bump = bump_planning_revision
        self._database_manager = database_manager
        self._history_undo = history_undo
        self._database_lock = database_lock
        self._maintenance_gate = maintenance_gate
        self._publish_change = publish_change

    def run_batch(self, db: Any) -> BatchReport:
        """Fill every eligible future unit in the caller's transaction, once."""
        state = _load_state(self._key_values, db)
        if state.get("version") == VERSION and state.get("status") == "complete":
            return BatchReport(items=0, done=True)
        counts = {"focus": 0, "intensity": 0, "undecided": 0, "skipped": 0}
        estimate = self._estimator()
        units = self._future_units(MAX_UNITS)
        with change_history.collect_changes() as changes:
            for unit in units:
                self._fill(db, unit, estimate, counts)
        if changes:
            self._bump(db)
            self._database_manager().after_commit(self._publish_change)
        # Earlier passes stay undoable together with this one.
        kept = [] if state.get("undone_at") else list(state.get("changes") or [])
        # A unit the calendar checks refused is tried again on the next pass.
        complete = not counts["skipped"]
        self._save(
            db,
            {
                "version": VERSION,
                "status": "complete" if complete else "incomplete",
                "completed_at": self._clock(),
                "counts": counts,
                "truncated": len(units) >= MAX_UNITS,
                "changes": [*kept, *changes],
            },
        )
        return BatchReport(items=len(changes), done=True)

    def _fill(
        self,
        db: Any,
        unit: Mapping[str, Any],
        estimate: Callable[[Mapping[str, Any]], WorkoutEstimate],
        counts: dict[str, int],
    ) -> None:
        sport = planned_sport_environment(unit)[0]
        values = unambiguous_values(
            unit, estimate(unit) if sport in _ESTIMATED else None
        )
        if values:
            try:
                self._update_unit(
                    str(unit.get("local_id") or unit.get("id")),
                    values,
                    skip_calendar_conflict=True,
                    bump_planning_revision=False,
                    db=db,
                )
            except AppError:
                # Refused before any write (calendar markers, pending refresh).
                counts["skipped"] += 1
                return
            counts["focus"] += FOCUS_KEY in values
            counts["intensity"] += len(values) - (FOCUS_KEY in values)
        if allowed_foci(sport) and FOCUS_KEY not in values and not unit.get(FOCUS_KEY):
            counts["undecided"] += 1

    def mark_failed(self, db: Any) -> None:
        state = _load_state(self._key_values, db)
        self._save(db, {**state, "status": "failed"})

    def summary(self, db: Any) -> dict[str, Any]:
        """Content-free status and counts, for diagnostics."""
        state = _load_state(self._key_values, db)
        return summarize_state(state)

    def undo(self) -> dict[str, Any]:
        """Restore every unit the backfill changed, or none of them."""
        history_undo = self._history_undo()
        with (
            self._maintenance_gate.operation(),
            history_undo.profile_mutation_coordinator,
            self._database_lock,
            self._database_manager().unit_of_work() as db,
        ):
            state = _load_state(self._key_values, db)
            changes = state.get("changes")
            if state.get("status") != "complete" or not changes:
                raise AppError(409, "Der Backfill hat nichts geändert.")
            if state.get("undone_at"):
                raise AppError(409, "Der Backfill wurde bereits zurückgenommen.")
            history_undo.apply_many(db, changes)
            self._save(db, {**state, "undone_at": self._clock()})
            self._database_manager().after_commit(self._publish_change)
        return {
            "status": "undone",
            "restored": len(changes),
            "remote_untouched": True,
        }

    def _save(self, db: Any, state: Mapping[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )


def summarize_state(state: Mapping[str, Any]) -> dict[str, Any]:
    counts = state.get("counts")
    return {
        "status": state.get("status", "pending"),
        "version": state.get("version"),
        "counts": counts if isinstance(counts, dict) else {},
        "truncated": bool(state.get("truncated")),
        "undone": bool(state.get("undone_at")),
    }


def summarize_session_focus_backfill(
    key_values: KeyValueRepository, db: Any
) -> dict[str, Any]:
    return summarize_state(_load_state(key_values, db))


def _load_state(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    raw = key_values.get(db, STATE_KEY)
    try:
        state = json.loads(raw) if raw else {}
    except ValueError:
        state = {}
    return state if isinstance(state, dict) else {}
