"""Diagnostic projection of Intervals.icu plan-push jobs and unsynced plan units."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.providers.descriptors import INTERVALS_ID
from backend.sync.jobs import list_jobs

_JOB_LIMIT = 10
_UNIT_LIMIT = 50
_ERROR_LIMIT = 300


def summarize_plan_sync(db: Any, redact: Callable[[str], str]) -> dict[str, Any]:
    """Report recent plan_push outcomes and every unit still waiting or failing."""

    def clean(value: Any) -> str | None:
        return redact(str(value))[:_ERROR_LIMIT] if value else None

    jobs = [
        job
        for job in list_jobs(db, 50)
        if job["provider"] == INTERVALS_ID and job["type"] == "plan_push"
    ][:_JOB_LIMIT]
    units = db.execute(
        "SELECT local_id, sync_state, sync_error, "
        "json_extract(payload, '$.date') AS date FROM planned_units "
        "WHERE tombstone=0 AND sync_state<>'synced' ORDER BY date LIMIT ?",
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
