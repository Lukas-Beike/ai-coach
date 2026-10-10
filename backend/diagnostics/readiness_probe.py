"""Database readiness probe owned by the diagnostics domain."""

from __future__ import annotations

from typing import Any

from backend.db.repositories import ReadinessRepository


class ReadinessProbeService:
    def __init__(self, repository: ReadinessRepository | None = None) -> None:
        self._repository = repository or ReadinessRepository()

    def database_available(self, db: Any) -> bool:
        return self._repository.database_available(db)
