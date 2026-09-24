"""Bounded, session-aware pages of local Coach chat history."""

from __future__ import annotations

import threading
from typing import Any

from backend.coach.proposals import CoachProposalReadService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.http_api import pagination


class ChatHistoryPageService:
    def __init__(
        self,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        proposal_read_service: CoachProposalReadService,
        database_lock: threading.RLock,
        *,
        maximum: int = 100,
    ) -> None:
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._proposal_read_service = proposal_read_service
        self._database_lock = database_lock
        self._maximum = maximum

    def page(
        self,
        cursor: Any = None,
        limit: Any = None,
        search: Any = None,
        *,
        session_csrf_hash: str = "",
    ) -> dict[str, Any]:
        page_size = pagination.api_page_limit(
            limit, pagination.API_PAGE_DEFAULT, self._maximum
        )
        term = str(search or "").strip()[:200]
        params: list[Any] = []
        clauses: list[str] = []
        if term:
            clauses.append("content LIKE ? ESCAPE '\\'")
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        decoded = pagination.decode_page_cursor(cursor)
        if isinstance(decoded, int) or (
            isinstance(decoded, str) and decoded.isdigit()
        ):
            clauses.append("id < ?")
            params.append(int(decoded))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

        with self._database_lock, self._database_manager.unit_of_work() as db:
            rows = db.execute(
                "SELECT id, role, content, client_turn_id, created_at, "
                "(SELECT json_group_array(json_extract(value, '$.name')) "
                "FROM json_each(messages.attachments)) AS attachment_names "
                f"FROM messages{where} ORDER BY id DESC LIMIT ?",
                (*params, page_size + 1),
            ).fetchall()
            generation = (
                self._key_value_repository.get(db, "chat_generation") or "initial"
            )

        has_more = len(rows) > page_size
        rows = rows[:page_size]
        return {
            "generation": generation,
            "messages": [
                {
                    key: value
                    for key, value in row.items()
                    if (key != "client_turn_id" or value is not None)
                    and (key != "attachment_names" or value != "[]")
                }
                for row in reversed(rows)
            ],
            "proposed_actions": self._proposal_read_service.current(
                session_csrf_hash
            ),
            "next_cursor": pagination.encode_page_cursor(int(rows[-1]["id"]))
            if has_more and rows
            else None,
            "limit": page_size,
            "search": term,
        }
