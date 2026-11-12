"""One-time removal of the retired Garmin rating backfill's state (#2067).

The one-off ``rating_backfill`` chain finished in production and its code is gone.
``RatingBackfillRemoval`` is a follow-up stage of the canonical backfill worker:
once per ``VERSION`` it deletes the chain's own state key and its ``rating_history``
cursor, nothing else. Stored jobs of the removed type stay as history; the queue
already settles a leftover one (an interrupted run is not replayed, a queued one
fails with ``invalid_job_request``). A database restored from an older backup
carries no state row of this stage, so it runs again on it. The state holds a
status and counts only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from backend.canonical.vocabulary import GARMIN_ID
from backend.db.repositories import KeyValueRepository
from backend.sync.canonical_backfill import BatchReport

STAGE: Final = "rating_backfill_removal"
STATE_KEY: Final = "rating_backfill_removal_state"
VERSION: Final = 1
RETIRED_STATE_KEY: Final = "garmin_rating_backfill_state"
RETIRED_CURSOR: Final = (GARMIN_ID, "rating_history")


class RatingBackfillRemoval:
    """Delete the retired rating backfill's state key and cursor, once."""

    stage = STAGE

    def __init__(self, *, key_values: KeyValueRepository, clock: Any) -> None:
        self._key_values = key_values
        self._clock = clock

    def run_batch(self, db: Any) -> BatchReport:
        state = self._state(db)
        if state.get("version") == VERSION and state.get("status") == "complete":
            return BatchReport(items=0, done=True)
        removed = {
            "state_keys": db.execute(
                "DELETE FROM kv WHERE key = ?", (RETIRED_STATE_KEY,)
            ).rowcount,
            "cursors": db.execute(
                "DELETE FROM provider_sync_cursors WHERE provider = ? AND stream = ?",
                RETIRED_CURSOR,
            ).rowcount,
        }
        self._save(
            db,
            {
                "version": VERSION,
                "status": "complete",
                "completed_at": self._clock(),
                "removed": removed,
            },
        )
        return BatchReport(items=sum(removed.values()), done=True)

    def mark_failed(self, db: Any) -> None:
        self._save(db, {**self._state(db), "status": "failed"})

    def _state(self, db: Any) -> dict[str, Any]:
        try:
            state = json.loads(self._key_values.get(db, STATE_KEY) or "{}")
        except ValueError:
            return {}
        return state if isinstance(state, dict) else {}

    def _save(self, db: Any, state: Mapping[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )
