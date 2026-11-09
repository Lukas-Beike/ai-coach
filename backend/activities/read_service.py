"""Completed-activity read use cases backed by the canonical session summaries."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from backend.activities.activity_reference import (
    ActivityReferenceResolver,
    NoActivityReferences,
)
from backend.activities.sync_time import activities_synced_at
from backend.canonical.activity_summary import ActivitySummary
from backend.runtime.ports import (
    ActivityFingerprintReader,
    ActivitySummaryReader,
    ProviderCoverageReader,
)

ALL_DAYS = -1
PAGE_DEFAULT = 100
PAGE_MAX = 250
# Version 3 pages by session start and local session id; older cursors restart.
PAGE_CURSOR_VERSION = 3

type PageKey = tuple[datetime, str]


class ActivitySummarySource(ActivitySummaryReader, ActivityFingerprintReader, Protocol):
    """Session summaries and the fingerprints their stored details compare with."""


def _page_key(summary: ActivitySummary) -> PageKey:
    return (datetime.fromisoformat(summary["started_at"]), summary["id"])


def _encode_cursor(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: Any) -> Any | None:
    if not value:
        return None
    try:
        padding = "=" * (-len(str(value)) % 4)
        return json.loads(base64.urlsafe_b64decode(f"{value}{padding}"))
    except TypeError, ValueError:
        return None


def _encode_page_cursor(summary: ActivitySummary) -> str:
    return _encode_cursor(
        {
            "v": PAGE_CURSOR_VERSION,
            "after": [summary["started_at"], summary["id"]],
            "day": str(summary.get("started_at_local") or "")[:10],
        }
    )


def _decode_page_cursor(value: Any) -> tuple[PageKey, date] | None:
    """Return the last listed key and its local day; None restarts at page one."""
    decoded = _decode_cursor(value)
    if not isinstance(decoded, dict) or decoded.get("v") != PAGE_CURSOR_VERSION:
        return None
    after, day = decoded.get("after"), decoded.get("day")
    if not (isinstance(after, list) and len(after) == 2 and isinstance(day, str)):
        return None
    try:
        started = datetime.fromisoformat(str(after[0]))
        local_day = date.fromisoformat(day)
    except ValueError:
        return None
    if started.tzinfo is None:
        return None
    return (started, str(after[1])), local_day


def _page_limit(raw: Any) -> int:
    try:
        return max(1, min(int(raw), PAGE_MAX))
    except TypeError, ValueError:
        return PAGE_DEFAULT


class ActivityReadService:
    """Own activity listing without provider refreshes: one entry per session."""

    def __init__(
        self,
        database_manager: Any,
        summaries: ActivitySummarySource,
        feedback_service: Any,
        *,
        read_equipment: Callable[[str], dict[str, Any]] = lambda _: {},
        references: ActivityReferenceResolver | None = None,
        coverage: Callable[[], ProviderCoverageReader] | None = None,
    ):
        self._database_manager = database_manager
        self._summaries = summaries
        self._feedback_service = feedback_service
        self._read_equipment = read_equipment
        self._references = NoActivityReferences() if references is None else references
        # Where the activities' sync time comes from; without it the time is unknown.
        self._coverage = coverage

    def _synced_at(self, db: Any) -> Any:
        return activities_synced_at(
            None if self._coverage is None else self._coverage(), db
        )

    def _newest(
        self,
        db: Any,
        count: int,
        *,
        start: date | None,
        after: tuple[PageKey, date] | None,
    ) -> list[ActivitySummary]:
        """Return up to ``count`` newest summaries from ``start`` on, below ``after``.

        The cursor's local day bounds the read (one spare day for zone edges);
        the read grows until enough sessions lie below the cursor key.
        """
        end = None if after is None else after[1] + timedelta(days=1)
        fetch = count
        while True:
            summaries = self._summaries.activity_summaries(
                db, start=start, end=end, limit=fetch
            )
            below = [
                summary
                for summary in summaries
                if after is None or _page_key(summary) < after[0]
            ]
            if len(below) >= count or len(summaries) < fetch:
                return below[:count]
            fetch *= 2

    def page(
        self,
        cursor: Any = None,
        limit: Any = None,
        days: Any = ALL_DAYS,
        *,
        today: date,
    ) -> dict[str, Any]:
        try:
            days_value = int(days)
        except TypeError, ValueError:
            days_value = ALL_DAYS
        start = (
            None
            if days_value == ALL_DAYS
            else today - timedelta(days=max(1, days_value) - 1)
        )
        page_size = _page_limit(limit)
        with self._database_manager.read_snapshot() as db:
            synced_at = self._synced_at(db)
            listed = self._newest(
                db, page_size + 1, start=start, after=_decode_page_cursor(cursor)
            )
            page = listed[:page_size]
        attached = self._feedback_service.attach_to_activities(
            [dict(summary) for summary in page]
        )
        return {
            "snapshot_synced_at": synced_at,
            "activities": attached,
            "next_cursor": _encode_page_cursor(page[-1])
            if len(listed) > len(page)
            else None,
            "limit": page_size,
            "days": days_value,
        }

    def recent(
        self, days: int = ALL_DAYS, limit: int = 250, *, today: date
    ) -> dict[str, Any]:
        """The newest session summaries of the last ``days`` days, for the Coach."""
        start = None if days == ALL_DAYS else today - timedelta(days=days - 1)
        with self._database_manager.read_snapshot() as db:
            synced_at = self._synced_at(db)
            summaries = self._summaries.activity_summaries(
                db, start=start, limit=max(1, min(int(limit), 500))
            )
        return {
            "snapshot_synced_at": synced_at,
            "activities": self._feedback_service.attach_to_activities(
                [dict(summary) for summary in summaries]
            ),
            "days": days,
        }
