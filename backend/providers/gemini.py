"""Pure Gemini response and tool-schema adapters."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from backend import observability
from backend.errors import COACH_ABORTED_ERROR, GEMINI_API_KEY_ERROR, AppError
from backend.providers import http as provider_http

_STREAMING_EVENT_ERROR = "Gemini hat ein ung\\u00fcltiges Streaming-Ereignis zur\\u00fcckgegeben."
_STREAMING_RESPONSE_TOO_LARGE = "Die Streaming-Antwort von Gemini ist zu\\u00df."
_STREAMING_TIMEOUT = "Gemini hat nicht rechtzeitig geantwortet."
_STREAMING_UNAVAILABLE = "Gemini ist vor\\u00fcbergehend nicht verf\\u00fcgbar."


class GeminiStreamClient:
    """Execute and observe one Gemini GenerateContent SSE request."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        response_timeout_seconds: int,
        max_bytes: int,
        app_version: str,
        json_media_type: str,
        provider_state: Any,
        logger: Any,
        opener: Any = urlopen,
        monotonic: Callable[[], float] = time.perf_counter,
        now: Callable[[], str],
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.response_timeout_seconds = response_timeout_seconds
        self.max_bytes = max_bytes
        self.app_version = app_version
        self.json_media_type = json_media_type
        self.provider_state = provider_state
        self.logger = logger
        self.opener = opener
        self.monotonic = monotonic
        self.now = now

    def stream(
        self,
        model: str,
        payload: Mapping[str, Any],
        on_text_delta: Callable[[str], None],
        *,
        cancel_event: Any = None,
    ) -> dict[str, Any]:
        """Stream one prepared Gemini request and return its raw aggregate."""
        if not self.api_key:
            raise AppError(503, GEMINI_API_KEY_ERROR)
        if not re.fullmatch(r"(?a:[\w.-]{1,128})", str(model or "")):
            raise AppError(400, "Ung\\u00fcltiges Gemini-Modell.")

        body = json.dumps(payload).encode("utf-8")
        endpoint = f"{self.base_url.rstrip('/')}/models/{model}:streamGenerateContent?alt=sse"
        request = Request(
            endpoint,
            data=body,
            headers={
                "Accept": "text/event-stream",
                "Content-Type": self.json_media_type,
                "x-goog-api-key": self.api_key,
                "User-Agent": f"IntervalsCoach/{self.app_version}",
            },
            method="POST",
        )
        parsed_endpoint = urlparse(endpoint)
        context = {
            "service": "gemini",
            "method": "POST",
            "host": observability.safe_url_netloc(parsed_endpoint),
            "path": observability.safe_provider_path(parsed_endpoint.path),
            "timeout_seconds": self.response_timeout_seconds,
            "request_bytes": len(body),
            "query_keys": ["alt"],
        }
        started = self.monotonic()
        self.logger.info(
            "External HTTP request started",
            extra={"event": "external_request_started", "context": context},
        )
        response_bytes = 0
        try:
            self._raise_cancelled(cancel_event)
            stream_result = read_stream_response(
                request,
                timeout=self.response_timeout_seconds,
                max_bytes=self.max_bytes,
                on_text_delta=on_text_delta,
                cancel_event=cancel_event,
                opener=self.opener,
            )
            self._raise_cancelled(cancel_event)
            response_bytes = stream_result.response_bytes
            aggregate = stream_result.aggregate
            if not aggregate.get("candidates"):
                raise AppError(502, "Gemini hat keine Coach-Antwort geliefert.", reason="invalid_response")
            self.provider_state.record_success("gemini", 200)
            self.provider_state.record_usage("gemini", aggregate, "generate_content_stream")
            self.logger.info(
                "External HTTP request completed",
                extra={
                    "event": "external_request_completed",
                    "context": {
                        **context,
                        "status": 200,
                        "duration_ms": round((self.monotonic() - started) * 1000, 1),
                        "response_bytes": response_bytes,
                    },
                },
            )
            return aggregate
        except provider_http.ProviderRequestCancelled as exc:
            raise self._cancelled_error() from exc
        except provider_http.ProviderResponseTooLarge as exc:
            error = AppError(502, _STREAMING_RESPONSE_TOO_LARGE, reason="response_too_large")
            self._record_error(error)
            raise error from exc
        except HTTPError as exc:
            raw_error = provider_http.read_error_body(exc, self.max_bytes)
            details = error_details(int(exc.code), raw_error, updated_at=self.now())
            error = AppError(int(exc.code), details["message"], reason=details["reason"])
            self._record_error(error)
            raise error from exc
        except AppError as exc:
            self._record_error(exc)
            raise
        except TimeoutError as exc:
            if self._cancelled(cancel_event):
                raise self._cancelled_without_status() from exc
            error = AppError(504, _STREAMING_TIMEOUT, reason="provider_timeout")
            self._record_error(error)
            raise error from exc
        except (URLError, OSError, UnicodeDecodeError, ValueError) as exc:
            if self._cancelled(cancel_event):
                raise self._cancelled_without_status() from exc
            error = AppError(503, _STREAMING_UNAVAILABLE, reason="provider_unavailable")
            self._record_error(error)
            raise error from exc

    @staticmethod
    def _cancelled(cancel_event: Any) -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def _raise_cancelled(self, cancel_event: Any) -> None:
        if self._cancelled(cancel_event):
            raise provider_http.ProviderRequestCancelled

    def _cancelled_error(self) -> AppError:
        error = AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")
        self._record_error(error)
        return error

    @staticmethod
    def _cancelled_without_status() -> AppError:
        return AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")

    def _record_error(self, error: AppError) -> None:
        self.provider_state.record_status(
            "gemini",
            state="error",
            reason=error.reason or "request_failed",
            message=error.message,
            http_status=error.status,
        )


class GeminiJsonClient:
    """Own Gemini model validation and one generateContent request."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        response_timeout_seconds: int,
        http_client: provider_http.JsonHttpClient,
        provider_state: Any,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.response_timeout_seconds = response_timeout_seconds
        self.http_client = http_client
        self.provider_state = provider_state

    def generate(
        self,
        model: str,
        payload: Mapping[str, Any],
        *,
        operation: str,
        cancel_event: Any = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise AppError(503, GEMINI_API_KEY_ERROR)
        if not re.fullmatch(r"(?a:[\w.-]{1,128})", str(model or "")):
            raise AppError(400, "Ungültiges Gemini-Modell.")
        try:
            result = self.http_client.request(
                "POST",
                f"{self.base_url}/models/{model}:generateContent",
                payload,
                {"x-goog-api-key": self.api_key},
                timeout=self.response_timeout_seconds,
                service="gemini",
                cancel_event=cancel_event,
            )
        except AppError as exc:
            self.provider_state.record_status(
                "gemini",
                state="error",
                reason=exc.reason or "request_failed",
                message=exc.message,
                http_status=exc.status,
            )
            raise
        if not isinstance(result, dict):
            self.provider_state.record_status(
                "gemini",
                state="error",
                reason="invalid_response",
                message="Gemini hat keine JSON-Antwort geliefert.",
                http_status=502,
            )
            raise AppError(502, "Gemini hat keine gültige Antwort geliefert.", reason="invalid_response")
        self.provider_state.record_success("gemini", None)
        self.provider_state.record_usage("gemini", result, operation)
        return result


@dataclass(frozen=True)
class StreamReadResult:
    aggregate: dict[str, Any]
    response_bytes: int


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


def read_stream_response(
    request: Any,
    *,
    timeout: int,
    max_bytes: int,
    on_text_delta: Callable[[str], None],
    cancel_event: Any = None,
    opener: Any = urlopen,
) -> StreamReadResult:
    """Read and aggregate a Gemini SSE response."""
    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise provider_http.ProviderRequestCancelled

    accumulator = StreamAccumulator(on_text_delta)
    response_bytes = 0
    data_lines: list[str] = []

    def flush_event() -> None:
        nonlocal data_lines
        event_lines = data_lines
        data_lines = []
        accumulator.consume_data_lines(event_lines)

    check_cancelled()
    with provider_http.open_interruptibly(request, timeout, cancel_event, opener=opener) as response:
        if cancel_event is not None:
            cancel_event._provider_response = response
        try:
            for raw_line in response:
                check_cancelled()
                response_bytes += len(raw_line)
                if response_bytes > max_bytes:
                    raise provider_http.ProviderResponseTooLarge("provider response exceeds configured size limit")
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if not line:
                    flush_event()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
            flush_event()
            check_cancelled()
        finally:
            missing = object()
            if cancel_event is not None and getattr(cancel_event, "_provider_response", missing) is response:
                delattr(cancel_event, "_provider_response")
    return StreamReadResult(accumulator.aggregate, response_bytes)


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


def _user_content_parts(content: list[Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "input_text":
            parts.append({"text": item.get("text")})
        elif item_type == "input_image":
            part = _data_url_part(item.get("image_url"))
            if part:
                parts.append(part)
        elif item_type == "input_file":
            part = _data_url_part(item.get("file_data"))
            if part:
                parts.append(part)
    return parts


def _function_response_part(item: dict[str, Any], call_names: Mapping[str, str]) -> dict[str, Any]:
    try:
        output = json.loads(item.get("output") or "{}")
    except (TypeError, ValueError):
        output = {"error": "Tool output was not JSON."}
    return {
        "functionResponse": {
            "name": call_names.get(str(item.get("call_id") or ""), "coach_tool"),
            "response": output if isinstance(output, dict) else {"result": output},
        }
    }


def _input_item_parts(item: Any, call_names: Mapping[str, str]) -> list[dict[str, Any]]:
    if isinstance(item, dict) and item.get("role") == "user" and isinstance(item.get("content"), list):
        return _user_content_parts(item["content"])
    if isinstance(item, dict) and item.get("type") == "function_call_output":
        return [_function_response_part(item, call_names)]
    return []


def _has_input_media(parts: list[dict[str, Any]]) -> bool:
    return any(
        "inlineData" in part or "untrusted_fit_raw_base64" in str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict)
    )


def _transient_media_parts(transient_media: Any) -> list[dict[str, Any]]:
    if not isinstance(transient_media, (list, tuple)):
        return []
    return [
        {"inlineData": {"mimeType": image["mime"], "data": image["data"]}}
        for image in transient_media
        if isinstance(image, dict) and image.get("mime") and image.get("data")
    ]


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
        parts.extend(_input_item_parts(item, names))
    if not _has_input_media(parts):
        parts.extend(_transient_media_parts(transient_media))
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
    request.update(_tool_request_parts(payload))
    request["generationConfig"].update(_response_schema_config(payload, json_media_type))
    thinking_config = _thinking_config(payload, model, default_thinking_level)
    if thinking_config:
        request["generationConfig"]["thinkingConfig"] = thinking_config
    return request


def _tool_request_parts(payload: Mapping[str, Any]) -> dict[str, Any]:
    tools = function_tools(payload.get("tools"))
    if not tools:
        return {}
    choice = payload.get("tool_choice", "auto")
    config: dict[str, Any] = {"mode": "AUTO"}
    if choice == "none":
        config["mode"] = "NONE"
    elif isinstance(choice, dict) and choice.get("type") == "function":
        config = {"mode": "ANY", "allowedFunctionNames": [str(choice.get("name"))]}
    return {"tools": tools, "toolConfig": {"functionCallingConfig": config}}


def _response_schema_config(payload: Mapping[str, Any], json_media_type: str) -> dict[str, Any]:
    text_format = payload.get("text") if isinstance(payload.get("text"), dict) else {}
    format_config = text_format.get("format") if isinstance(text_format.get("format"), dict) else {}
    if format_config.get("type") == "json_schema" and isinstance(format_config.get("schema"), dict):
        return {
            "responseMimeType": json_media_type,
            "responseJsonSchema": format_config["schema"],
        }
    return {}


def _thinking_config(payload: Mapping[str, Any], model: str, default_thinking_level: str) -> dict[str, Any]:
    explicit_reasoning = payload.get("reasoning") if isinstance(payload.get("reasoning"), dict) else {}
    thinking_level = str(explicit_reasoning.get("effort") or default_thinking_level).casefold()
    if thinking_level not in {"low", "medium", "high"}:
        thinking_level = str(default_thinking_level).casefold()
    if model.startswith("gemini-3."):
        return {"thinkingLevel": thinking_level}
    thinking = {"low": 1024, "medium": 8192, "high": 24576}.get(thinking_level)
    return {"thinkingBudget": thinking} if thinking else {}


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
