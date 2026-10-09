"""OpenAI-specific upstream metadata classification for the shared transport."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.providers.openai_errors import error_details

__all__ = ["OpenAIErrorClassifier"]


class OpenAIErrorClassifier:
    def __init__(self, provider_state: Callable[[], Any], now: Callable[[], str]):
        self._provider_state = provider_state
        self._now = now

    def cache_key(self) -> Any:
        return self._provider_state()

    def __call__(
        self,
        service: str | None,
        status: int,
        raw_body: bytes,
        headers: Any,
    ) -> dict[str, Any] | None:
        if service != "openai":
            return None
        state = self._provider_state()
        state.record_rate_limits(headers)
        details = error_details(status, raw_body, headers, updated_at=self._now())
        state.record_status(
            "openai",
            state=details.get("state"),
            reason=details.get("reason"),
            message=details.get("message"),
            http_status=details.get("http_status"),
            provider_error_code=details.get("provider_error_code"),
        )
        return details

    def on_network_error(self, service: str | None) -> None:
        if service == "openai":
            self._provider_state().record_status(
                "openai",
                state="error",
                reason="network_error",
                message="OpenAI ist nicht erreichbar. Bitte Netzwerkverbindung pruefen und spaeter erneut versuchen.",
            )

    def on_client_error(self, service: str | None) -> None:
        if service == "openai":
            self._provider_state().record_status(
                "openai",
                state="error",
                reason="client_error",
                message="Die OpenAI-Antwort konnte nicht verarbeitet werden. Bitte spaeter erneut versuchen.",
            )

    def on_success(self, service: str | None, response: Any) -> None:
        if service == "openai":
            state = self._provider_state()
            state.record_rate_limits(response.headers)
            state.record_success("openai", response.status)
