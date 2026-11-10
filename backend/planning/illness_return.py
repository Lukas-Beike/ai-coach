"""Stepwise return to training after an approved illness pause (#2042).

Athlete decision: after the pause window three stages follow, stage 1 easy only,
stage 2 easy and moderate, stage 3 the normal plan. A stage lasts at least two
days. One stage is gained per morning when the check-in reports no complaint and
a normal body feel, the overnight HRV is not below the athlete's usual range and
the resting heart rate is at most 5 bpm above the usual value. A poor sign holds
the stage, a new complaint steps back one stage. A missing overnight value leaves
the check-in alone to decide. A step is a previewed local proposal; the stage
state lives in the payload of the applied adjustment. No I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Final

from backend.athlete.checkins import reports_complaint
from backend.canonical.vocabulary import ProviderId
from backend.providers.source_labels import SourceView, provider_label

LAST_STAGE: Final = 3
MIN_STAGE_DAYS: Final = 2
# Resting heart rate above the usual value by more than this holds the stage.
RESTING_HR_MARGIN_BPM: Final = 5
# Check-in soreness (0-10) up to this value is a normal body feel.
NORMAL_SORENESS_MAX: Final = 5
# Sessions of the stage limit are held for today and the days up to the earliest
# possible advance; later days are judged when a stage is gained.
RETURN_HORIZON_DAYS: Final = MIN_STAGE_DAYS
# A return nobody advanced for this long after the pause is no longer enforced.
RETURN_MAX_DAYS: Final = 28
HISTORY_LIMIT: Final = 20
CHECKIN_SOURCE: Final = "Check-in (lokal)"
GARMIN_SOURCE: Final = provider_label(ProviderId.GARMIN, SourceView.DAILY_HEALTH)
# Highest session level a stage allows: 0 easy, 1 moderate, 2 hard (normal plan).
STAGE_MAX_LEVEL: Final = {1: 0, 2: 1, 3: 2}
STAGE_LABELS: Final = {
    1: "nur lockere Einheiten",
    2: "lockere und moderate Einheiten",
    3: "normaler Plan",
}


def initial_state(pause: Mapping[str, Any]) -> dict[str, Any]:
    """Stage 1 from the day after the pause window."""
    end = date.fromisoformat(str(pause["end_date"]))
    return {
        "pause_end": end.isoformat(),
        "stage": 1,
        "since": (end + timedelta(days=1)).isoformat(),
        "history": [],
    }


def current_state(
    pause: Mapping[str, Any] | None, stored: Mapping[str, Any] | None, today: date
) -> dict[str, Any] | None:
    """The return state while one is running after an approved pause, else None."""
    if not pause or not pause.get("approved") or not pause.get("end_date"):
        return None
    end = date.fromisoformat(str(pause["end_date"]))
    if not end < today <= end + timedelta(days=RETURN_MAX_DAYS):
        return None
    if stored and stored.get("pause_end") == end.isoformat():
        return dict(stored)
    return initial_state(pause)


def enforced_stage(state: Mapping[str, Any] | None) -> int | None:
    """The stage whose limit applies; None without a return or at the normal plan."""
    if not state or int(state["stage"]) >= LAST_STAGE:
        return None
    return int(state["stage"])


def _evidence(
    source: str, label: str, value: Any, ok: bool | None, **extra: Any
) -> dict[str, Any]:
    return {"source": source, "label": label, "value": value, "ok": ok, **extra}


def _checkin_signs(checkin: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    complaint = reports_complaint(checkin.get("pain")) or reports_complaint(
        checkin.get("illness")
    )
    evidence = [_evidence(CHECKIN_SOURCE, "complaint", complaint, not complaint)]
    soreness = checkin.get("soreness")
    if isinstance(soreness, int | float):
        evidence.append(
            _evidence(
                CHECKIN_SOURCE,
                "soreness",
                soreness,
                soreness <= NORMAL_SORENESS_MAX,
            )
        )
    return evidence, complaint


def _hrv_sign(item: Mapping[str, Any] | None) -> dict[str, Any]:
    if not item:
        return _evidence(GARMIN_SOURCE, "hrv", None, None, missing=True)
    return _evidence(
        str(item.get("source") or GARMIN_SOURCE),
        "hrv",
        item.get("value"),
        item.get("position") != "below",
        unit=item.get("unit"),
        lower=item.get("lower"),
        observed_at=item.get("observed_at"),
    )


def _resting_hr_sign(item: Mapping[str, Any] | None) -> dict[str, Any]:
    if not item:
        return _evidence(GARMIN_SOURCE, "resting_hr", None, None, missing=True)
    value, usual = item.get("value"), item.get("median")
    if value is None or usual is None:
        return _evidence(GARMIN_SOURCE, "resting_hr", None, None, missing=True)
    ok = value - usual <= RESTING_HR_MARGIN_BPM
    return _evidence(
        str(item.get("source") or GARMIN_SOURCE),
        "resting_hr",
        value,
        ok,
        unit=item.get("unit"),
        usual=usual,
        observed_at=item.get("observed_at"),
    )


_POOR_REASONS: Final = {
    "soreness": "body_feel",
    "hrv": "hrv_below_range",
    "resting_hr": "resting_hr_high",
}


def _result(
    action: str,
    from_stage: int,
    stage: int,
    reasons: Sequence[str],
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "action": action,
        "from_stage": from_stage,
        "stage": stage,
        "reasons": list(reasons),
        "evidence": [dict(item) for item in evidence],
    }


def decide(
    state: Mapping[str, Any],
    today: date,
    checkin: Mapping[str, Any] | None,
    overnight: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Advance, hold or step back for this morning; never more than one stage."""
    stage = int(state["stage"])
    if not checkin or str(checkin.get("checkin_date") or "") != today.isoformat():
        return _result("hold", stage, stage, ["no_checkin"], [])
    overnight = overnight or {}
    evidence, complaint = _checkin_signs(checkin)
    evidence += [
        _hrv_sign(overnight.get("hrv")),
        _resting_hr_sign(overnight.get("resting_hr")),
    ]
    if complaint:
        target = max(1, stage - 1)
        return _result(
            "step_back" if target < stage else "hold",
            stage,
            target,
            ["complaint"],
            evidence,
        )
    poor = [_POOR_REASONS[item["label"]] for item in evidence if item["ok"] is False]
    if poor:
        return _result("hold", stage, stage, poor, evidence)
    if stage >= LAST_STAGE:
        return _result("hold", stage, stage, ["complete"], evidence)
    if (today - date.fromisoformat(str(state["since"]))).days < MIN_STAGE_DAYS:
        return _result("hold", stage, stage, ["stage_days"], evidence)
    return _result("advance", stage, stage + 1, [], evidence)


def state_after(
    state: Mapping[str, Any], decision: Mapping[str, Any], today: date
) -> dict[str, Any]:
    """The state a decision leaves; unchanged while the stage holds."""
    if decision["stage"] == state["stage"]:
        return dict(state)
    entry = {
        "date": today.isoformat(),
        "stage": decision["stage"],
        "action": decision["action"],
    }
    return {
        **state,
        "stage": decision["stage"],
        "since": today.isoformat(),
        "history": [*state.get("history", []), entry][-HISTORY_LIMIT:],
    }
