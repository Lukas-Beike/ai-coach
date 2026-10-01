"""HTTP request adapter composed from explicit application dependencies."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.errors import AppError, public_error_payload
from backend.http_api.requests import (
    read_audio_body as read_request_audio_body,
)
from backend.http_api.requests import (
    read_body as read_request_body,
)
from backend.http_api.requests import (
    read_json as read_request_json,
)
from backend.http_api.static_assets import StaticAssetService
from backend.runtime.socket_deadline import SocketDeadline


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


class RequestHandler(BaseHTTPRequestHandler):
    input_timeout_seconds = 20
    dependencies: HttpRequestHandlerDependencies
    server_version: str
    client_disconnect_errors = (
        BrokenPipeError,
        ConnectionResetError,
        ConnectionAbortedError,
        TimeoutError,
    )
    static_asset_service: StaticAssetService

    @property
    def auth_service(self) -> Any:
        return self.dependencies.session_auth_service()

    def log_message(self, fmt: str, *args: Any) -> None:
        self.dependencies.logger.info(
            fmt % args,
            extra={
                "event": "http_access",
                "context": {
                    "method": self.command,
                    "path": urlparse(self.path).path,
                    "request_id": getattr(self, "request_id", None),
                },
            },
        )

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(20)

    def handle_one_request(self) -> None:
        try:
            with SocketDeadline(
                self.connection, self.input_timeout_seconds
            ) as deadline:
                self._header_deadline = deadline
                super().handle_one_request()
        except TimeoutError:
            self.close_connection = True

    def parse_request(self) -> bool:
        try:
            return super().parse_request()
        finally:
            self._header_deadline.cancel()

    def _read_input(self, size: int) -> bytes:
        with SocketDeadline(self.connection, self.input_timeout_seconds):
            return self.rfile.read(size)

    def log_client_disconnect(self) -> None:
        context = {
            "method": self.command,
            "path": urlparse(self.path).path,
            "request_id": getattr(self, "request_id", None),
        }
        for attribute, key in (
            ("_response_status", "response_status"),
            ("_response_bytes", "response_bytes"),
            ("_response_error_type", "error_type"),
        ):
            value = getattr(self, attribute, None)
            if value is not None:
                context[key] = value
        started = getattr(self, "_response_started_at", None)
        if started is not None:
            context["response_duration_ms"] = round(
                (time.perf_counter() - started) * 1000, 1
            )
        self.dependencies.logger.info(
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
            self.dependencies.route_dispatcher.handle_get(self, path)
        except AppError as exc:
            if exc.status >= 500:
                self.dependencies.logger.exception(
                    exc.message,
                    extra={
                        "event": "http_app_error",
                        "context": {
                            "method": "GET",
                            "path": self.path,
                            "status": exc.status,
                            "request_id": self.request_id,
                        },
                    },
                )
            self.send_json(
                self.dependencies.public_app_error_status(exc),
                public_error_payload(exc, self.dependencies.redact_text),
            )
        except Exception:
            self.dependencies.logger.exception(
                "Unhandled GET error",
                extra={
                    "event": "http_unhandled_error",
                    "context": {
                        "method": "GET",
                        "path": self.path,
                        "request_id": self.request_id,
                    },
                },
            )
            self.send_json(500, {"error": self.dependencies.internal_server_error})

    def do_POST(self) -> None:
        self.request_id = uuid.uuid4().hex[:12]
        try:
            path = urlparse(self.path).path
            if self.dependencies.post_dispatcher.handle_before_auth(self, path):
                return
            session = self.auth_service.require_auth(self)
            self.auth_service.require_csrf(self, session)
            if self.dependencies.post_dispatcher.handle_before_maintenance(
                self, path, session
            ):
                return
            with self.dependencies.maintenance_gate.operation():
                self.dependencies.post_dispatcher.handle_authenticated(
                    self, path, session
                )
        except AppError as exc:
            if exc.status >= 500:
                self.dependencies.logger.exception(
                    exc.message,
                    extra={
                        "event": "http_app_error",
                        "context": {
                            "method": "POST",
                            "path": self.path,
                            "status": exc.status,
                            "request_id": self.request_id,
                        },
                    },
                )
            status = self.dependencies.public_app_error_status(exc)
            headers: dict[str, str | list[str]] | None = (
                {"WWW-Authenticate": "Session"} if status == 401 else None
            )
            self.send_json(
                status,
                public_error_payload(exc, self.dependencies.redact_text),
                headers,
            )
        except Exception:
            self.dependencies.logger.exception(
                "Unhandled POST error",
                extra={
                    "event": "http_unhandled_error",
                    "context": {
                        "method": "POST",
                        "path": self.path,
                        "request_id": self.request_id,
                    },
                },
            )
            self.send_json(500, {"error": self.dependencies.internal_server_error})

    def send_sse_headers(self, *, persistent: bool = True) -> None:
        self.dependencies.response_transport.send_sse_headers(
            self, persistent=persistent
        )

    def send_sse_event(
        self, event: str, payload: Any, event_id: int | None = None
    ) -> None:
        self.dependencies.response_transport.send_sse_event(
            self, event, payload, event_id
        )

    def do_PUT(self) -> None:
        try:
            with self.dependencies.maintenance_gate.operation():
                self._do_PUT()
        except AppError as exc:
            self.send_json(
                self.dependencies.public_app_error_status(exc),
                public_error_payload(exc, self.dependencies.redact_text),
            )

    def _do_PUT(self) -> None:
        self.request_id = uuid.uuid4().hex[:12]
        try:
            path = urlparse(self.path).path
            session = self.auth_service.require_auth(self)
            self.auth_service.require_csrf(self, session)
            self.dependencies.route_dispatcher.handle_put(self, path)
        except AppError as exc:
            if exc.status >= 500:
                self.dependencies.logger.exception(
                    exc.message,
                    extra={
                        "event": "http_app_error",
                        "context": {
                            "method": "PUT",
                            "path": self.path,
                            "status": exc.status,
                            "request_id": self.request_id,
                        },
                    },
                )
            self.send_json(
                self.dependencies.public_app_error_status(exc),
                public_error_payload(exc, self.dependencies.redact_text),
            )
        except Exception:
            self.dependencies.logger.exception(
                "Unhandled PUT error",
                extra={
                    "event": "http_unhandled_error",
                    "context": {
                        "method": "PUT",
                        "path": self.path,
                        "request_id": self.request_id,
                    },
                },
            )
            self.send_json(500, {"error": self.dependencies.internal_server_error})

    def read_body(self, max_bytes: int | None = None) -> bytes:
        if max_bytes is None:
            max_bytes = self.dependencies.max_body_bytes
        return read_request_body(
            self.headers,
            self._read_input,
            max_bytes,
            error=AppError,
            too_large_status_threshold=self.dependencies.max_body_bytes,
        )

    def read_audio_body(self) -> bytes:
        return read_request_audio_body(
            self.headers,
            self._read_input,
            allowed_types=self.dependencies.voice_audio_types,
            normalize_type=self.dependencies.normalize_audio_type,
            max_bytes=self.dependencies.max_audio_body_bytes,
            error=AppError,
        )

    def read_json(self, max_bytes: int | None = None) -> dict[str, Any]:
        if max_bytes is None:
            max_bytes = self.dependencies.max_body_bytes
        return read_request_json(
            self.headers,
            self._read_input,
            max_bytes,
            error=AppError,
            too_large_status_threshold=self.dependencies.max_body_bytes,
        )

    def send_json(
        self,
        status: int,
        payload: Any,
        headers: dict[str, str | list[str]] | None = None,
    ) -> None:
        self.dependencies.response_transport.send_json(self, status, payload, headers)

    def send_file_stream(
        self,
        path: Path,
        content_type: str,
        filename: str,
        *,
        deadline: float | None = None,
        cleanup: bool = False,
    ) -> None:
        self.dependencies.response_transport.send_file_stream(
            self,
            path,
            content_type,
            filename,
            deadline=deadline,
            cleanup=cleanup,
        )

    def send_bytes(
        self,
        status: int,
        data: bytes,
        content_type: str,
        headers: dict[str, str | list[str]] | None = None,
    ) -> None:
        self.dependencies.response_transport.send_bytes(
            self, status, data, content_type, headers
        )

    def send_static(self, path: str) -> None:
        self.dependencies.response_transport.send_static(self, path)


def create_request_handler(
    dependencies: HttpRequestHandlerDependencies,
) -> type[BaseHTTPRequestHandler]:
    return type(
        "ComposedRequestHandler",
        (RequestHandler,),
        {
            "dependencies": dependencies,
            "server_version": f"IntervalsCoach/{dependencies.app_version}",
            "static_asset_service": dependencies.static_asset_service,
        },
    )
