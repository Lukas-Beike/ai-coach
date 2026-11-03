"""Diagnostic projection of Intervals.icu plan-push jobs and unsynced plan units."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.providers.descriptors import INTERVALS_ID
from backend.sync.jobs import job_dto, read_job

_JOB_LIMIT = 10
_UNIT_LIMIT = 50
_ERROR_LIMIT = 300


def summarize_plan_sync(db: Any, redact: Callable[[str], str]) -> dict[str, Any]:
    """Report recent plan_push outcomes and every unit still waiting or failing."""

    def clean(value: Any) -> str | None:
        return redact(str(value))[:_ERROR_LIMIT] if value else None

    job_rows = db.execute(
        "SELECT id FROM sync_jobs WHERE provider=? AND type='plan_push' "
        "ORDER BY created_at DESC LIMIT ?",
        (INTERVALS_ID, _JOB_LIMIT),
    ).fetchall()
    jobs = [job_dto(*read_job(db, row["id"])) for row in job_rows]
    unsynced = "FROM planned_units WHERE tombstone=0 AND sync_state<>'synced'"
    total = db.execute(f"SELECT COUNT(*) AS count {unsynced}").fetchone()["count"]
    # Upcoming units first: past units must not hide the ones still to be pushed.
    units = db.execute(
        "SELECT local_id, sync_state, sync_error, "
        f"json_extract(payload, '$.date') AS date {unsynced} "
        "ORDER BY date < date('now'), date LIMIT ?",
        (_UNIT_LIMIT,),
    ).fetchall()
    return {
        "recent_jobs": [
            {
                "id": job["id"],
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
                        "error_detail": clean(item["error_detail"]),
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
                "sync_error": clean(unit["sync_error"]),
            }
            for unit in units
        ],
    }
