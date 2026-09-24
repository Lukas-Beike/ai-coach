"""Unauthenticated and bootstrap GET routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.auth import SessionAuthService
from backend.http_api.bootstrap_state import PublicBootstrapService
from backend.http_api.readiness import ReadinessService
from backend.runtime.maintenance import MaintenanceGate


class PublicGetRoutes:
    """Dispatch public GET routes through their existing state owners."""

    def __init__(
        self,
        maintenance_gate: MaintenanceGate,
        readiness_service: Callable[[], ReadinessService],
        auth_service: Callable[[], SessionAuthService],
        public_bootstrap_service: Callable[[], PublicBootstrapService],
    ) -> None:
        self._maintenance_gate = maintenance_gate
        self._readiness_service = readiness_service
        self._auth_service = auth_service
        self._public_bootstrap_service = public_bootstrap_service

    def handle(self, handler: Any, path: str) -> bool:
        if path == "/api/health":
            handler.send_json(
                200,
                {"status": "ok", "maintenance": self._maintenance_gate.state()},
            )
        elif path == "/api/readiness":
            readiness = self._readiness_service().state()
            handler.send_json(200 if readiness["ready"] else 503, readiness)
        elif path == "/api/auth/status":
            session = self._auth_service().authenticated_session(handler)
            result = {
                "authenticated": bool(session),
                "maintenance": self._maintenance_gate.state(),
            }
            handler.send_json(200, result)
        elif path == "/api/bootstrap":
            self._auth_service().require_auth(handler)
            handler.send_json(200, self._public_bootstrap_service().read())
        else:
            return False
        return True
