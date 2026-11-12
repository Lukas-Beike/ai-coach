"""Diagnostic projection of plan-push jobs of every provider and unsynced plan units."""

from __future__ import annotations

import json
from typing import Any

from backend.db.repositories import KeyValueRepository
from backend.sync.garmin_strength_push import APP_WORKOUT_CLEANUP_KEY
from backend.sync.jobs import job_dto, read_job

_OUTCOMES = frozenset({"ok", "failed", "skipped"})

_JOB_LIMIT = 10
_UNIT_LIMIT = 50


def summarize_plan_sync(db: Any) -> dict[str, Any]:
    """Report plan_push outcomes by status and error class, never provider error text.

    The unsynced units are the local planned calendar, which only Intervals.icu
    receives; the last plan sync of each provider is in ``sync.providers``.
    """

    job_rows = db.execute(
        "SELECT id FROM sync_jobs WHERE type='plan_push' "
        "ORDER BY created_at DESC LIMIT ?",
        (_JOB_LIMIT,),
    ).fetchall()
    jobs = [job_dto(*read_job(db, row["id"])) for row in job_rows]
    unsynced = "FROM planned_units WHERE tombstone=0 AND sync_state<>'synced'"
    total = db.execute(f"SELECT COUNT(*) AS count {unsynced}").fetchone()["count"]
    # Upcoming units first: past units must not hide the ones still to be pushed.
    units = db.execute(
        "SELECT local_id, sync_state, sync_error, "
        # A payload that is not valid JSON has no date instead of failing the report.
        "CASE WHEN json_valid(payload) THEN json_extract(payload, '$.date') "
        f"END AS date {unsynced} "
        "ORDER BY date < date('now'), date LIMIT ?",
        (_UNIT_LIMIT,),
    ).fetchall()
    return {
        "recent_jobs": [
            {
                "id": job["id"],
                "provider": job["provider"],
                "status": job["status"],
                "requested_by": job["requested_by"],
                "entries": len(job["payload"].get("entries") or []),
                "repair": bool(job["payload"].get("repair")),
                "attempts": job["attempts"],
                "error_class": job["error_class"],
                "created_at": job["created_at"],
                "finished_at": job["finished_at"],
                "items": [
                    {
                        "status": item["status"],
                        "error_class": item["error_class"],
                    }
                    for item in job["items"]
                    if item["status"] not in {"completed", "skipped"}
                ],
            }
            for job in jobs
        ],
        "unsynced_total": total,
        "unsynced_units": [
            {
                "local_id": unit["local_id"],
                "date": unit["date"],
                "sync_state": unit["sync_state"],
                "has_error": bool(unit["sync_error"]),
            }
            for unit in units
        ],
    }


def summarize_garmin_removal(db: Any) -> dict[str, Any]:
    """Counts only: the one-time removal's state, removals and the last run.

    ``past_links_pending`` counts the past linked workouts the last run left,
    by the athlete-local day the removal uses.
    """
    try:
        state = json.loads(
            KeyValueRepository(str).get(db, APP_WORKOUT_CLEANUP_KEY) or "{}"
        )
    except TypeError, ValueError:
        state = {}
    state = state if isinstance(state, dict) else {}
    last_run = state.get("last_run_at")
    checked = state.get("checked")
    outcome = state.get("last_outcome")
    return {
        "one_time_done": state.get("done") is True,
        "checked": len(checked) if isinstance(checked, list) else 0,
        "removed": _count(state.get("removed")),
        "last_run_at": last_run if isinstance(last_run, str) else None,
        "last_outcome": outcome if outcome in _OUTCOMES else None,
        "past_links_pending": _count(state.get("pending")),
    }


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
