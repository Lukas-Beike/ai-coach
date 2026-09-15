"""Bounded state-event publication and cursor reads."""

import threading
from collections import deque
from typing import Any

from backend.errors import AppError


class StateEventBuffer:
    """Own a bounded, thread-safe stream of non-athlete-facing state events."""

    _ALLOWED_EVENTS = frozenset({"provider", "job", "planning", "coach", "sync"})

    def __init__(self, maxlen: int = 500):
        self._condition = threading.Condition()
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._next_id = 0

    def publish(self, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Publish one event and return its shallow top-level copy."""
        if not isinstance(event, str) or event not in self._ALLOWED_EVENTS:
            raise ValueError("invalid state event")
        safe_payload = payload if isinstance(payload, dict) else {}
        with self._condition:
            self._next_id += 1
            item = {
                "event_id": self._next_id,
                "event": event,
                "data": dict(safe_payload),
            }
            self._events.append(item)
            self._condition.notify_all()
            return dict(item)

    def since(self, since: int = 0) -> dict[str, Any]:
        """Return retained events and explicitly report a retention gap."""
        try:
            cursor = max(0, int(since))
        except (TypeError, ValueError) as exc:
            raise AppError(400, "Die Event-ID ist ungültig.", reason="invalid_event_cursor") from exc
        with self._condition:
            latest = self._next_id
            retained = list(self._events)
        if not retained:
            return {"events": [], "latest_event_id": latest, "gap": False}
        oldest = int(retained[0]["event_id"])
        gap = cursor < oldest - 1
        events = [] if gap else [item for item in retained if int(item["event_id"]) > cursor]
        return {"events": events, "latest_event_id": latest, "gap": gap}

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for a publication notification on this buffer's condition."""
        with self._condition:
            return self._condition.wait(timeout)

    def clear(self) -> None:
        """Atomically reset retained events and the event-id sequence."""
        with self._condition:
            self._events.clear()
            self._next_id = 0
