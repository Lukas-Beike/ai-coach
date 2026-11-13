"""OpenAI Responses provider internals."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from backend.errors import COACH_ABORTED_ERROR, OPENAI_API_KEY_ERROR, AppError
from backend.providers import http as provider_http
from backend.providers.http import endpoint
from backend.providers.model_seam import ModelRequest, ModelTurn
from backend.providers.openai_responses_adapter import model_turn, request_payload

if TYPE_CHECKING:
    from backend.providers.state import ProviderStateService

__all__ = [
    "OPENAI_RATE_LIMIT_HEADERS",
    "OPENAI_UNEXPECTED_RESPONSE_MESSAGE",
    "OpenAIResponsesClient",
    "endpoint",
    "request_with_conversation_retry",
    "responses_payload",
]


def _payload_shape(value: Any) -> dict[str, Any]:
    """Describe payload structure without retaining athlete content."""
    if isinstance(value, dict):
        return {"kind": "object", "keys": sorted(str(key) for key in value)[:200]}
    if isinstance(value, list):
        return {"kind": "array", "length": len(value)}
    return {"kind": type(value).__name__}


if TYPE_CHECKING:
    from backend.providers.state import ProviderStateService

OPENAI_UNEXPECTED_RESPONSE_MESSAGE = (
    "OpenAI hat eine unerwartete Antwort zurückgegeben."
)

OPENAI_RATE_LIMIT_HEADERS = {
    "retry-after": "retry_after",
    "x-ratelimit-limit-requests": "limit_requests",
    "x-ratelimit-remaining-requests": "remaining_requests",
    "x-ratelimit-reset-requests": "reset_requests",
    "x-ratelimit-limit-tokens": "limit_tokens",
    "x-ratelimit-remaining-tokens": "remaining_tokens",
    "x-ratelimit-reset-tokens": "reset_tokens",
}

_SAFE_LOG_REASONS = {
    "chat_cancelled": "chat_cancelled",
    "client_disconnected": "client_disconnected",
    "conversation_locked": "conversation_locked",
    "conversation_state_invalid": "conversation_state_invalid",
    "credit_balance_exhausted": "credit_balance_exhausted",
    "invalid_response": "invalid_response",
    "provider_timeout": "provider_timeout",
    "request_failed": "request_failed",
    "response_error": "response_error",
    "response_failed": "response_failed",
    "response_too_large": "response_too_large",
    "organization_spend_limit_exceeded": "usage_limit_exceeded",
    "project_spend_limit_exceeded": "usage_limit_exceeded",
    "organization_usage_limit_exceeded": "usage_limit_exceeded",
    "insufficient_quota": "insufficient_quota",
    "rate_limit_exceeded": "rate_limit_exceeded",
    "authentication_or_permission": "authentication_or_permission",
    "not_found": "not_found",
    "provider_unavailable": "provider_unavailable",
    "usage_limit_exceeded": "usage_limit_exceeded",
}


def _conversation_retry_cancelled(cancel_event: Any) -> bool:
    return cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)()


def _raise_if_conversation_retry_cancelled(
    cancel_event: Any, cause: BaseException
) -> None:
    if _conversation_retry_cancelled(cancel_event):
        raise provider_http.ProviderRequestCancelled from cause


def _wait_for_conversation_retry(
    delay: int,
    cancel_event: Any,
    wait: Callable[[float], Any],
    cause: BaseException,
) -> None:
    if cancel_event is None:
        wait(delay)
    elif cancel_event.wait(delay) or _conversation_retry_cancelled(cancel_event):
        raise provider_http.ProviderRequestCancelled from cause


def request_with_conversation_retry(
    request: Callable[[], Any],
    *,
    cancel_event: Any = None,
    on_retry: Callable[[int, int], None] | None = None,
    wait: Callable[[float], Any] = time.sleep,
    max_attempts: int = 3,
) -> Any:
    """Run a request, retrying only while its conversation is locked."""
    if (
        not isinstance(max_attempts, int)
        or isinstance(max_attempts, bool)
        or max_attempts <= 0
    ):
        raise ValueError("max_attempts must be positive")

    for attempt in range(max_attempts):
        try:
            return request()
        except Exception as exc:
            if (
                getattr(exc, "reason", None) != "conversation_locked"
                or attempt + 1 >= max_attempts
            ):
                raise
            delay = 2**attempt
            _raise_if_conversation_retry_cancelled(cancel_event, exc)
            if on_retry is not None:
                on_retry(attempt + 1, delay)
            _wait_for_conversation_retry(delay, cancel_event, wait, exc)

    raise AssertionError("unreachable")


@dataclass(frozen=True)
class ResponsesClock:
    wait: Callable[[float], Any] = time.sleep


class OpenAIResponsesClient:
    """Orchestrate OpenAI Responses calls over the injected provider owners."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        default_base_url: str,
        responses_path: str,
        response_timeout_seconds: int,
        thinking_level: Callable[[], str],
        http_client: provider_http.JsonHttpClient,
        provider_state: ProviderStateService,
        logger: Any,
        clock: ResponsesClock | None = None,
        service_tier: Callable[[str], str | None] = lambda model: None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.default_base_url = default_base_url
        self.responses_path = responses_path
        self.response_timeout_seconds = response_timeout_seconds
        self.thinking_level = thinking_level
        self.service_tier = service_tier
        self.http_client = http_client
        self.provider_state = provider_state
        self.logger = logger
        clock = clock or ResponsesClock()
        self.wait = clock.wait

    def _require_api_key(self) -> None:
        if not self.api_key:
            raise AppError(503, OPENAI_API_KEY_ERROR, reason="not_configured")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _send(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        cancel_event: Any = None,
        prepared: bool = False,
    ) -> dict[str, Any]:
        self._require_api_key()
        if prepared:
            request_payload = dict(payload)
        elif path == self.responses_path:
            request_payload = responses_payload(
                payload,
                thinking_level=self.thinking_level(),
                service_tier=self.service_tier(str(payload.get("model", ""))),
            )
        else:
            request_payload = dict(payload)
        request_kwargs = {
            "headers": self._headers(),
            "timeout": self.response_timeout_seconds,
            "service": "openai",
        }
        if cancel_event is not None:
            request_kwargs["cancel_event"] = cancel_event
        result = self.http_client.request(
            "POST",
            endpoint(self.base_url, path, default_base_url=self.default_base_url),
            request_payload,
            **request_kwargs,  # type: ignore[arg-type]
        )
        operation = path.strip("/") or "request"
        model = str(payload.get("model") or "")
        result = self._validated(path, result, operation, model)
        self.provider_state.record_usage("openai", result, operation, model)
        return result

    def _validated(
        self, path: str, result: Any, operation: str, model: str = ""
    ) -> dict[str, Any]:
        """Validate a decoded response, billing the usage of a failed one first."""
        try:
            validated = self.provider_state.validate_openai_response(path, result)
        except AppError as exc:
            if exc.reason != "invalid_response":
                self._record_terminal_usage(result, operation, model)
            raise
        if not isinstance(validated, dict):
            raise AppError(502, OPENAI_UNEXPECTED_RESPONSE_MESSAGE)
        return validated

    def _record_terminal_usage(
        self, result: Any, operation: str, model: str = ""
    ) -> None:
        """Record usage carried by a failed, cancelled, or incomplete response body."""
        if isinstance(result, dict):
            self.provider_state.record_usage("openai", result, operation, model)

    def request(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Send one OpenAI JSON request and observe its response."""
        return self._send(path, payload)

    def responses(
        self, payload: Mapping[str, Any], *, cancel_event: Any = None
    ) -> dict[str, Any]:
        """Send a Responses request, retrying only transient conversation locks."""
        request_payload = responses_payload(
            payload,
            thinking_level=self.thinking_level(),
            service_tier=self.service_tier(str(payload.get("model", ""))),
        )
        return self._responses_prepared(request_payload, cancel_event=cancel_event)

    def complete(self, request: ModelRequest) -> ModelTurn:
        """Send a one-shot model request and return the model's turn."""
        return model_turn(self.responses(request_payload(request)))

    def create_conversation(self, metadata: Mapping[str, str]) -> str:
        """Create a remote conversation and return its id."""
        result = self.request("/conversations", {"metadata": dict(metadata)})
        conversation_id = result.get("id")
        if not isinstance(conversation_id, str):
            raise AppError(502, "OpenAI hat keine Konversations-ID zurückgegeben.")
        return conversation_id

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete an explicitly identified remote conversation, when configured."""
        if not self.api_key or not conversation_id:
            return False
        self.http_client.request(
            "DELETE",
            endpoint(
                self.base_url,
                "/conversations/" + quote(conversation_id, safe=""),
                default_base_url=self.default_base_url,
            ),
            headers=self._headers(),
            timeout=30,
            service="openai",
        )
        return True

    def _responses_prepared(
        self, payload: Mapping[str, Any], *, cancel_event: Any = None
    ) -> dict[str, Any]:
        try:
            return request_with_conversation_retry(
                lambda: self._send(
                    self.responses_path,
                    payload,
                    cancel_event=cancel_event,
                    prepared=True,
                ),
                cancel_event=cancel_event,
                on_retry=lambda attempt, delay: self.logger.warning(
                    "OpenAI conversation is temporarily locked; retrying",
                    extra={
                        "event": "openai_conversation_locked",
                        "context": {"attempt": attempt, "retry_in_seconds": delay},
                    },
                ),
                wait=self.wait,
            )
        except provider_http.ProviderRequestCancelled as exc:
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled") from exc


def responses_payload(
    payload: Mapping[str, Any],
    *,
    thinking_level: str,
    service_tier: str | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    """Build an OpenAI Responses API payload without mutating caller state."""
    request_payload = dict(payload)
    request_payload.setdefault("reasoning", {"effort": thinking_level})
    if service_tier is not None:
        request_payload.setdefault("service_tier", service_tier)
    if stream:
        request_payload["stream"] = True
    return request_payload
