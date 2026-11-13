"""Every SQL statement on ``planned_units`` and ``workout_library`` (#2118).

Functions take the caller's connection; transactions stay with the use case.
Payload arguments are dictionaries stored as JSON; rows come back unparsed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

_ACTIVE = (
    "COALESCE(json_extract(payload, '$.archived'), 0) = 0 "
    "AND COALESCE(json_extract(payload, '$.local_deleted'), 0) = 0"
)
_DAY = "substr(COALESCE(json_extract(payload, '$.date'), ''), 1, 10)"
_DAY_ORDER = (
    "json_extract(payload, '$.date'), lower(json_extract(payload, '$.name')), local_id"
)
_UNIT_COLUMNS = "local_id, payload, sync_state, sync_error, sync_conflict"
_STATE_COLUMNS = "*"
_OPEN_STATES = "'local', 'sync_error', 'remote_missing', 'conflict'"
_GARMIN_LINKS = (
    "FROM remote_links l JOIN planned_units p ON p.local_id = l.local_id "
    "WHERE l.provider=? AND l.entity_kind=? AND json_valid(p.payload) "
)
_TEMPLATES = "json_type(payload)='object' AND json_extract(payload, '$.date') IS NULL"


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _marks(values: Sequence[Any]) -> str:
    return ",".join("?" for _ in values)


# Planned units: reads.


def planned_unit_row(db: Any, local_id: str) -> Any:
    return db.execute(
        "SELECT * FROM planned_units WHERE local_id=?", (local_id,)
    ).fetchone()


def planned_unit_rows_by_ids(db: Any, local_ids: Sequence[str]) -> list[Any]:
    return db.execute(
        f"SELECT {_STATE_COLUMNS} FROM planned_units "
        f"WHERE local_id IN ({_marks(local_ids)}) ORDER BY local_id",
        tuple(local_ids),
    ).fetchall()


def planned_unit_rows_in_states(db: Any, states: Sequence[str]) -> list[Any]:
    return db.execute(
        f"SELECT {_STATE_COLUMNS} FROM planned_units "
        f"WHERE sync_state IN ({_marks(states)}) ORDER BY local_id",
        tuple(states),
    ).fetchall()


def planned_unit_rows_in_period(db: Any, start: Any, end: Any) -> list[Any]:
    """Every unit dated from ``start`` to ``end``, archived ones included."""
    return db.execute(
        f"SELECT local_id, payload FROM planned_units WHERE {_DAY} BETWEEN ? AND ? "
        "ORDER BY local_id",
        (start, end),
    ).fetchall()


def active_planned_unit_rows(db: Any, plan_id: str | None = None) -> list[Any]:
    """Units neither archived nor deleted, all or those of one plan."""
    return db.execute(
        f"SELECT local_id, payload FROM planned_units WHERE {_ACTIVE} "
        "AND (? IS NULL OR json_extract(payload, '$.plan_id') = ?)",
        (plan_id, plan_id),
    ).fetchall()


def replaceable_planned_unit_rows(
    db: Any, plan_id: str, start: str, end: str
) -> list[Any]:
    """Active units of the period; without a plan only Coach, library or Intervals ones."""
    return db.execute(
        f"SELECT local_id, payload FROM planned_units WHERE {_ACTIVE} "
        "AND (? = '' OR json_extract(payload, '$.plan_id') = ?) "
        "AND (? <> '' OR COALESCE(json_extract(payload, '$.source'), 'coach') "
        "IN ('coach', 'library', 'intervals')) "
        f"AND {_DAY} BETWEEN ? AND ?",
        (plan_id, plan_id, plan_id, start, end),
    ).fetchall()


def hidden_planned_unit_ids(db: Any) -> set[str]:
    """Deleted units and archived ones that never reached a provider."""
    rows = db.execute(
        "SELECT local_id FROM planned_units "
        "WHERE COALESCE(json_extract(payload, '$.local_deleted'), 0) = 1 "
        "OR (COALESCE(json_extract(payload, '$.archived'), 0) = 1 "
        "AND (external_id IS NULL OR external_id = ''))"
    ).fetchall()
    return {str(row.get("local_id") or "") for row in rows if row.get("local_id")}


def synced_capped_planned_unit_rows(db: Any) -> list[Any]:
    return db.execute(
        f"SELECT {_STATE_COLUMNS} FROM planned_units "
        "WHERE sync_state='synced' AND json_extract(payload, '$.hr_cap') IS NOT NULL "
        "ORDER BY local_id"
    ).fetchall()


def planned_unit_rows(
    db: Any,
    limit: int,
    include_archived: bool,
    future_only: bool,
    *,
    today: date,
    since: date | None = None,
) -> list[Any]:
    clauses: list[str] = []
    if not include_archived:
        clauses.append("COALESCE(json_extract(payload, '$.archived'), 0) = 0")
    if future_only:
        clauses.append("COALESCE(json_extract(payload, '$.local_deleted'), 0) = 0")
    descending = (
        "json_extract(payload, '$.date') DESC, "
        "lower(json_extract(payload, '$.name')) DESC, local_id DESC"
    )
    bounded_limit = max(1, min(int(limit) * (2 if include_archived else 1), 1000))

    # ``since`` only widens a future-only read back to that date.
    lower = (since if future_only and since else today).isoformat()

    def select(extra: str, order: str, count: int) -> list[Any]:
        where = " AND ".join([*clauses, extra])
        sql = f"SELECT {_UNIT_COLUMNS} FROM planned_units WHERE {where} ORDER BY {order} LIMIT ?"
        return db.execute(sql, (lower, count)).fetchall()

    upcoming_filter = f"{_DAY} >= ?"
    if future_only:
        return select(upcoming_filter, _DAY_ORDER, bounded_limit)
    # A limited window is anchored on today: the nearest upcoming units plus the
    # most recent past ones. A side that has fewer rows than its half hands the
    # unused share to the other side.
    upcoming = select(upcoming_filter, _DAY_ORDER, bounded_limit)
    past = select(f"{_DAY} < ?", descending, bounded_limit)
    past_share = min(len(past), bounded_limit // 2)
    upcoming_count = min(len(upcoming), bounded_limit - past_share)
    past_count = min(len(past), bounded_limit - upcoming_count)
    return [*reversed(past[:past_count]), *upcoming[:upcoming_count]]


def planned_unit_rows_between(db: Any, start: date, end: date) -> list[Any]:
    """Unarchived rows planned from ``start`` to ``end`` inclusive, in day order."""
    return db.execute(
        f"SELECT {_UNIT_COLUMNS} FROM planned_units "
        "WHERE COALESCE(json_extract(payload, '$.archived'), 0) = 0 "
        f"AND {_DAY} BETWEEN ? AND ? ORDER BY {_DAY_ORDER}",
        (start.isoformat(), end.isoformat()),
    ).fetchall()


def planned_unit_page(
    db: Any, include_inactive: bool, today: str, after: Sequence[str], limit: int
) -> list[Any]:
    """One keyset page of units from ``today`` on, ordered by day, name and id."""
    return db.execute(
        "SELECT local_id, sync_state, payload, COALESCE(json_extract(payload, '$.date'), '') AS plan_date, "
        "lower(COALESCE(json_extract(payload, '$.name'), '')) AS sort_name FROM planned_units "
        f"WHERE (? OR ({_ACTIVE})) AND {_DAY} >= ? "
        "AND (COALESCE(json_extract(payload, '$.date'), ''), lower(COALESCE(json_extract(payload, '$.name'), '')), local_id) > (?, ?, ?) "
        "ORDER BY plan_date, sort_name, local_id LIMIT ?",
        (int(include_inactive), today, *after, limit),
    ).fetchall()


def newest_planned_date(db: Any, local_ids: Sequence[str]) -> str:
    row = db.execute(
        "SELECT MAX(json_extract(payload, '$.date')) AS newest "
        f"FROM planned_units WHERE local_id IN ({_marks(local_ids)})",
        tuple(local_ids),
    ).fetchone()
    return str((row or {}).get("newest") or "")


def other_planned_event_ids(db: Any, local_id: str) -> list[Any]:
    """The Intervals.icu event slots of every other unit."""
    return db.execute(
        "SELECT local_id, json_extract(payload, '$.remote_event_id') AS remote_id, "
        "json_extract(payload, '$.remote_event_external_id') AS remote_external_id "
        "FROM planned_units WHERE local_id<>?",
        (local_id,),
    ).fetchall()


def garmin_link_rows(db: Any, provider: str, entity_kind: str) -> list[Any]:
    """Every Garmin unit link with its unit, if the unit still exists."""
    return db.execute(
        "SELECT l.local_id AS link_id, p.local_id AS unit_id, p.payload, p.tombstone "
        "FROM remote_links l LEFT JOIN planned_units p ON p.local_id = l.local_id "
        "WHERE l.provider=? AND l.entity_kind=?",
        (provider, entity_kind),
    ).fetchall()


def garmin_links_until(
    db: Any, provider: str, entity_kind: str, last_day: str
) -> list[Any]:
    """Links of units dated up to ``last_day`` inclusive, oldest first."""
    return db.execute(
        f"SELECT l.local_id, l.remote_id, l.remote_external_id {_GARMIN_LINKS}"
        "AND substr(json_extract(p.payload, '$.date'), 1, 10) "
        "BETWEEN '0001-01-01' AND ? "
        "ORDER BY substr(json_extract(p.payload, '$.date'), 1, 10), l.local_id",
        (provider, entity_kind, last_day),
    ).fetchall()


def garmin_remote_ids_from(
    db: Any, provider: str, entity_kind: str, first_day: str
) -> set[str]:
    rows = db.execute(
        f"SELECT l.remote_id {_GARMIN_LINKS}AND l.remote_id IS NOT NULL "
        "AND substr(json_extract(p.payload, '$.date'), 1, 10) >= ?",
        (provider, entity_kind, first_day),
    ).fetchall()
    return {str(row["remote_id"]) for row in rows}


def garmin_exercise_rows(db: Any) -> list[Any]:
    """Active units and templates naming a Garmin exercise, oldest change first."""
    return db.execute(
        "SELECT payload, updated_at FROM planned_units "
        f"WHERE tombstone=0 AND {_ACTIVE} AND payload LIKE '%garmin_exercise%' "
        "UNION ALL SELECT payload, updated_at FROM workout_library "
        f"WHERE {_ACTIVE} AND payload LIKE '%garmin_exercise%' "
        "ORDER BY updated_at"
    ).fetchall()


def push_candidate_rows(
    db: Any, local_ids: Sequence[str] | None, limit: int
) -> list[Any]:
    """Templates and units by id, or every open one when ``local_ids`` is None."""
    values = tuple(local_ids or ())
    where = (
        f"sync_state IN ({_OPEN_STATES})"
        if local_ids is None
        else f"local_id IN ({_marks(local_ids)})"
    )
    return db.execute(
        f"SELECT local_id, payload FROM workout_library WHERE {where} "
        f"UNION ALL SELECT local_id, payload FROM planned_units WHERE {where} "
        "ORDER BY local_id LIMIT ?",
        (*values, *values, limit),
    ).fetchall()


def sync_state_counts(db: Any) -> tuple[list[Any], list[Any]]:
    """Rows per sync state of the library and of the planned units."""
    count = "SELECT sync_state, COUNT(*) AS count FROM {} GROUP BY sync_state"
    return (
        db.execute(count.format("workout_library")).fetchall(),
        db.execute(count.format("planned_units")).fetchall(),
    )


def version_counters(db: Any) -> tuple[Any, Any]:
    """Count and newest change of the undated templates and of the units."""
    count = "SELECT COUNT(*) AS count, COALESCE(MAX(updated_at), '') AS latest FROM "
    return (
        db.execute(
            count + "workout_library WHERE json_extract(payload, '$.date') IS NULL"
        ).fetchone(),
        db.execute(count + "planned_units").fetchone(),
    )


def unsynced_planned_units(db: Any, limit: int) -> tuple[int, list[Any]]:
    """How many live units are not synced, and up to ``limit``, upcoming first."""
    unsynced = "FROM planned_units WHERE tombstone=0 AND sync_state<>'synced'"
    total = db.execute(f"SELECT COUNT(*) AS count {unsynced}").fetchone()["count"]
    # Past units must not hide the ones still to be pushed.
    units = db.execute(
        "SELECT local_id, sync_state, sync_error, "
        # A payload that is not valid JSON has no date instead of failing the report.
        "CASE WHEN json_valid(payload) THEN json_extract(payload, '$.date') "
        f"END AS date {unsynced} "
        "ORDER BY date < date('now'), date LIMIT ?",
        (limit,),
    ).fetchall()
    return total, units


def planned_unit_export_rows(db: Any) -> Iterable[Any]:
    return db.execute(
        "SELECT id, local_id, external_id, payload, sync_dirty, sync_state, sync_error, sync_conflict, baseline_hash, last_synced_at, plan_id, revision, tombstone, command_id, created_at, updated_at "
        "FROM planned_units ORDER BY updated_at"
    )


# Planned units: writes.


def insert_planned_unit(
    db: Any,
    payload: dict[str, Any],
    *,
    local_id: str,
    external_id: str | None,
    sync_dirty: int,
    sync_state: str,
    sync_error: str | None,
    sync_conflict: str,
    baseline_hash: str | None,
    last_synced_at: str | None,
    now: str,
) -> None:
    db.execute(
        "INSERT INTO planned_units(id, local_id, external_id, payload, sync_dirty, sync_state, sync_error, sync_conflict, baseline_hash, last_synced_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            local_id,
            local_id,
            external_id,
            _json(payload),
            sync_dirty,
            sync_state,
            sync_error,
            sync_conflict,
            baseline_hash,
            last_synced_at,
            now,
            now,
        ),
    )


def update_planned_unit(
    db: Any,
    local_id: str,
    payload: dict[str, Any],
    now: str,
    *,
    mark_local: bool = True,
    clear_error: bool = True,
) -> None:
    """Store a local edit; ``mark_local=False`` keeps the sync state (focus edits)."""
    if mark_local:
        error = "sync_error=NULL, " if clear_error else ""
        sync = f"sync_dirty=1, sync_state='local', {error}sync_conflict='', "
    else:
        sync = ""
    db.execute(
        f"UPDATE planned_units SET payload=?, {sync}updated_at=? WHERE local_id=?",
        (_json(payload), now, local_id),
    )


def store_planned_unit_sync(
    db: Any,
    local_id: str,
    payload: dict[str, Any],
    *,
    sync_dirty: int,
    sync_state: str,
    sync_error: str | None,
    sync_conflict: Any,
    external_id: str | None,
    baseline_hash: str | None,
    last_synced_at: str | None,
    now: str,
) -> None:
    """Store a provider outcome; empty identity and baseline values keep the old ones."""
    db.execute(
        "UPDATE planned_units SET payload=?, sync_dirty=?, sync_state=?, sync_error=?, "
        "sync_conflict=?, external_id=COALESCE(?, external_id), baseline_hash=COALESCE(?, baseline_hash), "
        "last_synced_at=COALESCE(?, last_synced_at), updated_at=? WHERE local_id=?",
        (
            _json(payload),
            sync_dirty,
            sync_state,
            sync_error,
            sync_conflict,
            external_id,
            baseline_hash,
            last_synced_at,
            now,
            local_id,
        ),
    )


def delete_planned_unit(db: Any, local_id: str) -> None:
    db.execute("DELETE FROM planned_units WHERE local_id=?", (local_id,))


def reset_interrupted_syncs(db: Any, now: str, message: str) -> int:
    """Turn units and templates a crash left "syncing" into errors."""
    return sum(
        db.execute(
            f"UPDATE {table} SET sync_state='sync_error', sync_error=?, updated_at=? "
            "WHERE sync_state='syncing'",
            (message, now),
        ).rowcount
        for table in ("planned_units", "workout_library")
    )


# Workout library: reads.


def library_row(db: Any, local_id: str) -> Any:
    return db.execute(
        "SELECT * FROM workout_library WHERE local_id=?", (local_id,)
    ).fetchone()


def library_rows_in_states(db: Any, states: Sequence[str]) -> list[Any]:
    return db.execute(
        "SELECT local_id, external_id, sync_state, payload FROM workout_library "
        f"WHERE sync_state IN ({_marks(states)}) ORDER BY local_id",
        tuple(states),
    ).fetchall()


def library_template_page(
    db: Any, cursor: Sequence[str] | None, limit: int
) -> list[Any]:
    """One keyset page of active templates ordered by sport, name and id."""
    after_clause = (
        "" if cursor is None else "WHERE (sport_key, name_key, id) > (?, ?, ?)"
    )
    return db.execute(
        "WITH templates AS ("
        "SELECT id, local_id, payload, lower(COALESCE(json_extract(payload, '$.sport'), '')) AS sport_key, "
        "lower(COALESCE(json_extract(payload, '$.name'), '')) AS name_key "
        f"FROM workout_library WHERE json_valid(payload) AND {_TEMPLATES} "
        "AND COALESCE(json_extract(payload, '$.archived'), 0)=0) "
        f"SELECT id, local_id, payload, sport_key, name_key FROM templates {after_clause} "
        "ORDER BY sport_key, name_key, id LIMIT ?",
        (*(cursor or ()), limit),
    ).fetchall()


def library_templates(db: Any, include_archived: bool, limit: int) -> list[Any]:
    return db.execute(
        f"SELECT payload FROM workout_library WHERE {_TEMPLATES} "
        "AND (? OR COALESCE(json_extract(payload, '$.archived'), 0)=0) "
        "ORDER BY lower(json_extract(payload, '$.sport')), "
        "lower(json_extract(payload, '$.name')), id LIMIT ?",
        (int(include_archived), limit),
    ).fetchall()


def recent_library_templates(db: Any) -> list[Any]:
    return db.execute(
        "SELECT local_id, sync_state, payload FROM workout_library "
        "WHERE json_extract(payload, '$.date') IS NULL "
        "ORDER BY updated_at DESC LIMIT 100"
    ).fetchall()


def wahoo_links_without_template(db: Any, provider: str, entity_kind: str) -> list[Any]:
    return db.execute(
        "SELECT l.local_id FROM remote_links l "
        "LEFT JOIN workout_library w ON w.local_id = l.local_id "
        "WHERE l.provider=? AND l.entity_kind=? AND w.local_id IS NULL "
        "ORDER BY l.local_id",
        (provider, entity_kind),
    ).fetchall()


def library_count(db: Any) -> int:
    return db.execute("SELECT COUNT(*) AS count FROM workout_library").fetchone()[
        "count"
    ]


def library_export_rows(db: Any) -> Iterable[Any]:
    return db.execute(
        "SELECT id, local_id, external_id, payload, sync_dirty, sync_state, sync_error, last_synced_at, updated_at "
        "FROM workout_library "
        "ORDER BY lower(json_extract(payload, '$.sport')), lower(json_extract(payload, '$.name'))"
    )


# Workout library: writes.


def insert_library_workout(
    db: Any, local_id: str, payload: dict[str, Any], now: str
) -> None:
    db.execute(
        "INSERT INTO workout_library(id, local_id, external_id, payload, sync_dirty, "
        "sync_state, sync_error, last_synced_at, updated_at) "
        "VALUES (?, ?, NULL, ?, 1, 'local', NULL, NULL, ?)",
        (local_id, local_id, _json(payload), now),
    )


def set_library_sync_state(
    db: Any,
    local_id: str,
    payload: dict[str, Any],
    now: str,
    *,
    state: str,
    dirty: int,
    error: str | None = None,
) -> None:
    db.execute(
        "UPDATE workout_library SET payload=?, sync_dirty=?, sync_state=?, "
        "sync_error=?, updated_at=? WHERE local_id=?",
        (_json(payload), dirty, state, error, now, local_id),
    )


def set_library_payload(
    db: Any, local_id: str, payload: dict[str, Any], now: str
) -> None:
    db.execute(
        "UPDATE workout_library SET payload=?, updated_at=? WHERE local_id=?",
        (_json(payload), now, local_id),
    )


def set_library_external_id(
    db: Any, local_id: str, external_id: str, payload: dict[str, Any]
) -> None:
    db.execute(
        "UPDATE workout_library SET external_id=?, payload=? WHERE local_id=?",
        (external_id, _json(payload), local_id),
    )


def mark_library_synced(
    db: Any, local_id: str, external_id: str, payload: dict[str, Any], now: str
) -> None:
    db.execute(
        "UPDATE workout_library SET external_id=?, payload=?, sync_dirty=0, "
        "sync_state='synced', sync_error=NULL, last_synced_at=?, updated_at=? "
        "WHERE local_id=?",
        (external_id, _json(payload), now, now, local_id),
    )


def delete_library_workout(db: Any, local_id: str) -> None:
    db.execute("DELETE FROM workout_library WHERE local_id=?", (local_id,))
