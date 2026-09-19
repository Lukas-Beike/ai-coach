"""Pure OpenAI Responses API wire adapters."""

from __future__ import annotations

import json
import math
import re
from typing import Any

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


def response_failure_reason(path: str, result: Any, responses_path: str = "/responses") -> str | None:
    """Return the normalized wire-level failure, without application side effects."""
    if not isinstance(result, dict):
        return "invalid_response"
    if result.get("error"):
        return "response_error"
    if path != responses_path:
        return None
    status = str(result.get("status") or "").casefold()
    if status in {"failed", "cancelled"}:
        return "response_failed"
    if status and status not in {"completed", "incomplete", "in_progress", "queued"}:
        return "invalid_response_status"
    return None


def _content_text(content: Any) -> str | None:
    if not isinstance(content, dict):
        return None
    if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str) and content["text"]:
        return content["text"]
    if content.get("type") == "refusal" and content.get("refusal"):
        return f"The coach declined to answer: {content['refusal']}"
    return None


def _item_text(item: Any) -> list[str]:
    if not isinstance(item, dict):
        return []
    refusal = _content_text(item) if item.get("type") == "refusal" else None
    if refusal:
        return [refusal]
    if item.get("type") != "message":
        return []
    return [text for content in item.get("content", []) if (text := _content_text(content))]


def response_text(response: dict[str, Any]) -> str:
    """Extract displayable text from a Responses API response."""
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    return "\n".join(text for item in response.get("output", []) for text in _item_text(item)).strip()


def retry_after_seconds(headers: Any) -> int | None:
    """Parse a bounded numeric Retry-After hint without retaining raw headers."""
    if headers is None:
        return None
    try:
        seconds = float(str(headers.get("retry-after")).strip())
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return max(1, min(math.ceil(seconds), 24 * 60 * 60))


def _safe_openai_error_token(value: Any) -> str | None:
    """Keep a provider error classifier without retaining provider text."""
    token = str(value or "").strip().casefold()
    if not token or len(token) > 160 or not re.fullmatch(r"[a-z0-9_.\[\]-]+", token):
        return None
    return token


def _provider_error_payload(raw_body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw_body) if raw_body else None
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    return error if isinstance(error, dict) else {}


def error_diagnostic_details(raw_body: bytes, headers: Any = None, *, max_response_bytes: int) -> dict[str, Any]:
    """Return safe OpenAI error metadata; never retain an upstream message/body."""
    error = _provider_error_payload(raw_body)
    max_bytes = max(0, max_response_bytes)
    details: dict[str, Any] = {"error_body_bytes": min(len(raw_body or b""), max_bytes + 1)}
    for source, target in (("code", "error_code"), ("type", "error_type"), ("param", "parameter")):
        token = _safe_openai_error_token(error.get(source))
        if token:
            details[target] = token
    try:
        request_id = _safe_openai_error_token(headers.get("x-request-id")) if headers is not None else None
    except (AttributeError, TypeError):
        request_id = None
    if request_id:
        details["request_id"] = request_id
    return details


def _openai_error_tokens(error: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Return transient normalized tokens used only for OpenAI error classification."""
    code = str(error.get("code") or "").strip().casefold()
    error_type = str(error.get("type") or "").strip().casefold()
    parameter = str(error.get("param") or "").strip().casefold()
    provider_message = str(error.get("message") or "").strip().casefold()
    searchable = f"{code} {error_type} {provider_message}"
    return code, error_type, parameter, provider_message, searchable


def _openai_invalid_input_state(error_type: str, parameter: str, provider_message: str) -> bool:
    """Identify recoverable tool-output and reasoning continuation state errors."""
    return error_type == "invalid_request_error" and parameter.startswith("input") and (
        "no tool output found for function call" in provider_message
        or ("reasoning" in provider_message and "required following item" in provider_message)
    )


def _openai_conversation_error(
    status: int,
    code: str,
    error_type: str,
    parameter: str,
    provider_message: str,
    searchable: str,
) -> tuple[str, str] | None:
    """Classify conversation locking and invalid continuation state separately."""
    if code in {"conversation_locked", "conversation_lock_timeout", "concurrent_request"} or (
        "conversation" in searchable and "lock" in searchable
    ):
        return "conversation_locked", "Die OpenAI-Konversation wird gerade von einer anderen Anfrage verwendet. Bitte kurz warten und erneut versuchen."
    invalid_state = _openai_invalid_input_state(error_type, parameter, provider_message)
    continuation_error = "conversation" in searchable and any(
        marker in searchable for marker in ("state", "previous", "invalid", "not found")
    )
    if status == 400 and (
        code in {"conversation_not_found", "invalid_conversation", "conversation_state_invalid", "invalid_function_call_output"}
        or "function_call_output" in searchable
        or invalid_state
        or continuation_error
    ):
        return "conversation_state_invalid", "Der KI-Dienst konnte den bisherigen Gesprächszustand nicht fortsetzen. Bitte versuche es erneut; dein lokaler Chat bleibt erhalten."
    return None


def _openai_billing_error(code: str, error_type: str, searchable: str) -> tuple[str, str] | None:
    """Classify quota and billing limits before generic rate limiting."""
    if code == "credit_balance_exhausted":
        return "credit_balance_exhausted", "Das OpenAI-Guthaben ist aufgebraucht. Bitte im OpenAI-Billing Guthaben hinzufügen."
    if code in {"organization_spend_limit_exceeded", "project_spend_limit_exceeded", "organization_usage_limit_exceeded"}:
        return code, "Das OpenAI-Ausgaben- oder Nutzungslimit ist erreicht. Bitte das Limit im OpenAI-Konto prüfen."
    if code in {"insufficient_quota", "billing_hard_limit_reached"} or error_type == "insufficient_quota" or any(
        marker in searchable for marker in ("insufficient_quota", "quota", "billing_hard_limit", "credits")
    ):
        return "insufficient_quota", "Das OpenAI-Guthaben bzw. Kontingent ist aufgebraucht. Bitte Guthaben und Abrechnung im OpenAI-Konto prüfen."
    return None


def _openai_error_reason(status: int, error: dict[str, Any]) -> tuple[str, str]:
    """Map safe OpenAI error markers to an athlete-facing recovery action."""
    code, error_type, parameter, provider_message, searchable = _openai_error_tokens(error)
    conversation_error = _openai_conversation_error(status, code, error_type, parameter, provider_message, searchable)
    if conversation_error:
        return conversation_error
    billing_error = _openai_billing_error(code, error_type, searchable)
    if billing_error:
        return billing_error
    if status == 429 or code == "rate_limit_exceeded" or error_type == "rate_limit_exceeded":
        return "rate_limit_exceeded", "OpenAI hat das Anfragelimit erreicht. Bitte kurz warten und erneut versuchen."
    if status in {401, 403} or code in {"invalid_api_key", "invalid_organization", "permission_denied"}:
        return "authentication_or_permission", "Der OpenAI-Zugang wurde abgelehnt. Bitte API-Schlüssel und Projektberechtigungen prüfen."
    if status == 404 or code in {"model_not_found", "not_found"}:
        return "not_found", "Das konfigurierte OpenAI-Modell oder der angeforderte Dienst wurde nicht gefunden."
    if status >= 500:
        return "provider_unavailable", "OpenAI ist vorübergehend nicht verfügbar. Bitte später erneut versuchen."
    return "http_error", f"OpenAI konnte die Anfrage nicht verarbeiten (HTTP {status})."


def error_details(
    status: int,
    raw_body: bytes,
    headers: Any = None,
    *,
    updated_at: str,
) -> dict[str, Any]:
    """Classify an OpenAI error without exposing the provider's raw message."""
    reason, message = _openai_error_reason(status, _provider_error_payload(raw_body))
    details = {
        "state": "error",
        "reason": reason,
        "message": message,
        "http_status": status,
        "updated_at": updated_at,
    }
    retry_after = retry_after_seconds(headers)
    if retry_after is not None:
        details["retry_after_seconds"] = retry_after
    return details


def safe_log_reason(reason: Any) -> str:
    """Project an OpenAI status reason onto static values safe for structured logs."""
    if not isinstance(reason, str):
        return "http_error"
    return _SAFE_LOG_REASONS.get(reason, "http_error")


def rate_limit_snapshot(headers: Any, *, updated_at: str) -> dict[str, Any] | None:
    """Project only the allowlisted OpenAI rate-limit headers."""
    if headers is None:
        return None
    values: dict[str, str] = {}
    for header_name, value_name in OPENAI_RATE_LIMIT_HEADERS.items():
        try:
            value = headers.get(header_name)
        except (AttributeError, TypeError):
            continue
        if value not in (None, ""):
            values[value_name] = str(value)
    return {"updated_at": updated_at, **values} if values else None
