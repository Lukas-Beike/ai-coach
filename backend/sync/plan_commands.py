"""Coach commands that enqueue explicit planned-workout pushes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.canonical.vocabulary import INTERVALS_ID, ProviderId
from backend.errors import AppError
from backend.sync.garmin_personal_status import SDK_REQUIRED_MESSAGE
from backend.sync.queue import SyncJobQueueService

_NOTHING_QUEUED = (
    "Es wurde nichts synchronisiert: keine offenen Einträge ausgewählt. "
    "Das nicht als erfolgreiche Übertragung melden."
)


class PlanPushCommandService:
    """Chunk authorized plan pushes and enqueue their provider jobs."""

    def __init__(
        self,
        queue_service: SyncJobQueueService,
        garmin_writable: Callable[[], bool] = lambda: True,
    ) -> None:
        self._queue_service = queue_service
        # False without an SDK login: the Personal API key cannot write.
        self._garmin_writable = garmin_writable

    def enqueue(
        self,
        entries: list[dict[str, str]],
        sync_job_ids: list[str],
        *,
        reason: str,
        repair: bool = False,
        provider: str = INTERVALS_ID,
    ) -> dict[str, Any]:
        if provider == ProviderId.GARMIN.value and not self._garmin_writable():
            raise AppError(409, SDK_REQUIRED_MESSAGE, reason="garmin_sdk_required")
        jobs: list[dict[str, Any]] = []
        for offset in range(0, len(entries), 28):
            chunk = entries[offset : offset + 28]
            payload: dict[str, Any] = {
                "entries": chunk,
                "reason": reason[:200] or "coach",
            }
            if repair:
                payload["repair"] = True
            # A Garmin removal has no payload hash; the store derives one.
            item_operations = [
                {
                    "item_key": entry["library_workout_id"],
                    "operation": "plan_push",
                    "payload_hash": entry.get("expected_payload_hash") or "",
                }
                for entry in chunk
            ]
            job = self._queue_service.enqueue(
                provider,
                "plan_push",
                payload,
                requested_by="coach",
                item_operations=item_operations,
            )
            jobs.append(job)
            sync_job_ids.append(job["id"])

        job_ids = [job["id"] for job in jobs]
        note = {} if jobs else {"message": _NOTHING_QUEUED}
        return {
            **note,
            "ok": True,
            "status": "queued" if jobs else "completed",
            "sync_job_id": job_ids[0] if len(job_ids) == 1 else None,
            "sync_job_ids": job_ids,
            "entries": len(entries),
        }
