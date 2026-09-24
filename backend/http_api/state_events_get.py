"""Authenticated dispatch for the state-event stream endpoint."""

from collections.abc import Callable
from typing import Any

from backend.http_api.auth import SessionAuthService
from backend.http_api.state_events_transport import StateEventTransport


class StateEventsGetRoutes:
    """Authenticate state-event requests before delegating to the SSE transport."""

    def __init__(
        self,
        session_auth_service: Callable[[], SessionAuthService],
        state_event_transport: StateEventTransport,
    ) -> None:
        self._session_auth_service = session_auth_service
        self._state_event_transport = state_event_transport

    def handle(self, handler: Any, path: str) -> bool:
        if path != "/api/state/events":
            return False

        self._session_auth_service().require_auth(handler)
        self._state_event_transport.handle(
            handler.path,
            send_headers=handler.send_sse_headers,
            send_event=handler.send_sse_event,
            set_connection_timeout=handler.connection.settimeout,
        )
        return True
