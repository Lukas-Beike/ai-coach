"""Session-RPE load (M1): elapsed minutes × whole-session RPE, in arbitrary units.

Evidence card: ``docs/performance-methods/m1-session-rpe-load.md``. The rating
is the athlete's local feedback ``session_rpe`` of the canonical session; only
without one, the provider RPE of that session is a labelled fallback, never
averaged with it. Provider ratings that disagree within one session give no
value. The duration is the session's elapsed duration; a session with only a
moving time gets no value. RPE 0 is valid, a missing RPE is unknown. Sums keep
the known partial value and the count of rated and open sessions; values are
rounded only for output. AU are never added to TSS, Garmin load or TRIMP.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any, Final

from backend.canonical.activity_summary import (
    ActivitySummary,
    stored_activity_key,
    summary_local_date,
)

METRIC_ID: Final = "session_rpe_load"
METHOD_ID: Final = "session-rpe-load"
METHOD_VERSION: Final = 1
UNIT: Final = "AU"
EVIDENCE_CARD: Final = "docs/performance-methods/m1-session-rpe-load.md"
SOURCE_ATHLETE: Final = "athlete_feedback"
SOURCE_PROVIDER: Final = "provider"
ATHLETE_LABEL: Final = "Athletenfeedback"
METHOD_NOTE: Final = (
    "Session-RPE load (Foster): elapsed minutes of the whole session × the "
    "athlete's global session RPE 0-10, in arbitrary units (AU). Local feedback "
    "first; only without it the provider RPE of the same session, labelled."
)
LIMITS: Final = (
    "Descriptive subjective load only. Never convert or add AU to TSS, "
    "Intervals.icu or Garmin load or TRIMP; no injury risk, overtraining, "
    "readiness or ramp statement. Unrated sessions and days without records are "
    "unknown, not zero. Ratings follow the about-30-minutes protocol only where "
    "rated_minutes_after_end shows it; otherwise the rating time is unknown."
)

# Why a session has no value.
REASON_NO_RATING: Final = "no_rating"
REASON_CONFLICTING_PROVIDER_RATINGS: Final = "conflicting_provider_ratings"
REASON_NO_ELAPSED_DURATION: Final = "no_elapsed_duration"
REASON_INVALID_DURATION: Final = "invalid_duration"

type FeedbackLookup = Callable[[list[str]], list[dict[str, Any]]]


def _finite(value: Any) -> float | None:
    if type(value) not in {int, float}:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _rating(
    summary: Mapping[str, Any], feedback: Mapping[str, Any] | None
) -> tuple[float, str, str] | str:
    """The session's RPE with its source and label, or the reason it has none."""
    local = _finite((feedback or {}).get("session_rpe"))
    if local is not None:
        return local, SOURCE_ATHLETE, ATHLETE_LABEL
    if summary.get("rpe_conflict"):
        return REASON_CONFLICTING_PROVIDER_RATINGS
    provider = _finite(summary.get("rpe"))
    if provider is None:
        return REASON_NO_RATING
    label = str((summary.get("sources") or {}).get("rpe") or "Provider")
    return provider, SOURCE_PROVIDER, label


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _minutes_after_end(
    summary: Mapping[str, Any], elapsed_s: float, rated_at: Any
) -> int | None:
    started, rated = _parse_time(summary.get("started_at")), _parse_time(rated_at)
    if started is None or rated is None:
        return None
    end = started + timedelta(seconds=elapsed_s)
    return round((rated - end).total_seconds() / 60)


def session_load(
    summary: Mapping[str, Any],
    feedback: Mapping[str, Any] | None,
    timezone: str | None = None,
) -> tuple[dict[str, Any], float | None]:
    """One session's output entry and its unrounded AU, or ``None`` with a reason."""
    rating = _rating(summary, feedback)
    rpe, source, label = (None, None, None) if isinstance(rating, str) else rating
    raw_elapsed = _finite(summary.get("elapsed_duration_s"))
    elapsed = raw_elapsed if raw_elapsed is not None and raw_elapsed > 0 else None
    value: float | None = None
    reason: str | None = None
    if isinstance(rating, str):
        reason = rating
    elif raw_elapsed is None:
        reason = REASON_NO_ELAPSED_DURATION
    elif elapsed is None:
        reason = REASON_INVALID_DURATION
    elif rpe is not None:
        value = elapsed / 60 * rpe
    rated_after_end = None
    if source == SOURCE_ATHLETE and elapsed is not None:
        rated_after_end = _minutes_after_end(
            summary, elapsed, (feedback or {}).get("session_rpe_rated_at")
        )
    entry: dict[str, Any] = {
        "activity_id": summary.get("id"),
        "date": summary_local_date(summary, timezone),
        "name": str(summary.get("name") or "")[:200],
        "sport": summary.get("sport"),
        "value": None if value is None else round(value, 1),
        "rpe": rpe,
        "rpe_source": source,
        "rpe_source_label": label,
        "duration_min": None if elapsed is None else round(elapsed / 60, 1),
        "rated_minutes_after_end": rated_after_end,
        "status": "descriptive" if value is not None else "insufficient_data",
        "reason": reason,
    }
    return entry, value


def _period(loads: Sequence[tuple[dict[str, Any], float | None]]) -> dict[str, Any]:
    known = [value for _entry, value in loads if value is not None]
    sources = {SOURCE_ATHLETE: 0, SOURCE_PROVIDER: 0}
    for entry, value in loads:
        if value is not None:
            sources[entry["rpe_source"]] += 1
    return {
        "value": round(math.fsum(known), 1) if known else None,
        "rated_sessions": len(known),
        "total_sessions": len(loads),
        "rpe_sources": sources,
    }


def _days(start: date, end: date) -> Iterable[date]:
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def feedback_by_session(
    summaries: Sequence[Mapping[str, Any]], read: FeedbackLookup | None
) -> dict[str, dict[str, Any]]:
    """The effective feedback of each summary's session, keyed by its stored key.

    ``read`` must return only feedback assigned to a session: a rating whose
    session is ambiguous is excluded from the load.
    """
    keys = [key for summary in summaries if (key := stored_activity_key(summary))]
    if read is None or not keys:
        return {}
    return {str(item["activity_id"]): item for item in read(keys)}


def session_rpe_load(
    summaries: Sequence[ActivitySummary],
    feedback: Mapping[str, Mapping[str, Any]],
    *,
    start: date,
    end: date,
    timezone: str,
    computed_at: str | None = None,
    session_limit: int = 100,
) -> dict[str, Any]:
    """Session-RPE load per session, local day, ISO week and sport of a period.

    ``feedback`` maps a summary's stored key to its effective feedback. Each
    canonical session counts once; days and weeks list every date of the period,
    also days without a session.
    """
    loads = sorted(
        (
            session_load(summary, feedback.get(stored_activity_key(summary)), timezone)
            for summary in summaries
            if start.isoformat()
            <= summary_local_date(summary, timezone)
            <= end.isoformat()
        ),
        key=lambda item: (item[0]["date"], str(item[0]["activity_id"])),
        reverse=True,
    )
    by_day: dict[str, list[tuple[dict[str, Any], float | None]]] = {}
    by_sport: dict[str, list[tuple[dict[str, Any], float | None]]] = {}
    for item in loads:
        by_day.setdefault(item[0]["date"], []).append(item)
        by_sport.setdefault(str(item[0]["sport"] or "unknown"), []).append(item)
    weeks = []
    monday = start - timedelta(days=start.weekday())
    while monday <= end:
        sunday = monday + timedelta(days=6)
        weeks.append(
            {
                "start": monday.isoformat(),
                "end": sunday.isoformat(),
                "partial_period": monday < start or sunday > end,
                **_period(
                    [
                        item
                        for item in loads
                        if monday.isoformat() <= item[0]["date"] <= sunday.isoformat()
                    ]
                ),
            }
        )
        monday += timedelta(days=7)
    totals = _period(loads)
    return {
        "metric_id": METRIC_ID,
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "unit": UNIT,
        "status": "descriptive" if totals["rated_sessions"] else "insufficient_data",
        "period": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": timezone,
        },
        "computed_at": computed_at,
        "method": METHOD_NOTE,
        "limits": LIMITS,
        "evidence_card": EVIDENCE_CARD,
        "totals": totals,
        "days": [
            {"date": day.isoformat(), **_period(by_day.get(day.isoformat(), []))}
            for day in _days(start, end)
        ],
        "weeks": weeks,
        "sports": {sport: _period(items) for sport, items in sorted(by_sport.items())},
        "sessions": [entry for entry, _value in loads[:session_limit]],
    }
