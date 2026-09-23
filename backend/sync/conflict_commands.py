"""Coach commands for resolving local sync conflicts and retrying sync jobs."""

from __future__ import annotations

from typing import Any

from backend.db.manager import DatabaseManager
from backend.planning.competition_service import CompetitionService
from backend.planning.planned_unit_service import PlannedUnitService
from backend.sync.queue import SyncJobQueueService


class SyncConflictCommandService:
    """Orchestrate conflict decisions after Coach authorization has succeeded."""

    _PUSH_JOB_TYPES = frozenset({"plan_push", "competition_push"})

    def __init__(
        self,
        database_manager: DatabaseManager,
        planned_unit_service: PlannedUnitService,
        competition_service: CompetitionService,
        job_queue_service: SyncJobQueueService,
    ) -> None:
        self._database_manager = database_manager
        self._planned_unit_service = planned_unit_service
        self._competition_service = competition_service
        self._job_queue_service = job_queue_service

    def resolve_local(
        self, local_id: str, strategy: str = "keep_local"
    ) -> dict[str, Any]:
        """Resolve a planned-unit or competition conflict by its local ID."""
        normalized_id = str(local_id or "").strip()
        selected_strategy = str(strategy or "keep_local").strip().casefold()
        with self._database_manager.reader() as db:
            planned = db.execute(
                "SELECT 1 FROM planned_units WHERE local_id=?", (normalized_id,)
            ).fetchone()
        service = (
            self._planned_unit_service if planned else self._competition_service
        )
        return {
            "ok": True,
            **service.resolve_conflict(normalized_id, selected_strategy),
        }

    def job_state(self, job_id: str) -> dict[str, Any]:
        """Return the queue-owned state needed to authorize a retry."""
        return self._job_queue_service.state(str(job_id or "").strip())

    def retry_job(self, job_id: str) -> dict[str, Any]:
        """Explicitly retry a previously authorized sync job."""
        normalized_id = str(job_id or "").strip()
        job = self._job_queue_service.resolve(
            normalized_id, {"action": "retry"}
        )
        return {"ok": True, "status": "queued", "job": job}

    @classmethod
    def is_push_job(cls, job: dict[str, Any]) -> bool:
        """Classify queue jobs using the existing remote-write type contract."""
        return job.get("type") in cls._PUSH_JOB_TYPES
