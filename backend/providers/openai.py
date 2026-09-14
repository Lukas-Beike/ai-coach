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


def response_text(response: dict[str, Any]) -> str:
    """Extract displayable text from a Responses API response."""
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "refusal" and item.get("refusal"):
            parts.append(f"The coach declined to answer: {item['refusal']}")
            continue
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                parts.append(str(content["text"]))
            elif content.get("type") == "refusal" and content.get("refusal"):
                parts.append(f"The coach declined to answer: {content['refusal']}")
    return "\n".join(parts).strip()
