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
        *,
        equipment: Any = None,
    ) -> None:
        self._checkins = checkins
        self._activity_feedback = activity_feedback
        self._competitions = competitions
        self._nutrition = nutrition
        self._equipment = equipment

    def execute(
        self, name: str, arguments: dict[str, Any], intent: dict[str, Any]
    ) -> dict[str, Any] | None:
        if name in {
            "save_equipment",
            "assign_activity_equipment",
            "log_equipment_maintenance",
        }:
            self._authorize(
                intent, name, "Diese lokale Erfassung ist nicht autorisiert."
            )
            require_coach_scope(intent, "local_equipment")
            if self._equipment is None:
                raise AppError(503, "Ausrüstung ist nicht verfügbar.")
            method = {
                "save_equipment": self._equipment.save,
                "assign_activity_equipment": self._equipment.assign,
                "log_equipment_maintenance": self._equipment.maintain,
            }[name]
            return method(structured_action_payload(arguments))
        if name in {
            "save_nutrition_template",
            "delete_nutrition_template",
            "log_nutrition_template",
            "save_nutrition_entry",
            "update_nutrition_entry",
            "delete_nutrition_entry",
            "save_fueling_plan",
        }:
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
                        for key in (
                            "activity_name",
                            "activity_date",
                            "notes",
                            "session_rpe",
                            "deviation_reason",
                        )
                        if key in payload
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
                **self._activity_feedback.save(
                    activity_id,
                    {"notes": "", "session_rpe": None, "deviation_reason": ""},
                ),
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
            if name in {"save_nutrition_entry", "update_nutrition_entry"}
            else "Die strukturierte Coach-Autorisierung erlaubt das Löschen dieses Eintrags nicht."
        )
        self._authorize(intent, operation, message)
        require_coach_scope(intent, "local_nutrition")
        if not self._nutrition:
            raise AppError(500, "NutritionService ist nicht verfügbar.")
        if name == "save_fueling_plan":
            return self._nutrition.fueling().save(structured_action_payload(arguments))
        if name == "save_nutrition_template":
            template_payload = structured_action_payload(arguments)
            if not template_payload.get("id"):
                template_payload.setdefault("source", "coach")
            return {
                "ok": True,
                "template": self._nutrition.save_template(
                    template_payload,
                    **(
                        {"expected_calculation": arguments["_food_calculation"]}
                        if "_food_calculation" in arguments
                        else {}
                    ),
                ),
            }
        if name == "delete_nutrition_template":
            return {
                "ok": True,
                **self._nutrition.delete_template(str(arguments.get("id") or "")),
            }
        if name == "log_nutrition_template":
            return {
                "ok": True,
                "entry": self._nutrition.log_template(
                    str(arguments.get("id") or ""),
                    arguments.get("portions", 1),
                    meal_date=arguments.get("meal_date"),
                    meal_time=arguments.get("meal_time"),
                ),
            }
        if name == "save_nutrition_entry":
            payload = structured_action_payload(arguments)
            return {"ok": True, "entry": self._nutrition.log_meal(payload)}
        if name == "update_nutrition_entry":
            return {
                "ok": True,
                "entry": self._nutrition.correct_meal(
                    str(arguments.get("id") or ""), arguments.get("changes")
                ),
            }
        entry_id = str(arguments.get("id") or arguments.get("entry_id") or "").strip()
        return {"ok": True, **self._nutrition.delete_meal(entry_id)}

    @staticmethod
    def _authorize(intent: dict[str, Any], operation: str, message: str) -> None:
        if not require_operation(intent, operation):
            raise AppError(403, message, reason="intent_scope_denied")
