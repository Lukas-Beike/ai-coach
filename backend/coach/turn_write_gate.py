"""Bind the pure write gate to one Coach turn and its tool calls."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from backend.coach.context_selection import select_coach_context
from backend.coach.write_gate import (
    TOOL_DOMAIN,
    UNGATED_TOOLS,
    GateDecision,
    ImpactClassifier,
    ImpactVerdict,
    PendingOrigin,
    TurnGateState,
    build_turn_authority,
    check_write,
)

_RETRYABLE_PENDING_STATUSES = frozenset({"needs_clarification", "failed"})
_NOT_PERFORMED = (
    "Nothing was saved or sent. Do not repeat this write call and do not claim it "
    "happened."
)
_DENIAL_GUIDANCE = {
    "impact_not_confirmed": (
        "Deleting or archiving records, replacing or committing a whole plan, and "
        "changing many records at once need the athlete's explicit request for "
        "exactly that. Ask one concise question with clarify_coach_request that "
        "names what would be deleted, replaced or changed."
    ),
    "approval_not_confirmed": (
        "The athlete's message does not ask to apply the previewed plan change. "
        "Do not apply it. Only the athlete's very next message after a preview "
        "can approve it, so create a fresh preview with preview_adaptive_replan "
        "now and ask once, in your answer, whether to apply it."
    ),
    "remote_not_requested": (
        "The athlete's message does not ask to write to Intervals.icu. Keep the "
        "change local and offer the sync instead."
    ),
    "cap_exceeded": (
        "This turn already made the maximum number of changes. Tell the athlete "
        "what was saved so far and offer to continue in a new message."
    ),
}
_DEFAULT_GUIDANCE = (
    "This change is not available in this turn. Answer without saving and say "
    "that nothing was changed."
)


def _previous_assistant_text(context: Mapping[str, Any]) -> str:
    """Return the directly preceding chat message, only when it is the Coach's."""
    current_id = context.get("current_user_message_id")
    if not isinstance(current_id, int):
        return ""
    earlier = [
        item
        for item in context.get("messages") or []
        if isinstance(item, dict)
        and isinstance(item.get("id"), int)
        and item["id"] < current_id
    ]
    previous = max(earlier, key=lambda item: item["id"], default=None)
    if previous is None or previous.get("role") != "assistant":
        return ""
    return str(previous.get("content") or "")


def _pending_origin(
    message: str, context: Mapping[str, Any], current_id: int
) -> PendingOrigin | None:
    """Let an explicit retry or answer inherit the athlete's original request."""
    pending = context.get("pending_request")
    if (
        not isinstance(pending, dict)
        or pending.get("status") not in _RETRYABLE_PENDING_STATUSES
        or not select_coach_context(message, dict(context)).retain_pending_request
    ):
        return None
    source_ids = pending.get("source_message_ids")
    wanted = {
        value
        for value in (source_ids if isinstance(source_ids, list) else [])
        if isinstance(value, int)
    } - {current_id}
    origins = [
        item
        for item in context.get("messages") or []
        if isinstance(item, dict)
        and item.get("role") == "user"
        and item.get("id") in wanted
    ]
    if not origins:
        return None
    return PendingOrigin(
        origin_message_id=max(item["id"] for item in origins),
        origin_text="\n".join(str(item.get("content") or "") for item in origins),
    )


class CoachTurnWriteGate:
    """Decide every non-read tool call of one turn; owns the per-turn counters."""

    def __init__(
        self,
        *,
        message: str,
        context: Mapping[str, Any],
        model: str | None,
        command_receipts: list[dict[str, Any]],
        read_only_tools: frozenset[str],
        classifier_factory: Callable[[str], ImpactClassifier],
        logger: logging.Logger,
    ) -> None:
        self._message = message
        self._previous = _previous_assistant_text(context)
        current_id = context.get("current_user_message_id")
        self._authority = build_turn_authority(
            current_id if isinstance(current_id, int) else 0,
            message,
            self._previous,
            _pending_origin(
                message, context, current_id if isinstance(current_id, int) else 0
            ),
        )
        # A resumed turn already spent part of its write and bulk budget.
        writes = [
            entry for entry in command_receipts if entry.get("tool") in TOOL_DOMAIN
        ]
        self._state = TurnGateState(
            writes_count=len(writes),
            records_count=sum(
                len(changes)
                for entry in writes
                if isinstance(changes := entry.get("changes"), list)
            ),
        )
        self._model = model
        self._read_only_tools = read_only_tools
        self._classifier_factory = classifier_factory
        self._classifier: ImpactClassifier | None = None
        self._logger = logger

    def _classify(
        self, current_text: str, previous_text: str, origin_text: str
    ) -> ImpactVerdict:
        if not self._model:
            raise LookupError("no Coach model for the impact classifier")
        if self._classifier is None:
            self._classifier = self._classifier_factory(self._model)
        return self._classifier(current_text, previous_text, origin_text)

    def denial(
        self, tool_name: str, arguments: Mapping[str, Any] | None
    ) -> dict[str, Any] | None:
        """Return the structured not-performed result, or None when allowed."""
        if tool_name in self._read_only_tools:
            return None
        decision = check_write(
            tool_name,
            self._authority,
            state=self._state,
            classifier=self._classify,
            current_text=self._message,
            previous_assistant_text=self._previous,
            arguments=arguments,
        )
        if decision.allowed:
            return None
        self._log(tool_name, decision)
        return {
            "ok": False,
            "status": "not_performed",
            "reason": "write_cap_exceeded"
            if decision.reason == "cap_exceeded"
            else "write_not_authorized",
            "gate_reason": decision.reason,
            "message": f"{_NOT_PERFORMED} "
            + _DENIAL_GUIDANCE.get(decision.reason, _DEFAULT_GUIDANCE),
        }

    def _log(self, tool_name: str, decision: GateDecision) -> None:
        self._logger.warning(
            "Coach write denied",
            extra={
                "event": "coach_write_denied",
                "context": {
                    "tool": tool_name
                    if tool_name in TOOL_DOMAIN or tool_name in UNGATED_TOOLS
                    else "unknown",
                    "domain": decision.domain,
                    "reason": decision.reason,
                },
            },
        )


class CoachWriteGateService:
    """Open one write gate per Coach turn with injected provider access."""

    def __init__(
        self,
        read_only_tools: frozenset[str],
        classifier_factory: Callable[[str], ImpactClassifier],
        logger: logging.Logger,
    ) -> None:
        self._read_only_tools = read_only_tools
        self._classifier_factory = classifier_factory
        self._logger = logger

    def open_turn(
        self,
        *,
        message: str,
        context: Mapping[str, Any],
        model: str | None,
        command_receipts: list[dict[str, Any]],
    ) -> CoachTurnWriteGate:
        return CoachTurnWriteGate(
            message=message,
            context=context,
            model=model,
            command_receipts=command_receipts,
            read_only_tools=self._read_only_tools,
            classifier_factory=self._classifier_factory,
            logger=self._logger,
        )
