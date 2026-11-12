"""The OpenAI Responses adapter: the one module that knows the wire format.

A ModelRequest becomes a Responses payload and a Responses reply becomes a
ModelTurn. Responses is the only supported dialect; nothing else may read or
write its item types (function_call, reasoning, encrypted_content, input_text,
input_image, ...).
"""

from __future__ import annotations

import json
from typing import Any

from backend.providers.model_seam import ModelRequest, ModelTurn
from backend.providers.openai_responses import response_text

ENCRYPTED_REASONING_INCLUDE = "reasoning.encrypted_content"
# The sources a web search read; JSON output carries no inline citations.
WEB_SEARCH_SOURCES_INCLUDE = "web_search_call.action.sources"


def _data_url(mime: str, data: str) -> str:
    return f"data:{mime};base64,{data}"


def model_input(text: str, attachments: list[dict[str, Any]]) -> Any:
    """The user input: plain text, or one user message with the attachment parts.

    Each attachment is {"evidence": dict, "kind": "file" | "image" | absent,
    "mime", "data" (base64), "filename" for a file}.
    """
    if not attachments:
        return text
    parts = [{"type": "input_text", "text": text}]
    for item in attachments:
        parts.append(
            {
                "type": "input_text",
                "text": json.dumps(item["evidence"], ensure_ascii=False),
            }
        )
        if item.get("kind") == "file":
            parts.append(
                {
                    "type": "input_file",
                    "filename": item["filename"],
                    "file_data": _data_url(item["mime"], item["data"]),
                }
            )
        elif item.get("kind") == "image":
            parts.append(
                {
                    "type": "input_image",
                    "image_url": _data_url(item["mime"], item["data"]),
                    "detail": "auto",
                }
            )
    return [{"role": "user", "content": parts}]


def _tool_outputs(results: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function_call_output",
            "call_id": result["call_id"],
            "output": result["output"],
        }
        for result in results
    ]


def _input(request: ModelRequest) -> Any:
    if request.images:
        return [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": request.input},
                    *(
                        {
                            "type": "input_image",
                            "image_url": _data_url(image["mime"], image["data"]),
                        }
                        for image in request.images
                    ),
                ],
            }
        ]
    if not request.steps:
        return model_input(request.input, request.attachments)
    if request.conversation_id:
        # The conversation holds the earlier items: send only the new results.
        return _tool_outputs(request.steps[-1].tool_results)
    first = model_input(request.input, request.attachments)
    # Nothing is stored remotely: resend the turn's items so far, the model's
    # calls and (encrypted) reasoning, and the new tool outputs.
    items = (
        [dict(item) for item in first if isinstance(item, dict)]
        if isinstance(first, list)
        else [{"role": "user", "content": str(first or "")}]
    )
    for step in request.steps:
        items = [*items, *step.opaque_state, *_tool_outputs(step.tool_results)]
    return items


def _one_shot_payload(request: ModelRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": request.model}
    if request.instructions:
        payload["instructions"] = request.instructions
    payload["input"] = _input(request)
    if request.output_schema is not None:
        output_format: dict[str, Any] = {
            "type": "json_schema",
            "name": request.output_schema["name"],
            "strict": True,
            "schema": request.output_schema["schema"],
        }
    else:
        output_format = {"type": "json_object"}
    payload["text"] = {"format": output_format}
    if request.stateless:
        payload["store"] = False
    if request.max_output_tokens is not None:
        payload["max_output_tokens"] = request.max_output_tokens
    if request.reasoning_effort:
        payload["reasoning"] = {"effort": request.reasoning_effort}
    return payload


def _with_options(payload: dict[str, Any], request: ModelRequest) -> dict[str, Any]:
    """Add the web search and a fixed service tier to any request shape."""
    if request.web_search:
        payload["tools"] = [*payload.get("tools", []), {"type": "web_search"}]
        payload["include"] = [*payload.get("include", []), WEB_SEARCH_SOURCES_INCLUDE]
    if request.service_tier:
        payload["service_tier"] = request.service_tier
    return payload


def request_payload(request: ModelRequest) -> dict[str, Any]:
    """The Responses API payload for one request."""
    if request.output_schema is not None or request.json_output:
        return _with_options(_one_shot_payload(request), request)
    payload: dict[str, Any] = {"model": request.model}
    if request.reasoning_effort:
        payload["reasoning"] = {"effort": request.reasoning_effort}
    if request.conversation_id:
        payload["conversation"] = request.conversation_id
    payload.update(
        {
            "instructions": request.instructions,
            "input": _input(request),
            "tools": request.tools,
            "tool_choice": request.tool_choice,
            "max_output_tokens": request.max_output_tokens,
            "truncation": "auto",
            "store": not request.stateless,
        }
    )
    if request.stateless:
        payload["include"] = [ENCRYPTED_REASONING_INCLUDE]
    payload["parallel_tool_calls"] = False
    return _with_options(payload, request)


def model_turn(response: Any) -> ModelTurn:
    """Read a Responses reply: text, tool calls, replayable items, usage, stop."""
    if not isinstance(response, dict):
        return ModelTurn()
    output = [item for item in response.get("output") or [] if isinstance(item, dict)]
    status = response.get("status")
    details = response.get("incomplete_details")
    if status == "incomplete":
        reason = details.get("reason") if isinstance(details, dict) else None
        stop_reason = "max_tokens" if reason == "max_output_tokens" else "incomplete"
    else:
        stop_reason = status if status in {"completed", "failed", "cancelled"} else ""
    usage = response.get("usage")
    return ModelTurn(
        text=response_text(response),
        tool_calls=[
            {key: item.get(key) for key in ("call_id", "name", "arguments")}
            for item in output
            if item.get("type") == "function_call"
        ],
        # A reasoning item needs its encrypted content: the provider kept nothing
        # to look it up by id.
        opaque_state=[
            dict(item)
            for item in output
            if item.get("type") != "reasoning" or item.get("encrypted_content")
        ],
        usage=usage if isinstance(usage, dict) else {},
        stop_reason=stop_reason,
        final_text=_final_text(output),
        sources=_sources(output),
    )


def _list(value: Any) -> list[Any]:
    """A reply field that should be a list; anything else reads as empty."""
    return value if isinstance(value, list) else []


def _final_text(output: list[dict[str, Any]]) -> str:
    messages = [item for item in output if item.get("type") == "message"]
    return "".join(
        str(content.get("text") or "")
        for content in (_list(messages[-1].get("content")) if messages else [])
        if isinstance(content, dict) and content.get("type") == "output_text"
    )


def _sources(output: list[dict[str, Any]]) -> list[str]:
    """The pages a web search read and the pages the answer cites."""
    urls: list[Any] = []
    for item in output:
        if item.get("type") == "web_search_call":
            action = item.get("action")
            found = action.get("sources") if isinstance(action, dict) else None
            urls += [
                source.get("url") for source in _list(found) if isinstance(source, dict)
            ]
        elif item.get("type") == "message":
            urls += [
                annotation.get("url")
                for content in _list(item.get("content"))
                if isinstance(content, dict)
                for annotation in _list(content.get("annotations"))
                if isinstance(annotation, dict)
                and annotation.get("type") == "url_citation"
            ]
    return [url for url in urls if isinstance(url, str)]
