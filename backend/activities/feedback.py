"""Activity-feedback normalization and local use-case orchestration."""

from __future__ import annotations

import builtins
import math
from typing import Any

from backend.errors import AppError
from backend.runtime.ports import ProviderSnapshotReader

ACTIVITY_FEEDBACK_TEXT_LIMITS = {
    "activity_name": 200,
    "activity_date": 40,
    "notes": 4000,
}


def normalize_activity_feedback(activity_id: Any, value: Any) -> dict[str, Any]:
    """Normalize an untrusted activity-feedback payload without mutating it."""
    normalized_id = str(activity_id or "").strip()
    if not normalized_id or len(normalized_id) > 200:
        raise AppError(400, "Die Aktivität konnte nicht eindeutig zugeordnet werden.")
    if not isinstance(value, dict):
        raise AppError(400, "Die Aktivitätsrückmeldung muss ein Objekt sein.")
    normalized: dict[str, Any] = {
        "activity_id": normalized_id,
        "activity_name": str(value.get("activity_name") or "").strip()[
            : ACTIVITY_FEEDBACK_TEXT_LIMITS["activity_name"]
        ],
        "activity_date": str(value.get("activity_date") or "").strip()[
            : ACTIVITY_FEEDBACK_TEXT_LIMITS["activity_date"]
        ],
        "notes": str(value.get("notes") or "").strip()[
            : ACTIVITY_FEEDBACK_TEXT_LIMITS["notes"]
        ],
    }
    if "session_rpe" in value:
        rpe = value["session_rpe"]
        if rpe is not None and (
            type(rpe) not in {int, float}
            or not math.isfinite(rpe)
            or not 0 <= rpe <= 10
        ):
            raise AppError(400, "Der Aktivitäts-RPE muss zwischen 0 und 10 liegen.")
        normalized["session_rpe"] = rpe
    if "deviation_reason" in value:
        normalized["deviation_reason"] = str(
            value.get("deviation_reason") or ""
        ).strip()[:500]
    return normalized


def _activity_id(activity: Any) -> Any:
    if not isinstance(activity, dict):
        return None
    for key in ("id", "activityId", "external_id"):
        value = activity.get(key)
        if value not in (None, ""):
            return value
    return None


class ActivityFeedbackService:
    """Coordinate local activity-feedback use cases and their transactions."""

    def __init__(
        self,
        database_manager: Any,
        feedback_repository: Any,
        snapshot_reader: ProviderSnapshotReader,
    ):
        self._database_manager = database_manager
        self._feedback_repository = feedback_repository
        self._snapshot_reader = snapshot_reader

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 500))
        with self._database_manager.unit_of_work() as db:
            return self._feedback_repository.list(db, bounded_limit)

    def save(self, activity_id: Any, value: Any) -> dict[str, Any]:
        feedback = normalize_activity_feedback(activity_id, value)
        with self._database_manager.unit_of_work() as db:
            existing = self._feedback_repository.get(db, feedback["activity_id"]) or {}
            for field in (
                "notes",
                "activity_name",
                "activity_date",
                "session_rpe",
                "deviation_reason",
            ):
                if field not in value and field in existing:
                    feedback[field] = existing[field]
            if (
                not feedback["notes"]
                and feedback.get("session_rpe") is None
                and not feedback.get("deviation_reason")
            ):
                self._feedback_repository.delete(db, feedback["activity_id"])
                return {"status": "ok", "activity_feedback": None}
            self._feedback_repository.upsert(db, feedback)
        saved = next(
            (
                item
                for item in self.list(500)
                if item["activity_id"] == feedback["activity_id"]
            ),
            feedback,
        )
        return {"status": "ok", "activity_feedback": saved}

    def save_coach(self, activity_id: Any, value: Any) -> dict[str, Any]:
        """Save feedback only for an activity in the latest local snapshot."""
        normalized = normalize_activity_feedback(activity_id, value)
        if (
            not normalized["notes"]
            and normalized.get("session_rpe") is None
            and not normalized.get("deviation_reason")
        ):
            raise AppError(400, "Die Rückmeldung darf nicht leer sein.")
        with self._database_manager.unit_of_work() as db:
            snapshot = self._snapshot_reader.latest_snapshot(db) or {}
            activities = (
                snapshot.get("recent_activities", [])
                if isinstance(snapshot, dict)
                else []
            )
            if not isinstance(activities, list):
                activities = []
            known_ids = {
                str(candidate_id)
                for activity in activities
                for candidate_id in (_activity_id(activity),)
                if candidate_id not in (None, "")
            }
            if normalized["activity_id"] not in known_ids:
                raise AppError(
                    404,
                    "Die Aktivität ist im aktuellen lokalen Trainingssnapshot nicht vorhanden.",
                )
        return self.save(normalized["activity_id"], value)

    def context(self) -> dict[str, Any]:
        return {
            "recent": self.list(),
            "scope": "Only athlete-entered notes, session RPE and deviation reasons about completed activities; this feedback is separate from daily check-ins and provider values.",
        }

    def attach_to_activities(self, activities: Any) -> builtins.list[dict[str, Any]]:
        feedback_by_activity = {item["activity_id"]: item for item in self.list(500)}
        result = []
        for activity in activities if isinstance(activities, list) else []:
            if not isinstance(activity, dict):
                continue
            activity_copy = dict(activity)
            activity_id = _activity_id(activity)
            if (
                activity_id not in (None, "")
                and str(activity_id) in feedback_by_activity
            ):
                activity_copy["activity_feedback"] = feedback_by_activity[
                    str(activity_id)
                ]
            result.append(activity_copy)
        return result
