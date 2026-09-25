"""HTTP request adapter composed from explicit application dependencies."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from backend.errors import AppError
from backend.http_api.requests import (
    read_audio_body as read_request_audio_body,
    read_body as read_request_body,
    read_json as read_request_json,
)
from backend.http_api.static_assets import StaticAssetService


@dataclass(frozen=True)
class HttpRequestHandlerDependencies:
    app_version: str
    logger: Any
    session_auth_service: Callable[[], Any]
    route_dispatcher: Any
    post_dispatcher: Any
    response_transport: Any
    maintenance_gate: Any
    redact_text: Callable[[str], str]
    public_app_error_status: Callable[[AppError], int]
    internal_server_error: str
    max_body_bytes: int
    max_audio_body_bytes: int
    voice_audio_types: tuple[str, ...]
    normalize_audio_type: Callable[[str], str]
    static_asset_service: StaticAssetService


def create_request_handler(dependencies: HttpRequestHandlerDependencies) -> type[BaseHTTPRequestHandler]:
    class RequestHandler(BaseHTTPRequestHandler):
        server_version = f"IntervalsCoach/{dependencies.app_version}"
        client_disconnect_errors = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)
        static_asset_service = dependencies.static_asset_service

        @property
        def auth_service(self) -> Any:
            return dependencies.session_auth_service()

        def log_message(self, fmt: str, *args: Any) -> None:
            dependencies.logger.info(
                fmt % args,
                extra={
                    "event": "http_access",
                    "context": {"method": self.command, "path": urlparse(self.path).path, "request_id": getattr(self, "request_id", None)},
                },
            )

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(20)

        def log_client_disconnect(self) -> None:
            context = {
                "method": self.command,
                "path": urlparse(self.path).path,
                "request_id": getattr(self, "request_id", None),
            }
            for attribute, key in (("_response_status", "response_status"), ("_response_bytes", "response_bytes"), ("_response_error_type", "error_type")):
                value = getattr(self, attribute, None)
                if value is not None:
                    context[key] = value
            started = getattr(self, "_response_started_at", None)
            if started is not None:
                context["response_duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
            dependencies.logger.info(
                "HTTP client disconnected before response completed",
                extra={
                    "event": "http_client_disconnected",
                    "context": context,
                },
            )

        def do_GET(self) -> None:
            self.request_id = uuid.uuid4().hex[:12]
            try:
                path = urlparse(self.path).path
                dependencies.route_dispatcher.handle_get(self, path)
            except AppError as exc:
                if exc.status >= 500:
                    dependencies.logger.exception(
                        exc.message,
                        extra={"event": "http_app_error", "context": {"method": "GET", "path": self.path, "status": exc.status, "request_id": self.request_id}},
                        exc_info=True,
                    )
                self.send_json(dependencies.public_app_error_status(exc), {"error": dependencies.redact_text(exc.message)[:1000]})
            except Exception:
                dependencies.logger.exception(
                    "Unhandled GET error",
                    extra={"event": "http_unhandled_error", "context": {"method": "GET", "path": self.path, "request_id": self.request_id}},
                    exc_info=True,
                )
                self.send_json(500, {"error": dependencies.internal_server_error})

        def do_POST(self) -> None:
            self.request_id = uuid.uuid4().hex[:12]
            try:
                path = urlparse(self.path).path
                if dependencies.post_dispatcher.handle_before_auth(self, path):
                    return
                session = self.auth_service.require_auth(self)
                self.auth_service.require_csrf(self, session)
                if dependencies.post_dispatcher.handle_before_maintenance(self, path, session):
                    return
                with dependencies.maintenance_gate.operation():
                    dependencies.post_dispatcher.handle_authenticated(self, path, session)
            except AppError as exc:
                if exc.status >= 500:
                    dependencies.logger.exception(
                        exc.message,
                        extra={"event": "http_app_error", "context": {"method": "POST", "path": self.path, "status": exc.status, "request_id": self.request_id}},
                        exc_info=True,
                    )
                status = dependencies.public_app_error_status(exc)
                headers = {"WWW-Authenticate": "Session"} if status == 401 else None
                self.send_json(status, {"error": dependencies.redact_text(exc.message)[:1000]}, headers)
            except Exception:
                dependencies.logger.exception(
                    "Unhandled POST error",
                    extra={"event": "http_unhandled_error", "context": {"method": "POST", "path": self.path, "request_id": self.request_id}},
                    exc_info=True,
                )
                self.send_json(500, {"error": dependencies.internal_server_error})

        def send_sse_headers(self, *, persistent: bool = True) -> None:
            dependencies.response_transport.send_sse_headers(self, persistent=persistent)

        def send_sse_event(self, event: str, payload: Any, event_id: int | None = None) -> None:
            dependencies.response_transport.send_sse_event(self, event, payload, event_id)

        def do_PUT(self) -> None:
            try:
                with dependencies.maintenance_gate.operation():
                    self._do_PUT()
            except AppError as exc:
                self.send_json(dependencies.public_app_error_status(exc), {"error": dependencies.redact_text(exc.message)[:1000]})

        def _do_PUT(self) -> None:
            self.request_id = uuid.uuid4().hex[:12]
            try:
                path = urlparse(self.path).path
                session = self.auth_service.require_auth(self)
                self.auth_service.require_csrf(self, session)
                dependencies.route_dispatcher.handle_put(self, path)
            except AppError as exc:
                if exc.status >= 500:
                    dependencies.logger.exception(
                        exc.message,
                        extra={"event": "http_app_error", "context": {"method": "PUT", "path": self.path, "status": exc.status, "request_id": self.request_id}},
                        exc_info=True,
                    )
                self.send_json(dependencies.public_app_error_status(exc), {"error": dependencies.redact_text(exc.message)[:1000]})
            except Exception:
                dependencies.logger.exception(
                    "Unhandled PUT error",
                    extra={"event": "http_unhandled_error", "context": {"method": "PUT", "path": self.path, "request_id": self.request_id}},
                    exc_info=True,
                )
                self.send_json(500, {"error": dependencies.internal_server_error})

        def read_body(self, max_bytes: int = dependencies.max_body_bytes) -> bytes:
            return read_request_body(
                self.headers,
                self.rfile.read,
                max_bytes,
                error=AppError,
                too_large_status_threshold=dependencies.max_body_bytes,
            )

        def read_audio_body(self) -> bytes:
            return read_request_audio_body(
                self.headers,
                self.rfile.read,
                allowed_types=dependencies.voice_audio_types,
                normalize_type=dependencies.normalize_audio_type,
                max_bytes=dependencies.max_audio_body_bytes,
                error=AppError,
            )

        def read_json(self, max_bytes: int = dependencies.max_body_bytes) -> dict[str, Any]:
            return read_request_json(
                self.headers,
                self.rfile.read,
                max_bytes,
                error=AppError,
                too_large_status_threshold=dependencies.max_body_bytes,
            )

        def send_json(self, status: int, payload: Any, headers: dict[str, str | list[str]] | None = None) -> None:
            dependencies.response_transport.send_json(self, status, payload, headers)

        def send_file_stream(
            self,
            path: Path,
            content_type: str,
            filename: str,
            *,
            deadline: float | None = None,
            cleanup: bool = False,
        ) -> None:
            dependencies.response_transport.send_file_stream(
                self,
                path,
                content_type,
                filename,
                deadline=deadline,
                cleanup=cleanup,
            )

        def send_bytes(self, status: int, data: bytes, content_type: str, headers: dict[str, str | list[str]] | None = None) -> None:
            dependencies.response_transport.send_bytes(self, status, data, content_type, headers)

        def send_static(self, path: str) -> None:
            dependencies.response_transport.send_static(self, path)
    return RequestHandler
