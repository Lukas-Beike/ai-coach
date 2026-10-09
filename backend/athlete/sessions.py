"""Persistence operations for authenticated athlete sessions."""

from __future__ import annotations

from typing import Any

from backend.db.repositories import SessionRepository


class AthleteSessionService:
    def __init__(self, repository: SessionRepository | None = None) -> None:
        self._repository = repository or SessionRepository()

    def cleanup_expired(self, db: Any, now: float, limit: int) -> int:
        return self._repository.cleanup_expired(db, now, limit)

    def get(self, db: Any, token_hash: str) -> Any:
        return self._repository.get(db, token_hash)

    def delete(self, db: Any, token_hash: str) -> None:
        self._repository.delete(db, token_hash)

    def touch(self, db: Any, token_hash: str, last_seen: str) -> None:
        self._repository.touch(db, token_hash, last_seen)

    def create(
        self,
        db: Any,
        token_hash: str,
        csrf_hash: str,
        expires_at: float,
        created_at: str,
        last_seen: str,
    ) -> None:
        self._repository.create(
            db, token_hash, csrf_hash, expires_at, created_at, last_seen
        )

    def list_csrf(self, db: Any) -> list[Any]:
        return self._repository.list_csrf(db)
