"""Transaction-scoped application of adaptive plan changes."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from backend import change_history
from backend.athlete.checkins import CHECKIN_TEXT_LIMITS
from backend.errors import AppError
from backend.planning import workouts as planning_workouts
from backend.planning.planned_unit_service import UPDATE_SQL as PLANNED_UNIT_UPDATE_SQL

DEFAULT_ILLNESS_PAUSE_DAYS = 3
WEATHER_ADAPTIVE_MAX_MINUTES = 90


def workout_is_hard(workout: dict[str, Any]) -> bool:
    text = f"{workout.get('name', '')} {workout.get('description', '')}".casefold()
    return any(
        term in text
        for term in (
            "interval",
            "vo2",
            "threshold",
            "tempo",
            "sprint",
            "race",
            "105%",
            "110%",
            "115%",
        )
    )


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


def adaptive_recovery_replacement(
    workout: dict[str, Any],
    reason: str,
    available_minutes: int | None = None,
    max_minutes: int | None = None,
) -> dict[str, Any]:
    sport = planning_workouts.intervals_workout_sport(
        workout.get("sport") or workout.get("type")
    )
    duration_limit = int(available_minutes or workout.get("duration_minutes") or 30)
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
        "duration_minutes": duration,
        "description": adaptive_recovery_description(sport, duration),
        "target": "AUTO",
        "rationale": f"Adaptive adjustment: {reason}. The original workout remains available in the local library history.",
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
                "event_date": str(event.get("event_date") or "")[:10],
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
    changes = preview.get("changes") if isinstance(preview.get("changes"), list) else []
    for change in changes:
        if not isinstance(change, dict):
            continue
        try:
            change_date = date.fromisoformat(str(change.get("date") or "")[:10])
        except (TypeError, ValueError):
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
        key: workout.get(key)
        for key in (
            "date",
            "name",
            "type",
            "duration_minutes",
            "description",
            "target",
            "rationale",
            "private_calendar_adjustment",
        )
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
    if not illness:
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
    start = date.fromisoformat(str(pause["start_date"])[:10])
    end = date.fromisoformat(str(pause["end_date"])[:10])
    events: list[dict[str, Any]] = []
    current = start
    while current <= end:
        date_key = current.isoformat()
        events.append(
            {
                "category": category,
                "start_date_local": f"{date_key}{midnight_suffix}",
                "name": "Krankheit",
                "description": str(illness or "Krankheit").strip()[:12000],
                "external_id": f"{external_prefix}{date_key}",
            }
        )
        current += timedelta(days=1)
    return events


class AdaptiveReplanApplyService:
    """Apply one local adaptive preview atomically, without remote side effects."""

    def __init__(
        self,
        database_manager: Any,
        adjustment_repository: Any,
        revision_service: Any,
        today: Callable[[], date],
        now: Callable[[], str],
    ):
        self._database_manager = database_manager
        self._adjustment_repository = adjustment_repository
        self._revision_service = revision_service
        self._today = today
        self._now = now

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
            updated, stale = self._apply_changes(db, payload.get("changes"), now, today)
            updated_checkins = 0
            if updated:
                self._revision_service.bump(db)
            if active_illness_pause:
                updated_checkins = self._fill_illness_checkins(
                    db, active_illness_pause, now
                )
                payload["illness_pause"] = {**active_illness_pause, "approved": True}
            if stale and not updated:
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

    @staticmethod
    def _illness_checkin_values(
        existing: Any, illness: str, marker: str
    ) -> tuple[str, str]:
        values = dict(existing)
        existing_illness = str(values.get("illness") or "").strip()
        combined_illness = existing_illness or illness
        if existing_illness and illness and illness not in existing_illness:
            combined_illness = f"{existing_illness}; {illness}"[
                : CHECKIN_TEXT_LIMITS["illness"]
            ]
        notes = str(values.get("notes") or "").strip()
        if marker not in notes:
            notes = f"{notes} · {marker}".strip(" ·")[: CHECKIN_TEXT_LIMITS["notes"]]
        return combined_illness, notes

    @classmethod
    def _upsert_illness_checkin(
        cls, db: Any, date_key: str, illness: str, marker: str, now: str
    ) -> None:
        existing = db.execute(
            "SELECT illness, notes FROM athlete_checkins WHERE checkin_date=?",
            (date_key,),
        ).fetchone()
        if existing:
            combined_illness, notes = cls._illness_checkin_values(
                existing, illness, marker
            )
            db.execute(
                "UPDATE athlete_checkins SET illness=?, notes=?, updated_at=? WHERE checkin_date=?",
                (combined_illness, notes, now, date_key),
            )
            return
        db.execute(
            "INSERT INTO athlete_checkins(checkin_date, soreness, stress, motivation, session_rpe, day_form, illness, pain, available_minutes, availability_notes, notes, created_at, updated_at) "
            "VALUES (?, NULL, NULL, NULL, NULL, '', ?, '', NULL, '', ?, ?, ?)",
            (date_key, illness, marker, now, now),
        )

    @classmethod
    def _fill_illness_checkins(cls, db: Any, pause: dict[str, Any], now: str) -> int:
        illness = str(pause.get("illness") or "Krankheit").strip()[
            : CHECKIN_TEXT_LIMITS["illness"]
        ]
        start = date.fromisoformat(str(pause["start_date"])[:10])
        end = date.fromisoformat(str(pause["end_date"])[:10])
        marker = f"Krankheitspause prognostiziert ab {start.isoformat()}"
        filled = 0
        current = start
        while current <= end:
            cls._upsert_illness_checkin(db, current.isoformat(), illness, marker, now)
            filled += 1
            current += timedelta(days=1)
        return filled

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
        draft = db.execute(
            "SELECT id, payload, sync_state FROM planned_units WHERE local_id=?",
            (draft_id,),
        ).fetchone()
        if not draft:
            return 0, {"library_workout_id": draft_id, "reason": "missing"}
        draft = dict(draft)
        try:
            current = json.loads(draft["payload"])
        except (TypeError, ValueError):
            current = None
        expected_fingerprint = str(change.get("source_fingerprint") or "")
        stale_reason = cls._adaptive_change_stale_reason(current, expected_fingerprint)
        if stale_reason:
            return 0, {"library_workout_id": draft_id, "reason": stale_reason}
        before = {
            **current,
            "sync_status": draft.get("sync_state") or current.get("sync_status"),
        }
        if str(current.get("date") or "")[:10] < today.isoformat():
            return 0, {"library_workout_id": draft_id, "reason": "past"}
        replacement = {
            **replacement,
            "id": draft_id,
            "moving_time": int(replacement.get("duration_minutes") or 0) * 60,
            "sync_status": "local",
        }
        if not replacement.get("archived") and not replacement.get("local_deleted"):
            planning_workouts.validate_workout_description(replacement)
            for key in ("workout_doc", "icu_training_load", "icu_intensity"):
                replacement.pop(key, None)
        db.execute(
            PLANNED_UNIT_UPDATE_SQL,
            (json.dumps(replacement, ensure_ascii=False), now, draft_id),
        )
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
