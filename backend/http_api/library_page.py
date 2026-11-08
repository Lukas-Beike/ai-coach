"""Read-only pagination for active workout-library templates."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from backend.db import DatabaseManager
from backend.http_api import pagination
from backend.planning.sport import with_activity_type


class LibraryPageService:
    def __init__(
        self,
        database_manager: DatabaseManager,
        workout_library: Any,
        *,
        maximum: int = 100,
        wahoo_states: Callable[[Iterable[Mapping[str, Any]]], dict[str, dict[str, str]]]
        | None = None,
    ):
        self._database_manager = database_manager
        self._workout_library = workout_library
        self._wahoo_states = wahoo_states
        self._maximum = maximum

    def page(self, cursor: Any = None, limit: Any = None) -> dict[str, Any]:
        decoded = pagination.decode_page_cursor(cursor)
        decoded_cursor: list[str] | None = None
        if isinstance(decoded, list) and len(decoded) == 3:
            decoded_cursor = [str(part) for part in decoded]
        page_size = pagination.api_page_limit(
            limit, pagination.API_PAGE_DEFAULT, self._maximum
        )
        with self._database_manager.reader() as db:
            rows = self._workout_library.page_in_transaction(
                db, decoded_cursor, page_size + 1
            )
        page = rows[:page_size]
        wahoo = self._wahoo_states(page) if self._wahoo_states else {}
        return {
            "workouts": [
                {
                    **with_activity_type(json.loads(row["payload"])),
                    **(
                        {"wahoo_state": wahoo[row["local_id"]]}
                        if row["local_id"] in wahoo
                        else {}
                    ),
                }
                for row in page
            ],
            "next_cursor": pagination.encode_page_cursor(
                [page[-1][key] for key in ("sport_key", "name_key", "id")]
            )
            if len(rows) > page_size
            else None,
            "limit": page_size,
        }
