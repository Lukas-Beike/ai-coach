"""Coach commands for resolving local sync conflicts and retrying sync jobs."""

from __future__ import annotations

from typing import Any

from backend.planning.competition_service import CompetitionService
from backend.sync.queue import SyncJobQueueService


class SyncConflictCommandService:
    """Orchestrate conflict decisions after Coach authorization has succeeded."""

    _PUSH_JOB_TYPES = frozenset({"plan_push", "competition_push", "nutrition_sync"})

    def __init__(
        self,
        competition_service: CompetitionService,
        job_queue_service: SyncJobQueueService,
    ) -> None:
        self._competition_service = competition_service
        self._job_queue_service = job_queue_service

    def resolve_local(
        self, local_id: str, strategy: str = "keep_local"
    ) -> dict[str, Any]:
        """Resolve a competition conflict by its local ID."""
        return {
            "ok": True,
            **self._competition_service.resolve_conflict(
                str(local_id or "").strip(),
                str(strategy or "keep_local").strip().casefold(),
            ),
        }

    def job_state(self, job_id: str) -> dict[str, Any]:
        """Return the queue-owned state needed to authorize a retry."""
        return self._job_queue_service.state(str(job_id or "").strip())

    def retry_job(self, job_id: str) -> dict[str, Any]:
        """Explicitly retry a previously authorized sync job."""
        normalized_id = str(job_id or "").strip()
        job = self._job_queue_service.resolve(normalized_id, {"action": "retry"})
        return {"ok": True, "status": "queued", "job": job}

    @classmethod
    def is_push_job(cls, job: dict[str, Any]) -> bool:
        """Classify queue jobs using the existing remote-write type contract."""
        return job.get("type") in cls._PUSH_JOB_TYPES
