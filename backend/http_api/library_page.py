"""Read-only pagination for active workout-library templates."""

from __future__ import annotations

import json
from typing import Any

from backend.db import DatabaseManager
from backend.db.repositories import LibraryPageRepository
from backend.http_api import pagination


class LibraryPageService:
    def __init__(self, database_manager: DatabaseManager, *, maximum: int = 100):
        self._database_manager = database_manager
        self._maximum = maximum
        self._repository = LibraryPageRepository()

    def page(self, cursor: Any = None, limit: Any = None) -> dict[str, Any]:
        decoded = pagination.decode_page_cursor(cursor)
        decoded_cursor: list[str] | None = None
        if isinstance(decoded, list) and len(decoded) == 3:
            decoded_cursor = [str(part) for part in decoded]
        page_size = pagination.api_page_limit(
            limit, pagination.API_PAGE_DEFAULT, self._maximum
        )
        with self._database_manager.reader() as db:
            rows = self._repository.page(db, decoded_cursor, page_size + 1)
        page = rows[:page_size]
        return {
            "workouts": [json.loads(row["payload"]) for row in page],
            "next_cursor": pagination.encode_page_cursor(
                [page[-1][key] for key in ("sport_key", "name_key", "id")]
            )
            if len(rows) > page_size
            else None,
            "limit": page_size,
        }
