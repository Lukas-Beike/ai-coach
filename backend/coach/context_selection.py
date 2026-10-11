"""Deterministic request projections; selection is never authorization."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix

CONTEXT_SECTIONS = frozenset(
    {
        "durable_profile",
        "target_competitions",
        "training_plans",
        "local_feedback",
        "activity_feedback",
        "planning",
        "local_planned_workouts",
        "calendar",
        "external_calendar",
        "intervals",
        "current_performance",
        "garmin",
        "weather",
        "daily_planning_context",
        "source_policy",
    }
)
BASE_SECTIONS = frozenset(
    {
        "durable_profile",
        "target_competitions",
        "local_feedback",
        "activity_feedback",
        "local_planned_workouts",
        "intervals",
        "current_performance",
        "daily_planning_context",
        "source_policy",
    }
)
PROFILE_KEYWORDS = (
    (
        "provider_refresh_or_sync",
        r"sync|synchron|refresh|aktualis|neu laden|latest data|current data",
    ),
    (
        "plan_editing",
        r"verschieb|löschen|loeschen|archivier|restore|delete|move|ändern|aender|anpass|adjust|undo|rückgängig",
    ),
    (
        "weekly_planning",
        r"plan|woche|week|kalender|calendar|schedule|bibliothek|library|template|vorlage",
    ),
    ("competition_preparation", r"wettkampf|rennen|race|competition|marathon"),
    (
        "profile_or_checkin",
        r"check.?in|ruhepuls|gewicht|profil|gegessen|mittag|frühstück|fruehstueck|abendessen|kcal|snack|\bate\b|calorie|kalorie|nutrition|ernährung|ernaehrung|mahlzeit|befinden",
    ),
    (
        "activity_analysis",
        r"aktivität|aktivitaet|activity|analyse|analy[sz]|einheit|session|workout",
    ),
    ("today_training", r"heute|morgen|today|tomorrow|wetter|weather"),
)
CONTINUATION_PATTERN = (
    r"^\s*(?:bitte\s+|please\s+)?"
    r"(?:ja|yes|ok|okay|mach(?:\s+(?:das|es|den\s+plan))?|plan\s+fortsetzen"
    r"|do\s+it|that's\s+it|weiter|fortsetzen|continue)"
    r"(?:\s+(?:bitte|please|das|es|so|trotzdem|weiter|mach|do|it))*[.!?,\s]*$"
)
RETRY_PATTERN = (
    r"^\s*(?:bitte\s+|please\s+)?"
    r"(?:nochmal|noch\s+einmal|erneut|retry|wiederholen|versuch(?:\s+es)?|try(?:\s+it)?)"
    r"(?:\s+(?:nochmal|noch|einmal|erneut|again|versuchen|bitte|please))*[.!?,\s]*$"
)
PRONOUN_PATTERN = r"\b(?:das|diese|diesen|that|those|it)\b"
CLARIFICATION_ANSWER_PATTERN = (
    r"^\s*(?:(?:die|der|das|the)\s+(?:erste|zweite|dritte|first|second|third)"
    r"|(?:(?:auf|am|on)\s+)?(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag"
    r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday))"
    r"[.!?,\s]*$"
)


def _domain_of_profiles(profiles: set[str]) -> str | None:
    profiles = profiles - {"today_training"} if len(profiles) > 1 else profiles
    if not profiles:
        return None
    if profiles <= {"profile_or_checkin"}:
        return "nutrition_or_profile"
    if profiles <= {"provider_refresh_or_sync"}:
        return "sync"
    return "training"


def infer_coach_domain(
    text: str = "",
    *,
    tools: Sequence[str] | None = None,
) -> str | None:
    if tools:
        for t in tools:
            if any(sub in t for sub in ("nutrition", "checkin", "profile")):
                return "nutrition_or_profile"
        for t in tools:
            if any(sub in t for sub in ("sync", "refresh")):
                return "sync"
        return "training"

    normalized = text.casefold()
    matched = {
        name for name, pattern in PROFILE_KEYWORDS if re.search(pattern, normalized)
    }
    return _domain_of_profiles(matched)


@dataclass(frozen=True)
class CoachContextSelection:
    name: str
    sections: frozenset[str] = CONTEXT_SECTIONS
    horizon_days: int | None = None
    activity_limit: int = 5
    include_library: bool = True
    retain_dialogue: bool = False
    retain_pending_request: bool = True

    def project(self, context: dict[str, Any], local_date: str = "") -> dict[str, Any]:
        result = {key: value for key, value in context.items() if key in self.sections}
        if self.horizon_days is None:
            return result
        try:
            today = date.fromisoformat(local_date)
        except ValueError:
            return result
        for key in ("local_planned_workouts", "calendar", "daily_planning_context"):
            if key in result:
                result[key] = self.dated_items(result[key], today)
        intervals = result.get("intervals")
        if isinstance(intervals, dict):
            intervals = dict(intervals)
            intervals.pop("planned_workouts", None)
            recent = intervals.get("recent_activities_by_sport")
            if isinstance(recent, dict):
                intervals["recent_activities_by_sport"] = {
                    sport: rows[: self.activity_limit]
                    if isinstance(rows, list)
                    else rows
                    for sport, rows in recent.items()
                }
            result["intervals"] = intervals
        performance = result.get("current_performance")
        if isinstance(performance, dict) and self.name not in {
            "activity_analysis",
            "attachment_analysis",
        }:
            result["current_performance"] = {
                key: value
                for key, value in performance.items()
                if key not in {"comparisons", "activity_validation"}
            }
        return result

    def dated_items(self, items: Any, today: date) -> Any:
        if not isinstance(items, list) or self.horizon_days is None:
            return items
        first = (today - timedelta(days=2)).isoformat()
        last = (today + timedelta(days=self.horizon_days)).isoformat()
        return [
            item
            for item in items
            if not isinstance(item, dict)
            or not (
                value := iso_date_prefix(
                    str(
                        item.get("date")
                        or item.get("event_date")
                        or item.get("start_date_local")
                        or ""
                    )
                )
            )
            or first <= value <= last
        ]


def select_coach_context(
    message: str,
    dialogue: dict[str, Any],
    *,
    attachments: bool = False,
    has_receipts: bool = False,
) -> CoachContextSelection:
    normalized = message.casefold()
    continuation = bool(re.search(CONTINUATION_PATTERN, normalized))
    retry = bool(re.search(RETRY_PATTERN, normalized))
    pronoun = bool(re.search(PRONOUN_PATTERN, normalized))
    matched = [
        name for name, pattern in PROFILE_KEYWORDS if re.search(pattern, normalized)
    ]
    pending = dialogue.get("pending_request")
    pending_status = pending.get("status") if isinstance(pending, dict) else None
    pending_domain = _pending_domain(pending)
    message_domain = _domain_of_profiles(set(matched))
    is_pending_active = _pending_request_is_active(
        pending,
        pending_status,
        pending_domain,
        message_domain,
        normalized,
        retry,
        continuation,
    )

    if _needs_fallback_context(
        is_pending_active, continuation, pronoun, matched, normalized
    ):
        return CoachContextSelection(
            "fallback", retain_pending_request=is_pending_active
        )
    name = matched[0] if matched else "general_coaching"
    sections = set(BASE_SECTIONS)
    planning = bool(
        set(matched) & {"weekly_planning", "plan_editing", "competition_preparation"}
    )
    if planning:
        sections.update({"planning", "training_plans"})
    if "provider_refresh_or_sync" in matched:
        return CoachContextSelection(name, retain_pending_request=is_pending_active)
    if _requires_full_time_context(planning, normalized):
        return CoachContextSelection(name, retain_pending_request=is_pending_active)
    if attachments:
        name = "attachment_analysis"
    return CoachContextSelection(
        name,
        frozenset(sections),
        14 if planning else 3,
        5 if planning or "activity_analysis" in matched else 1,
        planning,
        retain_dialogue=bool(continuation or pronoun or has_receipts),
        retain_pending_request=is_pending_active,
    )


def _pending_domain(pending: object) -> str | None:
    if not isinstance(pending, dict):
        return None
    domain = pending.get("domain")
    if domain:
        return domain
    pending_text = (
        f"{pending.get('summary', '')} {pending.get('question', '')}".casefold()
    )
    matched = {
        name for name, pattern in PROFILE_KEYWORDS if re.search(pattern, pending_text)
    }
    return _domain_of_profiles(matched)


def _pending_request_is_active(
    pending: object,
    status: object,
    pending_domain: str | None,
    message_domain: str | None,
    normalized: str,
    retry: bool,
    continuation: bool,
) -> bool:
    if not isinstance(pending, dict):
        return False
    if status not in {"failed", "needs_clarification"}:
        return True
    if pending_domain and message_domain and pending_domain != message_domain:
        return False
    if status == "failed":
        return bool(retry or continuation)
    return bool(
        continuation
        or retry
        or (pending_domain is not None and message_domain == pending_domain)
        or re.search(CLARIFICATION_ANSWER_PATTERN, normalized)
        or _is_concise_clarification_answer(pending, normalized, message_domain)
    )


def _is_concise_clarification_answer(
    pending: dict[str, Any], normalized: str, message_domain: str | None
) -> bool:
    question = pending.get("question")
    return bool(
        isinstance(question, str)
        and question.strip()
        and normalized.strip()
        and "?" not in normalized
        and len(normalized.split()) <= 3
        and message_domain is None
    )


def _needs_fallback_context(
    pending_active: bool,
    continuation: bool,
    pronoun: bool,
    matched: list[str],
    normalized: str,
) -> bool:
    ambiguous_continuation = continuation and (
        not matched or len(normalized.split()) <= 3
    )
    multiple_topics = len(set(matched) - {"today_training"}) > 1
    return pending_active or (
        (continuation or pronoun) and (ambiguous_continuation or multiple_topics)
    )


def _requires_full_time_context(planning: bool, normalized: str) -> bool:
    if re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.", normalized):
        return True
    return planning and any(
        re.search(pattern, normalized)
        for pattern in (
            r"monat|month|jahr|year|saison|season",
            r"\b(?:wochen|weeks|tage|days)\b",
        )
    )


def compact_coach_dialogue(
    context: dict[str, Any], selection: CoachContextSelection
) -> dict[str, Any]:
    result = dict(context)
    retain_history = selection.horizon_days is None or selection.retain_dialogue
    messages = context.get("messages")
    if isinstance(messages, list):
        selected = messages if retain_history else messages[-8:]
        current_id = context.get("current_user_message_id")
        result["messages"] = [
            item
            for item in selected
            if not isinstance(item, dict)
            or current_id is None
            or item.get("id") != current_id
            or item.get("role") != "user"
        ]
    results = context.get("confirmed_results")
    if isinstance(results, list) and not retain_history:
        result["confirmed_results"] = results[:3]
    pending = result.get("pending_request")
    if (
        isinstance(pending, dict)
        and pending.get("status") in {"failed", "needs_clarification"}
        and not selection.retain_pending_request
    ):
        result["pending_request"] = None
    return result
