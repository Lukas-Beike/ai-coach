"""Transport orchestration for the authenticated public state-event stream."""

import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.errors import AppError, ClientDisconnected, DatabaseBusyError

_LOGGER = logging.getLogger("intervals_coach")
# Event ids are positive integers that fit a signed 64-bit value.
_MAX_CURSOR_DIGITS = 19
_HEARTBEAT_SECONDS = 15
# A stream holds one request slot; a closed browser tab must free it within this
# time, not at the next heartbeat write.
_DISCONNECT_CHECK_SECONDS = 1


class StateEventTransport:
    """Own cursor, gap, heartbeat, and connection-loop behavior for state SSE."""

    def __init__(self, event_buffer: Any):
        self.event_buffer = event_buffer

    @staticmethod
    def send_batch(
        batch: dict[str, Any], since: int, send_event: Callable[..., None]
    ) -> tuple[int, bool]:
        if batch["gap"]:
            latest_event_id = int(batch["latest_event_id"])
            send_event(
                "reset",
                {"reason": "gap", "latest_event_id": latest_event_id},
                latest_event_id or None,
            )
            return latest_event_id, True
        for item in batch["events"]:
            since = int(item["event_id"])
            send_event(item["event"], item["data"], since)
        return since, False

    def _wait_for_activity(self, client_is_connected: Callable[[], bool]) -> bool:
        """Wait for an event or the heartbeat time; False once the client left."""
        deadline = time.monotonic() + _HEARTBEAT_SECONDS
        while client_is_connected():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            if self.event_buffer.wait(
                timeout=min(_DISCONNECT_CHECK_SECONDS, remaining)
            ):
                return True
        return False

    def handle(
        self,
        request_target: str,
        *,
        send_headers: Callable[[], None],
        send_event: Callable[..., None],
        set_connection_timeout: Callable[[float | None], None],
        client_is_connected: Callable[[], bool],
        session_is_active: Callable[[], bool],
    ) -> None:
        query = parse_qs(urlparse(request_target).query)
        raw_since = query.get("since", ["0"])[0]
        if not (
            raw_since.isascii()
            and raw_since.isdigit()
            and len(raw_since) <= _MAX_CURSOR_DIGITS
        ):
            raise AppError(
                400, "Die Event-ID ist ungültig.", reason="invalid_event_cursor"
            )
        since = int(raw_since)
        set_connection_timeout(None)
        try:
            send_headers()
        except ClientDisconnected:
            return
        # The 200 status line is out: an error from here on must end the stream,
        # never become a second HTTP response written into it. The client's
        # event source reconnects with its last event id.
        try:
            since, _ = self.send_batch(
                self.event_buffer.since(since), since, send_event
            )
            send_event("ready", {"latest_event_id": since}, since or None)
            while True:
                if not self._wait_for_activity(client_is_connected):
                    return
                if not session_is_active():
                    return
                pending = self.event_buffer.since(since)
                since, gap = self.send_batch(pending, since, send_event)
                if gap:
                    continue
                if not pending["events"]:
                    send_event(
                        "heartbeat", {"latest_event_id": pending["latest_event_id"]}
                    )
        except ClientDisconnected:
            return
        except Exception as exc:
            expected = isinstance(exc, AppError | DatabaseBusyError)
            _LOGGER.log(
                logging.WARNING if expected else logging.ERROR,
                "State event stream ended after an error",
                extra={
                    "event": "state_events_stream_error",
                    "context": {"error_type": type(exc).__name__},
                },
                exc_info=not expected,
            )
