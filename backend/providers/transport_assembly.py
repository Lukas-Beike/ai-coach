"""Lazy composition for the shared JSON and Intervals transports."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.config import Config
from backend.providers import http as provider_http
from backend.providers import intervals_client as intervals_client_module


class ProviderTransportAssembly:
    """Build provider transports from explicit runtime dependencies."""

    def __init__(
        self,
        *,
        app_version: str,
        max_response_bytes: int,
        logger: Any,
        diagnostic_capture: Any,
        provider_state: Callable[[], Any],
        redact_text: Callable[[str], str],
        safe_response_headers: Callable[[Mapping[str, Any]], Mapping[str, str]],
        now: Callable[[], str],
        operation_context: Callable[[], Mapping[str, Any] | None],
        opener: Callable[[], Any],
        config: Callable[[], Config],
        athlete_now: Callable[[], Any],
    ) -> None:
        self._app_version = app_version
        self._max_response_bytes = max_response_bytes
        self._logger = logger
        self._diagnostic_capture = diagnostic_capture
        self._provider_state = provider_state
        self._redact_text = redact_text
        self._safe_response_headers = safe_response_headers
        self._now = now
        self._operation_context = operation_context
        self._opener = opener
        self._config = config
        self._athlete_now = athlete_now

    def json_http_client(self) -> provider_http.JsonHttpClient:
        """Return the cache-owned JSON transport for the current provider state."""
        return provider_http.JSON_HTTP_CLIENT_CACHE.get(
            self._app_version,
            self._max_response_bytes,
            self._logger,
            self._diagnostic_capture,
            self._provider_state(),
            self._redact_text,
            self._safe_response_headers,
            self._now,
            self._operation_context,
            opener=self._opener(),
        )

    def intervals_client(
        self, config: Config | None = None
    ) -> intervals_client_module.IntervalsClient:
        """Create an Intervals adapter using the active shared transport."""
        active_config = config if config is not None else self._config()
        return intervals_client_module.IntervalsClient(
            active_config,
            request=self.json_http_client().request,
            now=self._athlete_now,
        )
