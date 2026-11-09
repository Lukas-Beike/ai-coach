"""One-time removal of the retired weekly plan from the stored profile (#1850).

The weekly plan ("Wochenplan") was a structured JSON string in the stored
profile. The profile no longer reads or writes it, so a stored copy is dead
data. ``ProfileWeeklyPlanRemoval`` is a follow-up stage of the canonical
backfill worker: once per ``VERSION`` it deletes that one key from the stored
profile, nothing else. A database restored from an older backup carries the
older state row, so the stage runs again on it. The state holds a status and a
flag only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from backend.db.repositories import KeyValueRepository, ProfileRepository
from backend.sync.canonical_backfill import BatchReport

STAGE: Final = "profile_weekly_plan_removal"
STATE_KEY: Final = "profile_weekly_plan_removal_state"
VERSION: Final = 1
RETIRED_FIELD: Final = "weekly_plan"


class ProfileWeeklyPlanRemoval:
    """Delete the retired ``weekly_plan`` key from the stored profile, once."""

    stage = STAGE

    def __init__(self, *, key_values: KeyValueRepository, clock: Any) -> None:
        self._key_values = key_values
        self._profile = ProfileRepository(key_values)
        self._clock = clock

    def run_batch(self, db: Any) -> BatchReport:
        state = _load_state(self._key_values, db)
        if state.get("version") == VERSION and state.get("status") == "complete":
            return BatchReport(items=0, done=True)
        removed = self._remove(db)
        self._save(
            db,
            {
                "version": VERSION,
                "status": "complete",
                "completed_at": self._clock(),
                "removed": removed,
            },
        )
        return BatchReport(items=int(removed), done=True)

    def _remove(self, db: Any) -> bool:
        raw = self._profile.get(db)
        try:
            stored = json.loads(raw) if raw else None
        except ValueError:
            return False
        if not isinstance(stored, dict) or RETIRED_FIELD not in stored:
            return False
        del stored[RETIRED_FIELD]
        self._profile.set(db, json.dumps(stored, ensure_ascii=False))
        return True

    def mark_failed(self, db: Any) -> None:
        state = _load_state(self._key_values, db)
        self._save(db, {**state, "status": "failed"})

    def _save(self, db: Any, state: Mapping[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )


def summarize_profile_weekly_plan_removal(
    key_values: KeyValueRepository, db: Any
) -> dict[str, Any]:
    """Content-free status for diagnostics."""
    state = _load_state(key_values, db)
    return {
        "status": state.get("status", "pending"),
        "version": state.get("version"),
        "removed": bool(state.get("removed")),
    }


def _load_state(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    raw = key_values.get(db, STATE_KEY)
    try:
        state = json.loads(raw) if raw else {}
    except ValueError:
        state = {}
    return state if isinstance(state, dict) else {}
