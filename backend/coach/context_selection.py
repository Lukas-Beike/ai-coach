"""Deterministic request projections; selection is never authorization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

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
        r"profil|check.?in|befinden|nutrition|ernährung|ernaehrung|gegessen|mahlzeit|frühstück|fruehstueck|snack|\bate\b|calorie|kalorie",
    ),
    (
        "activity_analysis",
        r"aktivität|aktivitaet|activity|analyse|analy[sz]|einheit|session|workout",
    ),
    ("today_training", r"heute|morgen|today|tomorrow|wetter|weather"),
)


@dataclass(frozen=True)
class CoachContextSelection:
    name: str
    sections: frozenset[str] = CONTEXT_SECTIONS
    horizon_days: int | None = None
    activity_limit: int = 5
    include_library: bool = True
    retain_dialogue: bool = False

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
                value := str(
                    item.get("date")
                    or item.get("event_date")
                    or item.get("start_date_local")
                    or ""
                )[:10]
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
    continuation = re.search(
        r"\b(ja|yes|ok|okay|mach|weiter|fortsetzen|das|diese|diesen|that|those|it|continue)\b",
        normalized,
    )
    matched = [
        name for name, pattern in PROFILE_KEYWORDS if re.search(pattern, normalized)
    ]
    if dialogue.get("pending_request") or (
        continuation
        and (
            not matched
            or len(normalized.split()) <= 3
            or len(set(matched) - {"today_training"}) > 1
        )
    ):
        return CoachContextSelection("fallback")
    name = matched[0] if matched else "general_coaching"
    sections = set(BASE_SECTIONS)
    planning = bool(
        set(matched) & {"weekly_planning", "plan_editing", "competition_preparation"}
    )
    if planning:
        sections.update({"planning", "training_plans"})
    if "provider_refresh_or_sync" in matched:
        return CoachContextSelection(name)
    if re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.", normalized):
        return CoachContextSelection(name)
    if planning and any(
        re.search(pattern, normalized)
        for pattern in (
            r"monat|month|jahr|year|saison|season",
            r"\b(?:wochen|weeks|tage|days)\b",
        )
    ):
        return CoachContextSelection(name)
    if attachments:
        name = "attachment_analysis"
    return CoachContextSelection(
        name,
        frozenset(sections),
        14 if planning else 3,
        5 if planning or "activity_analysis" in matched else 1,
        planning,
        retain_dialogue=bool(continuation or has_receipts),
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
    return result


def select_coach_tools(
    tools: list[dict[str, Any]],
    selection: CoachContextSelection,
) -> list[dict[str, Any]]:
    if selection.horizon_days is None or selection.name == "attachment_analysis":
        return tools
    always = {
        "read_coach_context",
        "read_profile",
        "read_training_state",
        "list_recent_activities",
        "get_activity_details",
        "list_workout_library",
        "list_planned_workouts",
        "list_change_history",
        "list_competitions",
        "list_training_plans",
        "get_sync_job",
        "read_nutrition",
        "inspect_activity_duplicates",
        "clarify_coach_request",
        "cancel_coach_request",
    }
    groups = {
        "weekly_planning": {
            "stage_training_plan",
            "commit_training_plan",
            "apply_training_patch",
            "replace_training_plan",
            "apply_workout_library_plan",
            "manage_training_templates",
            "update_training_plan",
            "preview_adaptive_replan",
            "apply_adaptive_replan",
        },
        "plan_editing": {
            "apply_training_patch",
            "replace_training_plan",
            "manage_training_templates",
            "update_training_plan",
            "undo_training_change",
            "preview_adaptive_replan",
            "apply_adaptive_replan",
            "update_profile",
            "delete_competition",
            "delete_activity_feedback",
            "update_nutrition_entry",
            "save_nutrition_template",
            "delete_nutrition_template",
            "log_nutrition_template",
            "delete_nutrition_entry",
        },
        "profile_or_checkin": {
            "update_profile",
            "save_checkin",
            "save_nutrition_entry",
            "save_nutrition_template",
            "delete_nutrition_template",
            "log_nutrition_template",
        },
        "competition_preparation": {"save_competition", "delete_competition"},
        "activity_analysis": {"save_activity_feedback"},
    }
    selected = always | groups.get(selection.name, set())
    if not any(tool.get("name") == "read_coach_context" for tool in tools):
        return tools
    return [tool for tool in tools if tool.get("name") in selected]
