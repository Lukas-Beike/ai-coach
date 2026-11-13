"""Transaction-scoped application of adaptive plan changes."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from backend import change_history
from backend.athlete.checkins import (
    CHECKIN_TEXT_LIMITS,
    CheckinService,
    reports_complaint,
)
from backend.athlete.local_date import LocalDate, iso_date_prefix
from backend.canonical.planning_fields import (
    HR_CAP,
    SESSION_FOCUS,
    STRENGTH_INTENSITY,
    STRENGTH_STRUCTURE,
    TEMPLATE_ID,
)
from backend.canonical.vocabulary import Sport
from backend.db import planning_store
from backend.db.repositories import CheckinRepository
from backend.errors import AppError
from backend.planning import calendar as planning_calendar
from backend.planning import workouts as planning_workouts
from backend.planning.plan_checks import ILLNESS_DAYS
from backend.planning.repository import parse_payload
from backend.planning.sport import planned_activity_type, planned_sport_environment

DEFAULT_ILLNESS_PAUSE_DAYS = ILLNESS_DAYS
WEATHER_ADAPTIVE_MAX_MINUTES = 90
# The only planned-unit fields an adaptive replacement may change on apply.
ADAPTIVE_REPLACEMENT_KEYS = (
    "name",
    "duration_minutes",
    "description",
    "target",
    "rationale",
    "archived",
    "private_calendar_adjustment",
    # "adaptive" marks a generic replacement that has no template (#2379).
    "source",
    TEMPLATE_ID,
    # Re-derived for the easier content; None removes a field that no longer fits.
    SESSION_FOCUS,
    STRENGTH_INTENSITY,
    STRENGTH_STRUCTURE,
    HR_CAP,
)
# Focus of an endurance unit the replan makes easy.
ADAPTIVE_EASY_FOCUS = "easy"
# Neutral title for a hard draft replaced on a [NO_INTENSITY] day.
ADAPTIVE_EASY_NAME = "Lockere Einheit"


def adaptive_recovery_description(sport: str, duration: int) -> str:
    descriptions = {
        "Run": f"- {duration}m Z1 HR Easy aerobic run at conversational effort",
        "Swim": f"- {duration}m Z1 Pace Easy relaxed swim with controlled breathing",
        "OpenWaterSwim": f"- {duration}m Z1 Pace Easy relaxed swim with controlled breathing",
        "WeightTraining": f"- {duration}m Mobility and easy strength; stop if pain increases",
        "Ride": f"- {duration}m 50-65% Easy endurance ride",
        "VirtualRide": f"- {duration}m 50-65% Easy endurance ride",
    }
    return descriptions.get(
        sport, f"- {duration}m Z1 HR Easy aerobic session at conversational effort"
    )


def easier_fields(
    workout: dict[str, Any], run_caps: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Focus, strength and cap fields that match an easy replacement.

    A run or ride becomes ``easy`` (a run with the easy cap from ``run_caps``,
    the athlete's effective caps); a strength unit keeps its exercises, sets and
    weights and only gets the light intensity (athlete decision on #2379). Other
    sports keep their fields.
    """
    sport = planned_sport_environment(workout)[0]
    if sport is Sport.RUN:
        return {
            SESSION_FOCUS: ADAPTIVE_EASY_FOCUS,
            HR_CAP: (run_caps or {}).get(ADAPTIVE_EASY_FOCUS),
        }
    if sport is Sport.RIDE:
        return {SESSION_FOCUS: ADAPTIVE_EASY_FOCUS, HR_CAP: None}
    if sport is Sport.STRENGTH:
        return {STRENGTH_INTENSITY: "light"}
    return {}


def adaptive_recovery_replacement(
    workout: dict[str, Any],
    reason: str,
    available_minutes: int | None = None,
    max_minutes: int | None = None,
    run_caps: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sport = planned_activity_type(workout)
    rationale = (
        f"Adaptive adjustment: {reason}. The original workout remains available "
        "in the local library history."
    )
    planned = int(workout.get("duration_minutes") or 30)
    if planned_sport_environment(workout)[0] is Sport.STRENGTH:
        # Its exercises, sets and weights stay (#2379); only a time limit
        # (availability, [SHORT_ONLY], return stage) shortens it.
        limits = [int(v) for v in (available_minutes, max_minutes) if v is not None]
        return {
            **workout,
            **easier_fields(workout),
            "duration_minutes": max(15, min(planned, *limits)) if limits else planned,
            "rationale": rationale,
        }
    duration_limit = int(available_minutes or planned)
    duration = max(
        15,
        min(
            min(duration_limit, int(max_minutes))
            if max_minutes is not None
            else duration_limit,
            90,
        ),
    )
    return {
        **workout,
        **easier_fields(workout, run_caps),
        "duration_minutes": duration,
        "description": adaptive_recovery_description(sport, duration),
        "target": "AUTO",
        "rationale": rationale,
        # The generic replacement is not one of the athlete's templates.
        "source": "adaptive",
        TEMPLATE_ID: None,
    }


def private_calendar_adjustment_context(
    draft: dict[str, Any],
    calendar_events: list[dict[str, Any]],
    adjusted: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Create bounded provenance for a draft changed because of iCalendar events."""
    return {
        "label": "Aufgrund privater Termine angepasst",
        "reason": str(reason or "Private Termine erforderten eine Anpassung")[:1000],
        "events": [
            {
                "name": str(event.get("name") or "Privater Termin")[:200],
                "event_date": iso_date_prefix(str(event.get("event_date") or "")),
                "duration_minutes": int(event.get("duration_minutes") or 0),
                "no_intensity": bool(event.get("no_intensity")),
                "short_only": bool(event.get("short_only")),
            }
            for event in calendar_events[:10]
            if isinstance(event, dict)
        ],
        "original_duration_minutes": draft.get("duration_minutes"),
        "adjusted_duration_minutes": adjusted.get("duration_minutes"),
        "intensity_adjusted": True,
        "no_intensity_requested": any(
            bool(event.get("no_intensity")) for event in calendar_events
        ),
        "short_only_requested": any(
            bool(event.get("short_only")) for event in calendar_events
        ),
    }


def adaptive_quick_action_blockers(
    preview: dict[str, Any] | None,
    today: date,
    *,
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(preview, dict) or preview.get("status") != "preview":
        return []
    horizon = today + timedelta(days=2)
    blockers = []
    changes_value = preview.get("changes")
    changes = changes_value if isinstance(changes_value, list) else []
    for change in changes:
        if not isinstance(change, dict):
            continue
        try:
            change_date = LocalDate.parse(change.get("date")).to_date()
        except TypeError, ValueError:
            continue
        trigger_values = change.get("blocking_triggers")
        triggers = (
            {str(value) for value in trigger_values}
            if isinstance(trigger_values, list)
            else set()
        )
        relevant = sorted(
            triggers.intersection({"calendar", "illness", "injury", "weather"})
        )
        if today <= change_date <= horizon and relevant:
            blockers.append(
                {
                    "date": change_date.isoformat(),
                    "name": str(change.get("name") or label)[:200],
                    "triggers": relevant,
                }
            )
    return blockers


def adaptive_workout_fingerprint(workout: dict[str, Any]) -> str:
    """Hash the mutable fields that an adaptive preview is allowed to replace."""
    source = {
        "type": planned_activity_type(workout),
        **{
            key: workout.get(key)
            for key in (
                "date",
                "name",
                "duration_minutes",
                "description",
                "target",
                "rationale",
                "private_calendar_adjustment",
            )
        },
    }
    return hashlib.sha256(
        json.dumps(
            source, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def illness_pause_forecast(
    feedback: dict[str, Any],
    today: date,
    *,
    illness_text_limit: int,
    default_days: int,
) -> dict[str, Any] | None:
    illness = str(feedback.get("illness") or "").strip()[:illness_text_limit]
    if not reports_complaint(illness):
        return None
    end_date = today + timedelta(days=default_days - 1)
    return {
        "start_date": today.isoformat(),
        "end_date": end_date.isoformat(),
        "recommended_pause_days": default_days,
        "illness": illness,
        "forecast": "Vorsichtige Trainingsprognose: zunächst vollständige Sportpause und danach schrittweise Rückkehr. Die Dauer ist ein Coach-Vorschlag, keine medizinische Diagnose, und muss bestätigt werden.",
    }


def illness_pause_replacement(workout: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **workout,
        "archived": True,
        "rationale": f"Krankheitspause: {reason}. Die ursprüngliche Einheit bleibt in der lokalen Bibliothekshistorie erhalten.",
    }


def illness_calendar_events(
    pause: dict[str, Any],
    illness: str,
    *,
    category: str,
    external_prefix: str,
    midnight_suffix: str,
) -> list[dict[str, Any]]:
    start = LocalDate.parse(pause["start_date"]).to_date()
    end = LocalDate.parse(pause["end_date"]).to_date()
    events: list[dict[str, Any]] = []
    current = start
    while current <= end:
        date_key = current.isoformat()
        events.append(
            {
                "category": category,
                "starts_at_local": f"{date_key}{midnight_suffix}",
                "name": "Krankheit",
                "description": str(illness or "Krankheit").strip()[:12000],
                "external_id": f"{external_prefix}{date_key}",
            }
        )
        current += timedelta(days=1)
    return events


def _overlaid(current: dict[str, Any], replacement: dict[str, Any]) -> dict[str, Any]:
    """The current row with the replaced fields; a None replacement removes one."""
    replaced = {
        key: replacement[key] for key in ADAPTIVE_REPLACEMENT_KEYS if key in replacement
    }
    merged = {**current, **replaced}
    return {
        key: value
        for key, value in merged.items()
        if not (key in replaced and value is None)
    }


def _return_stage_pending(payload: dict[str, Any]) -> bool:
    """Whether the approved preview also moves the stage of the illness return."""
    block = payload.get("illness_return")
    return isinstance(block, dict) and bool(block.get("pending"))


class AdaptiveReplanApplyService:
    """Apply one local adaptive preview atomically, without remote side effects."""

    def __init__(
        self,
        database_manager: Any,
        adjustment_repository: Any,
        revision_service: Any,
        today: Callable[[], date],
        now: Callable[[], str],
        calendar_conflict_service: Any | None = None,
    ):
        self._database_manager = database_manager
        self._adjustment_repository = adjustment_repository
        self._revision_service = revision_service
        self._today = today
        self._now = now
        self._calendar_conflict_service = calendar_conflict_service
        self._checkins = CheckinService(database_manager, CheckinRepository(now), today)

    def apply(self, adjustment_id: Any) -> dict[str, Any]:
        try:
            normalized_id = str(uuid.UUID(str(adjustment_id)))
        except (ValueError, AttributeError, TypeError) as exc:
            raise AppError(400, "Ungültige Plananpassung.") from exc

        with self._database_manager.unit_of_work() as db:
            row = self._adjustment_repository.get(db, normalized_id)
            if not row:
                raise AppError(404, "Plananpassung nicht gefunden.")
            status = str(row["status"])
            if status in {"applied", "stale", "partial"}:
                return {"status": f"already_{status}", "id": normalized_id}
            latest = self._adjustment_repository.latest(db)
            if not latest or str(latest["id"]) != normalized_id:
                raise AppError(
                    409,
                    "Diese Plananpassung wurde durch eine neuere Vorschau ersetzt. "
                    "Bitte die aktuelle Vorschau verwenden.",
                )

            payload = json.loads(row["payload"])
            illness_pause = (
                payload.get("illness_pause")
                if isinstance(payload.get("illness_pause"), dict)
                else None
            )
            active_illness_pause = (
                illness_pause
                if illness_pause and not illness_pause.get("approved")
                else None
            )
            now = self._now()
            today = self._today()
            applicable_changes, calendar_stale = self._calendar_changes(
                payload.get("changes") or []
            )
            updated, stale = self._apply_changes(db, applicable_changes, now, today)
            stale = calendar_stale + stale
            updated_checkins = 0
            if updated:
                self._revision_service.bump(db)
            if active_illness_pause:
                updated_checkins = self._fill_illness_checkin(
                    db, active_illness_pause, today
                )
                payload["illness_pause"] = {
                    **active_illness_pause,
                    "approved": True,
                    "status": "approved",
                }
            if stale and not updated and not _return_stage_pending(payload):
                status = "stale"
            elif stale:
                status = "partial"
            else:
                status = "applied"
            self._adjustment_repository.mark_applied(
                db,
                normalized_id,
                json.dumps(payload, ensure_ascii=False),
                status,
                now,
            )

        return {
            "status": status,
            "id": normalized_id,
            "updated": updated,
            "updated_checkins": updated_checkins,
            "stale": stale,
            "illness_pause": illness_pause,
        }

    def _calendar_changes(
        self, changes: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if self._calendar_conflict_service is None:
            return changes, []
        applicable, stale = [], []
        for change in changes:
            replacement = change.get("payload")
            if not isinstance(replacement, dict):
                applicable.append(change)
                continue
            archived = bool(replacement.get("archived"))
            candidate = replacement
            if archived:
                candidate = {**(change.get("before") or {}), "date": change.get("date")}
            blockers = self._calendar_conflict_service.constraints(candidate)
            if planning_calendar.adaptive_change_calendar_blocked(change, blockers):
                stale.append(
                    {
                        "library_workout_id": change.get("library_workout_id"),
                        "reason": "calendar_constraint_changed",
                        "events": blockers,
                    }
                )
            else:
                applicable.append(change)
        return applicable, stale

    def _fill_illness_checkin(self, db: Any, pause: dict[str, Any], today: date) -> int:
        """Mark today's check-in while the approved pause runs; never a future day."""
        start = LocalDate.parse(pause["start_date"]).to_date()
        end = LocalDate.parse(pause["end_date"]).to_date()
        if not start <= today <= end:
            return 0
        illness = str(pause.get("illness") or "Krankheit").strip()[
            : CHECKIN_TEXT_LIMITS["illness"]
        ]
        marker = f"Krankheitspause prognostiziert ab {start.isoformat()}"
        self._checkins.add_illness_in_transaction(db, illness, marker)
        return 1

    @staticmethod
    def _adaptive_change_stale_reason(
        current: Any, expected_fingerprint: str
    ) -> str | None:
        if not isinstance(current, dict):
            return "changed"
        if current.get("local_deleted") or current.get("archived"):
            return "missing"
        if (
            not expected_fingerprint
            or adaptive_workout_fingerprint(current) != expected_fingerprint
        ):
            return "changed"
        return None

    @classmethod
    def _apply_change(
        cls, db: Any, change: dict[str, Any], now: str, today: date
    ) -> tuple[int, dict[str, Any] | None]:
        draft_id = str(change.get("library_workout_id") or "")
        replacement = change.get("payload")
        if not draft_id or not isinstance(replacement, dict):
            return 0, None
        draft = planning_store.planned_unit_row(db, draft_id)
        if not draft:
            return 0, {"library_workout_id": draft_id, "reason": "missing"}
        current = parse_payload(draft["payload"])
        expected_fingerprint = str(change.get("source_fingerprint") or "")
        stale_reason = cls._adaptive_change_stale_reason(current, expected_fingerprint)
        if stale_reason or current is None:
            return 0, {"library_workout_id": draft_id, "reason": stale_reason}
        before = {
            **current,
            "sync_status": draft.get("sync_state") or current.get("sync_status"),
        }
        try:
            current_date = LocalDate.parse(current.get("date")).isoformat()
        except TypeError, ValueError:
            return 0, {"library_workout_id": draft_id, "reason": "invalid_date"}
        if current_date < today.isoformat():
            return 0, {"library_workout_id": draft_id, "reason": "past"}
        # Overlay only the fields a preview replaces on the current row, so athlete
        # edits to start time, plan membership or remote identity survive.
        replacement = {
            **_overlaid(current, replacement),
            "id": draft_id,
            "sync_status": "local",
        }
        replacement["planned_duration_s"] = (
            int(replacement.get("duration_minutes") or 0) * 60
        )
        if not replacement.get("archived") and not replacement.get("local_deleted"):
            planning_workouts.validate_workout_description(replacement)
            for key in planning_workouts.DERIVED_WORKOUT_KEYS:
                replacement.pop(key, None)
        planning_store.update_planned_unit(db, draft_id, replacement, now)
        change_history.record_change(
            db,
            "planned_unit",
            draft_id,
            "update",
            before,
            {**replacement, "sync_status": "local"},
            source="adaptive_replan",
        )
        return 1, None

    @classmethod
    def _apply_changes(
        cls, db: Any, changes: Any, now: str, today: date
    ) -> tuple[int, list[dict[str, Any]]]:
        updated = 0
        stale: list[dict[str, Any]] = []
        for change in changes if isinstance(changes, list) else []:
            if not isinstance(change, dict):
                continue
            changed, stale_item = cls._apply_change(db, change, now, today)
            updated += changed
            if stale_item:
                stale.append(stale_item)
        return updated, stale
