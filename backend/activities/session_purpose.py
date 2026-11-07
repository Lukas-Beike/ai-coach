"""Session purpose and the link of completed races to stored competitions.

A session's ``purpose`` comes from its records: RACE when any record says so
(an athlete marks a race in one place), else the first purpose in derived order.
Garmin's event type is the only provider source (#1678).

``with_competitions`` links each stored competition to the sessions of its local
date and sport when it reads them; nothing is stored. Sessions a provider marks
as RACE are linked. Without such a session, the best candidate becomes a RACE
hint from the competition: the session that starts nearest the competition's
local start time, else the longest one, then the earliest. A commute, warm-up
or cool-down is never a candidate. A session links to at most one competition.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from backend.canonical.activity_summary import summary_duration_s, summary_local_date
from backend.canonical.records import ActivityRecord
from backend.canonical.stored_sports import resolve_competition_sport
from backend.canonical.vocabulary import ActivityPurpose

COMPETITION_SOURCE_LABEL: Final = "Lokale Wettkämpfe"
_NOT_RACE_CANDIDATES: Final = frozenset(
    {
        ActivityPurpose.COMMUTE.value,
        ActivityPurpose.WARMUP.value,
        ActivityPurpose.COOLDOWN.value,
    }
)


def session_purpose(
    derived: Sequence[ActivityRecord],
) -> ActivityRecord | None:
    """Return the record whose purpose the session takes, in derived order."""
    return next(
        (record for record in derived if record.purpose is ActivityPurpose.RACE),
        None,
    ) or next((record for record in derived if record.purpose is not None), None)


def with_competitions(
    summaries: Iterable[dict[str, Any]], competitions: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Link stored competitions to the summaries of their date and sport.

    Linked summaries get ``competition_id`` and, when they had no RACE purpose,
    ``purpose`` RACE with the competition source. Unlinked summaries are
    returned unchanged; the input objects are never modified.
    """
    result = list(summaries)
    linked: set[int] = set()
    for competition in sorted(competitions, key=_competition_order):
        matches = _matches(result, competition, linked)
        if not matches:
            continue
        competition_id = str(competition["id"])
        for index in matches:
            summary = dict(result[index])
            summary["competition_id"] = competition_id
            if summary.get("purpose") != ActivityPurpose.RACE.value:
                summary["purpose"] = ActivityPurpose.RACE.value
                summary["sources"] = {
                    **summary.get("sources", {}),
                    "purpose": COMPETITION_SOURCE_LABEL,
                }
            result[index] = summary
            linked.add(index)
    return result


def _matches(
    summaries: Sequence[Mapping[str, Any]],
    competition: Mapping[str, Any],
    linked: set[int],
) -> list[int]:
    stored = resolve_competition_sport(
        competition.get("sport"), competition.get("environment")
    )
    day = str(competition.get("event_date") or "")[:10]
    if stored is None or not day:
        return []
    candidates = [
        index
        for index, summary in enumerate(summaries)
        if index not in linked
        and summary.get("sport") == stored.sport.value
        and summary_local_date(summary) == day
        and summary.get("purpose") not in _NOT_RACE_CANDIDATES
    ]
    races = [
        index
        for index in candidates
        if summaries[index].get("purpose") == ActivityPurpose.RACE.value
    ]
    if races or not candidates:
        return races
    start = _local_start(competition.get("starts_at_local"))
    return [
        min(
            candidates,
            key=lambda index: _hint_rank(summaries[index], start),
        )
    ]


def _hint_rank(
    summary: Mapping[str, Any], start: datetime | None
) -> tuple[float, float, str]:
    began = _local_start(summary.get("started_at_local"))
    distance = (
        abs((began - start).total_seconds())
        if start is not None and began is not None
        else 0.0
    )
    return (
        distance,
        -(summary_duration_s(summary) or 0.0),
        str(summary.get("started_at") or ""),
    )


def _local_start(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) < 16:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def _competition_order(competition: Mapping[str, Any]) -> tuple[str, str]:
    return str(competition.get("event_date") or ""), str(competition.get("id") or "")
