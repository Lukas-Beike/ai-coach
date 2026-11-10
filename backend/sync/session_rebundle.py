"""One-time re-bundling of stored Garmin and Wahoo copies after a matching change (#1954).

Session bundling runs only when an ingest or re-projection touches a day, so
copies stored before the matching rule widened stay separate sessions.
``SessionRebundle`` is a follow-up stage of the canonical backfill worker: once
per ``VERSION`` it runs the regular session linking (``link_activity_sessions``,
the entry point ingest uses, with no second matching rule) on every day holding
an active Garmin and an active Wahoo record.

Linking never touches hidden or deleted sessions or athlete-confirmed sessions,
and it never splits a session. The whole pass is one transaction: a failure
leaves the data unchanged and the next pass retries. The state and the log line
hold counts only, never names, dates or activity content.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, date, tzinfo
from typing import Any, Final

from backend.activities.session_linking import link_activity_sessions
from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_store
from backend.db.repositories import KeyValueRepository
from backend.sync.canonical_backfill import BatchReport

STAGE: Final = "session_rebundle"
STATE_KEY: Final = "session_rebundle_state"
# Bump to run the pass once more after the matching rules change again.
VERSION: Final = 1
_PROVIDERS: Final = (ProviderId.GARMIN.value, ProviderId.WAHOO.value)
_LOGGER = logging.getLogger("intervals_coach")


class SessionRebundle:
    """Link stored Garmin and Wahoo copies of one session, once per version."""

    stage = STAGE

    def __init__(
        self,
        *,
        key_values: KeyValueRepository,
        clock: Callable[[], str],
        zone_provider: Callable[[], tzinfo | None],
        database_manager: Callable[[], Any],
    ) -> None:
        self._key_values = key_values
        self._clock = clock
        self._zone_provider = zone_provider
        self._database_manager = database_manager

    def run_batch(self, db: Any) -> BatchReport:
        """Link every eligible day in the caller's transaction, once."""
        state = _load_state(self._key_values, db)
        if state.get("version") == VERSION and state.get("status") == "complete":
            return BatchReport(items=0, done=True)
        zone = self._zone_provider() or UTC
        now = self._clock()
        days = canonical_store.linkable_dates_with_providers(db, _PROVIDERS)
        linked = sum(
            link_activity_sessions(
                db, touched_dates={date.fromisoformat(day)}, zone=zone, now=now
            )
            for day in days
        )
        counts = {"days": len(days), "linked": linked}
        self._save(
            db,
            {
                "version": VERSION,
                "status": "complete",
                "completed_at": now,
                "counts": counts,
            },
        )
        # Logged only once the transaction committed.
        self._database_manager().after_commit(lambda: _log_completed(counts))
        return BatchReport(items=linked, done=True)

    def mark_failed(self, db: Any) -> None:
        state = _load_state(self._key_values, db)
        self._save(db, {**state, "status": "failed"})

    def _save(self, db: Any, state: Mapping[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )


def summarize_session_rebundle(
    key_values: KeyValueRepository, db: Any
) -> dict[str, Any]:
    """Content-free status and counts, for diagnostics."""
    state = _load_state(key_values, db)
    stored = state.get("counts")
    counts: Mapping[str, Any] = stored if isinstance(stored, dict) else {}
    return {
        "status": state.get("status", "pending"),
        "version": state.get("version"),
        "counts": {name: int(counts.get(name) or 0) for name in ("days", "linked")},
    }


def _log_completed(counts: Mapping[str, int]) -> None:
    _LOGGER.info(
        "Session rebundle completed",
        extra={"event": "session_rebundle_completed", "context": dict(counts)},
    )


def _load_state(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    raw = key_values.get(db, STATE_KEY)
    try:
        state = json.loads(raw) if raw else {}
    except ValueError:
        state = {}
    return state if isinstance(state, dict) else {}
