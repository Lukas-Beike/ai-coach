"""Transport orchestration for the authenticated public state-event stream."""

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.errors import AppError, ClientDisconnected


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

    def handle(
        self,
        request_target: str,
        *,
        send_headers: Callable[[], None],
        send_event: Callable[..., None],
        set_connection_timeout: Callable[[float | None], None],
    ) -> None:
        query = parse_qs(urlparse(request_target).query)
        raw_since = query.get("since", ["0"])[0]
        if not str(raw_since).isdigit():
            raise AppError(400, "Die Event-ID ist ungültig.", reason="invalid_event_cursor")
        since = int(raw_since)
        set_connection_timeout(None)
        try:
            send_headers()
            since, _ = self.send_batch(self.event_buffer.since(since), since, send_event)
            send_event("ready", {"latest_event_id": since}, since or None)
            while True:
                self.event_buffer.wait(timeout=15)
                pending = self.event_buffer.since(since)
                since, gap = self.send_batch(pending, since, send_event)
                if gap:
                    continue
                if not pending["events"]:
                    send_event("heartbeat", {"latest_event_id": pending["latest_event_id"]})
        except ClientDisconnected:
            return
