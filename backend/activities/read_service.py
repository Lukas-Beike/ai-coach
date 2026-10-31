"""Completed-activity read use cases backed by the canonical activity rows."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from backend.activities.activity_reference import (
    ActivityReferenceResolver,
    NoActivityReferences,
)
from backend.activities.detail_store import ActivityDetailStore, summary_fingerprint
from backend.activities.matching import record_date
from backend.activities.sync_time import activities_synced_at
from backend.runtime.ports import (
    ActivityRowReader,
    ProviderCoverageReader,
    ProviderSnapshotReader,
)

ALL_DAYS = -1
PAGE_DEFAULT = 100
PAGE_MAX = 250
PAGE_CURSOR_VERSION = 2


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _page_key(activity: dict[str, Any]) -> tuple[str, str]:
    return (
        str(_first_present(activity, ("start_date_local", "start_date", "date")) or "")[
            :40
        ],
        str(_first_present(activity, ("id", "activityId", "external_id")) or ""),
    )


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


def _encode_page_cursor(key: tuple[str, str]) -> str:
    return _encode_cursor({"v": PAGE_CURSOR_VERSION, "after": list(key)})


def _decode_page_cursor(value: Any) -> tuple[str, str] | None:
    """Accept the versioned cursor and the unversioned list cursor of older clients."""
    decoded = _decode_cursor(value)
    if isinstance(decoded, dict) and decoded.get("v") == PAGE_CURSOR_VERSION:
        after = decoded.get("after")
    elif isinstance(decoded, list):
        after = decoded
    else:
        return None
    if isinstance(after, list) and len(after) == 2:
        return (str(after[0]), str(after[1]))
    return None


def _page_limit(raw: Any) -> int:
    try:
        return max(1, min(int(raw), PAGE_MAX))
    except TypeError, ValueError:
        return PAGE_DEFAULT


class ActivityReadService:
    """Own activity listing without provider refreshes."""

    def __init__(
        self,
        database_manager: Any,
        snapshot_reader: ProviderSnapshotReader,
        row_reader: ActivityRowReader,
        feedback_service: Any,
        detail_store: ActivityDetailStore | None = None,
        *,
        read_equipment: Callable[[str], dict[str, Any]] = lambda _: {},
        references: ActivityReferenceResolver | None = None,
        summary_rows: ActivityRowReader | None = None,
        coverage: Callable[[], ProviderCoverageReader] | None = None,
    ):
        self._database_manager = database_manager
        self._snapshot_reader = snapshot_reader
        self._row_reader = row_reader
        self._feedback_service = feedback_service
        self._detail_store = detail_store
        self._read_equipment = read_equipment
        self._references = NoActivityReferences() if references is None else references
        # Full rows, as fingerprinted by detail prefetch; the listed rows may be compact.
        self._summary_rows = summary_rows
        # Where the activities' sync time comes from; without it the time is unknown.
        self._coverage = coverage

    def _read(self) -> tuple[Any, list[dict[str, Any]]]:
        """Read the sync time and the activity rows in one read snapshot."""
        with self._database_manager.read_snapshot() as db:
            rows = self._row_reader.activity_rows(db)
            synced_at = activities_synced_at(
                None if self._coverage is None else self._coverage(), db
            )
        return synced_at, list(rows)

    def _with_local_ids(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        local_ids = self._references.local_ids(_page_key(item)[1] for item in items)
        for item in items:
            item["local_activity_id"] = local_ids.get(_page_key(item)[1])
        return items

    def _detail_errors(self, page: list[dict[str, Any]]) -> dict[str, str]:
        """Name the detail failure recorded for each listed activity's summary."""
        if self._detail_store is None:
            return {}
        failures = self._detail_store.failures(_page_key(item)[1] for item in page)
        if not failures or self._summary_rows is None:
            return {key: failure["message"] for key, failure in failures.items()}
        with self._database_manager.read_snapshot() as db:
            rows = self._summary_rows.activity_rows(db)
        fingerprints = {
            str(row.get("id")): summary_fingerprint(row)
            for row in rows
            if str(row.get("id")) in failures
        }
        # A note left by another summary version no longer describes this one.
        return {
            key: failure["message"]
            for key, failure in failures.items()
            if failure.get("summary_sha256") == fingerprints.get(key)
        }

    def page(
        self,
        cursor: Any = None,
        limit: Any = None,
        days: Any = ALL_DAYS,
        *,
        today: date,
    ) -> dict[str, Any]:
        synced_at, activities = self._read()
        try:
            days_value = int(days)
        except TypeError, ValueError:
            days_value = ALL_DAYS
        if days_value != ALL_DAYS:
            cutoff = today - timedelta(days=max(1, days_value) - 1)
            activities = [
                item
                for item in activities
                if record_date(_page_key(item)[0]) >= cutoff.isoformat()
            ]
        activities.sort(key=_page_key, reverse=True)
        after = _decode_page_cursor(cursor)
        if after is not None:
            activities = [item for item in activities if _page_key(item) < after]
        page_size = _page_limit(limit)
        page = activities[:page_size]
        failures = self._detail_errors(page)
        attached = self._with_local_ids(
            self._feedback_service.attach_to_activities(page)
        )
        for item in attached:
            item["detail_error"] = failures.get(_page_key(item)[1])
        return {
            "snapshot_synced_at": synced_at,
            "activities": attached,
            "next_cursor": _encode_page_cursor(_page_key(page[-1]))
            if len(activities) > len(page) and page
            else None,
            "limit": page_size,
            "days": days_value,
        }

    def recent(
        self, days: int = ALL_DAYS, limit: int = 250, *, today: date
    ) -> dict[str, Any]:
        synced_at, activities = self._read()
        if days != ALL_DAYS:
            cutoff = today - timedelta(days=days - 1)
            activities = [
                activity
                for activity in activities
                if record_date(
                    _first_present(activity, ("start_date_local", "start_date", "date"))
                )
                >= cutoff.isoformat()
            ]
        return {
            "snapshot_synced_at": synced_at,
            "activities": self._with_local_ids(
                self._feedback_service.attach_to_activities(
                    activities[: max(1, min(int(limit), 500))]
                )
            ),
            "days": days,
        }
