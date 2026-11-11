"""Unauthenticated and bootstrap GET routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.auth import SessionAuthService
from backend.http_api.bootstrap_state import PublicBootstrapService
from backend.http_api.readiness import ReadinessService
from backend.http_api.route_table import Access, Route, RouteRequest
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

    def routes(self) -> list[Route]:
        return [
            Route("GET", "/api/health", Access.PUBLIC, self._health),
            Route("GET", "/api/readiness", Access.PUBLIC, self._readiness),
            Route("GET", "/api/auth/status", Access.PUBLIC, self._auth_status),
            Route("GET", "/api/bootstrap", Access.SESSION, self._bootstrap),
        ]

    def _health(self, handler: Any, _request: RouteRequest) -> None:
        """Liveness and maintenance state."""
        handler.send_json(
            200, {"status": "ok", "maintenance": self._maintenance_gate.state()}
        )

    def _readiness(self, handler: Any, _request: RouteRequest) -> None:
        """Readiness status; 503 while not ready."""
        readiness = self._readiness_service().state()
        handler.send_json(200 if readiness["ready"] else 503, readiness)

    def _auth_status(self, handler: Any, _request: RouteRequest) -> None:
        """Current login status."""
        session = self._auth_service().authenticated_session(handler)
        handler.send_json(
            200,
            {
                "authenticated": bool(session),
                "maintenance": self._maintenance_gate.state(),
            },
        )

    def _bootstrap(self, handler: Any, _request: RouteRequest) -> None:
        """Initial authenticated client state."""
        handler.send_json(200, self._public_bootstrap_service().read())
