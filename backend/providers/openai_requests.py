"""OpenAI Responses provider internals."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse, urlunparse

from backend.errors import COACH_ABORTED_ERROR, OPENAI_API_KEY_ERROR, AppError
from backend.providers import http as provider_http

if TYPE_CHECKING:
    from backend.providers.state import ProviderStateService

__all__ = [
    "OPENAI_RATE_LIMIT_HEADERS",
    "OPENAI_UNEXPECTED_RESPONSE_MESSAGE",
    "OpenAIResponsesClient",
    "endpoint",
    "poll_background_response",
    "request_with_conversation_retry",
    "response_id",
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


def response_id(value: Any) -> str:
    """Normalize and validate an OpenAI Responses API response identifier."""
    normalized = str(value or "").strip()
    if not re.fullmatch(r"(?a:resp_[\w-]{1,200})", normalized):
        raise AppError(
            502,
            "OpenAI hat keine gültige Response-ID zurückgegeben.",
            reason="invalid_response",
        )
    return normalized


_validate_response_id = response_id


def poll_background_response(
    initial_response: dict[str, Any],
    *,
    retrieve: Callable[[str], dict[str, Any]],
    cancel: Callable[[str], Any],
    cancel_event: Any = None,
    poll_seconds: float,
    max_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    wait: Callable[[float], Any] | None = None,
) -> dict[str, Any]:
    """Poll one OpenAI background response until it reaches a terminal status."""
    started = monotonic()
    wait = time.sleep if wait is None else wait
    active_response_id = response_id(initial_response.get("id"))
    current = initial_response

    def abort(error: AppError) -> None:
        try:
            cancel(active_response_id)
        except Exception:  # noqa: BLE001, S110 - remote cancellation is best effort
            pass
        raise error

    while str(current.get("status") or "").casefold() in {"queued", "in_progress"}:
        if cancel_event is not None:
            if (
                cancel_event.wait(poll_seconds)
                or getattr(cancel_event, "is_set", lambda: False)()
            ):
                abort(AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled"))
        else:
            wait(poll_seconds)
        if monotonic() - started >= max_seconds:
            abort(
                AppError(
                    504,
                    "Die Hintergrundplanung hat das Zeitlimit überschritten.",
                    reason="provider_timeout",
                )
            )
        current = retrieve(active_response_id)
    return current


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
        background_poll_seconds: float,
        background_max_seconds: float,
        thinking_level: Callable[[], str],
        http_client: provider_http.JsonHttpClient,
        provider_state: ProviderStateService,
        logger: Any,
        monotonic: Callable[[], float] = time.monotonic,
        wait: Callable[[float], Any] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.default_base_url = default_base_url
        self.responses_path = responses_path
        self.response_timeout_seconds = response_timeout_seconds
        self.background_poll_seconds = background_poll_seconds
        self.background_max_seconds = background_max_seconds
        self.thinking_level = thinking_level
        self.http_client = http_client
        self.provider_state = provider_state
        self.logger = logger
        self.monotonic = monotonic
        self.wait = wait

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
                payload, thinking_level=self.thinking_level()
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
        result = self.provider_state.validate_openai_response(path, result)
        if not isinstance(result, dict):
            raise AppError(502, OPENAI_UNEXPECTED_RESPONSE_MESSAGE)
        if not (
            path == self.responses_path and request_payload.get("background") is True
        ):
            self.provider_state.record_usage(
                "openai", result, path.strip("/") or "request"
            )
        return result

    def request(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Send one OpenAI JSON request and observe its response."""
        return self._send(path, payload)

    def responses(
        self, payload: Mapping[str, Any], *, cancel_event: Any = None
    ) -> dict[str, Any]:
        """Send a Responses request, retrying only transient conversation locks."""
        request_payload = responses_payload(
            payload, thinking_level=self.thinking_level()
        )
        return self._responses_prepared(request_payload, cancel_event=cancel_event)

    def retrieve(self, response_id: str) -> dict[str, Any]:
        """Retrieve one background response without exposing its identifier."""
        self._require_api_key()
        normalized_id = _validate_response_id(response_id)
        result = self.http_client.request(
            "GET",
            endpoint(
                self.base_url,
                f"{self.responses_path}/{quote(normalized_id, safe='')}",
                default_base_url=self.default_base_url,
            ),
            headers=self._headers(),
            timeout=self.response_timeout_seconds,
            service="openai",
        )
        result = self.provider_state.validate_openai_response(
            self.responses_path, result
        )
        if not isinstance(result, dict):
            raise AppError(502, OPENAI_UNEXPECTED_RESPONSE_MESSAGE)
        return result

    def cancel(self, response_id: str) -> None:
        """Best-effort cancellation for an active background response."""
        if not self.api_key:
            return
        normalized_id = _validate_response_id(response_id)
        try:
            self.http_client.request(
                "POST",
                endpoint(
                    self.base_url,
                    f"{self.responses_path}/{quote(normalized_id, safe='')}/cancel",
                    default_base_url=self.default_base_url,
                ),
                {},
                headers=self._headers(),
                timeout=self.response_timeout_seconds,
                service="openai",
            )
        except Exception:  # noqa: BLE001 - remote cancellation is best effort
            self.logger.warning(
                "OpenAI background response cancellation failed",
                extra={"event": "openai_background_cancel_failed"},
            )

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

    def background(
        self,
        payload: Mapping[str, Any],
        *,
        response_id: str | None = None,
        on_response_id: Callable[[str], Any] | None = None,
        cancel_event: Any = None,
    ) -> dict[str, Any]:
        """Create or resume a bounded background response and poll it."""
        started = self.monotonic()
        if response_id is not None:
            current = self.retrieve(response_id)
            active_response_id = _validate_response_id(current.get("id") or response_id)
        else:
            request_payload = responses_payload(
                payload,
                thinking_level=self.thinking_level(),
                background=True,
            )
            current = self._responses_prepared(
                request_payload, cancel_event=cancel_event
            )
            active_response_id = _validate_response_id(current.get("id"))
            if on_response_id is not None:
                on_response_id(active_response_id)
        remaining_seconds = max(
            0.0, self.background_max_seconds - (self.monotonic() - started)
        )
        current = poll_background_response(
            {**current, "id": active_response_id},
            retrieve=self.retrieve,
            cancel=self.cancel,
            cancel_event=cancel_event,
            poll_seconds=self.background_poll_seconds,
            max_seconds=remaining_seconds,
            monotonic=self.monotonic,
            wait=self.wait,
        )
        current = self.provider_state.validate_openai_response(
            self.responses_path, current
        )
        if not isinstance(current, dict):
            raise AppError(502, OPENAI_UNEXPECTED_RESPONSE_MESSAGE)
        self.provider_state.record_usage("openai", current, "responses_background")
        return current

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
    stream: bool = False,
    background: bool = False,
) -> dict[str, Any]:
    """Build an OpenAI Responses API payload without mutating caller state."""
    request_payload = dict(payload)
    request_payload.setdefault("reasoning", {"effort": thinking_level})
    if stream:
        request_payload["stream"] = True
    if background:
        request_payload["background"] = True
        request_payload["store"] = True
    return request_payload


def endpoint(base_url: Any, path: str, *, default_base_url: str) -> str:
    """Resolve an OpenAI-compatible API path against a configured base URL."""
    base = str(base_url or default_base_url).strip() or default_base_url
    parsed = urlparse(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AppError(
            500,
            "OPENAI_BASE_URL muss eine gültige HTTP(S)-Basis-URL ohne Zugangsdaten oder Query-Parameter sein.",
        )
    normalized_path = "/" + str(path or "").lstrip("/")
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/") + normalized_path,
            "",
            "",
            "",
        )
    )
