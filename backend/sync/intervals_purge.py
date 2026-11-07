"""Remove the stored Intervals.icu ingest data once (#1728).

Intervals.icu is an output target only. Once the Garmin rating backfill reports
``finished``, ``IntervalsPurgeRunner`` writes an encrypted recovery copy of the
database and then, in one transaction, runs ``run_purge``:

1. Every Intervals.icu activity is tombstoned through the deletion path of a
   removed activity, so the Garmin or Wahoo copy becomes the survivor and the
   old session id keeps resolving through ``merged_into_retained``.
2. Athlete data is moved off the Intervals.icu sessions. A feedback row or an
   equipment assignment whose session (``feedback_origin_sessions``) is an
   Intervals.icu session moves to the live session that survives it, keyed by
   that session id (feedback also gets ``session_id`` = that id and no
   provider). The newest ``updated_at`` (feedback) or ``observed_at``
   (assignment) wins against every item stored under the survivor's key family
   (its id, alias session ids and provider activity ids); the others are dropped
   and counted. Data
   of a session without a surviving Garmin or Wahoo record is dropped and
   counted. A target snapshot of an Intervals.icu session's analysis moves to
   the survivor when the survivor has none.
3. The recorded feedback changes, and the session corrections that touched an
   Intervals.icu session, become non-undoable.
4. The Intervals.icu rows of the provider, activity, detail, observation and
   domain tables, every stored snapshot, the Intervals.icu sync cursors, ingest
   jobs, refresh history and ingest key-value state are deleted. A session
   without a survivor is deleted once nothing references it; the others stay
   as tombstones.
5. The ingest switch is turned off and a versioned completion marker stored;
   the switch then refuses to turn on and no one-off read runs. A marker file
   in the data directory keeps a restored pre-purge database from being purged
   again automatically.

Output state is kept: remote links, competition and workout ids, the library,
metric export and nutrition sync state, and the output job types. The local
load and session analysis follow-ups of the same canonical backfill pass
recompute what changed. Counts only, never ids, names, dates or values, reach
the marker, the logs and diagnostics.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Final

from backend import change_history
from backend.activities.detail_store import LEGACY_KEY_PATTERNS
from backend.canonical.vocabulary import ActivitySessionState, ProviderId
from backend.db import canonical_store
from backend.db.repositories import ActivityFeedbackRepository, KeyValueRepository
from backend.errors import AppError
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.runtime.maintenance import MaintenanceGate
from backend.sync import activity_detail_backfill, activity_detail_retirement
from backend.sync.canonical_backfill import STATE_KEY as BACKFILL_STATE_KEY
from backend.sync.canonical_coverage_store import COVERAGE_KEY_PREFIX
from backend.sync.freshness_sources import INTERVALS_RUNNING_FLAG
from backend.sync.garmin_rating_backfill import rating_backfill_finished
from backend.sync.intervals_ingest import (
    INGEST_ENABLED_KEY,
    PURGE_DONE,
    PURGE_MARKER_FILE,
    PURGE_STATE_KEY,
    PURGE_VERSION,
    purge_done,
    purge_marker_exists,
    purge_state,
)

_LOGGER = logging.getLogger("intervals_coach")
STATE_KEY: Final = PURGE_STATE_KEY
# One recovery copy per purge version; a later attempt reuses it.
BACKUP_LABEL: Final = f"pre-intervals-purge-v{PURGE_VERSION}"
# Written beside the database after a purge, so a restored pre-purge copy is
# not purged again automatically and its ingest stays off.
MARKER_FILE: Final = PURGE_MARKER_FILE
# The purge waits this long for a running foreground write before it fails.
WRITER_WAIT_SECONDS: Final = 600.0
STATUS_DONE: Final = PURGE_DONE
STATUS_DONE_RESTORED: Final = "done_restored"
STATUS_PENDING: Final = "pending"
STATUS_WAITING: Final = "waiting_for_rating_backfill"

_INTERVALS: Final = ProviderId.INTERVALS.value
_DELETED: Final = ActivitySessionState.DELETED.value
_NOT_SURVIVING: Final = frozenset({_DELETED, ActivitySessionState.DUPLICATE.value})
_CHUNK: Final = 500
_EQUIPMENT_PREFIX: Final = "equipment_assignment:"
# The change-history entity of a session correction; its id lists the sessions.
SESSION_CORRECTION_ENTITY: Final = "activity_session"
# Job types and refresh areas that read Intervals.icu; output jobs stay.
INGEST_JOB_TYPES: Final = (
    "activity_details",
    "historical_backfill",
    "performance_refresh",
    "refresh",
)
INGEST_REFRESH_AREAS: Final = ("activities", "performance")
# Rows with a provider column, in deletion order: detail rows before their set,
# sets before their activity record.
PROVIDER_TABLES: Final = (
    "activity_stream_channels",
    "activity_laps",
    "activity_zone_times",
    "activity_strength_sets",
    "activity_detail_sets",
    "gear_activity_links",
    "activity_records",
    "provider_records",
    "observations",
    "categorical_observations",
    "sleep_periods",
    "zone_configurations",
    "power_curve_points",
    "power_curve_fetches",
    "gear_items",
)
# Ingest key-value state: exact keys, then GLOB patterns (``_`` is literal there).
INGEST_KEYS: Final = (
    INTERVALS_RUNNING_FLAG,
    "sync_status",
    "intervals_full_window_read_on",
    activity_detail_backfill.STATE_KEY,
    activity_detail_retirement.STATE_KEY,
    COVERAGE_KEY_PREFIX + _INTERVALS,
)
INGEST_KEY_PATTERNS: Final = (
    "last_sync_*",
    "performance_refresh_*",
    "last_performance_*",
    "intervals_full_resync_*",
    *LEGACY_KEY_PATTERNS,
)


@dataclass(frozen=True, slots=True)
class _Stored:
    """One athlete item stored under ``key`` for the Intervals.icu session ``origin``."""

    key: str
    origin: str
    stamp: str


@dataclass(frozen=True, slots=True)
class _Moves:
    moved: dict[str, str]
    dropped: tuple[str, ...]
    lost: tuple[str, ...]


def _placeholders(values: Sequence[object]) -> str:
    return ", ".join("?" * len(values))


def _chunks(values: Iterable[str]) -> list[list[str]]:
    unique = sorted(set(values))
    return [unique[start : start + _CHUNK] for start in range(0, len(unique), _CHUNK)]


def _count(db: Any, sql: str, params: tuple[object, ...] = ()) -> int:
    return int(db.execute(sql, params).fetchone()["count"])


def _kv_filter() -> tuple[str, tuple[str, ...]]:
    clauses = [f"key IN ({_placeholders(INGEST_KEYS)})"]
    clauses += ["key GLOB ?"] * len(INGEST_KEY_PATTERNS)
    return " OR ".join(clauses), (*INGEST_KEYS, *INGEST_KEY_PATTERNS)


def intervals_row_counts(db: Any) -> dict[str, Any]:
    """Count the stored Intervals.icu ingest rows per table, kind and metric."""
    counts: dict[str, Any] = {
        table: _count(
            db,
            f"SELECT COUNT(*) AS count FROM {table} WHERE provider = ?",
            (_INTERVALS,),
        )
        for table in PROVIDER_TABLES
    }
    counts["provider_records_by_kind"] = {
        str(row["kind"]): int(row["count"])
        for row in db.execute(
            "SELECT record_kind AS kind, COUNT(*) AS count FROM provider_records "
            "WHERE provider = ? GROUP BY record_kind ORDER BY record_kind",
            (_INTERVALS,),
        )
    }
    counts["observations_by_metric"] = {
        str(row["metric"]): int(row["count"])
        for row in db.execute(
            "SELECT metric, COUNT(*) AS count FROM observations WHERE provider = ? "
            "GROUP BY metric ORDER BY metric",
            (_INTERVALS,),
        )
    }
    counts["activity_sessions"] = _count(
        db,
        "SELECT COUNT(*) AS count FROM activity_sessions WHERE primary_provider = ?",
        (_INTERVALS,),
    )
    counts["activity_detail_analysis"] = _count(
        db,
        "SELECT COUNT(*) AS count FROM activity_detail_analysis AS a "
        "JOIN activity_sessions AS s ON s.activity_id = a.activity_id "
        "WHERE s.primary_provider = ?",
        (_INTERVALS,),
    )
    counts["snapshots"] = _count(db, "SELECT COUNT(*) AS count FROM snapshots")
    counts["provider_sync_cursors"] = _count(
        db,
        "SELECT COUNT(*) AS count FROM provider_sync_cursors WHERE provider = ?",
        (_INTERVALS,),
    )
    counts["sync_jobs"] = _count(
        db,
        "SELECT COUNT(*) AS count FROM sync_jobs WHERE provider = ? "
        f"AND type IN ({_placeholders(INGEST_JOB_TYPES)})",
        (_INTERVALS, *INGEST_JOB_TYPES),
    )
    counts["provider_refresh_history"] = _count(
        db,
        "SELECT COUNT(*) AS count FROM provider_refresh_history WHERE provider = ? "
        f"AND area IN ({_placeholders(INGEST_REFRESH_AREAS)})",
        (_INTERVALS, *INGEST_REFRESH_AREAS),
    )
    where, params = _kv_filter()
    counts["kv"] = _count(db, f"SELECT COUNT(*) AS count FROM kv WHERE {where}", params)
    return counts


def _intervals_sessions(db: Any) -> dict[str, str]:
    """Every Intervals.icu session id with its state."""
    return {
        str(row["activity_id"]): str(row["state"])
        for row in db.execute(
            "SELECT activity_id, state FROM activity_sessions WHERE primary_provider = ?",
            (_INTERVALS,),
        )
    }


def _feedback_items(db: Any, sessions: Mapping[str, str]) -> tuple[list[_Stored], int]:
    """Feedback rows written for an Intervals.icu session, and the count of
    Intervals.icu rows that name no session and stay as they are."""
    rows = db.execute(
        "SELECT activity_id, provider, session_id, updated_at FROM activity_feedback"
    ).fetchall()
    attached = canonical_store.feedback_origin_sessions(
        db,
        [
            (str(row["activity_id"]), row["provider"])
            for row in rows
            if not row["session_id"]
        ],
    )
    items: list[_Stored] = []
    unresolved = 0
    for row in rows:
        key = str(row["activity_id"])
        origin = row["session_id"] or attached.get(key)
        if origin is not None and origin in sessions:
            items.append(_Stored(key, str(origin), str(row["updated_at"] or "")))
        elif origin is None and row["provider"] == _INTERVALS:
            unresolved += 1
    return items, unresolved


def _equipment_items(db: Any, sessions: Mapping[str, str]) -> list[_Stored]:
    """Equipment assignments stored for an Intervals.icu session."""
    rows = db.execute(
        "SELECT key, value, updated_at FROM kv WHERE substr(key, 1, ?) = ?",
        (len(_EQUIPMENT_PREFIX), _EQUIPMENT_PREFIX),
    ).fetchall()
    keys = {str(row["key"])[len(_EQUIPMENT_PREFIX) :]: row for row in rows}
    origins = canonical_store.feedback_origin_sessions(
        db, [(key, None) for key in keys]
    )
    items: list[_Stored] = []
    for key, row in keys.items():
        origin = origins.get(key)
        if origin is not None and origin in sessions:
            items.append(_Stored(key, origin, _observed_at(row)))
    return items


def _observed_at(row: Mapping[str, Any]) -> str:
    try:
        value = json.loads(row["value"])
    except TypeError, ValueError:
        value = None
    stamp = value.get("observed_at") if isinstance(value, dict) else None
    return str(stamp or row["updated_at"] or "")


def _live_roots(db: Any) -> set[str]:
    """Sessions that are not deleted and hold an active record or an alias with one."""
    owners = [
        str(row["activity_id"])
        for row in db.execute(
            "SELECT DISTINCT activity_id FROM activity_records "
            "WHERE state = 'active' AND activity_id IS NOT NULL"
        )
    ]
    effective = canonical_store.effective_session_ids(db, owners)
    roots = canonical_store.activity_sessions_by_ids(db, list(set(effective.values())))
    return {root for root, row in roots.items() if row["state"] != _DELETED}


def _survivors(db: Any, sessions: Mapping[str, str]) -> dict[str, str]:
    """Map each Intervals.icu session to the live session it now resolves to."""
    effective = canonical_store.effective_session_ids(db, list(sessions))
    live = _live_roots(db)
    return {
        session: target
        for session, target in effective.items()
        if target in live and target not in sessions
    }


def _families(db: Any, targets: Mapping[str, str]) -> dict[str, set[str]]:
    """Each survivor's key family: its id, alias session ids and the provider
    activity ids of their records, as the feedback and equipment reads use."""
    survivors = sorted(set(targets.values()))
    legacy = canonical_store.session_legacy_keys(db, survivors)
    return {target: {target, *legacy.get(target, ())} for target in survivors}


def _residents(
    families: Mapping[str, set[str]],
    stored: Mapping[str, str],
    moving: set[str],
) -> dict[str, list[tuple[str, str]]]:
    """Per survivor the (stamp, key) of the items already stored in its family."""
    return {
        target: [
            (stored[key], key)
            for key in sorted(family)
            if key in stored and key not in moving
        ]
        for target, family in families.items()
    }


def _plan(
    items: Sequence[_Stored],
    targets: Mapping[str, str],
    residents: Mapping[str, Sequence[tuple[str, str]]],
) -> _Moves:
    """Choose per survivor the newest of the moving and the resident items."""
    lost = tuple(sorted(item.key for item in items if item.origin not in targets))
    moving = {item.key for item in items}
    pools: dict[str, list[tuple[str, str]]] = {}
    for item in items:
        if item.origin in targets:
            pools.setdefault(targets[item.origin], []).append((item.stamp, item.key))
    moved: dict[str, str] = {}
    dropped: list[str] = []
    for target, pool in sorted(pools.items()):
        pool.extend(residents.get(target, ()))
        # Newest first; a tie keeps the item under the survivor id, then another
        # stored item, then the smaller key.
        ordered = sorted(pool, key=lambda entry: entry[1])
        ordered.sort(key=partial(_collision_rank, target, moving), reverse=True)
        (_, winner), *losers = ordered
        dropped.extend(key for _, key in losers)
        if winner in moving:
            moved[winner] = target
    return _Moves(moved, tuple(dropped), lost)


def _collision_rank(
    survivor: str, moving: set[str], entry: tuple[str, str]
) -> tuple[str, bool, bool]:
    """Newest first; a tie keeps the item under the survivor id, then a stored one."""
    return (entry[0], entry[1] == survivor, entry[1] not in moving)


def _rekey_feedback(
    db: Any, items: Sequence[_Stored], targets: Mapping[str, str], now: str
) -> dict[str, int]:
    families = _families(db, targets)
    stored = {
        str(row["activity_id"]): str(row["updated_at"] or "")
        for chunk in _chunks(key for family in families.values() for key in family)
        for row in db.execute(
            "SELECT activity_id, updated_at FROM activity_feedback "
            f"WHERE activity_id IN ({_placeholders(chunk)})",
            tuple(chunk),
        )
    }
    moving = {item.key for item in items}
    moves = _plan(items, targets, _residents(families, stored, moving))
    for key in (*moves.lost, *moves.dropped):
        db.execute("DELETE FROM activity_feedback WHERE activity_id = ?", (key,))
    repository = ActivityFeedbackRepository(lambda: now)
    for key, target in sorted(moves.moved.items()):
        repository.rekey(db, key, target)
    return {
        "feedback_rekeyed": len(moves.moved),
        "feedback_collisions_dropped": len(moves.dropped),
        "feedback_lost_intervals_only": len(moves.lost),
    }


def _rekey_equipment(
    db: Any, items: Sequence[_Stored], targets: Mapping[str, str]
) -> dict[str, int]:
    families = _families(db, targets)
    stored = {
        str(row["key"])[len(_EQUIPMENT_PREFIX) :]: _observed_at(row)
        for chunk in _chunks(key for family in families.values() for key in family)
        for row in db.execute(
            f"SELECT key, value, updated_at FROM kv WHERE key IN ({_placeholders(chunk)})",
            tuple(_EQUIPMENT_PREFIX + key for key in chunk),
        )
    }
    moving = {item.key for item in items}
    moves = _plan(items, targets, _residents(families, stored, moving))
    for key in (*moves.lost, *moves.dropped):
        db.execute("DELETE FROM kv WHERE key = ?", (_EQUIPMENT_PREFIX + key,))
    for key, target in sorted(moves.moved.items()):
        row = db.execute(
            "SELECT value, updated_at FROM kv WHERE key = ?", (_EQUIPMENT_PREFIX + key,)
        ).fetchone()
        try:
            value = json.loads(row["value"])
        except TypeError, ValueError:
            value = None
        stored = value if isinstance(value, dict) else {}
        db.execute("DELETE FROM kv WHERE key = ?", (_EQUIPMENT_PREFIX + key,))
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
            (
                _EQUIPMENT_PREFIX + target,
                json.dumps({**stored, "activity_id": target}),
                row["updated_at"],
            ),
        )
    return {
        "equipment_rekeyed": len(moves.moved),
        "equipment_collisions_dropped": len(moves.dropped),
        "equipment_lost_intervals_only": len(moves.lost),
    }


def _carry_targets(
    db: Any, sessions: Mapping[str, str], targets: Mapping[str, str], now: str
) -> int:
    """Move each frozen target snapshot to a survivor without one, then delete
    the analyses of the Intervals.icu sessions; return the snapshots carried."""
    carried = 0
    for chunk in _chunks(sessions):
        rows = db.execute(
            "SELECT activity_id, json_extract(payload, '$.target_snapshot') AS targets "
            "FROM activity_detail_analysis WHERE json_type(payload, "
            f"'$.target_snapshot') = 'object' AND activity_id IN ({_placeholders(chunk)}) "
            "ORDER BY activity_id",
            tuple(chunk),
        ).fetchall()
        for row in rows:
            target = targets.get(str(row["activity_id"]))
            if target is None:
                continue
            existing = db.execute(
                "SELECT json_type(payload, '$.target_snapshot') AS kind "
                "FROM activity_detail_analysis WHERE activity_id = ?",
                (target,),
            ).fetchone()
            if existing is None:
                db.execute(
                    "UPDATE activity_detail_analysis SET activity_id = ?, updated_at = ? "
                    "WHERE activity_id = ?",
                    (target, now, row["activity_id"]),
                )
            elif existing["kind"] != "object":
                db.execute(
                    "UPDATE activity_detail_analysis SET payload = json_set(payload, "
                    "'$.target_snapshot', json(?)), updated_at = ? WHERE activity_id = ?",
                    (row["targets"], now, target),
                )
            else:
                continue
            carried += 1
        db.execute(
            "DELETE FROM activity_detail_analysis "
            f"WHERE activity_id IN ({_placeholders(chunk)})",
            tuple(chunk),
        )
    return carried


def _delete_rows(db: Any) -> dict[str, int]:
    deleted = {
        table: int(
            db.execute(
                f"DELETE FROM {table} WHERE provider = ?", (_INTERVALS,)
            ).rowcount
        )
        for table in PROVIDER_TABLES
    }
    deleted["snapshots"] = int(db.execute("DELETE FROM snapshots").rowcount)
    deleted["provider_sync_cursors"] = int(
        db.execute(
            "DELETE FROM provider_sync_cursors WHERE provider = ?", (_INTERVALS,)
        ).rowcount
    )
    jobs = f"provider = ? AND type IN ({_placeholders(INGEST_JOB_TYPES)}) AND status <> 'running'"
    db.execute(
        f"DELETE FROM sync_job_items WHERE job_id IN (SELECT id FROM sync_jobs WHERE {jobs})",
        (_INTERVALS, *INGEST_JOB_TYPES),
    )
    deleted["sync_jobs"] = int(
        db.execute(
            f"DELETE FROM sync_jobs WHERE {jobs}", (_INTERVALS, *INGEST_JOB_TYPES)
        ).rowcount
    )
    deleted["provider_refresh_history"] = int(
        db.execute(
            "DELETE FROM provider_refresh_history WHERE provider = ? "
            f"AND area IN ({_placeholders(INGEST_REFRESH_AREAS)})",
            (_INTERVALS, *INGEST_REFRESH_AREAS),
        ).rowcount
    )
    where, params = _kv_filter()
    deleted["kv"] = int(db.execute(f"DELETE FROM kv WHERE {where}", params).rowcount)
    return deleted


def _referenced(db: Any, candidates: set[str]) -> set[str]:
    """The candidate sessions a row outside the candidates still references."""
    found: set[str] = set()
    for chunk in _chunks(candidates):
        marks = _placeholders(chunk)
        for column in ("merged_into", "merged_into_retained"):
            found.update(
                str(row["target"])
                for row in db.execute(
                    f"SELECT activity_id, {column} AS target FROM activity_sessions "
                    f"WHERE {column} IN ({marks})",
                    tuple(chunk),
                )
                if str(row["activity_id"]) not in candidates
            )
        for table, column in (
            ("activity_records", "activity_id"),
            ("activity_feedback", "session_id"),
            ("activity_detail_analysis", "activity_id"),
        ):
            found.update(
                str(row["target"])
                for row in db.execute(
                    f"SELECT DISTINCT {column} AS target FROM {table} "
                    f"WHERE {column} IN ({marks})",
                    tuple(chunk),
                )
            )
    return found


def _delete_sessions(
    db: Any, sessions: Mapping[str, str], targets: Mapping[str, str]
) -> int:
    """Delete the deleted Intervals.icu sessions without a survivor that nothing
    else references; the others stay as tombstones."""
    states = canonical_store.activity_sessions_by_ids(db, list(sessions))
    candidates = {
        session
        for session, row in states.items()
        if session not in targets and row["state"] == _DELETED
    }
    while referenced := _referenced(db, candidates):
        candidates -= referenced
    deleted = 0
    for chunk in _chunks(candidates):
        marks = _placeholders(chunk)
        # Retained references among the candidates go first, so no chunk order
        # can break the foreign key.
        db.execute(
            "UPDATE activity_sessions SET merged_into_retained = NULL "
            f"WHERE activity_id IN ({marks})",
            tuple(chunk),
        )
    for chunk in _chunks(candidates):
        deleted += int(
            db.execute(
                "DELETE FROM activity_sessions "
                f"WHERE activity_id IN ({_placeholders(chunk)})",
                tuple(chunk),
            ).rowcount
        )
    return deleted


def _mark_session_corrections(db: Any, sessions: Mapping[str, str]) -> int:
    """Keep session corrections that touched an Intervals.icu session from being
    undone, so an undo cannot bring a purged session back."""
    touching = [
        str(row["id"])
        for row in db.execute(
            "SELECT id, entity_id FROM change_history "
            "WHERE entity_type = ? AND action <> 'undo'",
            (SESSION_CORRECTION_ENTITY,),
        )
        if set(str(row["entity_id"]).split(",")) & sessions.keys()
    ]
    return change_history.mark_not_undoable(
        db, SESSION_CORRECTION_ENTITY, change_ids=touching
    )


def _drop_backfill_counters(db: Any, key_values: KeyValueRepository) -> None:
    """Remove the Intervals.icu counters of the canonical backfill state."""
    raw = key_values.get(db, BACKFILL_STATE_KEY)
    try:
        state = json.loads(raw) if raw else None
    except ValueError:
        return
    counters = state.get("counters") if isinstance(state, dict) else None
    if isinstance(counters, dict) and counters.pop(_INTERVALS, None) is not None:
        key_values.set(db, BACKFILL_STATE_KEY, json.dumps(state, sort_keys=True))


def purge_intervals_ingest(
    db: Any, key_values: KeyValueRepository, *, now: str
) -> dict[str, Any]:
    """Re-key the athlete data, then delete the Intervals.icu ingest data, in
    the caller's transaction; return content-free counts."""
    sessions = _intervals_sessions(db)
    feedback, unresolved = _feedback_items(db, sessions)
    equipment = _equipment_items(db, sessions)
    tombstoned = canonical_store.tombstone_provider_activities(
        db, _INTERVALS, record_kind=ACTIVITY_RECORD_KIND, now=now
    )
    targets = _survivors(db, sessions)
    counts: dict[str, Any] = {
        "activities_tombstoned": tombstoned,
        # Surviving sessions before (active or hidden) that handed their bundle on.
        "sessions_rebundled": sum(
            1
            for session, state in sessions.items()
            if session in targets and state not in _NOT_SURVIVING
        ),
        **_rekey_feedback(db, feedback, targets, now),
        "feedback_unresolved_kept": unresolved,
        **_rekey_equipment(db, equipment, targets),
        "target_snapshots_carried": _carry_targets(db, sessions, targets, now),
        "history_entries_not_undoable": change_history.mark_not_undoable(
            db, "activity_feedback"
        ),
        "session_corrections_not_undoable": _mark_session_corrections(db, sessions),
        "deleted": _delete_rows(db),
    }
    counts["sessions_deleted"] = _delete_sessions(db, sessions, targets)
    counts["sessions_kept_as_tombstones"] = _count(
        db,
        "SELECT COUNT(*) AS count FROM activity_sessions WHERE primary_provider = ?",
        (_INTERVALS,),
    )
    _drop_backfill_counters(db, key_values)
    key_values.set(db, INGEST_ENABLED_KEY, "0")
    return counts


def _ingest_job_running(db: Any) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sync_jobs WHERE provider = ? AND status = 'running' "
            f"AND type IN ({_placeholders(INGEST_JOB_TYPES)}) LIMIT 1",
            (_INTERVALS, *INGEST_JOB_TYPES),
        ).fetchone()
        is not None
    )


def purge_due(
    db: Any, key_values: KeyValueRepository, *, marker_exists: bool = False
) -> bool:
    """Whether the purge of this version still has to run and may run now.

    It waits for the finished Garmin rating backfill and for a running
    Intervals.icu ingest job. A direct sync is caught by the runner, which holds
    the Intervals.icu sync lock while it writes; the stored ``sync_running``
    flag is not read, as a crash can leave it set (the purge deletes it).
    ``marker_exists`` (the marker file of a completed purge) means a restored
    pre-purge database, which is not purged again automatically.
    """
    return (
        not marker_exists
        and not purge_done(purge_state(key_values, db))
        and rating_backfill_finished(key_values, db)
        and not _ingest_job_running(db)
    )


def run_purge(
    db: Any, key_values: KeyValueRepository, *, now: str, ignore_gate: bool = False
) -> dict[str, Any] | None:
    """Run the purge in the caller's transaction once it is due and store the
    completion marker; return its counts, or None when it was not due.

    ``ignore_gate`` runs it regardless, for the dry run that rolls back.
    """
    if not ignore_gate and not purge_due(db, key_values):
        return None
    counts = purge_intervals_ingest(db, key_values, now=now)
    key_values.set(
        db,
        STATE_KEY,
        json.dumps(
            {
                "version": PURGE_VERSION,
                "status": STATUS_DONE,
                "completed_at": now,
                "counts": counts,
            },
            sort_keys=True,
        ),
    )
    return counts


def purge_status(
    db: Any, key_values: KeyValueRepository, *, marker_exists: bool = False
) -> dict[str, Any]:
    """The purge state for diagnostics: a state word, the version and counts.

    ``done_restored``: the marker file exists but the database has no marker,
    as after restoring the pre-purge copy; it is not purged again automatically.
    """
    state = purge_state(key_values, db)
    if purge_done(state):
        return {
            "status": STATUS_DONE,
            "version": state["version"],
            "counts": state.get("counts") or {},
        }
    if marker_exists:
        return {"status": STATUS_DONE_RESTORED, "version": PURGE_VERSION}
    finished = rating_backfill_finished(key_values, db)
    return {
        "status": STATUS_PENDING if finished else STATUS_WAITING,
        "version": PURGE_VERSION,
    }


class IntervalsPurgeRunner:
    """Run the purge once it is due, after a recovery copy of the database.

    A failed run is rolled back and not retried before the next start, so a
    repeating failure never writes one recovery copy per pass.
    """

    def __init__(
        self,
        *,
        database: Callable[[], Any],
        key_values: KeyValueRepository,
        maintenance_gate: MaintenanceGate,
        backup: Callable[[], str],
        clock: Callable[[], str],
        data_dir: Callable[[], Path],
        sync_lock: Any,
        writer_wait_seconds: float = WRITER_WAIT_SECONDS,
    ) -> None:
        self._database = database
        self._key_values = key_values
        self._maintenance_gate = maintenance_gate
        self._backup = backup
        self._clock = clock
        self._data_dir = data_dir
        # The Intervals.icu sync lock: held while the purge writes, so no direct
        # sync stores Intervals.icu rows meanwhile.
        self._sync_lock = sync_lock
        self._writer_wait_seconds = writer_wait_seconds
        self._stopped = False

    def marker_exists(self) -> bool:
        """Whether this data directory holds the marker of a completed purge."""
        return purge_marker_exists(self._data_dir())

    def _recovery_copy(self) -> str:
        """Reuse this version's recovery copy, else write it."""
        existing = sorted(self._data_dir().glob(f"*.{BACKUP_LABEL}-*"))
        return existing[0].name if existing else self._backup()

    def _write_marker(self, completed_at: str) -> None:
        try:
            (self._data_dir() / MARKER_FILE).write_text(
                completed_at + "\n", encoding="utf-8"
            )
        except OSError as exc:
            _LOGGER.warning(
                "Intervals.icu purge marker file not written",
                extra={
                    "event": "intervals_purge_marker_failed",
                    "error_class": type(exc).__name__,
                },
            )

    def run(self) -> None:
        """Purge when due; a restore in progress postpones it to a later pass."""
        if self._stopped:
            return
        try:
            with self._maintenance_gate.operation():
                counts = self._run()
        except AppError as exc:
            if exc.reason == "maintenance":
                return
            raise
        if counts is not None:
            _LOGGER.info(
                "Intervals.icu ingest data purged",
                extra={"event": "intervals_purge_done", "context": counts},
            )

    def _run(self) -> dict[str, Any] | None:
        marker = self.marker_exists()
        with self._database().reader() as db:
            if not purge_due(db, self._key_values, marker_exists=marker):
                return None
        try:
            # Outside the writer: copying the database must not block other writes.
            self._recovery_copy()
            if not self._sync_lock.acquire(blocking=False):
                return None
            try:
                now = self._clock()
                with self._database().unit_of_work(
                    timeout=self._writer_wait_seconds
                ) as db:
                    counts = run_purge(db, self._key_values, now=now)
            finally:
                self._sync_lock.release()
            if counts is not None:
                self._write_marker(now)
            return counts
        except Exception as exc:  # noqa: BLE001 - rolled back, logged, not retried
            self._stopped = True
            _LOGGER.error(
                "Intervals.icu purge failed",
                extra={
                    "event": "intervals_purge_failed",
                    "error_class": type(exc).__name__,
                },
            )
            return None
