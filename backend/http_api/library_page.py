"""Read-only pagination for active workout-library templates."""

from __future__ import annotations

import json
from typing import Any

from backend.db import DatabaseManager
from backend.http_api import pagination


class LibraryPageService:
    def __init__(self, database_manager: DatabaseManager, *, maximum: int = 100):
        self._database_manager = database_manager
        self._maximum = maximum

    def page(self, cursor: Any = None, limit: Any = None) -> dict[str, Any]:
        decoded = pagination.decode_page_cursor(cursor)
        after_clause = ""
        params: list[Any] = []
        if isinstance(decoded, list) and len(decoded) == 3:
            after_clause = "WHERE (sport_key, name_key, id) > (?, ?, ?)"
            params.extend(str(part) for part in decoded)
        page_size = pagination.api_page_limit(
            limit, pagination.API_PAGE_DEFAULT, self._maximum
        )
        with self._database_manager.reader() as db:
            rows = db.execute(
                "WITH templates AS ("
                "SELECT id, payload, lower(COALESCE(json_extract(payload, '$.type'), '')) AS sport_key, "
                "lower(COALESCE(json_extract(payload, '$.name'), '')) AS name_key "
                "FROM workout_library WHERE json_valid(payload) AND json_type(payload)='object' "
                "AND json_extract(payload, '$.date') IS NULL AND COALESCE(json_extract(payload, '$.archived'), 0)=0) "
                f"SELECT id, payload, sport_key, name_key FROM templates {after_clause} "
                "ORDER BY sport_key, name_key, id LIMIT ?",
                (*params, page_size + 1),
            ).fetchall()
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
