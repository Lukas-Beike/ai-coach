"""OpenAI Responses provider internals."""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Any

from backend import observability
from backend.providers.openai_errors import (
    _openai_error_reason,
    _safe_openai_error_token,
)

__all__ = [
    "OpenAIResponseFailure",
    "response_diagnostic_content",
    "response_diagnostic_details",
    "response_failure_reason",
    "response_text",
    "validate_response",
]


def response_failure_reason(
    path: str, result: Any, responses_path: str = "/responses"
) -> str | None:
    """Return the normalized wire-level failure, without application side effects."""
    if not isinstance(result, dict):
        return "invalid_response"
    if path != responses_path:
        return "response_error" if result.get("error") else None
    if result.get("type") == "error":
        return "response_error"
    status = str(result.get("status") or "").casefold()
    if status in {"failed", "cancelled"}:
        return "response_failed"
    if status and status not in {"completed", "incomplete", "in_progress", "queued"}:
        return "invalid_response_status"
    if result.get("error"):
        return "response_error"
    return None


_RESPONSE_FAILURE_MESSAGES = MappingProxyType(
    {
        "invalid_response": "OpenAI response is not a JSON object.",
        "response_error": "OpenAI returned an error response.",
        "response_failed": "OpenAI did not complete the coach response.",
        "invalid_response_status": "OpenAI returned an unknown response status.",
    }
)


class OpenAIResponseFailure(Exception):
    """Safe, normalized failure from validating an OpenAI response."""

    def __init__(
        self,
        reason: str,
        *,
        provider_error_code: str | None = None,
        provider_error_type: str | None = None,
        provider_response_status: str | None = None,
        provider_incomplete_reason: str | None = None,
    ):
        self.reason = reason
        self.message = _RESPONSE_FAILURE_MESSAGES.get(
            reason, "OpenAI response validation failed."
        )
        classified_reason, classified_message = _openai_error_reason(
            0, {"code": provider_error_code, "type": provider_error_type}
        )
        if classified_reason != "http_error":
            self.reason, self.message = classified_reason, classified_message
        self.provider_error_code = provider_error_code
        self.provider_error_type = provider_error_type
        self.provider_response_status = provider_response_status
        self.provider_incomplete_reason = provider_incomplete_reason
        super().__init__(self.message)


def validate_response(
    path: str,
    result: Any,
    *,
    responses_path: str = "/responses",
    allowed_error_codes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Validate a decoded OpenAI response without provider or application side effects."""
    failure = response_failure_reason(path, result, responses_path)
    if failure is None:
        return result

    response = result if isinstance(result, dict) else {}
    provider_error = response.get("error")
    if not isinstance(provider_error, dict):
        provider_error = {}
    if response.get("type") == "error":
        provider_error = response
    error_code = provider_error.get("code")
    incomplete_details = response.get("incomplete_details")
    incomplete_reason = (
        incomplete_details.get("reason")
        if isinstance(incomplete_details, dict)
        else None
    )
    raise OpenAIResponseFailure(
        failure,
        provider_error_code=(
            error_code
            if isinstance(error_code, str) and error_code in allowed_error_codes
            else None
        ),
        provider_error_type=_safe_openai_error_token(provider_error.get("type")),
        provider_response_status=_safe_openai_error_token(response.get("status")),
        provider_incomplete_reason=_safe_openai_error_token(incomplete_reason),
    )


def response_diagnostic_details(response: Any) -> dict[str, str]:
    """Expose only bounded provider markers from a terminal Responses object."""
    if not isinstance(response, dict):
        return {}
    result: dict[str, str] = {}
    error = response.get("error")
    error = error if isinstance(error, dict) else {}
    if response.get("type") == "error":
        error = response
    if error:
        result["provider_error_present"] = "true"
    identifier = response.get("id")
    if isinstance(identifier, str) and re.fullmatch(
        r"(?a:resp_[\w-]{1,200})", identifier.strip()
    ):
        result["provider_response_id"] = identifier.strip()
    code = _safe_openai_error_token(error.get("code"))
    if code and code in observability.OPENAI_RESPONSE_ERROR_CODES:
        result["provider_error_code"] = code
    error_type = _safe_openai_error_token(error.get("type"))
    if error_type and error_type in {
        "invalid_request_error",
        "authentication_error",
        "permission_error",
        "rate_limit_error",
        "server_error",
    }:
        result["provider_error_type"] = error_type
    status = _safe_openai_error_token(response.get("status"))
    if status and status in {"failed", "cancelled", "incomplete", "completed"}:
        result["provider_response_status"] = status
    incomplete = response.get("incomplete_details")
    marker = _safe_openai_error_token(
        incomplete.get("reason") if isinstance(incomplete, dict) else None
    )
    if marker and marker in {"max_output_tokens", "content_filter", "stop", "timeout"}:
        result["provider_incomplete_reason"] = marker
    return result


def response_diagnostic_content(response: Any) -> dict[str, Any]:
    """Expose provider error content for the bounded, redacted diagnostic store."""
    if not isinstance(response, dict):
        return {}
    error = _response_error_object(response)
    content = {
        target: error[source]
        for source, target in (
            ("code", "provider_error_code_raw"),
            ("type", "provider_error_type"),
            ("param", "provider_error_parameter"),
            ("message", "provider_error_message"),
        )
        if isinstance(error.get(source), str) and error[source].strip()
    }
    incomplete = response.get("incomplete_details")
    if isinstance(incomplete, dict):
        content["incomplete_details"] = incomplete
    last_error = response.get("last_error")
    if isinstance(last_error, dict):
        content["last_error"] = last_error
    return content


def _response_error_object(response: dict[str, Any]) -> dict[str, Any]:
    error = response.get("error")
    if isinstance(error, dict):
        return error
    return response if response.get("type") == "error" else {}


def _content_text(content: Any) -> str | None:
    if not isinstance(content, dict):
        return None
    if (
        content.get("type") in {"output_text", "text"}
        and isinstance(content.get("text"), str)
        and content["text"]
    ):
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
    return [
        text for content in item.get("content", []) if (text := _content_text(content))
    ]


def response_text(response: dict[str, Any]) -> str:
    """Extract displayable text from a Responses API response."""
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    return "\n".join(
        text for item in response.get("output", []) for text in _item_text(item)
    ).strip()
