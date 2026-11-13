"""Build the shared JSON and Intervals.icu transports from explicit dependencies."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

from backend import observability
from backend.config import Config
from backend.providers import http as provider_http
from backend.providers import intervals_client as intervals_client_module
from backend.providers.openai_error_classifier import OpenAIErrorClassifier
from backend.runtime import clock as runtime_clock
from backend.runtime.ports import ProviderOperation


@dataclass(frozen=True)
class ProviderTransportServices:
    json_http_client: Callable[[], provider_http.JsonHttpClient]
    # Takes an optional Config; the active configuration when omitted.
    intervals_client: Callable[..., intervals_client_module.IntervalsClient]


def build_provider_transport(
    *,
    app_version: str,
    logger: Any,
    diagnostic_capture: Any,
    redact_text: Callable[[str], str],
    provider_state: Callable[[], Any],
    operation_context: Callable[[], Mapping[str, Any] | None],
    current_config: Callable[[], Config],
    athlete_now: Callable[[], Any],
    intervals_operation: ProviderOperation,
) -> ProviderTransportServices:
    """The cache-owned JSON transport and an Intervals.icu adapter over it.

    The arguments are the live owners; each is read when a client is built.
    """
    max_response_bytes = provider_http.MAX_EXTERNAL_RESPONSE_BYTES
    safe_response_headers = partial(
        observability.safe_response_headers, redact=redact_text
    )
    error_details = OpenAIErrorClassifier(provider_state, runtime_clock.utc_now)

    def json_http_client() -> provider_http.JsonHttpClient:
        """Return the cache-owned JSON transport for the current provider state."""
        return provider_http.JSON_HTTP_CLIENT_CACHE.get(
            app_version,
            max_response_bytes,
            logger,
            diagnostic_capture,
            redact_text,
            safe_response_headers,
            operation_context,
            provider_error_details=error_details,
            opener=provider_http.urlopen,
        )

    def intervals_client(
        config: Config | None = None,
    ) -> intervals_client_module.IntervalsClient:
        """Create an Intervals adapter using the active shared transport."""
        return intervals_client_module.IntervalsClient(
            config if config is not None else current_config(),
            request=json_http_client().request,
            now=athlete_now,
            operation=intervals_operation,
        )

    return ProviderTransportServices(json_http_client, intervals_client)
