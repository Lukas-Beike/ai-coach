"""Stable Coach tool metadata derived from the executable schemas and tool specs."""

from __future__ import annotations

from typing import Any

from backend.coach.tool_specs import (
    CONDITIONAL_REMOTE_WRITE,
    CONTROL,
    OPERATION_LABELS,
    PROVIDER_READ_JOB,
    READ,
    REMOTE_WRITE,
    SPECS,
)

# Authorization and receipt class per effect class.
_EFFECT_POLICY = {
    READ: ("none", "read_only"),
    CONTROL: ("pending_request", "turn_state"),
    PROVIDER_READ_JOB: ("request_scope", "durable_effect"),
    REMOTE_WRITE: ("request_scope+athlete_approval", "durable_effect"),
    CONDITIONAL_REMOTE_WRITE: (
        "request_scope+athlete_approval_when_remote",
        "durable_effect",
    ),
}
_LOCAL_WRITE_POLICY = ("request_scope", "durable_effect")


def build_capability_catalog(
    structured_tools: list[dict[str, Any]],
    dialogue_tools: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    canonical_schemas = {tool["name"]: tool for tool in structured_tools}
    dialogue_schemas = {tool["name"]: tool for tool in dialogue_tools}
    schemas = {**canonical_schemas, **dialogue_schemas}
    catalog = {}
    for name, schema in schemas.items():
        spec = SPECS.get(name)
        if spec is None:
            raise ValueError(f"Coach tool has no capability owner: {name}")
        authorization, receipt = _EFFECT_POLICY.get(spec.effect, _LOCAL_WRITE_POLICY)
        if receipt == "durable_effect" and name not in OPERATION_LABELS:
            raise ValueError(f"Coach mutation has no receipt label: {name}")
        catalog[name] = {
            "name": name,
            "schema": schema,
            "owner": spec.owner,
            "effect": spec.effect,
            "authorization": authorization,
            "receipt": receipt,
            "surface": _tool_surface(name, canonical_schemas, dialogue_schemas),
        }
    return catalog


def _tool_surface(
    name: str,
    canonical_schemas: dict[str, Any],
    dialogue_schemas: dict[str, Any],
) -> str:
    in_canonical = name in canonical_schemas
    in_dialogue = name in dialogue_schemas
    if in_canonical and in_dialogue:
        return "canonical_and_dialogue"
    return "canonical_only" if in_canonical else "dialogue_only"
