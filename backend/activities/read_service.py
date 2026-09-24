"""Completed-activity read use cases backed by the durable snapshot."""

from __future__ import annotations

import base64
import json
from datetime import date, timedelta
from typing import Any

from backend.activities import detail_projection
from backend.activities.matching import record_date
from backend.errors import AppError
from backend.performance import activity_validation
from backend.performance import context as performance_context
from backend.sync.snapshots import latest_snapshot

ALL_DAYS = -1
PAGE_DEFAULT = 100
PAGE_MAX = 250


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
    except (TypeError, ValueError):
        return None


def _page_limit(raw: Any) -> int:
    try:
        return max(1, min(int(raw), PAGE_MAX))
    except (TypeError, ValueError):
        return PAGE_DEFAULT


class ActivityReadService:
    """Own activity listing and detailed analysis without provider refreshes."""

    def __init__(
        self, database_manager: Any, snapshot_repository: Any, feedback_service: Any
    ):
        self._database_manager = database_manager
        self._snapshot_repository = snapshot_repository
        self._feedback_service = feedback_service

    def _snapshot(self) -> dict[str, Any]:
        with self._database_manager.unit_of_work() as db:
            snapshot = latest_snapshot(db, self._snapshot_repository)
        return snapshot if isinstance(snapshot, dict) else {}

    @staticmethod
    def _activities(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        values = snapshot.get("recent_activities")
        return (
            [item for item in values if isinstance(item, dict)]
            if isinstance(values, list)
            else []
        )

    def page(
        self,
        cursor: Any = None,
        limit: Any = None,
        days: Any = ALL_DAYS,
        *,
        today: date,
    ) -> dict[str, Any]:
        snapshot = self._snapshot()
        activities = self._activities(snapshot)
        try:
            days_value = int(days)
        except (TypeError, ValueError):
            days_value = ALL_DAYS
        if days_value != ALL_DAYS:
            cutoff = today - timedelta(days=max(1, days_value) - 1)
            activities = [
                item
                for item in activities
                if record_date(_page_key(item)[0]) >= cutoff.isoformat()
            ]
        activities.sort(key=_page_key, reverse=True)
        decoded = _decode_cursor(cursor)
        if isinstance(decoded, list) and len(decoded) == 2:
            after = (str(decoded[0]), str(decoded[1]))
            activities = [item for item in activities if _page_key(item) < after]
        page_size = _page_limit(limit)
        page = activities[:page_size]
        return {
            "snapshot_synced_at": snapshot.get("synced_at"),
            "activities": self._feedback_service.attach_to_activities(page),
            "next_cursor": _encode_cursor(_page_key(page[-1]))
            if len(activities) > len(page) and page
            else None,
            "limit": page_size,
            "days": days_value,
        }

    def recent(
        self, days: int = ALL_DAYS, limit: int = 250, *, today: date
    ) -> dict[str, Any]:
        snapshot = self._snapshot()
        values = snapshot.get("recent_activities")
        activities = values if isinstance(values, list) else []
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
            "snapshot_synced_at": snapshot.get("synced_at"),
            "activities": self._feedback_service.attach_to_activities(
                activities[: max(1, min(int(limit), 500))]
            ),
            "days": days,
        }

    def detail(
        self,
        activity_id: Any,
        *,
        garmin_snapshot: dict[str, Any],
        profile: dict[str, Any],
        today: date,
    ) -> dict[str, Any]:
        normalized_id = str(activity_id or "").strip()
        if not normalized_id or len(normalized_id) > 200:
            raise AppError(
                400,
                "Die Aktivität konnte nicht eindeutig zugeordnet werden.",
                reason="invalid_activity_request",
            )
        snapshot = self._snapshot()
        raw_provider_data = snapshot.get("raw_provider_data")
        raw_activities = (
            raw_provider_data.get("activities")
            if isinstance(raw_provider_data, dict)
            else None
        )
        activity = (
            next(
                (
                    item
                    for item in raw_activities
                    if isinstance(item, dict)
                    and str(
                        _first_present(item, ("id", "activityId", "external_id")) or ""
                    )
                    == normalized_id
                ),
                None,
            )
            if isinstance(raw_activities, list)
            else None
        )
        if activity is None:
            raise AppError(
                404,
                "Die vollständigen Rohdaten dieser Aktivität sind im lokalen Intervals.icu-Snapshot nicht vorhanden.",
                reason="activity_details_not_found",
            )
        feedback = next(
            (
                item
                for item in self._feedback_service.list(500)
                if item.get("activity_id") == normalized_id
            ),
            None,
        )
        performance = performance_context.current_performance_context(
            snapshot, garmin_snapshot, profile, today
        )
        return {
            "ok": True,
            "snapshot_synced_at": snapshot.get("synced_at"),
            "activity": detail_projection.detailed_activity(activity),
            "activity_validation": activity_validation.activity_performance_validation(
                [activity],
                performance.get("metrics", {}),
                performance.get("comparisons", {}),
            ),
            "activity_feedback": feedback,
            "data_scope": "bounded sanitized detail projection of exactly one Intervals.icu activity",
        }
