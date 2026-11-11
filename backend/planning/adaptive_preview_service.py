"""Create and read local adaptive training-plan previews."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.athlete.checkins import reports_complaint
from backend.athlete.local_date import LocalDate
from backend.errors import AppError
from backend.planning import adaptive, calendar, illness_return, plan_checks
from backend.planning.context import external_calendar_event_dates
from backend.planning.session_focus import is_hard
from backend.weather.adaptive import weather_adaptive_reason

MAX_PREVIEW_PLANNED_UNITS = 500
# A session made easy for the return stays below the long-session threshold.
RETURN_EASY_MAX_MINUTES = 60


@dataclass(frozen=True)
class AdaptivePreviewLimits:
    """Window and limits of an adaptive preview."""

    external_calendar_window_days: int
    illness_text_limit: int
    illness_pause_default_days: int
    weather_adaptive_max_minutes: int


def _as_number(value: Any) -> float | int | None:
    try:
        number = float(str(value).replace(",", "."))
    except TypeError, ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _forecast_freshness(weather: dict[str, Any]) -> dict[str, Any]:
    """Describe the forecast age the preview used, without the forecast days."""
    return {
        "state": weather.get("state"),
        "provider": weather.get("provider"),
        "fetched_at": weather.get("fetched_at"),
        "stale": bool(weather.get("stale")),
    }


def _feedback_signals(feedback: dict[str, Any]) -> list[str]:
    signals = []
    if reports_complaint(feedback.get("illness")):
        signals.append("illness reported")
    if reports_complaint(feedback.get("pain")):
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
        if not bool(event.get("training_relevant", True)) and not bool(
            event.get("no_training")
            or event.get("no_intensity")
            or event.get("short_only")
        ):
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
    """Carry an approved pause window over while it runs for the same illness.

    The stored window decides, not the date of the report, so a later report
    inside the window neither asks again nor extends the pause.
    """
    if not illness_pause or not previous:
        return illness_pause
    previous_status, previous_pause = previous
    start = str(previous_pause.get("start_date") or "")
    end = str(previous_pause.get("end_date") or "")
    same_pause = (
        previous_status in {"applied", "partial"}
        and start <= today <= end
        and str(previous_pause.get("illness") or "") == illness_pause["illness"]
    )
    if same_pause:
        illness_pause.update(start_date=start, end_date=end, approved=True)
        illness_pause["status"] = "approved"
    return illness_pause


def _calendar_limits(
    draft: dict[str, Any],
    calendar_events: list[dict[str, Any]],
    duration: float | None,
) -> tuple[int | None, str, bool, bool, bool]:
    if not calendar_events:
        return None, "", False, False, False
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
    if any(
        calendar.calendar_event_has_constraint(event, "short_only")
        for event in calendar_events
    ):
        calendar_limit = min(calendar_limit, calendar.SHORT_ONLY_MAX_MINUTES)
    calendar_reason = (
        f"family calendar has {len(calendar_events)} event(s), including "
        f"'{longest_event.get('name') or 'calendar event'}' for about "
        f"{total_minutes} minutes"
    )
    no_intensity_limited = any(
        calendar.calendar_event_has_constraint(event, "no_intensity")
        for event in calendar_events
    ) and calendar.breaks_no_intensity(draft)
    no_training = any(bool(event.get("no_training")) for event in calendar_events)
    calendar_limited = is_hard(draft) or (
        duration is not None and duration > calendar_limit
    )
    return (
        calendar_limit,
        calendar_reason,
        no_intensity_limited,
        calendar_limited,
        no_training,
    )


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
    no_training: bool,
    weather_reason: str,
) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    blocking_triggers: list[str] = []
    if illness_active and illness_pause is not None:
        reasons.append(
            f"illness reported; sport pause through {illness_pause['end_date']}"
        )
        blocking_triggers.append("illness")
    if severe:
        reasons.append("pain or high soreness reported")
        if reports_complaint(feedback.get("pain")):
            blocking_triggers.append("injury")
    if high_load and is_hard(draft):
        reasons.append("recovery signal suggests reducing intensity")
    if limited and not severe:
        reasons.append(f"only {available_minutes} minutes are available")
    if calendar_limited:
        reasons.append(calendar_reason)
    if no_training:
        reasons.append("calendar marker [NO_TRAINING] blocks training")
    if no_intensity_limited:
        reasons.append("calendar marker [NO_INTENSITY] requests an easy session")
    if calendar_limited or no_training or no_intensity_limited:
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
    return_stage: int | None = None,
) -> dict[str, Any] | None:
    if not draft.get("date") or str(draft.get("date") or "") < today:
        return None
    try:
        draft_date = LocalDate.parse(draft.get("date")).isoformat()
    except ValueError:
        return None
    duration = _as_number(draft.get("duration_minutes"))
    # Check-in limits (time, pain, soreness, stress) bind only the check-in day.
    on_checkin_day = draft_date == str(feedback.get("checkin_date") or today)
    day_feedback = feedback if on_checkin_day else {}
    available_minutes = _as_number(day_feedback.get("available_minutes"))
    motivation = _as_number(day_feedback.get("motivation"))
    calendar_events = events_by_date.get(str(draft.get("date") or ""), [])
    (
        calendar_limit,
        calendar_reason,
        no_intensity_limited,
        calendar_limited,
        no_training,
    ) = _calendar_limits(draft, calendar_events, duration)
    return {
        "illness_active": bool(
            illness_pause
            and not illness_pause.get("approved")
            and illness_pause["start_date"] <= draft_date <= illness_pause["end_date"]
        ),
        "severe": reports_complaint(day_feedback.get("pain"))
        or (day_feedback.get("soreness") or 0) >= 8,
        "high_load": bool(
            (day_feedback.get("stress") or 0) >= 8
            or (motivation is not None and motivation <= 2)
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
        "no_training": no_training,
        "calendar_limited": calendar_limited,
        "return_limited": _return_limited(draft, draft_date, today_date, return_stage),
        "return_stage": return_stage,
    }


def _return_limited(
    draft: dict[str, Any], draft_date: str, today_date: date, stage: int | None
) -> bool:
    """A session above the return stage inside the stage horizon."""
    if stage is None:
        return False
    last = today_date + timedelta(days=illness_return.RETURN_HORIZON_DAYS - 1)
    return (
        draft_date <= last.isoformat()
        and plan_checks.session_level(draft) > illness_return.STAGE_MAX_LEVEL[stage]
    )


def _without_focus(replacement: dict[str, Any]) -> dict[str, Any]:
    """The generated easy focus is no evidence; judge a replacement by its text."""
    return {**replacement, "session_focus": None, "strength_intensity": None}


def _replacement(
    draft: dict[str, Any],
    reason: str,
    state: dict[str, Any],
    max_minutes: int,
    run_caps: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    limits = [
        limit
        for limit in (
            state["calendar_limit"] if state["calendar_limited"] else None,
            max_minutes if state["weather_reason"] else None,
            RETURN_EASY_MAX_MINUTES if state["return_limited"] else None,
        )
        if limit is not None
    ]
    if state["illness_active"]:
        replacement = adaptive.illness_pause_replacement(draft, reason)
    elif state["no_training"]:
        replacement = {
            **draft,
            "archived": True,
            "duration_minutes": 0,
            "description": "Sportpause; die geplante Einheit wird archiviert.",
            "rationale": f"Calendar [NO_TRAINING]: {reason}. The original stays in local history.",
        }
    else:
        replacement = adaptive.adaptive_recovery_replacement(
            draft,
            reason,
            state["available_minutes"] if state["limited"] else None,
            min(limits) if limits else None,
            run_caps,
        )
        if state["no_intensity_limited"] and not calendar.workout_is_explicitly_easy(
            _without_focus(replacement)
        ):
            replacement["name"] = adaptive.ADAPTIVE_EASY_NAME
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
        or (state["high_load"] and is_hard(draft))
        or state["limited"]
        or state["calendar_limited"]
        or state["no_intensity_limited"]
        or state["no_training"]
        or state["weather_reason"]
        or state["return_limited"]
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
    run_caps: dict[str, dict[str, Any]] | None = None,
    return_stage: int | None = None,
) -> dict[str, Any] | None:
    state = _change_state(
        draft,
        today=today,
        today_date=today_date,
        feedback=feedback,
        illness_pause=illness_pause,
        events_by_date=events_by_date,
        weather_days=weather_days,
        return_stage=return_stage,
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
        state["no_training"],
        state["weather_reason"],
    )
    if state["return_limited"]:
        reasons.append(
            f"return after illness, stage {return_stage}: "
            f"{illness_return.STAGE_LABELS[state['return_stage']]}"
        )
        blocking_triggers.append("illness")
    reason = "; ".join(reasons)
    replacement = _replacement(
        draft, reason, state, weather_adaptive_max_minutes, run_caps
    )
    change = _change_result(draft, state, replacement, blocking_triggers)
    # Apply re-checks archives against the current calendar; a kept replacement
    # that would still break a marker of its day is never proposed.
    blockers = [
        decision
        for event in state["calendar_events"]
        if (
            decision := calendar.calendar_constraint_decision(
                _without_focus(replacement), event
            )
        )
    ]
    if not replacement.get("archived") and calendar.adaptive_change_calendar_blocked(
        change, blockers
    ):
        return None
    return change


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
        limits: AdaptivePreviewLimits,
        run_caps: Callable[[], dict[str, dict[str, Any]]] | None = None,
        overnight: Callable[[], dict[str, dict[str, Any]]] | None = None,
    ) -> None:
        """``run_caps`` gives the athlete's effective run heart-rate caps.

        ``overnight`` reads this morning's HRV and resting heart rate baselines
        for the return after an illness pause; without it the check-in decides.
        """
        self._database_manager = database_manager
        self._adjustment_repository = adjustment_repository
        self._checkin_service = checkin_service
        self._planned_unit_service = planned_unit_service
        self._external_calendar_reader = external_calendar_reader
        self._weather_service = weather_service
        self._today = today
        self._now = now
        self._id_factory = id_factory
        self._limits = limits
        self._run_caps = run_caps
        self._overnight = overnight

    def latest_preview(self, *, db: Any | None = None) -> dict[str, Any] | None:
        if db is None:
            with self._database_manager.reader() as connection:
                row = self._adjustment_repository.latest(connection)
        else:
            row = self._adjustment_repository.latest(db)
        if not row:
            return None
        try:
            payload = json.loads(row["payload"])
        except TypeError, ValueError:
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

    def status(self, *, db: Any | None = None) -> dict[str, Any]:
        preview = self.latest_preview(db=db)
        changes = preview.get("changes", []) if isinstance(preview, dict) else []
        illness_pause_pending = bool(
            preview
            and preview.get("status") == "preview"
            and isinstance(preview.get("illness_pause"), dict)
            and not preview["illness_pause"].get("approved")
        )
        change_count = len(changes) if isinstance(changes, list) else 0
        block = preview.get("illness_return") if isinstance(preview, dict) else None
        illness_return_pending = bool(
            preview
            and preview.get("status") == "preview"
            and isinstance(block, dict)
            and block.get("pending")
        )
        return {
            "needs_replan": bool(
                preview
                and preview.get("status") == "preview"
                and (change_count or illness_pause_pending or illness_return_pending)
            ),
            "replan_changes": change_count,
            "illness_pause_pending": illness_pause_pending,
            "illness_return_pending": illness_return_pending,
        }

    def latest_illness_pause(self) -> tuple[str, dict[str, Any]] | None:
        with self._database_manager.reader() as db:
            rows = self._adjustment_repository.list_applied(db)
        for row in rows:
            try:
                payload = json.loads(row.get("payload") or "{}")
            except TypeError, ValueError:
                continue
            pause = payload.get("illness_pause") if isinstance(payload, dict) else None
            status = str(row.get("status") or "")
            # A preview never holds the approval; the applied row does.
            if isinstance(pause, dict) and status in {"applied", "partial"}:
                return status, pause
        return None

    def latest_illness_return(self) -> dict[str, Any] | None:
        """The return state of the newest applied adjustment that holds one."""
        with self._database_manager.reader() as db:
            rows = self._adjustment_repository.list_applied(db)
        for row in rows:
            if str(row.get("status") or "") not in {"applied", "partial"}:
                continue
            try:
                payload = json.loads(row.get("payload") or "{}")
            except TypeError, ValueError:
                continue
            block = payload.get("illness_return") if isinstance(payload, dict) else None
            state = block.get("state_after") if isinstance(block, dict) else None
            if isinstance(state, dict):
                return state
        return None

    def active_illness_return(self) -> dict[str, Any] | None:
        """The running return after an approved pause, from stored approvals only."""
        pause = self.latest_illness_pause()
        return illness_return.current_state(
            pause[1] if pause else None, self.latest_illness_return(), self._today()
        )

    def enforced_return_stage(self) -> int | None:
        """The approved stage the plan guard enforces; None without a return."""
        return illness_return.enforced_stage(self.active_illness_return())

    def _illness_return_block(
        self, today: date, feedback: dict[str, Any], illness_pause: Any
    ) -> dict[str, Any] | None:
        """Stage decision for this morning; a new pause forecast outranks it."""
        state = None if illness_pause else self.active_illness_return()
        if state is None or illness_return.enforced_stage(state) is None:
            return None
        overnight = self._overnight() if self._overnight else {}
        decision = illness_return.decide(state, today, feedback, overnight)
        after = illness_return.state_after(state, decision, today)
        stage = decision["stage"]
        return {
            **decision,
            "pending": stage != state["stage"],
            "state_after": after,
            "stage_label": illness_return.STAGE_LABELS[stage],
        }

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
            illness_text_limit=self._limits.illness_text_limit,
            default_days=self._limits.illness_pause_default_days,
        )
        illness_pause = _approve_existing_pause(
            illness_pause, self.latest_illness_pause(), today
        )
        calendar_signals, events_by_date = _calendar_context(
            self._external_calendar_reader.list_events(1000),
            today=today,
            today_date=today_date,
            window_days=self._limits.external_calendar_window_days,
        )
        signals.extend(calendar_signals)
        drafts = self._planned_unit_service.list(
            MAX_PREVIEW_PLANNED_UNITS + 1, future_only=True
        )
        if len(drafts) > MAX_PREVIEW_PLANNED_UNITS:
            raise AppError(
                409,
                f"Es gibt mehr als {MAX_PREVIEW_PLANNED_UNITS} zukünftige lokale "
                "Einheiten; die adaptive Vorschau kann nicht vollständig erstellt werden. "
                "Bitte zuerst nicht mehr benötigte Einheiten archivieren.",
            )
        run_caps = self._run_caps() if self._run_caps else None
        return_block = self._illness_return_block(today_date, feedback, illness_pause)
        return_stage = (
            illness_return.enforced_stage(return_block["state_after"])
            if return_block
            else None
        )
        if return_block:
            signals.append(
                f"illness return: stage {return_block['stage']} "
                f"({return_block['action']})"
            )
        changes = [
            change
            for draft in drafts
            if (
                change := _change(
                    draft,
                    today=today,
                    today_date=today_date,
                    feedback=feedback,
                    illness_pause=illness_pause,
                    events_by_date=events_by_date,
                    weather_days=weather_days,
                    weather_adaptive_max_minutes=self._limits.weather_adaptive_max_minutes,
                    run_caps=run_caps,
                    return_stage=return_stage,
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
        elif return_block:
            message = (
                f"Rückkehr nach Krankheit: Stufe {return_block['stage']} "
                f"({return_block['stage_label']}). {change_message}"
            )
        else:
            message = change_message
        preview = {
            "generated_at": self._now(),
            "checkin_date": feedback.get("checkin_date") or today,
            "signals": signals,
            "changes": changes,
            "illness_pause": illness_pause,
            "illness_return": return_block,
            "weather_forecast": _forecast_freshness(weather),
            "message": message,
            "scope": (
                "Zeit-, Schmerz- und Belastungsangaben des Check-ins gelten nur "
                "am Check-in-Tag. Nur nach Bestätigung werden lokale zukünftige Einheiten angepasst "
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
