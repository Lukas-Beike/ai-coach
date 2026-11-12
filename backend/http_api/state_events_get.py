"""Authenticated dispatch for the state-event stream endpoint."""

import select
import socket
from collections.abc import Callable
from typing import Any

from backend.http_api.auth import SessionAuthService
from backend.http_api.route_table import Access, Route, RouteRequest
from backend.http_api.state_events_transport import StateEventTransport


def client_is_connected(connection: socket.socket) -> bool:
    """Return False once the peer closed its end, without consuming any bytes."""
    try:
        if not select.select([connection], [], [], 0)[0]:
            return True
        return connection.recv(1, socket.MSG_PEEK) != b""
    except OSError, ValueError:
        return False


class StateEventsGetRoutes:
    """Authenticate state-event requests before delegating to the SSE transport."""

    def __init__(
        self,
        session_auth_service: Callable[[], SessionAuthService],
        state_event_transport: StateEventTransport,
    ) -> None:
        self._session_auth_service = session_auth_service
        self._state_event_transport = state_event_transport

    def routes(self) -> list[Route]:
        return [Route("GET", "/api/state/events", Access.SESSION, self._events)]

    def _events(self, handler: Any, _request: RouteRequest) -> None:
        """Authenticated state event stream.

        Request: query `since` (last seen event id: ASCII digits, at most 19;
        default 0).

        Response: 200 `text/event-stream`, kept open until the client or its
        session ends. It sends the retained events after `since` as SSE events
        named `provider`, `job`, `planning`, `coach` or `sync` (each with `id:`
        and a JSON object), then `ready` with `latest_event_id`. A `since` the
        buffer no longer covers, or ahead of it (earlier process), sends `reset`
        with `reason` `gap` and `latest_event_id` instead. Every 15 seconds
        without an event it sends `heartbeat` with `latest_event_id`.

        Errors: 400 `invalid_event_cursor` "Die Event-ID ist ungültig." for a
        malformed `since`, before the stream starts.
        """
        self._state_event_transport.handle(
            handler.path,
            send_headers=handler.send_sse_headers,
            send_event=handler.send_sse_event,
            set_connection_timeout=handler.connection.settimeout,
            client_is_connected=lambda: client_is_connected(handler.connection),
            session_is_active=lambda: (
                self._session_auth_service().authenticated_session(handler) is not None
            ),
        )
