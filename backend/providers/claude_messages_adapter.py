"""The Anthropic Messages adapter: the one module that knows Claude's wire format.

A ModelRequest becomes a Messages payload and a Messages reply (or the message a
stream assembles) becomes a ModelTurn. Nothing else may read or write Claude's
content block types (tool_use, tool_result, thinking, server_tool_use, ...).
Claude keeps no conversation: every request resends the turn's earlier rounds,
whose assistant content (thinking signatures included) is replayed unchanged.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from backend.errors import AppError
from backend.providers.model_seam import ModelRequest, ModelTurn

# Server-side refusal fallback to an older Claude model (athlete decision 2 on #2355).
FALLBACK_BETA = "server-side-fallback-2026-07-01"
_FALLBACK_FAMILIES = frozenset({"opus", "sonnet"})
# The dynamic-filtering web search runs on Opus and Sonnet; Haiku keeps the basic one.
_WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search"}
_WEB_SEARCH_BASIC = {"type": "web_search_20250305", "name": "web_search"}
_EFFORTS = {
    "none": "low",
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
}
DEFAULT_MAX_TOKENS = 16_000
# Thinking counts toward max_tokens, so a short answer still needs room to think.
MIN_MAX_TOKENS = 4_096
_JSON_ONLY = (
    "\n\nAnswer with exactly one JSON object and nothing else: no Markdown fence, "
    "no text before or after it."
)
_FAMILY = re.compile(r"^claude-(opus|sonnet|haiku)-")
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_ACTION_BLOCKS = frozenset(
    {
        "tool_use",
        "server_tool_use",
        "web_search_tool_result",
        "web_fetch_tool_result",
        "fallback",
    }
)
REFUSED_MESSAGE = "Claude hat diese Anfrage abgelehnt."
_UNEXPECTED = "Claude hat eine unerwartete Antwort zurückgegeben."


def claude_family(model: str) -> str | None:
    """opus, sonnet or haiku for a Claude model id, else None."""
    match = _FAMILY.match(str(model or ""))
    return match.group(1) if match else None


def _attachment_parts(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for item in attachments:
        parts.append(
            {"type": "text", "text": json.dumps(item["evidence"], ensure_ascii=False)}
        )
        if item.get("kind") == "file":
            # Attachment files are parsed measurements as JSON text.
            parts.append(
                {
                    "type": "document",
                    "title": item["filename"],
                    "source": {
                        "type": "text",
                        "media_type": "text/plain",
                        "data": base64.b64decode(item["data"]).decode(
                            "utf-8", errors="replace"
                        ),
                    },
                }
            )
        elif item.get("kind") == "image":
            parts.append(_image(item["mime"], item["data"]))
    return parts


def _image(mime: str, data: str) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": mime, "data": data},
    }


def _user_content(request: ModelRequest) -> list[dict[str, Any]]:
    return [
        *(_image(image["mime"], image["data"]) for image in request.images),
        {"type": "text", "text": request.input},
        *_attachment_parts(request.attachments),
    ]


def _messages(request: ModelRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _user_content(request)}
    ]
    for step in request.steps:
        messages.append(
            {"role": "assistant", "content": [dict(b) for b in step.opaque_state]}
        )
        if step.tool_results:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result["call_id"],
                            "content": result["output"],
                        }
                        for result in step.tool_results
                    ],
                }
            )
    return messages


def _tools(request: ModelRequest) -> list[dict[str, Any]]:
    tools = [
        {
            "name": tool["name"],
            "description": tool.get("description") or "",
            "input_schema": tool.get("parameters")
            or {"type": "object", "properties": {}},
        }
        for tool in request.tools
        if tool.get("type") == "function"
    ]
    if tools:
        # The tool list is the stable start of every Coach request.
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
    if request.web_search:
        family = claude_family(request.model)
        tools.append(dict(_WEB_SEARCH if family != "haiku" else _WEB_SEARCH_BASIC))
    return tools


def _system(request: ModelRequest) -> str:
    system = request.instructions
    if request.output_schema is not None and request.web_search:
        # A schema-bound answer cannot carry the search citations: name the shape.
        system += (
            "\n\nThe JSON object follows this JSON schema:\n"
            + json.dumps(request.output_schema["schema"], ensure_ascii=False)
            + _JSON_ONLY
        )
    elif request.json_output and request.output_schema is None:
        system += _JSON_ONLY
    return system


def request_payload(request: ModelRequest, *, stream: bool = False) -> dict[str, Any]:
    """The Messages API payload for one request."""
    payload: dict[str, Any] = {
        "model": request.model,
        "max_tokens": max(
            request.max_output_tokens or DEFAULT_MAX_TOKENS, MIN_MAX_TOKENS
        ),
    }
    system = _system(request)
    if system:
        payload["system"] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
    payload["messages"] = _messages(request)
    # The last cacheable block: tool rounds of one turn reuse the earlier ones.
    payload["cache_control"] = {"type": "ephemeral"}
    tools = _tools(request)
    if tools:
        payload["tools"] = tools
    if request.tools:
        payload["tool_choice"] = (
            {"type": "none"}
            if request.tool_choice == "none"
            else {"type": "auto", "disable_parallel_tool_use": True}
        )
    output_config: dict[str, Any] = {}
    effort = _EFFORTS.get(str(request.reasoning_effort or ""))
    if effort:
        output_config["effort"] = effort
    if request.output_schema is not None and not request.web_search:
        output_config["format"] = {
            "type": "json_schema",
            "schema": request.output_schema["schema"],
        }
    if output_config:
        payload["output_config"] = output_config
    if claude_family(request.model) in _FALLBACK_FAMILIES:
        payload["fallbacks"] = "default"
    if stream:
        payload["stream"] = True
    return payload


def request_betas(payload: dict[str, Any]) -> list[str]:
    """The beta features a payload needs in its anthropic-beta header."""
    return [FALLBACK_BETA] if "fallbacks" in payload else []


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _count(value: Any) -> int:
    return value if type(value) is int and value > 0 else 0


def neutral_usage(usage: Any) -> dict[str, Any]:
    """Claude usage in the app's counters: input includes cache reads and writes."""
    raw = usage if isinstance(usage, dict) else {}
    cached = _count(raw.get("cache_read_input_tokens"))
    input_tokens = (
        _count(raw.get("input_tokens"))
        + _count(raw.get("cache_creation_input_tokens"))
        + cached
    )
    output_tokens = _count(raw.get("output_tokens"))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "input_tokens_details": {"cached_tokens": cached},
    }


def _stop_reason(value: Any) -> str:
    if value in {"end_turn", "tool_use", "stop_sequence"}:
        return "completed"
    if value in {"max_tokens", "model_context_window_exceeded"}:
        return "max_tokens"
    if value == "pause_turn":
        return "incomplete"
    if value == "refusal":
        return "refused"
    return ""


def _final_text(content: list[dict[str, Any]], *, json_answer: bool) -> str:
    """The text after the last tool or search block: earlier text narrates."""
    last_action = max(
        (i for i, block in enumerate(content) if block.get("type") in _ACTION_BLOCKS),
        default=-1,
    )
    text = "".join(
        str(block.get("text") or "")
        for block in content[last_action + 1 :]
        if block.get("type") == "text"
    ).strip()
    if json_answer:
        fenced = _FENCE.match(text)
        text = fenced.group(1) if fenced else text
    return text


def _sources(content: list[dict[str, Any]]) -> list[str]:
    """The pages a web search returned and the pages the answer cites."""
    urls: list[Any] = []
    for block in content:
        kind = block.get("type")
        if kind == "web_search_tool_result":
            urls += [
                result.get("url")
                for result in _list(block.get("content"))
                if isinstance(result, dict)
            ]
        elif kind == "web_fetch_tool_result":
            fetched = block.get("content")
            urls.append(fetched.get("url") if isinstance(fetched, dict) else None)
        elif kind == "text":
            urls += [
                citation.get("url")
                for citation in _list(block.get("citations"))
                if isinstance(citation, dict)
                and citation.get("type") == "web_search_result_location"
            ]
    return [url for url in urls if isinstance(url, str)]


def model_turn(message: Any, *, json_answer: bool = False) -> ModelTurn:
    """Read a Messages reply: text, tool calls, replayable content, usage, stop."""
    if not isinstance(message, dict) or message.get("type") != "message":
        raise AppError(502, _UNEXPECTED, reason="invalid_response")
    content = [
        block for block in _list(message.get("content")) if isinstance(block, dict)
    ]
    return ModelTurn(
        text="".join(
            str(block.get("text") or "")
            for block in content
            if block.get("type") == "text"
        ),
        tool_calls=[
            {
                "call_id": block.get("id"),
                "name": block.get("name"),
                "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
            }
            for block in content
            if block.get("type") == "tool_use"
        ],
        # Replayed unchanged: thinking blocks are bound to this exact content.
        opaque_state=[dict(block) for block in content],
        usage=neutral_usage(message.get("usage")),
        stop_reason=_stop_reason(message.get("stop_reason")),
        final_text=_final_text(content, json_answer=json_answer),
        sources=_sources(content),
    )


class StreamAssembler:
    """Build the final message from Messages SSE events, emitting text deltas."""

    def __init__(self) -> None:
        self.message: dict[str, Any] | None = None
        self._blocks: dict[int, dict[str, Any]] = {}
        self._partial_json: dict[int, str] = {}
        self.finished = False

    def feed(self, event: dict[str, Any]) -> str:
        """Apply one event; return the visible text it adds."""
        kind = event.get("type")
        if kind == "message_start":
            self.message = dict(event.get("message") or {})
        elif kind == "content_block_start":
            self._blocks[int(event["index"])] = dict(event.get("content_block") or {})
        elif kind == "content_block_delta":
            return self._delta(int(event["index"]), event.get("delta") or {})
        elif kind == "content_block_stop":
            self._close(int(event["index"]))
        elif kind == "message_delta":
            self._message_delta(event)
        elif kind == "message_stop":
            self.finished = True
        elif kind == "error":
            raise stream_error(event.get("error"))
        return ""

    def _delta(self, index: int, delta: dict[str, Any]) -> str:
        block = self._blocks[index]
        kind = delta.get("type")
        if kind == "text_delta":
            text = str(delta.get("text") or "")
            block["text"] = str(block.get("text") or "") + text
            return text
        if kind == "input_json_delta":
            self._partial_json[index] = self._partial_json.get(index, "") + str(
                delta.get("partial_json") or ""
            )
        elif kind == "thinking_delta":
            block["thinking"] = str(block.get("thinking") or "") + str(
                delta.get("thinking") or ""
            )
        elif kind == "signature_delta":
            block["signature"] = delta.get("signature")
        elif kind == "citations_delta":
            block["citations"] = [*_list(block.get("citations")), delta.get("citation")]
        return ""

    def _close(self, index: int) -> None:
        if index not in self._partial_json:
            return
        raw = self._partial_json.pop(index)
        try:
            self._blocks[index]["input"] = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise AppError(502, _UNEXPECTED, reason="invalid_response") from exc

    def _message_delta(self, event: dict[str, Any]) -> None:
        if self.message is None:
            raise AppError(502, _UNEXPECTED, reason="invalid_response")
        delta = event.get("delta") or {}
        for key in ("stop_reason", "stop_details", "stop_sequence"):
            if key in delta:
                self.message[key] = delta[key]
        usage = event.get("usage")
        if isinstance(usage, dict):
            # message_delta counters are cumulative for the whole message.
            self.message["usage"] = {
                **(self.message.get("usage") or {}),
                **{key: value for key, value in usage.items() if value is not None},
            }

    def result(self) -> dict[str, Any]:
        """The complete message; a stream without message_stop is incomplete."""
        if self.message is None or not self.finished:
            raise AppError(
                502,
                "Claude hat keine vollständige Streaming-Antwort zurückgegeben.",
                reason="invalid_response",
            )
        return {
            **self.message,
            "content": [self._blocks[index] for index in sorted(self._blocks)],
        }


# Anthropic error types and the app's safe reasons; the provider's text is dropped.
_ERROR_REASONS = {
    "authentication_error": "authentication_or_permission",
    "permission_error": "authentication_or_permission",
    "not_found_error": "not_found",
    "rate_limit_error": "rate_limit_exceeded",
    "overloaded_error": "provider_unavailable",
    "api_error": "provider_unavailable",
    "billing_error": "insufficient_quota",
    "request_too_large": "request_failed",
    "invalid_request_error": "request_failed",
}
_ERROR_MESSAGES = {
    "authentication_or_permission": "Claude hat den API-Schlüssel abgelehnt.",
    "not_found": "Claude kennt das angefragte Modell nicht.",
    "rate_limit_exceeded": "Claude begrenzt gerade die Anfragen.",
    "provider_unavailable": "Claude ist vorübergehend nicht verfügbar.",
    "insufficient_quota": "Das Claude-Guthaben reicht nicht aus.",
    "request_failed": "Claude hat die Anfrage zurückgewiesen.",
}


def error_reason(error_type: Any, status: int | None = None) -> str:
    """The safe reason for an Anthropic error type or HTTP status."""
    if isinstance(error_type, str) and error_type in _ERROR_REASONS:
        return _ERROR_REASONS[error_type]
    if status in {401, 403}:
        return "authentication_or_permission"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limit_exceeded"
    if status is not None and status >= 500:
        return "provider_unavailable"
    return "request_failed"


def error_message(reason: str) -> str:
    return _ERROR_MESSAGES.get(reason, _ERROR_MESSAGES["request_failed"])


def stream_error(error: Any) -> AppError:
    """An error event inside a stream, as a safe classified AppError."""
    error_type = error.get("type") if isinstance(error, dict) else None
    reason = error_reason(error_type)
    status = 503 if reason == "provider_unavailable" else 502
    return AppError(status, error_message(reason), reason=reason)
