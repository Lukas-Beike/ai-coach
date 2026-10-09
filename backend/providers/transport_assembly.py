"""Lazy composition for the shared JSON and Intervals transports."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.config import Config
from backend.providers import http as provider_http
from backend.providers import intervals_client as intervals_client_module
from backend.runtime.ports import ProviderOperation


@dataclass(frozen=True)
class ProviderHttpSettings:
    app_version: str
    max_response_bytes: int
    logger: Any
    diagnostic_capture: Any
    redact_text: Callable[[str], str]
    safe_response_headers: Callable[[Mapping[str, Any]], Mapping[str, str]]
    opener: Callable[[], Any]


@dataclass(frozen=True)
class ProviderOperationContext:
    provider_state: Callable[[], Any]
    now: Callable[[], str]
    operation_context: Callable[[], Mapping[str, Any] | None]


@dataclass(frozen=True)
class IntervalsTransportSettings:
    config: Callable[[], Config]
    athlete_now: Callable[[], Any]
    operation: ProviderOperation


class ProviderTransportAssembly:
    """Build provider transports from explicit runtime dependencies."""

    @dataclass(frozen=True)
    class Inputs:
        http: ProviderHttpSettings
        operation: ProviderOperationContext
        intervals: IntervalsTransportSettings

    def __init__(
        self,
        *,
        dependencies: ProviderTransportAssembly.Inputs,
    ) -> None:
        http = dependencies.http
        operation = dependencies.operation
        intervals = dependencies.intervals
        self._app_version = http.app_version
        self._max_response_bytes = http.max_response_bytes
        self._logger = http.logger
        self._diagnostic_capture = http.diagnostic_capture
        self._provider_state = operation.provider_state
        self._redact_text = http.redact_text
        self._safe_response_headers = http.safe_response_headers
        self._now = operation.now
        self._operation_context = operation.operation_context
        self._opener = http.opener
        self._config = intervals.config
        self._athlete_now = intervals.athlete_now
        self._intervals_operation = intervals.operation

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
            operation=self._intervals_operation,
        )
