"""Backward-compatible OpenAI Responses provider facade."""

from __future__ import annotations

import time

from backend.providers import http as provider_http
from backend.providers.http import urlopen
from backend.providers.openai_errors import (
    OPENAI_RATE_LIMIT_HEADERS,
    error_details,
    error_diagnostic_details,
    rate_limit_snapshot,
    retry_after_seconds,
    safe_log_reason,
)
from backend.providers.openai_events import (
    StreamReadResult,
    StreamReadState,
    consume_sse_event,
    read_stream_response,
    request_stream_response,
)
from backend.providers.openai_requests import (
    OpenAIResponsesClient,
    endpoint,
    poll_background_response,
    request_with_conversation_retry,
    response_id,
    responses_payload,
)
from backend.providers.openai_responses import (
    OpenAIResponseFailure,
    response_diagnostic_details,
    response_failure_reason,
    response_text,
    validate_response,
)
from backend.providers.openai_stream import (
    OpenAIStreamClient,
    OpenAIStreamConfig,
    OpenAIStreamTelemetry,
)

__all__ = [
    "OPENAI_RATE_LIMIT_HEADERS",
    "OpenAIResponseFailure",
    "OpenAIResponsesClient",
    "OpenAIStreamClient",
    "OpenAIStreamConfig",
    "OpenAIStreamTelemetry",
    "StreamReadResult",
    "StreamReadState",
    "consume_sse_event",
    "endpoint",
    "error_details",
    "error_diagnostic_details",
    "poll_background_response",
    "provider_http",
    "rate_limit_snapshot",
    "read_stream_response",
    "request_stream_response",
    "request_with_conversation_retry",
    "response_diagnostic_details",
    "response_failure_reason",
    "response_id",
    "response_text",
    "responses_payload",
    "retry_after_seconds",
    "safe_log_reason",
    "time",
    "urlopen",
    "validate_response",
]
