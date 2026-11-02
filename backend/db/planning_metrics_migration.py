"""Schema v19: normalize metric keys in stored local planning records."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend.canonical.legacy_planning_fields import (
    LEGACY_PLANNING_METRICS,
    LEGACY_TARGET_BASIS,
    normalize_legacy_detail_targets,
)


def _rename(record: Any, names: dict[str, str]) -> Any:
    if not isinstance(record, dict):
        return record
    result = dict(record)
    for old, new in names.items():
        if old in result:
            if new in result and (
                type(result[new]) is not type(result[old]) or result[new] != result[old]
            ):
                raise RuntimeError(f"Conflicting planning fields: {old} and {new}")
            value = result.pop(old)
            result.setdefault(new, value)
    return result


def _planning(record: Any) -> Any:
    return _rename(record, LEGACY_PLANNING_METRICS)


def _conflict(record: Any) -> Any:
    if not isinstance(record, dict) or "remote" not in record:
        return record
    return {**record, "remote": _planning(record["remote"])}


def _artifact(record: Any) -> Any:
    if not isinstance(record, dict) or not isinstance(record.get("workouts"), list):
        return record
    return {**record, "workouts": [_planning(item) for item in record["workouts"]]}


def _adjustment(record: Any) -> Any:
    if not isinstance(record, dict) or not isinstance(record.get("changes"), list):
        return record
    return {
        **record,
        "changes": [
            {**item, "payload": _planning(item["payload"])}
            if isinstance(item, dict) and "payload" in item
            else item
            for item in record["changes"]
        ],
    }


def _detail(record: Any) -> Any:
    return (
        normalize_legacy_detail_targets(record) if isinstance(record, dict) else record
    )


def _rewrite(
    db: Any,
    table: str,
    key: str,
    column: str,
    transform: Callable[[Any], Any],
    where: str = "1",
) -> None:
    patterns = tuple(
        f"%{name}%" for name in (*LEGACY_PLANNING_METRICS, *LEGACY_TARGET_BASIS)
    )
    predicates = " OR ".join(f"{column} LIKE ?" for _ in patterns)
    rows = db.execute(
        f"SELECT {key} AS row_id, {column} AS value FROM {table} WHERE ({where}) AND ({predicates})",
        patterns,
    )
    while batch := rows.fetchmany(64):
        for row in batch:
            _rewrite_row(db, table, key, column, transform, row)


def _rewrite_row(
    db: Any,
    table: str,
    key: str,
    column: str,
    transform: Callable[[Any], Any],
    row: Any,
) -> None:
    original = row["value"]
    if not isinstance(original, str):
        return
    try:
        value = json.loads(original)
    except ValueError as exc:
        if any(
            key in original for key in (*LEGACY_PLANNING_METRICS, *LEGACY_TARGET_BASIS)
        ):
            raise RuntimeError(f"Unreadable planning data in {table}.{column}") from exc
        return
    updated = transform(value)
    if updated != value:
        db.execute(
            f"UPDATE {table} SET {column} = ? WHERE {key} = ?",
            (
                json.dumps(updated, ensure_ascii=False, separators=(",", ":")),
                row["row_id"],
            ),
        )


def rename_planning_metrics(db: Any) -> None:
    """Rewrite only known local records within the caller's transaction."""
    _rewrite(db, "workout_library", "id", "payload", _planning)
    _rewrite(db, "planned_units", "id", "payload", _planning)
    _rewrite(db, "planned_units", "id", "sync_conflict", _conflict)
    _rewrite(db, "competitions", "id", "sync_conflict", _conflict)
    _rewrite(db, "coach_plan_artifacts", "id", "payload", _artifact)
    _rewrite(db, "plan_adjustments", "id", "payload", _adjustment)
    _rewrite(db, "activity_detail_analysis", "activity_id", "payload", _detail)
