"""Schema version 16: provider-neutral field names for local planning records.

Local planning records stored the Intervals.icu event fields ``start_date_local``
and ``moving_time``. Version 16 names them ``starts_at_local`` and
``planned_duration_s``; only the Intervals.icu adapter still uses the wire names.

The step renames the two competition columns in place and rewrites the JSON keys
of planned units, their stored remote conflicts, workout-library entries, stored
competition conflicts, staged Coach plan artifacts, adaptive previews and the
field list of pending undo proposals. Values, identities and every other key stay
as they are; a row without a renamed key, or whose JSON cannot be read, keeps its
exact bytes. Change history is never rewritten: ``backend.change_history``
translates the recorded field names on read and keeps their hashes matchable.

The logic is frozen with the release, so it does not import the current owners.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, Final

_START_RENAME: Final = ("start_date_local", "starts_at_local")
_DURATION_RENAME: Final = ("moving_time", "planned_duration_s")
_PLANNING_RENAMES: Final[Mapping[str, str]] = {
    _START_RENAME[0]: _START_RENAME[1],
    _DURATION_RENAME[0]: _DURATION_RENAME[1],
}

type _Rewrite = Callable[[Any], Any]


def rename_planning_fields(record: Any) -> Any:
    """Return ``record`` with the planning fields renamed, keeping key order.

    A non-object is returned unchanged. A key that already has its new name keeps
    its value; that cannot occur in a released schema, which never wrote it.
    """
    if not isinstance(record, dict):
        return record
    result: dict[str, Any] = {}
    for key, value in record.items():
        renamed = _PLANNING_RENAMES.get(key, key)
        if renamed != key and renamed in record:
            continue
        result[renamed] = value
    return result


def _rename_conflict_remote(conflict: Any) -> Any:
    if not isinstance(conflict, dict) or "remote" not in conflict:
        return conflict
    return {**conflict, "remote": rename_planning_fields(conflict["remote"])}


def _rename_artifact_workouts(artifact: Any) -> Any:
    if not isinstance(artifact, dict) or not isinstance(artifact.get("workouts"), list):
        return artifact
    return {
        **artifact,
        "workouts": [rename_planning_fields(item) for item in artifact["workouts"]],
    }


def _rename_adjustment_changes(adjustment: Any) -> Any:
    if not isinstance(adjustment, dict) or not isinstance(
        adjustment.get("changes"), list
    ):
        return adjustment
    return {
        **adjustment,
        "changes": [
            {**change, "payload": rename_planning_fields(change["payload"])}
            if isinstance(change, dict) and "payload" in change
            else change
            for change in adjustment["changes"]
        ],
    }


def _rename_diff_fields(diff: Any) -> Any:
    if not isinstance(diff, dict) or not isinstance(diff.get("fields"), dict):
        return diff
    return {**diff, "fields": rename_planning_fields(diff["fields"])}


def _dumps_like(original: str, value: Any) -> str:
    """Serialize ``value`` with the separators the stored text was written with."""
    compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    try:
        stored = json.loads(original)
    except ValueError:
        return compact
    if json.dumps(stored, ensure_ascii=False, separators=(",", ":")) == original:
        return compact
    return json.dumps(value, ensure_ascii=False)


def _rewrite_column(
    db: Any, table: str, column: str, rewrite: _Rewrite, where: str = ""
) -> None:
    """Rewrite one JSON column row by row; unreadable or unchanged rows stay as is."""
    rows = db.execute(
        f"SELECT id AS row_id, {column} AS stored FROM {table} "
        f"WHERE ({column} LIKE ? OR {column} LIKE ?)"
        + (f" AND {where}" if where else ""),
        ("%start_date_local%", "%moving_time%"),
    ).fetchall()
    for row in rows:
        original = row["stored"]
        try:
            value = json.loads(original)
        except TypeError, ValueError:
            continue
        rewritten = rewrite(value)
        if rewritten == value:
            continue
        db.execute(
            f"UPDATE {table} SET {column} = ? WHERE id = ?",
            (_dumps_like(original, rewritten), row["row_id"]),
        )


def _rewrite_pending_undo_diffs(db: Any) -> None:
    """Rename the field list of pending undo proposals for planning records.

    The proposal payload names only the change and the expected hash, so it and
    its payload_hash stay unchanged; the hash check accepts the recorded row's
    after_hash, which is the pre-upgrade hash of the same state.
    """
    _rewrite_column(
        db,
        "coach_action_proposals",
        "diff",
        _rename_diff_fields,
        "action_type = 'undo_change' AND status IN ('preview', 'ready') "
        "AND EXISTS (SELECT 1 FROM change_history WHERE change_history.id = "
        "json_extract(coach_action_proposals.payload, '$.change_id') "
        "AND change_history.entity_type IN "
        "('workout_library', 'planned_unit', 'competition'))",
    )


def rename_planning_fields_in_database(db: Any) -> None:
    """Apply the schema version 16 renames on the caller's open savepoint."""
    for old, new in (_START_RENAME, _DURATION_RENAME):
        db.execute(f"ALTER TABLE competitions RENAME COLUMN {old} TO {new}")
    _rewrite_column(db, "competitions", "sync_conflict", _rename_conflict_remote)
    _rewrite_column(db, "planned_units", "payload", rename_planning_fields)
    _rewrite_column(db, "planned_units", "sync_conflict", _rename_conflict_remote)
    _rewrite_column(db, "workout_library", "payload", rename_planning_fields)
    _rewrite_column(db, "coach_plan_artifacts", "payload", _rename_artifact_workouts)
    _rewrite_column(db, "plan_adjustments", "payload", _rename_adjustment_changes)
    _rewrite_pending_undo_diffs(db)
