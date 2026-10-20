"""Copy stored activity detail records into the canonical detail tables, once.

The backfill runs after the canonical backfill has completed. It reads each
``activity_detail:<sha>`` kv record in key order and hands it to the writer, which
skips a record whose activity already holds a fresh load. Each batch commits its
canonical rows and its cursor in one writer transaction, so a failed batch rolls
back and the next run resumes from the last committed key. The kv records are only
read; they are never deleted or modified. A change of the mapper or analysis version
starts the pass again from the first record.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Final

from backend.activities.detail_store import ActivityDetailStore
from backend.db.repositories import KeyValueRepository
from backend.providers.intervals_activity_detail_mapping import MAPPER_VERSION
from backend.sync.activity_detail_canonical import (
    ACTIVITY_DETAIL_ANALYSIS_VERSION,
    CanonicalDetailWriter,
    DetailWriteOutcome,
)
from backend.sync.canonical_backfill import BackfillStatus, BatchReport

STATE_KEY: Final = "activity_detail_backfill_state"
DEFAULT_BATCH_SIZE: Final = 20
MIN_BATCH_SIZE: Final = 1
MAX_BATCH_SIZE: Final = 100
STAGE: Final = "activity_details"
_COUNTER_NAMES: Final = (*(outcome.value for outcome in DetailWriteOutcome), "issues")


def _empty_counters() -> dict[str, int]:
    return dict.fromkeys(_COUNTER_NAMES, 0)


def _fresh_state() -> dict[str, Any]:
    return {
        "status": BackfillStatus.PENDING.value,
        "mapper_version": None,
        "analysis_version": None,
        "cursor": "",
        "batches": 0,
        "counters": _empty_counters(),
        "completed_at": None,
    }


def _is_well_formed(state: object) -> bool:
    return (
        isinstance(state, dict)
        and isinstance(state.get("status"), str)
        and isinstance(state.get("cursor"), str)
        and isinstance(state.get("counters"), dict)
        and isinstance(state.get("batches"), int)
    )


class ActivityDetailBackfill:
    """Copies stored detail records one batch at a time. The caller owns the transaction."""

    def __init__(
        self,
        *,
        key_values: KeyValueRepository,
        writer: CanonicalDetailWriter,
        clock: Callable[[], str],
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if not MIN_BATCH_SIZE <= batch_size <= MAX_BATCH_SIZE:
            raise ValueError(
                f"batch_size must be between {MIN_BATCH_SIZE} and {MAX_BATCH_SIZE}"
            )
        self._key_values = key_values
        self._writer = writer
        self._clock = clock
        self._batch_size = batch_size

    @property
    def stage(self) -> str:
        return STAGE

    def run_batch(self, db: Any) -> BatchReport:
        """Copy one batch and write its cursor in the caller's transaction."""
        state = self._load(db)
        if (
            state.get("mapper_version") != MAPPER_VERSION
            or state.get("analysis_version") != ACTIVITY_DETAIL_ANALYSIS_VERSION
        ):
            # A new mapper or analysis version copies every record again.
            state.update(
                mapper_version=MAPPER_VERSION,
                analysis_version=ACTIVITY_DETAIL_ANALYSIS_VERSION,
                cursor="",
                batches=0,
                counters=_empty_counters(),
                completed_at=None,
            )
        elif state["status"] == BackfillStatus.COMPLETE.value:
            return BatchReport(items=0, done=True)
        rows = ActivityDetailStore.records_after(db, state["cursor"], self._batch_size)
        now = self._clock()
        counters = state["counters"]
        for key, record in rows:
            result = self._writer.write_legacy(db, record=record, now=now)
            counters[result.outcome.value] += 1
            counters["issues"] += result.issues
            state["cursor"] = key
        done = len(rows) < self._batch_size
        state["status"] = (
            BackfillStatus.COMPLETE if done else BackfillStatus.RUNNING
        ).value
        state["completed_at"] = now if done else None
        state["batches"] += 1
        self._save(db, state)
        return BatchReport(items=len(rows), done=done)

    def mark_failed(self, db: Any) -> None:
        """Record that the run stopped; the cursor stays at the last committed batch."""
        state = self._load(db)
        state["status"] = BackfillStatus.FAILED.value
        self._save(db, state)

    def summary(self, db: Any) -> dict[str, Any]:
        """Return content-free status, batch count and counters of the current pass."""
        state = self._load(db)
        return {
            "status": state["status"],
            "batches": state["batches"],
            "counters": state["counters"],
        }

    def _load(self, db: Any) -> dict[str, Any]:
        raw = self._key_values.get(db, STATE_KEY)
        if raw is None:
            return _fresh_state()
        try:
            state = json.loads(raw)
        except ValueError:
            return _fresh_state()
        if not _is_well_formed(state):
            return _fresh_state()
        state["counters"] = {**_empty_counters(), **state["counters"]}
        return state

    def _save(self, db: Any, state: dict[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )
