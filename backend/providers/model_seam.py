"""Neutral request and answer types between the app and a model provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelStep:
    """A finished tool round: the model's replayable state and its tool results."""

    opaque_state: list[dict[str, Any]]
    tool_results: list[dict[str, str]]


@dataclass
class ModelRequest:
    """What the app asks of a model, independent of the provider's wire format."""

    model: str
    instructions: str = ""
    input: str = ""
    # Provider-safe parts that come with the input; see coach.attachments.
    attachments: list[dict[str, Any]] = field(default_factory=list)
    # Raw images ({"mime", "data" as base64}) read together with the input.
    images: list[dict[str, str]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_choice: str = "auto"
    reasoning_effort: str | None = None
    max_output_tokens: int | None = None
    # The provider keeps this conversation's items; None resends them every time.
    conversation_id: str | None = None
    # A turn keeps nothing at the provider; a one-shot request leaves it to the
    # provider's default when False.
    stateless: bool = True
    # Earlier tool rounds of this turn, resent when nothing is stored remotely.
    steps: list[ModelStep] = field(default_factory=list)
    # One-shot answer: a JSON object, or {"name": ..., "schema": ...} for a schema.
    json_output: bool = False
    output_schema: dict[str, Any] | None = None


@dataclass
class ModelTurn:
    """One model answer: its text, requested tool calls and what to replay next."""

    text: str = ""
    # Each call is {"call_id", "name", "arguments" (JSON text)}.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    opaque_state: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    # completed, max_tokens, incomplete, failed, cancelled; "" when not reported.
    stop_reason: str = ""

    @property
    def incomplete(self) -> bool:
        return self.stop_reason in {"max_tokens", "incomplete"}
