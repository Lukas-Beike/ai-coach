"""Bounded, session-aware pages of local Coach chat history."""

from __future__ import annotations

from typing import Any

from backend.coach.conversation import CoachConversationHistoryService
from backend.coach.proposal_read import CoachProposalReadService
from backend.errors import AppError
from backend.http_api import pagination

# SQLite integers are signed 64-bit, so a message id has at most 19 digits.
_SQLITE_MAX_INTEGER = 2**63 - 1
_MAX_CURSOR_DIGITS = 19


def _before_message_id(cursor: Any, decoded: Any) -> int | None:
    if not cursor:
        return None
    value: int | None = None
    if type(decoded) is int:
        value = decoded
    elif (
        isinstance(decoded, str)
        and len(decoded) <= _MAX_CURSOR_DIGITS
        and decoded.isascii()
        and decoded.isdigit()
    ):
        value = int(decoded)
    if value is None or not 0 <= value <= _SQLITE_MAX_INTEGER:
        raise AppError(400, "Ungültiger Cursor.", reason="invalid_page_cursor")
    return value


class ChatHistoryPageService:
    def __init__(
        self,
        conversation_history: CoachConversationHistoryService,
        proposal_read_service: CoachProposalReadService,
        *,
        maximum: int = 100,
    ) -> None:
        self._conversation_history = conversation_history
        self._proposal_read_service = proposal_read_service
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
        decoded = pagination.decode_page_cursor(cursor)
        before_message_id = _before_message_id(cursor, decoded)

        generation, rows = self._conversation_history.page(
            before_message_id=before_message_id,
            search=term,
            limit=page_size + 1,
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
            "proposed_actions": self._proposal_read_service.current(session_csrf_hash),
            "next_cursor": pagination.encode_page_cursor(int(rows[-1]["id"]))
            if has_more and rows
            else None,
            "limit": page_size,
            "search": term,
        }
