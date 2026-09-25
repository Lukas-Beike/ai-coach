"""Authenticated diagnostic capture POST routes."""

from __future__ import annotations

from typing import Any

from backend.observability import DiagnosticCapture


class DiagnosticsCapturePostRoutes:
    """Dispatch capture state changes to their owning diagnostic service."""

    def __init__(self, diagnostic_capture: DiagnosticCapture) -> None:
        self._diagnostic_capture = diagnostic_capture

    def handle(self, handler: Any, path: str) -> bool:
        if path != "/api/diagnostics/capture":
            return False

        payload = handler.read_json()
        handler.send_json(
            200, self._diagnostic_capture.set_enabled(payload.get("enabled"))
        )
        return True
