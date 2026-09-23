"""Create and read local adaptive training-plan previews."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.planning import adaptive
from backend.planning.context import external_calendar_event_dates
from backend.weather.adaptive import weather_adaptive_reason


def _as_number(value: Any) -> float | int | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _feedback_signals(feedback: dict[str, Any]) -> list[str]:
    signals = []
    if feedback.get("illness"):
        signals.append("illness reported")
    if feedback.get("pain"):
        signals.append("pain/injury reported")
    if feedback.get("soreness") is not None and feedback["soreness"] >= 8:
        signals.append("high soreness")
    if feedback.get("stress") is not None and feedback["stress"] >= 8:
        signals.append("high subjective stress")
    if feedback.get("motivation") is not None and feedback["motivation"] <= 2:
        signals.append("low motivation")
    return signals


def _calendar_context(
    events: list[dict[str, Any]],
    *,
    today: str,
    today_date: date,
    window_days: int,
) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    events_by_date: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if not bool(event.get("training_relevant", True)):
            continue
        for event_date in external_calendar_event_dates(
            event, today=today_date, window_days=window_days
        ):
            events_by_date.setdefault(event_date, []).append(event)
    signals = [
        f"family calendar on {event_date}: {len(day_events)} event(s)"
        for event_date, day_events in events_by_date.items()
        if event_date >= today
    ]
    return signals, events_by_date


def _approve_existing_pause(
    illness_pause: dict[str, Any] | None,
    previous: tuple[str, dict[str, Any]] | None,
    today: str,
) -> dict[str, Any] | None:
    if not illness_pause or not previous:
        return illness_pause
    previous_status, previous_pause = previous
    same_pause = (
        previous_status in {"applied", "partial"}
        and str(previous_pause.get("start_date") or "") == today
        and str(previous_pause.get("illness") or "") == illness_pause["illness"]
    )
    if same_pause:
        illness_pause["approved"] = True
    return illness_pause


def _calendar_limits(
    draft: dict[str, Any],
    calendar_events: list[dict[str, Any]],
    duration: float | None,
) -> tuple[int | None, str, bool, bool]:
    if not calendar_events:
        return None, "", False, False
    total_minutes = sum(
        int(event.get("duration_minutes") or 0) for event in calendar_events
    )
    longest_event = max(
        calendar_events, key=lambda event: int(event.get("duration_minutes") or 0)
    )
    all_day = any(bool(event.get("all_day")) for event in calendar_events)
    if all_day or total_minutes >= 240:
        calendar_limit = 45
    elif total_minutes >= 120:
        calendar_limit = 60
    else:
        calendar_limit = 75
    calendar_reason = (
        f"family calendar has {len(calendar_events)} event(s), including "
        f"'{longest_event.get('name') or 'calendar event'}' for about "
        f"{total_minutes} minutes"
    )
    no_intensity = [
        event for event in calendar_events if bool(event.get("no_intensity"))
    ]
    no_intensity_limited = bool(no_intensity) and adaptive.workout_is_hard(draft)
    calendar_limited = adaptive.workout_is_hard(draft) or (
        duration is not None and duration > calendar_limit
    )
    return calendar_limit, calendar_reason, no_intensity_limited, calendar_limited


def _reasons(
    draft: dict[str, Any],
    feedback: dict[str, Any],
    illness_pause: dict[str, Any] | None,
    illness_active: bool,
    severe: bool,
    high_load: bool,
    limited: bool,
    available_minutes: Any,
    calendar_reason: str,
    calendar_limited: bool,
    no_intensity_limited: bool,
    weather_reason: str,
) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    blocking_triggers: list[str] = []
    if illness_active:
        reasons.append(
            f"illness reported; sport pause through {illness_pause['end_date']}"
        )
        blocking_triggers.append("illness")
    if severe:
        reasons.append("pain or high soreness reported")
        if feedback.get("pain"):
            blocking_triggers.append("injury")
    if high_load and adaptive.workout_is_hard(draft):
        reasons.append("recovery signal suggests reducing intensity")
    if limited and not severe:
        reasons.append(f"only {available_minutes} minutes are available")
    if calendar_limited:
        reasons.append(calendar_reason)
        blocking_triggers.append("calendar")
    if no_intensity_limited:
        reasons.append("calendar marker [NO_INTENSITY] requests an easy session")
        if "calendar" not in blocking_triggers:
            blocking_triggers.append("calendar")
    if weather_reason:
        reasons.append(weather_reason)
        blocking_triggers.append("weather")
    return reasons, blocking_triggers


def _change_state(
    draft: dict[str, Any],
    *,
    today: str,
    today_date: date,
    feedback: dict[str, Any],
    illness_pause: dict[str, Any] | None,
    events_by_date: dict[str, list[dict[str, Any]]],
    weather_days: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not draft.get("date") or str(draft.get("date") or "") < today:
        return None
    draft_date = str(draft.get("date") or "")[:10]
    duration = _as_number(draft.get("duration_minutes"))
    available_minutes = feedback.get("available_minutes")
    calendar_events = events_by_date.get(str(draft.get("date") or ""), [])
    calendar_limit, calendar_reason, no_intensity_limited, calendar_limited = (
        _calendar_limits(draft, calendar_events, duration)
    )
    return {
        "illness_active": bool(
            illness_pause
            and not illness_pause.get("approved")
            and illness_pause["start_date"] <= draft_date <= illness_pause["end_date"]
        ),
        "severe": bool(feedback.get("pain") or (feedback.get("soreness") or 0) >= 8),
        "high_load": bool(
            (feedback.get("stress") or 0) >= 8
            or (
                feedback.get("motivation") is not None
                and feedback.get("motivation") <= 2
            )
        ),
        "available_minutes": available_minutes,
        "duration": duration,
        "limited": (
            available_minutes is not None
            and duration is not None
            and duration > available_minutes
        ),
        "calendar_events": calendar_events,
        "weather_reason": weather_adaptive_reason(draft, weather_days, today_date),
        "calendar_limit": calendar_limit,
        "calendar_reason": calendar_reason,
        "no_intensity_limited": no_intensity_limited,
        "calendar_limited": calendar_limited,
    }


def _replacement(
    draft: dict[str, Any], reason: str, state: dict[str, Any], max_minutes: int
) -> dict[str, Any]:
    limits = [
        limit
        for limit in (
            state["calendar_limit"] if state["calendar_limited"] else None,
            max_minutes if state["weather_reason"] else None,
        )
        if limit is not None
    ]
    if state["illness_active"]:
        replacement = adaptive.illness_pause_replacement(draft, reason)
    else:
        replacement = adaptive.adaptive_recovery_replacement(
            draft,
            reason,
            state["available_minutes"] if state["limited"] else None,
            min(limits) if limits else None,
        )
    if state["calendar_limited"]:
        replacement["private_calendar_adjustment"] = (
            adaptive.private_calendar_adjustment_context(
                draft, state["calendar_events"], replacement, state["calendar_reason"]
            )
        )
    return replacement


def _needs_change(draft: dict[str, Any], state: dict[str, Any]) -> bool:
    return bool(
        state["illness_active"]
        or state["severe"]
        or (state["high_load"] and adaptive.workout_is_hard(draft))
        or state["limited"]
        or state["calendar_limited"]
        or state["no_intensity_limited"]
        or state["weather_reason"]
    )


def _change_result(
    draft: dict[str, Any],
    state: dict[str, Any],
    replacement: dict[str, Any],
    blocking_triggers: list[str],
) -> dict[str, Any]:
    illness_active = state["illness_active"]
    return {
        "library_workout_id": draft["id"],
        "date": draft.get("date"),
        "name": draft.get("name"),
        "blocking_triggers": blocking_triggers,
        "external_events": state["calendar_events"],
        "before": {
            "duration_minutes": draft.get("duration_minutes"),
            "description": draft.get("description"),
        },
        "after": {
            "name": "Krankheitspause" if illness_active else replacement.get("name"),
            "duration_minutes": 0
            if illness_active
            else replacement["duration_minutes"],
            "description": (
                "Sportpause; die geplante Einheit wird archiviert."
                if illness_active
                else replacement["description"]
            ),
            "rationale": replacement["rationale"],
        },
        "source_fingerprint": adaptive.adaptive_workout_fingerprint(draft),
        "payload": replacement,
    }


def _change(
    draft: dict[str, Any],
    *,
    today: str,
    today_date: date,
    feedback: dict[str, Any],
    illness_pause: dict[str, Any] | None,
    events_by_date: dict[str, list[dict[str, Any]]],
    weather_days: dict[str, dict[str, Any]],
    weather_adaptive_max_minutes: int,
) -> dict[str, Any] | None:
    state = _change_state(
        draft,
        today=today,
        today_date=today_date,
        feedback=feedback,
        illness_pause=illness_pause,
        events_by_date=events_by_date,
        weather_days=weather_days,
    )
    if state is None or not _needs_change(draft, state):
        return None
    reasons, blocking_triggers = _reasons(
        draft,
        feedback,
        illness_pause,
        state["illness_active"],
        state["severe"],
        state["high_load"],
        state["limited"],
        state["available_minutes"],
        state["calendar_reason"],
        state["calendar_limited"],
        state["no_intensity_limited"],
        state["weather_reason"],
    )
    reason = "; ".join(reasons)
    replacement = _replacement(draft, reason, state, weather_adaptive_max_minutes)
    return _change_result(draft, state, replacement, blocking_triggers)


class AdaptiveReplanPreviewService:
    """Own local adaptive preview orchestration and its persistence boundary."""

    def __init__(
        self,
        database_manager: Any,
        adjustment_repository: Any,
        checkin_service: Any,
        planned_unit_service: Any,
        external_calendar_reader: Any,
        weather_service: Any,
        today: Callable[[], date],
        now: Callable[[], str],
        id_factory: Callable[[], Any],
        external_calendar_window_days: int,
        illness_text_limit: int,
        illness_pause_default_days: int,
        weather_adaptive_max_minutes: int,
    ) -> None:
        self._database_manager = database_manager
        self._adjustment_repository = adjustment_repository
        self._checkin_service = checkin_service
        self._planned_unit_service = planned_unit_service
        self._external_calendar_reader = external_calendar_reader
        self._weather_service = weather_service
        self._today = today
        self._now = now
        self._id_factory = id_factory
        self._external_calendar_window_days = external_calendar_window_days
        self._illness_text_limit = illness_text_limit
        self._illness_pause_default_days = illness_pause_default_days
        self._weather_adaptive_max_minutes = weather_adaptive_max_minutes

    def latest_preview(self) -> dict[str, Any] | None:
        with self._database_manager.unit_of_work() as db:
            row = self._adjustment_repository.latest(db)
        if not row:
            return None
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return {
            "id": row["id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "applied_at": row["applied_at"],
            **payload,
        }

    def status(self) -> dict[str, Any]:
        preview = self.latest_preview()
        changes = preview.get("changes", []) if isinstance(preview, dict) else []
        illness_pause_pending = bool(
            preview
            and preview.get("status") == "preview"
            and isinstance(preview.get("illness_pause"), dict)
            and not preview["illness_pause"].get("approved")
        )
        change_count = len(changes) if isinstance(changes, list) else 0
        return {
            "needs_replan": bool(
                preview
                and preview.get("status") == "preview"
                and (change_count or illness_pause_pending)
            ),
            "replan_changes": change_count,
            "illness_pause_pending": illness_pause_pending,
        }

    def latest_illness_pause(self) -> tuple[str, dict[str, Any]] | None:
        with self._database_manager.unit_of_work() as db:
            rows = self._adjustment_repository.list_recent(db)
        for row in rows:
            try:
                payload = json.loads(row.get("payload") or "{}")
            except (TypeError, ValueError):
                continue
            pause = payload.get("illness_pause") if isinstance(payload, dict) else None
            if isinstance(pause, dict):
                return str(row.get("status") or ""), pause
        return None

    def preview(self) -> dict[str, Any]:
        today_date = self._today()
        today = today_date.isoformat()
        feedback = self._checkin_service.context().get("today") or {}
        weather = self._weather_service.state(refresh=False)
        weather_days = {
            str(day.get("date")): day
            for day in weather.get("days", [])
            if isinstance(day, dict) and day.get("date")
        }
        signals = _feedback_signals(feedback)
        illness_pause = adaptive.illness_pause_forecast(
            feedback,
            today_date,
            illness_text_limit=self._illness_text_limit,
            default_days=self._illness_pause_default_days,
        )
        illness_pause = _approve_existing_pause(
            illness_pause, self.latest_illness_pause(), today
        )
        calendar_signals, events_by_date = _calendar_context(
            self._external_calendar_reader.list_events(1000),
            today=today,
            today_date=today_date,
            window_days=self._external_calendar_window_days,
        )
        signals.extend(calendar_signals)
        changes = [
            change
            for draft in self._planned_unit_service.list(500)
            if (
                change := _change(
                    draft,
                    today=today,
                    today_date=today_date,
                    feedback=feedback,
                    illness_pause=illness_pause,
                    events_by_date=events_by_date,
                    weather_days=weather_days,
                    weather_adaptive_max_minutes=self._weather_adaptive_max_minutes,
                )
            )
            is not None
        ]
        change_message = (
            "Keine zukünftigen lokalen Einheiten müssen angepasst werden."
            if not changes
            else f"{len(changes)} zukünftige lokale Einheit(en) brauchen eine Prüfung."
        )
        if illness_pause and not illness_pause.get("approved"):
            message = (
                f"Krankheitsprognose: {illness_pause['recommended_pause_days']} Tage "
                f"Sportpause bis {illness_pause['end_date']}. {change_message}"
            )
        else:
            message = change_message
        preview = {
            "generated_at": self._now(),
            "checkin_date": feedback.get("checkin_date") or today,
            "signals": signals,
            "changes": changes,
            "illness_pause": illness_pause,
            "message": message,
            "scope": (
                "Nur nach Bestätigung werden lokale zukünftige Einheiten angepasst "
                "und die prognostizierten Krankheitstage eingetragen. Intervals.icu "
                "wird nur bei ausdrücklicher Auswahl synchronisiert."
            ),
        }
        adjustment_id = str(self._id_factory())
        with self._database_manager.unit_of_work() as db:
            self._adjustment_repository.create_preview(
                db,
                adjustment_id,
                json.dumps(preview, ensure_ascii=False),
                preview["generated_at"],
            )
        return {"id": adjustment_id, "status": "preview", **preview}
