"""Deterministic request projections; selection is never authorization."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.vocabulary import ProviderId

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
        "activities",
        "current_performance",
        "recovery",
        "weather",
        "daily_planning_context",
        "nutrition_products",
        "source_policy",
    }
)
# Saved products ride along only when the message reports food or drink.
FULL_SECTIONS = CONTEXT_SECTIONS - {"nutrition_products"}
BASE_SECTIONS = frozenset(
    {
        "durable_profile",
        "target_competitions",
        "local_feedback",
        "activity_feedback",
        "local_planned_workouts",
        "activities",
        "current_performance",
        "daily_planning_context",
        "source_policy",
    }
)
# A vague follow-up gets the stable core plus the plan sections. Time-bound and
# external sections (calendar, external calendar, weather, recovery) are loaded on
# demand through read_coach_context instead of riding along on every "ok".
FALLBACK_SECTIONS = BASE_SECTIONS | {"planning", "training_plans"}
# Provider-named section names from before the domain grouping. They stay accepted
# on input (tool arguments, persisted selections) and resolve to one canonical name.
SECTION_ALIASES: Mapping[str, str] = {
    ProviderId.INTERVALS.value: "activities",
    ProviderId.GARMIN.value: "recovery",
}


def canonical_section(name: str) -> str:
    """Return the canonical section name; unknown names are returned unchanged."""
    return SECTION_ALIASES.get(name, name)


WEATHER_PATTERN = (
    r"wetter|weather|\b(?:regen|regnet|regnen|regnerisch|rain\w*)\b|forecast|vorhersage"
)
DAY_PATTERN = (
    r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag"
    r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday|wochenende|weekend"
)
# "letzte Woche" alone is a past-week reference, not a plan request; it only
# counts as planning when the message also contains a planning verb.
PAST_WEEK_PATTERN = (
    r"\b(?:vor)?(?:letzte[rsmn]?|vergangene[rsmn]?)\s+wochen?\b|\blast\s+weeks?\b"
)
PLANNING_VERB_PATTERN = r"\b(?:plan\w*|erstell\w*|schedul\w*|passe\b.*\ban\b)"
HISTORY_PATTERN = (
    r"\b(?:letzte[nrs]?|vergangene[nrsm]?|past|last)\s+(?:\d+|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn"
    r"|two|three|four|five|six|seven|eight|nine|ten)\s+(?:tage(?:n)?|wochen|monate(?:n)?|days|weeks|months)\b"
    r"|\bletzte[rsmn]?\s+monat\b|\bvergangene[nrsm]?\s+monat\b|\blast\s+month\b"
    r"|\bverlauf\b|\bvergleich\w*|\bcompared\s+(?:to|with)\b"
)
FULL_CALENDAR_PATTERN = (
    r"\btermine?\b|\bappointments?\b|\bmein(?:e[mnrs]?)?\s+kalender\b"
    r"|\bkalender\s+komplett\b|\bmy\s+calendar\b"
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
    ("today_training", r"heute|morgen|today|tomorrow|" + WEATHER_PATTERN),
)
FOOD_INTAKE_PATTERN = (
    r"gegessen|getrunken|\bmittag(?:essen)?\b|frühstück|fruehstueck|abendessen|kcal|snack"
    r"|\bate\b|\bdrank\b|calorie|kalorie|mahlzeit|\bmeal\b|ernährung|ernaehrung|nutrition"
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


def _matched_profiles(normalized: str) -> list[str]:
    text = normalized
    retrospective = False
    if not re.search(PLANNING_VERB_PATTERN, normalized) and re.search(
        PAST_WEEK_PATTERN, normalized
    ):
        text = re.sub(PAST_WEEK_PATTERN, " ", normalized)
        retrospective = True
    matched = [name for name, pattern in PROFILE_KEYWORDS if re.search(pattern, text)]
    # A bare past-week question is an activity review unless another topic (food,
    # weight, sync...) is named; then that topic keeps its own domain.
    if retrospective and not matched:
        return ["activity_analysis"]
    return matched


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

    matched = set(_matched_profiles(text.casefold()))
    return _domain_of_profiles(matched)


@dataclass(frozen=True)
class CoachContextSelection:
    name: str
    sections: frozenset[str] = FULL_SECTIONS
    horizon_days: int | None = None
    activity_limit: int = 5
    include_library: bool = True
    retain_dialogue: bool = False
    retain_pending_request: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sections",
            frozenset(canonical_section(name) for name in self.sections),
        )

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
        activities = result.get("activities")
        if isinstance(activities, dict):
            activities = dict(activities)
            activities.pop("planned_workouts", None)
            recent = activities.get("recent_activities_by_sport")
            if isinstance(recent, dict):
                activities["recent_activities_by_sport"] = {
                    sport: rows[: self.activity_limit]
                    if isinstance(rows, list)
                    else rows
                    for sport, rows in recent.items()
                }
            result["activities"] = activities
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


def is_bare_follow_up(message: str) -> bool:
    """Return whether the message only retries or continues, with no request of its own."""
    normalized = message.casefold()
    return bool(
        re.search(RETRY_PATTERN, normalized)
        or re.search(CONTINUATION_PATTERN, normalized)
    )


def _food_sections(normalized: str) -> frozenset[str]:
    """Return the saved-product section when the message reports food or drink."""
    return (
        frozenset({"nutrition_products"})
        if re.search(FOOD_INTAKE_PATTERN, normalized)
        else frozenset()
    )


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
    matched = _matched_profiles(normalized)
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
            "fallback", FALLBACK_SECTIONS, retain_pending_request=is_pending_active
        )
    name = matched[0] if matched else "general_coaching"
    sections = set(BASE_SECTIONS)
    planning = bool(
        set(matched) & {"weekly_planning", "plan_editing", "competition_preparation"}
    )
    if planning:
        sections.update({"planning", "training_plans"})
    food = _food_sections(normalized)
    sections |= food
    if "provider_refresh_or_sync" in matched or _requires_full_time_context(
        planning, normalized
    ):
        return CoachContextSelection(
            name, FULL_SECTIONS | food, retain_pending_request=is_pending_active
        )
    if attachments:
        name = "attachment_analysis"
    weather = bool(re.search(WEATHER_PATTERN, normalized))
    if weather:
        sections.add("weather")
    if re.search(FULL_CALENDAR_PATTERN, normalized):
        sections.add("external_calendar")
    horizon = 14 if planning else 3
    if weather and re.search(DAY_PATTERN, normalized):
        horizon = max(horizon, 7)
    return CoachContextSelection(
        name,
        frozenset(sections),
        horizon,
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
    matched = set(_matched_profiles(pending_text))
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
        # A retry re-runs the athlete's stored request, so it needs that provenance.
        return bool((retry or continuation) and _source_message_ids(pending))
    return bool(
        continuation
        or retry
        or (pending_domain is not None and message_domain == pending_domain)
        or re.search(CLARIFICATION_ANSWER_PATTERN, normalized)
        or _is_concise_clarification_answer(pending, normalized, message_domain)
    )


def _source_message_ids(pending: dict[str, Any]) -> list[int]:
    ids = pending.get("source_message_ids")
    return [item for item in ids if type(item) is int] if isinstance(ids, list) else []


def pending_origin_messages(
    pending: Mapping[str, Any], messages: object, current_id: object = None
) -> list[dict[str, Any]]:
    """Return the stored athlete messages a pending request was created from."""
    wanted = set(_source_message_ids(dict(pending))) - {current_id}
    return [
        item
        for item in (messages if isinstance(messages, list) else [])
        if isinstance(item, dict)
        and item.get("role") == "user"
        and item.get("id") in wanted
    ]


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
    if re.search(HISTORY_PATTERN, normalized):
        return True
    if re.search(PAST_WEEK_PATTERN, normalized) and not re.search(
        PLANNING_VERB_PATTERN, normalized
    ):
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
    elif isinstance(pending, dict) and pending.get("status") == "failed":
        result["pending_request"] = _grounded_failed_request(context, pending)
    return result


def _grounded_failed_request(
    context: dict[str, Any], pending: dict[str, Any]
) -> dict[str, Any] | None:
    """Show a retried request as the athlete's stored words, never a model summary."""
    origins = pending_origin_messages(
        pending, context.get("messages"), context.get("current_user_message_id")
    )
    if not origins:
        return None
    text = "\n".join(str(item.get("content") or "") for item in origins)
    return {
        **pending,
        "summary": text[:2000],
        "summary_source": "athlete_message",
    }
