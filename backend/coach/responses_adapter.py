"""The OpenAI Responses adapter: the one Coach module that knows the wire format.

A ModelRequest becomes a Responses payload and a Responses reply becomes a
ModelTurn. Responses is the only supported dialect; nothing else may read or
write its item types (function_call, reasoning, encrypted_content, ...).
"""

from __future__ import annotations

import json
from typing import Any

from backend.coach.attachments import openai_attachment_data
from backend.coach.response_transport import ModelRequest, ModelTurn
from backend.providers.openai_responses import response_text

ENCRYPTED_REASONING_INCLUDE = "reasoning.encrypted_content"


def model_input(text: str, attachments: list[dict[str, Any]]) -> Any:
    """The user input: plain text, or one user message with the attachment parts."""
    if not attachments:
        return text
    parts = [{"type": "input_text", "text": text}]
    for item in attachments:
        summary_key = item["type"] if item["type"] in {"gpx", "fit"} else None
        evidence = {"untrusted_attachment_name": item["name"]}
        if summary_key:
            evidence[summary_key] = item.get("summary")
        parts.append(
            {"type": "input_text", "text": json.dumps(evidence, ensure_ascii=False)}
        )
        if item["type"] in {"gpx", "fit"}:
            data, mime = openai_attachment_data(item)
            parts.append(
                {
                    "type": "input_file",
                    "filename": item["name"] + ".json",
                    "file_data": f"data:{mime};base64,{data}",
                }
            )
        elif item["type"] == "image":
            parts.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{item['mime']};base64,{openai_attachment_data(item)[0]}",
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


def request_payload(request: ModelRequest) -> dict[str, Any]:
    """The Responses API payload for one request."""
    if request.output_schema is not None:
        payload: dict[str, Any] = {
            "model": request.model,
            "instructions": request.instructions,
            "input": request.input,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.output_schema["name"],
                    "strict": True,
                    "schema": request.output_schema["schema"],
                }
            },
            "store": False,
            "max_output_tokens": request.max_output_tokens,
        }
        if request.reasoning_effort:
            payload["reasoning"] = {"effort": request.reasoning_effort}
        return payload
    payload = {"model": request.model}
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
    return payload


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
    )
