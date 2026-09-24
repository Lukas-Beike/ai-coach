"""Authorize and execute local Coach athlete-record tools."""

from __future__ import annotations

from typing import Any

from backend.activities.feedback import ActivityFeedbackService
from backend.athlete.checkins import CheckinService
from backend.coach.authorization import (
    require_coach_scope,
    require_operation,
    structured_action_payload,
)
from backend.errors import AppError
from backend.nutrition.service import NutritionService
from backend.planning.competition_service import CompetitionService


class CoachAthleteRecordToolService:
    """Own local Coach mutations for check-ins, feedback, competitions, and nutrition."""

    def __init__(
        self,
        checkins: CheckinService,
        activity_feedback: ActivityFeedbackService,
        competitions: CompetitionService,
        nutrition: NutritionService | None = None,
    ) -> None:
        self._checkins = checkins
        self._activity_feedback = activity_feedback
        self._competitions = competitions
        self._nutrition = nutrition

    def execute(
        self, name: str, arguments: dict[str, Any], intent: dict[str, Any]
    ) -> dict[str, Any] | None:
        if name in {"save_nutrition_entry", "delete_nutrition_entry"}:
            return self._execute_nutrition(name, arguments, intent)
        if name == "save_checkin":
            self._authorize(
                intent,
                name,
                "Die strukturierte Coach-Autorisierung erlaubt diesen Check-in nicht.",
            )
            require_coach_scope(intent, "local_checkin")
            return {
                "ok": True,
                **self._checkins.save_coach(structured_action_payload(arguments)),
            }
        if name == "save_activity_feedback":
            self._authorize(
                intent,
                name,
                "Die strukturierte Coach-Autorisierung erlaubt dieses Aktivitätsfeedback nicht.",
            )
            require_coach_scope(intent, "activity_feedback")
            payload = structured_action_payload(arguments)
            return {
                "ok": True,
                "stored_locally": True,
                **self._activity_feedback.save_coach(
                    payload.get("activity_id"),
                    {
                        key: payload.get(key)
                        for key in ("activity_name", "activity_date", "notes")
                    },
                ),
            }
        if name == "delete_activity_feedback":
            self._authorize(
                intent,
                name,
                "Die strukturierte Coach-Autorisierung erlaubt diese Feedbackänderung nicht.",
            )
            require_coach_scope(intent, "activity_feedback")
            activity_id = str(arguments.get("activity_id") or "").strip()
            return {
                "ok": True,
                "stored_locally": True,
                **self._activity_feedback.save(activity_id, {"notes": ""}),
            }
        if name == "save_competition":
            self._authorize(
                intent,
                name,
                "Die strukturierte Coach-Autorisierung erlaubt diese Aktion in diesem Turn nicht.",
            )
            payload = structured_action_payload(arguments)
            competition_id = str(payload.get("competition_id") or "").strip()
            require_coach_scope(
                intent,
                f"competition:{competition_id}"
                if competition_id
                else "local_competitions",
            )
            return {"ok": True, **self._competitions.save(payload)}
        if name == "delete_competition":
            self._authorize(
                intent,
                name,
                "Die strukturierte Coach-Autorisierung erlaubt diese Aktion in diesem Turn nicht.",
            )
            competition_id = str(arguments.get("competition_id") or "").strip()
            require_coach_scope(intent, f"competition:{competition_id}")
            return {"ok": True, **self._competitions.delete(competition_id)}
        return None

    def _execute_nutrition(
        self, name: str, arguments: dict[str, Any], intent: dict[str, Any]
    ) -> dict[str, Any]:
        operation = name
        message = (
            "Die strukturierte Coach-Autorisierung erlaubt diesen Ernährungseintrag nicht."
            if name == "save_nutrition_entry"
            else "Die strukturierte Coach-Autorisierung erlaubt das Löschen dieses Eintrags nicht."
        )
        self._authorize(intent, operation, message)
        require_coach_scope(intent, "local_nutrition")
        if not self._nutrition:
            raise AppError(500, "NutritionService ist nicht verfügbar.")
        if name == "save_nutrition_entry":
            payload = structured_action_payload(arguments)
            return {"ok": True, "entry": self._nutrition.log_meal(payload)}
        entry_id = str(arguments.get("id") or arguments.get("entry_id") or "").strip()
        return {"ok": True, **self._nutrition.delete_meal(entry_id)}

    @staticmethod
    def _authorize(intent: dict[str, Any], operation: str, message: str) -> None:
        if not require_operation(intent, operation):
            raise AppError(403, message, reason="intent_scope_denied")
