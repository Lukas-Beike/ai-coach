"""Pure OpenAI Responses API wire adapters."""

from __future__ import annotations

from typing import Any


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
