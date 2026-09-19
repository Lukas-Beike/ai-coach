"""Pure Gemini response and tool-schema adapters."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from backend.errors import AppError

_STREAMING_EVENT_ERROR = "Gemini hat ein ung\\u00fcltiges Streaming-Ereignis zur\\u00fcckgegeben."


class StreamAccumulator:
    """Aggregate Gemini SSE data events and emit text from candidate zero."""

    def __init__(self, on_text_delta: Callable[[str], None]):
        self._on_text_delta = on_text_delta
        self.aggregate: dict[str, Any] = {"candidates": []}

    def consume_data_lines(self, data_lines: list[str]) -> None:
        """Consume one SSE event's data lines."""
        if not data_lines:
            return
        raw = "\n".join(data_lines)
        if not raw.strip() or raw.strip() == "[DONE]":
            return
        try:
            chunk = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AppError(502, _STREAMING_EVENT_ERROR, reason="invalid_response") from exc
        self._merge_chunk(chunk)

    def _merge_chunk(self, chunk: Any) -> None:
        if not isinstance(chunk, dict):
            raise AppError(502, _STREAMING_EVENT_ERROR, reason="invalid_response")
        self._merge_response_metadata(chunk)
        candidates = chunk.get("candidates") if isinstance(chunk.get("candidates"), list) else []
        for index, candidate in enumerate(candidates):
            if isinstance(candidate, dict):
                self._merge_candidate(index, candidate)

    def _merge_response_metadata(self, chunk: dict[str, Any]) -> None:
        usage = chunk.get("usageMetadata")
        if isinstance(usage, dict):
            self.aggregate["usageMetadata"] = usage
        for key in ("modelVersion", "promptFeedback"):
            if key in chunk:
                self.aggregate[key] = chunk[key]

    def _merge_candidate(self, index: int, candidate: dict[str, Any]) -> None:
        while len(self.aggregate["candidates"]) <= index:
            self.aggregate["candidates"].append({"content": {"role": "model", "parts": []}})
        target = self.aggregate["candidates"][index]
        for key in ("finishReason", "finishMessage", "safetyRatings", "citationMetadata"):
            if key in candidate:
                target[key] = candidate[key]
        content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
        if content.get("role"):
            target["content"]["role"] = content["role"]
        parts = content.get("parts") if isinstance(content.get("parts"), list) else []
        for part in parts:
            if isinstance(part, dict):
                self._merge_part(index, target["content"]["parts"], part)

    def _merge_part(self, index: int, target_parts: list[dict[str, Any]], part: dict[str, Any]) -> None:
        delta = part.get("text")
        if not isinstance(delta, str) or not delta:
            target_parts.append(dict(part))
            return
        if index == 0:
            self._on_text_delta(delta)
        metadata = {key: value for key, value in part.items() if key != "text"}
        previous = target_parts[-1] if target_parts else None
        if isinstance(previous, dict) and set(previous) <= {"text", *metadata} and all(
            previous.get(key) == value for key, value in metadata.items()
        ):
            previous["text"] = str(previous.get("text") or "") + delta
        else:
            target_parts.append(dict(part))


def response_text(result: Any) -> str:
    """Extract visible text from the first Gemini candidate."""
    candidates = result.get("candidates") if isinstance(result, dict) else []
    candidate = candidates[0] if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict) else {}
    content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    return "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict) and part.get("text")).strip()


def function_tools(tools: Any) -> list[dict[str, Any]]:
    """Translate Responses-style function tools to Gemini declarations."""
    declarations = []
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, dict) or tool.get("type") != "function" or not tool.get("name"):
            continue
        declarations.append({
            "name": str(tool["name"]),
            "description": str(tool.get("description") or ""),
            "parametersJsonSchema": tool.get("parameters") if isinstance(tool.get("parameters"), dict)
            else {"type": "object", "properties": {}},
        })
    return [{"functionDeclarations": declarations}] if declarations else []


def _data_url_part(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str) or not value.startswith("data:"):
        return None
    try:
        header, data = value.split(",", 1)
    except ValueError:
        return None
    return {"inlineData": {"mimeType": header[5:].split(";", 1)[0], "data": data}}


def input_parts(
    value: Any,
    call_names: Mapping[str, str],
    transient_media: Any,
) -> list[dict[str, Any]]:
    """Translate Responses input items to Gemini user parts without side effects."""
    if not isinstance(value, list):
        return []
    names = call_names if isinstance(call_names, Mapping) else {}
    parts: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict) and item.get("role") == "user" and isinstance(item.get("content"), list):
            for content in item["content"]:
                if not isinstance(content, dict):
                    continue
                if content.get("type") == "input_text":
                    parts.append({"text": content.get("text")})
                elif content.get("type") == "input_image":
                    part = _data_url_part(content.get("image_url"))
                    if part:
                        parts.append(part)
                elif content.get("type") == "input_file":
                    part = _data_url_part(content.get("file_data"))
                    if part:
                        parts.append(part)
            continue
        if not isinstance(item, dict) or item.get("type") != "function_call_output":
            continue
        try:
            output = json.loads(item.get("output") or "{}")
        except (TypeError, ValueError):
            output = {"error": "Tool output was not JSON."}
        parts.append({
            "functionResponse": {
                "name": names.get(str(item.get("call_id") or ""), "coach_tool"),
                "response": output if isinstance(output, dict) else {"result": output},
            }
        })
    has_input_media = any(
        "inlineData" in part or "untrusted_fit_raw_base64" in str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict)
    )
    if not has_input_media and isinstance(transient_media, (list, tuple)):
        for image in transient_media:
            if isinstance(image, dict) and image.get("mime") and image.get("data"):
                parts.append({"inlineData": {"mimeType": image["mime"], "data": image["data"]}})
    return parts


def request_payload(
    payload: Mapping[str, Any],
    *,
    model: str,
    contents: list[dict[str, Any]],
    default_max_output_tokens: int,
    default_thinking_level: str,
    json_media_type: str = "application/json",
) -> dict[str, Any]:
    """Build a Gemini generateContent request from a Responses-style payload."""
    request: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": int(payload.get("max_output_tokens") or default_max_output_tokens),
        },
    }
    instructions = str(payload.get("instructions") or "")
    if instructions:
        request["systemInstruction"] = {"parts": [{"text": instructions}]}
    tools = function_tools(payload.get("tools"))
    if tools:
        request["tools"] = tools
        choice = payload.get("tool_choice", "auto")
        config: dict[str, Any] = {"mode": "AUTO"}
        if choice == "none":
            config["mode"] = "NONE"
        elif isinstance(choice, dict) and choice.get("type") == "function":
            config = {"mode": "ANY", "allowedFunctionNames": [str(choice.get("name"))]}
        request["toolConfig"] = {"functionCallingConfig": config}
    text_format = payload.get("text") if isinstance(payload.get("text"), dict) else {}
    format_config = text_format.get("format") if isinstance(text_format.get("format"), dict) else {}
    if format_config.get("type") == "json_schema" and isinstance(format_config.get("schema"), dict):
        request["generationConfig"].update({
            "responseMimeType": json_media_type,
            "responseJsonSchema": format_config["schema"],
        })
    explicit_reasoning = payload.get("reasoning") if isinstance(payload.get("reasoning"), dict) else {}
    thinking_level = str(explicit_reasoning.get("effort") or default_thinking_level).casefold()
    if thinking_level not in {"low", "medium", "high"}:
        thinking_level = str(default_thinking_level).casefold()
    if model.startswith("gemini-3."):
        request["generationConfig"]["thinkingConfig"] = {"thinkingLevel": thinking_level}
    else:
        thinking = {"low": 1024, "medium": 8192, "high": 24576}.get(thinking_level)
        if thinking:
            request["generationConfig"]["thinkingConfig"] = {"thinkingBudget": thinking}
    return request


def _provider_error_payload(raw_body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw_body) if raw_body else None
    except (TypeError, ValueError):
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    return error if isinstance(error, dict) else {}


def _gemini_error_tokens(error: dict[str, Any]) -> str:
    tokens = [str(error.get("status") or "").casefold()]
    for detail in error.get("details") if isinstance(error.get("details"), list) else []:
        if isinstance(detail, dict):
            tokens.extend(str(detail.get(key) or "").casefold() for key in ("reason", "@type"))
    return " ".join(tokens)


def _gemini_error_reason(status: int, searchable: str) -> tuple[str, str]:
    if status in {401, 403} or "permission" in searchable or "unauthenticated" in searchable:
        return "authentication_or_permission", "Der Gemini-Zugang wurde abgelehnt. Bitte API-Schlüssel und Berechtigungen prüfen."
    if status == 429 and "quota" in searchable:
        return "insufficient_quota", "Das Gemini-Kontingent ist aufgebraucht. Bitte Nutzung und Abrechnung im Google-Konto prüfen."
    if status == 429:
        return "rate_limit_exceeded", "Gemini hat das Anfragelimit erreicht. Bitte kurz warten und erneut versuchen."
    if status == 404:
        return "not_found", "Das konfigurierte Gemini-Modell oder der angeforderte Dienst wurde nicht gefunden."
    if status >= 500:
        return "provider_unavailable", "Gemini ist vorübergehend nicht verfügbar. Bitte später erneut versuchen."
    return "http_error", f"Gemini konnte die Anfrage nicht verarbeiten (HTTP {status})."


def error_details(status: int, raw_body: bytes, *, updated_at: str) -> dict[str, Any]:
    """Classify a Gemini failure without retaining provider response content."""
    reason, message = _gemini_error_reason(status, _gemini_error_tokens(_provider_error_payload(raw_body)))
    return {"state": "error", "reason": reason, "message": message, "http_status": status, "updated_at": updated_at}
