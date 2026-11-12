"""Anthropic Messages API transport constants and request headers."""

from __future__ import annotations

# The API version every Claude request sends.
ANTHROPIC_VERSION = "2026-10-21"
CLAUDE_MODELS_PATH = "/v1/models"


def claude_headers(api_key: str) -> dict[str, str]:
    """The authentication and version headers of one Claude request."""
    return {"x-api-key": api_key.strip(), "anthropic-version": ANTHROPIC_VERSION}
