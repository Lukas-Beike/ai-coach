"""The newest Claude model per family, with a step back to the last one that worked.

The athlete picks a family (Opus, Sonnet, Haiku); the app uses its newest model
from the Models API. When a newly resolved model rejects requests, the family
keeps using its last model that answered and reports the rejected one. This is
a model choice within Claude, never a switch to another provider.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from backend.errors import AppError

FAMILIES = ("opus", "sonnet", "haiku")
# Used until the Models API has answered once (issue #2355, 2026-11-12).
DEFAULT_MODELS = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "haiku": "claude-haiku-5-5",
}
# The model setting names a family; the request resolves it to a model id.
SETTING_FAMILIES = {f"claude-{family}": family for family in FAMILIES}
REFRESH_AFTER = timedelta(hours=24)
# After a failed listing, the next attempt waits this long instead of a day.
RETRY_AFTER = timedelta(hours=1)
# A family model id: no dated snapshot, no -fast or other deployment suffix.
_MODEL_ID = re.compile(r"^claude-(opus|sonnet|haiku)-\d{1,2}(?:-\d{1,2})?$")
# A newly resolved model that rejects the request shape or is unknown.
_REJECTION_STATUSES = frozenset({400, 404})


def setting_family(model: str | None) -> str | None:
    """The Claude family a model setting selects, or None for an OpenAI model."""
    return SETTING_FAMILIES.get(str(model or ""))


def newest_by_family(models: Any) -> dict[str, str]:
    """The newest model id of each family in a Models API page."""
    entries = models.get("data") if isinstance(models, Mapping) else None
    newest: dict[str, tuple[str, str]] = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, Mapping):
            continue
        model_id = str(entry.get("id") or "")
        match = _MODEL_ID.match(model_id)
        if not match:
            continue
        created = str(entry.get("created_at") or "")
        family = match.group(1)
        if family not in newest or (created, model_id) > newest[family]:
            newest[family] = (created, model_id)
    return {family: model_id for family, (_, model_id) in newest.items()}


def family_state(state: Any) -> dict[str, dict[str, str]]:
    """The stored newest, working and rejected model per family, sanitized."""
    stored = state if isinstance(state, Mapping) else {}
    return {
        key: {
            family: str(value[family])
            for family in FAMILIES
            if isinstance(value := stored.get(key), Mapping)
            and _MODEL_ID.match(str(value.get(family) or ""))
        }
        for key in ("newest", "working", "rejected")
    }


class ClaudeModelResolver:
    """Resolve, confirm and reject the model of a Claude family."""

    def __init__(
        self,
        *,
        read_state: Callable[[], Any],
        write_state: Callable[[dict[str, Any]], None],
        list_models: Callable[[], Any],
        now: Callable[[], datetime],
        logger: Any,
    ) -> None:
        self._read = read_state
        self._write = write_state
        self._list_models = list_models
        self._now = now
        self._logger = logger
        # One read-modify-write at a time, so a slow listing loses no mark.
        self._lock = threading.Lock()

    def _state(self) -> dict[str, Any]:
        raw = self._read()
        state: dict[str, Any] = dict(family_state(raw))
        fetched = raw.get("fetched_at") if isinstance(raw, Mapping) else None
        state["fetched_at"] = fetched if isinstance(fetched, str) else ""
        return state

    def _refreshed(self, state: dict[str, Any]) -> dict[str, Any]:
        try:
            fetched = datetime.fromisoformat(state["fetched_at"])
        except ValueError:
            fetched = None
        if fetched is not None and self._now() - fetched < REFRESH_AFTER:
            return state
        try:
            newest = newest_by_family(self._list_models())
        except AppError as error:
            # A failed listing keeps the last known models and retries later.
            self._logger.warning(
                "Claude model listing failed",
                extra={
                    "event": "anthropic_models_failed",
                    "context": {"reason": error.reason or "request_failed"},
                },
            )
            retry_at = self._now() - REFRESH_AFTER + RETRY_AFTER
            state = {**state, "fetched_at": retry_at.isoformat()}
            self._write(state)
            return state
        state = {
            **state,
            "newest": {**state["newest"], **newest},
            "fetched_at": self._now().isoformat(),
        }
        self._write(state)
        return state

    def resolve(self, family: str) -> str:
        """The model to use now: the newest one unless it was rejected."""
        with self._lock:
            state = self._refreshed(self._state())
        newest = state["newest"].get(family) or DEFAULT_MODELS[family]
        if state["rejected"].get(family) == newest:
            return state["working"].get(family) or DEFAULT_MODELS[family]
        return newest

    def status(self) -> dict[str, dict[str, str | None]]:
        """Per family: the model in use and a rejected newer model, without I/O."""
        state = self._state()
        result: dict[str, dict[str, str | None]] = {}
        for family in FAMILIES:
            newest = state["newest"].get(family) or DEFAULT_MODELS[family]
            rejected = state["rejected"].get(family)
            in_use = (
                state["working"].get(family) or DEFAULT_MODELS[family]
                if rejected == newest
                else newest
            )
            result[family] = {
                "model": in_use,
                "rejected": rejected if rejected == newest else None,
            }
        return result

    def _mark(self, key: str, family: str, model: str) -> None:
        with self._lock:
            state = self._state()
            if state[key].get(family) == model:
                return
            state[key] = {**state[key], family: model}
            self._write(state)

    def call(self, family: str, send: Callable[[str], Any]) -> Any:
        """Send with the resolved model; step back once if a new model is rejected."""
        model = self.resolve(family)
        try:
            result = send(model)
        except AppError as error:
            working = self._state()["working"].get(family)
            if (
                error.upstream_status not in _REJECTION_STATUSES
                or not working
                or working == model
            ):
                raise
            result = send(working)
            # Only a request the last model answered proves the new one is at fault.
            self._mark("rejected", family, model)
            self._logger.warning(
                "Claude model rejected; using the last working model",
                extra={
                    "event": "anthropic_model_rejected",
                    "context": {"rejected": model, "model": working},
                },
            )
            return result
        self._mark("working", family, model)
        return result
