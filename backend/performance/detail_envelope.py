"""Feedback, equipment and activity validation of one served activity detail."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.activities.activity_reference import ActivityReferenceResolver
from backend.performance.activity_validation import activity_performance_validation


class DetailEnvelopeReader:
    """Return the envelope blocks of the ``activity_detail.v1`` document.

    Feedback and equipment are keyed by the resolved session reference, the id
    that feedback writes and gear assignments use. Validation compares the
    session's activity summary with the performance context; a session without
    one gets the validation's explicit no-data result.
    """

    def __init__(
        self,
        *,
        feedback_service: Any,
        read_equipment: Callable[[str], dict[str, Any]],
        references: ActivityReferenceResolver,
        performance: Callable[[], Mapping[str, Any]],
        summary: Callable[[], Mapping[str, Any] | None],
    ) -> None:
        self._feedback_service = feedback_service
        self._read_equipment = read_equipment
        self._references = references
        self._performance = performance
        self._summary = summary

    def __call__(
        self,
        _db: Any,
        activity_id: str,
        _provider_activity_id: str | None,
        _raw_summary: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        reference = str(self._references.resolve_reference(activity_id).activity_id)
        items = self._feedback_service.list(500)
        # Feedback saved under the requested id before the merged record resolved.
        feedback = next(
            (item for item in items if item.get("activity_id") == reference),
            None,
        ) or next(
            (item for item in items if item.get("activity_id") == str(activity_id)),
            None,
        )
        summary = self._summary()
        if summary is None:
            validation = activity_performance_validation([], {}, {})
        else:
            performance = self._performance()
            validation = activity_performance_validation(
                [dict(summary)],
                performance.get("metrics", {}),
                performance.get("comparisons", {}),
            )
        return {
            "activity_feedback": feedback,
            "equipment": activity_equipment(self._read_equipment(reference), reference),
            "activity_validation": validation,
        }


def activity_equipment(equipment: dict, activity_id: str) -> list[dict]:
    # Garmin can link one activity to several main items.
    equipment_ids = {
        row["equipment_id"]
        for row in equipment.get("assignments", [])
        if row["activity_id"] == activity_id and row["equipment_id"]
    }
    return [
        row
        for row in equipment.get("items", [])
        if row["id"] in equipment_ids or row.get("parent_id") in equipment_ids
    ]
