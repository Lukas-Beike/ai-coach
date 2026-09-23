"""In-memory ownership for attached Coach streams and background cancel events."""

from __future__ import annotations

import queue
import threading
import uuid
from typing import Any

from backend.errors import AppError


class ChatStreamRegistry:
    """Own the process-local queues and cancellation state for Coach turns."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._streams: dict[str, dict[str, Any]] = {}
        self._background_events: dict[str, threading.Event] = {}

    def register(self, session: str) -> tuple[str, threading.Event]:
        operation_id = uuid.uuid4().hex
        cancel_event = threading.Event()
        with self._lock:
            if session in self._streams:
                raise AppError(409, "Für diese Sitzung läuft bereits eine Coach-Anfrage.", reason="chat_already_running")
            self._streams[session] = {
                "operation_id": operation_id,
                "cancel_event": cancel_event,
                "events": queue.Queue(),
            }
        return operation_id, cancel_event

    def publish(self, operation_id: str, event: str, data: Any) -> bool:
        """Forward a worker event to the currently attached finite SSE response."""
        with self._lock:
            stream = next(
                (candidate for candidate in self._streams.values()
                 if candidate["operation_id"] == operation_id),
                None,
            )
            events = stream["events"] if stream else None
        if not isinstance(events, queue.Queue):
            return False
        events.put((event, data))
        return True

    def events(self, session: str, operation_id: str) -> queue.Queue[Any] | None:
        with self._lock:
            stream = self._streams.get(session)
            if not stream or stream["operation_id"] != operation_id:
                return None
            events = stream["events"]
        return events if isinstance(events, queue.Queue) else None

    def attached_status(self, session: str) -> dict[str, str] | None:
        with self._lock:
            stream = self._streams.get(session)
            if not stream:
                return None
            return {"status": "running", "operation_id": stream["operation_id"]}

    def cancel_attached(self, session: str, operation_id: Any) -> tuple[dict[str, Any] | None, Any]:
        with self._lock:
            stream = self._streams.get(session)
            if not stream:
                return None, None
            if operation_id and str(operation_id) != stream["operation_id"]:
                raise AppError(409, "Die angegebene Coach-Anfrage ist nicht mehr aktiv.")
            cancel_event = stream["cancel_event"]
            cancel_event.set()
            response = getattr(cancel_event, "_provider_response", None) or getattr(
                cancel_event, "_openai_response", None
            )
            return {"status": "cancelling", "operation_id": stream["operation_id"]}, response

    def unregister(self, session: str, operation_id: str) -> None:
        with self._lock:
            stream = self._streams.get(session)
            if stream and stream["operation_id"] == operation_id:
                self._streams.pop(session, None)

    def set_background_event(self, operation_id: str, event: threading.Event) -> None:
        with self._lock:
            self._background_events[operation_id] = event

    def get_background_event(self, operation_id: str) -> threading.Event | None:
        with self._lock:
            return self._background_events.get(operation_id)

    def get_or_create_background_event(self, operation_id: str) -> threading.Event:
        with self._lock:
            return self._background_events.setdefault(operation_id, threading.Event())

    def remove_background_event(self, operation_id: str) -> None:
        with self._lock:
            self._background_events.pop(operation_id, None)

    def cancel_background_event(self, operation_id: str) -> tuple[threading.Event, Any]:
        with self._lock:
            event = self._background_events.setdefault(operation_id, threading.Event())
            event.set()
            response = getattr(event, "_provider_response", None) or getattr(
                event, "_openai_response", None
            )
            return event, response

    def cancel_existing_background_event(self, operation_id: str) -> tuple[threading.Event | None, Any]:
        """Cancel a registered event without recreating state lost on restart."""
        with self._lock:
            event = self._background_events.get(operation_id)
            if event is None:
                return None, None
            event.set()
            response = getattr(event, "_provider_response", None) or getattr(
                event, "_openai_response", None
            )
            return event, response

    def clear_state(self) -> None:
        """Clear ephemeral process state for isolated tests and process restart simulation."""
        with self._lock:
            self._streams.clear()
            self._background_events.clear()


CHAT_STREAM_REGISTRY = ChatStreamRegistry()
