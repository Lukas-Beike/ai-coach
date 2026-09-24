"""Coach commands that enqueue explicit planned-workout pushes."""

from __future__ import annotations

from typing import Any

from backend.sync.queue import SyncJobQueueService


class PlanPushCommandService:
    """Chunk authorized plan pushes and enqueue their provider jobs."""

    def __init__(self, queue_service: SyncJobQueueService) -> None:
        self._queue_service = queue_service

    def enqueue(
        self,
        entries: list[dict[str, str]],
        sync_job_ids: list[str],
        *,
        reason: str,
        repair: bool = False,
    ) -> dict[str, Any]:
        jobs: list[dict[str, Any]] = []
        for offset in range(0, len(entries), 28):
            chunk = entries[offset:offset + 28]
            payload: dict[str, Any] = {
                "entries": chunk,
                "reason": reason[:200] or "coach",
            }
            if repair:
                payload["repair"] = True
            item_operations = [
                {
                    "item_key": entry["library_workout_id"],
                    "operation": "plan_push",
                    "payload_hash": entry["expected_payload_hash"],
                }
                for entry in chunk
            ]
            job = self._queue_service.enqueue(
                "intervals",
                "plan_push",
                payload,
                requested_by="coach",
                item_operations=item_operations,
            )
            jobs.append(job)
            sync_job_ids.append(job["id"])

        job_ids = [job["id"] for job in jobs]
        return {
            "ok": True,
            "status": "queued" if jobs else "completed",
            "sync_job_id": job_ids[0] if len(job_ids) == 1 else None,
            "sync_job_ids": job_ids,
            "entries": len(entries),
        }
