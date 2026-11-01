"""Activity-feedback normalization and local use-case orchestration.

Feedback belongs to the canonical session it was written for. Rows whose
sessions lead to one effective session through confirmed merges form a group;
the group exposes one effective row, the newest by ``updated_at`` with the
smaller original id first on a tie, so session RPE counts once. Hidden rows stay
stored, and differing ones are listed as ``conflicting_feedback``. Rows without
a session (unknown or ambiguous references) stand alone; proximity never groups
feedback.
"""

from __future__ import annotations

import builtins
from collections.abc import Iterable
from typing import Any, Final

from backend import change_history
from backend.activities.activity_reference import (
    ActivityReference,
    ActivityReferenceResolver,
    NoActivityReferences,
)
from backend.activities.activity_summary import stored_activity_key
from backend.db import canonical_store
from backend.errors import AppError
from backend.runtime.ports import ActivityRowReader

ENTITY_TYPE: Final = "activity_feedback"
# Every stored column, so an undo restores rows exactly.
_STORED_FIELDS: Final = (
    "activity_id",
    "activity_name",
    "activity_date",
    "notes",
    "session_rpe",
    "deviation_reason",
    "created_at",
    "updated_at",
    "provider",
    "session_id",
    "session_rpe_rated_at",
)
FEEDBACK_CONTENT_FIELDS: Final = ("notes", "session_rpe", "deviation_reason")
_PUBLIC_FIELDS: Final = (
    "activity_id",
    "activity_name",
    "activity_date",
    "notes",
    "session_rpe",
    "deviation_reason",
    "created_at",
    "updated_at",
    "session_rpe_rated_at",
)

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
        # The range test alone rejects NaN and infinity and, unlike
        # math.isfinite, accepts any int, however large.
        if rpe is not None and (type(rpe) not in {int, float} or not 0 <= rpe <= 10):
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


def _feedback_key(activity: Any) -> Any:
    """The key an activity's feedback is stored under."""
    if not isinstance(activity, dict):
        return None
    return stored_activity_key(activity) or _activity_id(activity)


def _group_key(row: dict[str, Any], effective: dict[str, str]) -> tuple[str, str]:
    session = row.get("session_id")
    if session:
        return ("session", effective.get(str(session), str(session)))
    return ("activity", str(row["activity_id"]))


def _entity_id(key: tuple[str, str]) -> str:
    return f"{key[0]}:{key[1]}"


def _group_of(entity_id: str) -> tuple[str, str]:
    kind, _, value = str(entity_id).partition(":")
    return (kind, value)


def _audit_value(group: builtins.list[dict[str, Any]] | None) -> dict[str, Any] | None:
    if not group:
        return None
    rows = sorted(group, key=lambda row: str(row["activity_id"]))
    return {"rows": [_audit_row(row) for row in rows]}


def _audit_row(row: dict[str, Any]) -> dict[str, Any]:
    """One stored row; an unknown rating time is left out, as rows recorded
    before schema version 18 have no such field and keep their audit hash."""
    recorded = {field: row.get(field) for field in _STORED_FIELDS}
    if recorded["session_rpe_rated_at"] is None:
        del recorded["session_rpe_rated_at"]
    return recorded


def _ordered(group: Iterable[dict[str, Any]]) -> builtins.list[dict[str, Any]]:
    """Group rows, effective first: newest update, then the smaller original id."""
    rows = sorted(group, key=lambda row: str(row["activity_id"]))
    rows.sort(key=lambda row: str(row["updated_at"]), reverse=True)
    return rows


def _save_group_key(
    db: Any, key: str, origin: str | None, groups: dict[Any, Any]
) -> tuple[str, str]:
    """The group a save edits: the effective session, else the activity's rows."""
    if origin is None:
        return ("activity", key)
    effective = canonical_store.effective_session_ids(db, [origin])
    group_key = ("session", effective.get(origin, origin))
    if group_key not in groups and ("activity", key) in groups:
        return ("activity", key)
    return group_key


def _keep_omitted_fields(
    feedback: dict[str, Any], value: Any, existing: dict[str, Any]
) -> None:
    """Omitted fields keep their effective value."""
    for field in (
        "notes",
        "activity_name",
        "activity_date",
        "session_rpe",
        "deviation_reason",
    ):
        if field not in value and field in existing:
            feedback[field] = existing[field]


def _is_cleared(feedback: dict[str, Any]) -> bool:
    return (
        not feedback["notes"]
        and feedback.get("session_rpe") is None
        and not feedback.get("deviation_reason")
    )


def _group_containing(
    groups: dict[Any, builtins.list[dict[str, Any]]], activity_id: str, default: Any
) -> Any:
    return next(
        (
            candidate
            for candidate, rows in groups.items()
            if any(row["activity_id"] == activity_id for row in rows)
        ),
        default,
    )


def _effective_view(group: builtins.list[dict[str, Any]]) -> dict[str, Any]:
    chosen, *hidden = _ordered(group)
    view = {field: chosen.get(field) for field in _PUBLIC_FIELDS}
    conflicts = [
        {"activity_id": row["activity_id"], "updated_at": row["updated_at"]}
        for row in hidden
        if any(row.get(field) != chosen.get(field) for field in FEEDBACK_CONTENT_FIELDS)
    ]
    if conflicts:
        view["conflicting_feedback"] = conflicts
    return view


class ActivityFeedbackService:
    """Coordinate local activity-feedback use cases and their transactions."""

    def __init__(
        self,
        database_manager: Any,
        feedback_repository: Any,
        row_reader: ActivityRowReader,
        *,
        references: ActivityReferenceResolver | None = None,
    ):
        self._database_manager = database_manager
        self._feedback_repository = feedback_repository
        self._row_reader = row_reader
        self._references = NoActivityReferences() if references is None else references

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        """The effective feedback of each session, newest first."""
        bounded_limit = max(1, min(int(limit), 500))
        with self._database_manager.reader() as db:
            views = [_effective_view(group) for group in self._groups(db).values()]
        views.sort(key=lambda view: str(view["updated_at"]), reverse=True)
        return views[:bounded_limit]

    def for_activity_ids(
        self, activity_ids: builtins.list[str], *, sessions_only: bool = False
    ) -> builtins.list[dict[str, Any]]:
        """The effective feedback of each id's session, keyed by the requested id.

        An id reaches a group through its own feedback row or through the session
        of its only activity record, so every provider copy of one session shows
        the same feedback. ``sessions_only`` leaves out feedback that stands
        alone because its session is unknown or ambiguous.
        """
        requested = list(
            dict.fromkeys(
                str(value) for value in activity_ids if value not in (None, "")
            )
        )
        if not requested:
            return []
        with self._database_manager.reader() as db:
            groups = self._groups(db)
            origins = canonical_store.feedback_origin_sessions(
                db, [(activity_id, None) for activity_id in requested]
            )
            effective = canonical_store.effective_session_ids(
                db, list(origins.values())
            )
        member_keys = {
            str(row["activity_id"]): key
            for key, group in groups.items()
            for row in group
        }
        found = []
        for activity_id in requested:
            key = member_keys.get(activity_id)
            if key is None and activity_id in origins:
                session = origins[activity_id]
                key = ("session", effective.get(session, session))
            # A row without a stored session still counts when its id now
            # resolves to exactly one session.
            if (
                sessions_only
                and key is not None
                and key[0] != "session"
                and activity_id not in origins
            ):
                continue
            if key is not None and key in groups:
                found.append(
                    {**_effective_view(groups[key]), "activity_id": activity_id}
                )
        return found

    def _groups(self, db: Any) -> dict[tuple[str, str], builtins.list[dict[str, Any]]]:
        rows = self._feedback_repository.all(db)
        effective = canonical_store.effective_session_ids(
            db, [str(row["session_id"]) for row in rows if row.get("session_id")]
        )
        groups: dict[tuple[str, str], builtins.list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(_group_key(row, effective), []).append(row)
        return groups

    def save(self, activity_id: Any, value: Any) -> dict[str, Any]:
        return self._save(self._references.resolve_reference(activity_id), value)

    def _save(self, reference: ActivityReference, value: Any) -> dict[str, Any]:
        """Edit the effective feedback of the reference's session.

        Omitted fields keep their effective value. Clearing every field removes the
        whole group, so no hidden older row becomes effective again.
        """
        feedback = normalize_activity_feedback(reference.activity_id, value)
        with self._database_manager.unit_of_work() as db:
            key = feedback["activity_id"]
            origin = canonical_store.feedback_origin_sessions(
                db, [(key, reference.provider)]
            ).get(key)
            groups = self._groups(db)
            group_key = _save_group_key(db, key, origin, groups)
            group = groups.get(group_key) or []
            if len(group) >= change_history.MAX_FEEDBACK_GROUP_ROWS:
                raise AppError(
                    409,
                    "Zu viele Rückmeldungen für diese Einheit, um sie mit Undo zu ändern.",
                )
            existing = _ordered(group)[0] if group else {}
            if existing:
                feedback["activity_id"] = existing["activity_id"]
            own_row = feedback["activity_id"] == key
            _keep_omitted_fields(feedback, value, existing)
            if _is_cleared(feedback):
                for row in group or [{"activity_id": key}]:
                    self._feedback_repository.delete(db, row["activity_id"])
                change = self._record(db, group_key, group, None)
                return {"status": "ok", "activity_feedback": None, "change": change}
            self._feedback_repository.upsert(
                db,
                feedback,
                provider=reference.provider if own_row else None,
                session_id=origin if own_row else None,
            )
            after_groups = self._groups(db)
            saved_key = _group_containing(
                after_groups, feedback["activity_id"], group_key
            )
            change = self._record(db, saved_key, group, after_groups.get(saved_key))
        # The committed save stands even if this read fails.
        with self._database_manager.reader() as db:
            saved_group = self._groups(db).get(saved_key)
        saved = _effective_view(saved_group) if saved_group else feedback
        return {"status": "ok", "activity_feedback": saved, "change": change}

    @staticmethod
    def _record(
        db: Any,
        key: tuple[str, str],
        before: builtins.list[dict[str, Any]] | None,
        after: builtins.list[dict[str, Any]] | None,
    ) -> dict[str, str] | None:
        """Record the group change; its undo restores every stored row as it was."""
        before_value, after_value = _audit_value(before), _audit_value(after)
        if before_value is None:
            action = "create"
        elif after_value is None:
            action = "delete"
        else:
            action = "update"
        record = change_history.record_change(
            db, ENTITY_TYPE, _entity_id(key), action, before_value, after_value
        )
        if record is None:
            return None
        return {field: record[field] for field in change_history.UNDO_REFERENCE_FIELDS}

    def current(
        self, db: Any, entity_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The stored rows of one feedback group for change history."""
        value = _audit_value(self._groups(db).get(self._current_key(db, entity_id)))
        return value, change_history.audit_projection(ENTITY_TYPE, value)

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Replace the group's stored rows with the recorded ones, ids and times kept."""
        for row in (current or {}).get("rows") or []:
            self._feedback_repository.delete(db, str(row["activity_id"]))
        rows = (target or {}).get("rows")
        if not isinstance(rows, builtins.list):
            return None
        for row in rows:
            if not isinstance(row, dict) or self._feedback_repository.get(
                db, str(row.get("activity_id"))
            ):
                # Another group holds this id now; restoring would overwrite it.
                raise AppError(
                    409, "Die Rückmeldung kann nicht wiederhergestellt werden."
                )
            self._feedback_repository.restore(db, row)
        return _audit_value(self._groups(db).get(self._current_key(db, entity_id)))

    @staticmethod
    def _current_key(db: Any, entity_id: str) -> tuple[str, str]:
        """The group key of a recorded entity, through later session merges."""
        kind, value = _group_of(entity_id)
        if kind == "session":
            effective = canonical_store.effective_session_ids(db, [value])
            value = effective.get(value, value)
        return (kind, value)

    def save_coach(self, activity_id: Any, value: Any) -> dict[str, Any]:
        """Save feedback only for an activity the canonical activity reads serve."""
        reference = self._references.resolve_reference(activity_id)
        normalized = normalize_activity_feedback(reference.activity_id, value)
        if (
            not normalized["notes"]
            and normalized.get("session_rpe") is None
            and not normalized.get("deviation_reason")
        ):
            raise AppError(400, "Die Rückmeldung darf nicht leer sein.")
        with self._database_manager.unit_of_work() as db:
            activities = self._row_reader.activity_rows(db)
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
        return self._save(reference, value)

    def context(self) -> dict[str, Any]:
        return {
            "recent": self.list(),
            "scope": "Only athlete-entered notes, session RPE and deviation reasons about completed activities; this feedback is separate from daily check-ins and provider values.",
        }

    def attach_to_activities(self, activities: Any) -> builtins.list[dict[str, Any]]:
        activity_items = activities if isinstance(activities, list) else []
        activity_ids: builtins.list[str] = []
        for activity in activity_items:
            activity_id = _feedback_key(activity)
            if activity_id not in (None, ""):
                activity_ids.append(str(activity_id))
        feedback_by_activity = {
            item["activity_id"]: item for item in self.for_activity_ids(activity_ids)
        }
        result = []
        for activity in activity_items:
            if not isinstance(activity, dict):
                continue
            activity_copy = dict(activity)
            activity_id = _feedback_key(activity)
            if (
                activity_id not in (None, "")
                and str(activity_id) in feedback_by_activity
            ):
                activity_copy["activity_feedback"] = feedback_by_activity[
                    str(activity_id)
                ]
            result.append(activity_copy)
        return result
