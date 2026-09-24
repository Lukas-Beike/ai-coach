"""Socket writes for API, SSE, file, and static responses."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Any

from backend.errors import ClientDisconnected
from backend.http_api.responses import (
    header_items,
    json_bytes,
    response_headers,
)

LOGGER = logging.getLogger("intervals_coach")
STREAM_CHUNK_BYTES = 64 * 1024


class HttpResponseTransport:
    """Write already-authorized response data through a request handler socket."""

    def send_sse_headers(self, handler: Any, *, persistent: bool = True) -> None:
        try:
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Connection", "keep-alive" if persistent else "close")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.send_header("X-Frame-Options", "DENY")
            handler.send_header("X-Accel-Buffering", "no")
            handler.end_headers()
            handler.wfile.flush()
        except handler.client_disconnect_errors as exc:
            handler.log_client_disconnect()
            raise ClientDisconnected() from exc

    def send_sse_event(
        self, handler: Any, event: str, payload: Any, event_id: int | None = None
    ) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            prefix = f"id: {event_id}\n" if event_id is not None else ""
            handler.wfile.write(
                f"{prefix}event: {event}\ndata: {data}\n\n".encode("utf-8")
            )
            handler.wfile.flush()
        except handler.client_disconnect_errors as exc:
            handler.log_client_disconnect()
            raise ClientDisconnected() from exc

    def send_json(
        self,
        handler: Any,
        status: int,
        payload: Any,
        headers: dict[str, str | list[str]] | None = None,
    ) -> None:
        data = json_bytes(payload)
        handler.send_response(status)
        for key, value in response_headers("application/json; charset=utf-8", len(data)):
            handler.send_header(key, value)
        for key, value in header_items(headers):
            handler.send_header(key, value)
        handler._response_status = status
        handler._response_bytes = len(data)
        handler._response_started_at = time.perf_counter()
        try:
            handler.end_headers()
            handler.wfile.write(data)
        except handler.client_disconnect_errors as exc:
            handler._response_error_type = type(exc).__name__
            handler.log_client_disconnect()
        finally:
            for attribute in (
                "_response_status",
                "_response_bytes",
                "_response_started_at",
                "_response_error_type",
            ):
                handler.__dict__.pop(attribute, None)

    def send_file_stream(
        self,
        handler: Any,
        path: Path,
        content_type: str,
        filename: str,
        *,
        deadline: float | None = None,
        cleanup: bool = False,
    ) -> None:
        try:
            size = path.stat().st_size
            handler.send_response(200)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(size))
            handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.send_header("X-Frame-Options", "DENY")
            handler.end_headers()
            with path.open("rb") as source:
                while True:
                    if deadline is not None and time.monotonic() > deadline:
                        LOGGER.warning(
                            "File stream exceeded time limit",
                            extra={"event": "file_stream_timeout"},
                        )
                        break
                    chunk = source.read(STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    handler.wfile.write(chunk)
        except handler.client_disconnect_errors:
            handler.log_client_disconnect()
        except OSError:
            LOGGER.warning(
                "File stream failed",
                extra={"event": "file_stream_failed"},
                exc_info=True,
            )
        finally:
            if cleanup:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning(
                        "Temporary export cleanup failed",
                        extra={"event": "export_cleanup_failed"},
                    )

    def send_bytes(
        self,
        handler: Any,
        status: int,
        data: bytes,
        content_type: str,
        headers: dict[str, str | list[str]] | None = None,
    ) -> None:
        handler.send_response(status)
        for key, value in response_headers(content_type, len(data)):
            handler.send_header(key, value)
        for key, value in header_items(headers):
            handler.send_header(key, value)
        try:
            handler.end_headers()
            handler.wfile.write(data)
        except handler.client_disconnect_errors:
            handler.log_client_disconnect()

    def send_static(self, handler: Any, path: str) -> None:
        response = handler.static_asset_service.render(
            path,
            getattr(handler, "path", ""),
            getattr(handler, "headers", {}).get("If-None-Match"),
        )
        handler.send_response(response.status)
        for name, value in response.headers:
            handler.send_header(name, value)
        try:
            handler.end_headers()
            if response.body:
                handler.wfile.write(response.body)
        except handler.client_disconnect_errors:
            handler.log_client_disconnect()
