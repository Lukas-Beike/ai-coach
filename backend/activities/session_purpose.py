"""Session purpose and the link of completed races to stored competitions.

A session's ``purpose`` comes from its records: RACE when any record says so
(an athlete marks a race in one place), else the first purpose in derived order.
Garmin's event type is the only provider source (#1678).

``with_competitions`` links each stored competition to the sessions of its local
date and sport when it reads them; nothing is stored. Indoor (indoor, virtual)
and outdoor must agree when both are known. Each competition links the provider
RACE nearest its start. A day without a provider RACE gets a RACE hint from the
competition: the session nearest the competition's local start time (a stored
midnight counts as unknown), else the longest one, then the earliest; with a
planned duration it must last at least half of it. A commute, warm-up or
cool-down is never a candidate. A session links to at most one competition.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, time
from typing import Any, Final

from backend.canonical.activity_summary import summary_duration_s, summary_local_date
from backend.canonical.records import ActivityRecord
from backend.canonical.stored_sports import resolve_competition_sport
from backend.canonical.vocabulary import ActivityPurpose, Environment

COMPETITION_SOURCE_LABEL: Final = "Lokale Wettkämpfe"
# A hint needs at least this share of the competition's planned duration.
MIN_HINT_SHARE_OF_PLANNED: Final = 0.5
_INDOOR: Final = frozenset({Environment.INDOOR.value, Environment.VIRTUAL.value})
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
    returned unchanged; the input objects are never modified. ``summaries``
    must hold every session of each competition day.
    """
    result = list(summaries)
    days: dict[tuple[str, str], list[int]] = {}
    for index, summary in enumerate(result):
        key = (summary_local_date(summary), str(summary.get("sport") or ""))
        days.setdefault(key, []).append(index)
    linked: set[int] = set()
    for competition in sorted(competitions, key=_competition_order):
        match = _match(result, days, competition, linked)
        if match is None:
            continue
        summary = dict(result[match])
        summary["competition_id"] = str(competition["id"])
        if summary.get("purpose") != ActivityPurpose.RACE.value:
            summary["purpose"] = ActivityPurpose.RACE.value
            summary["sources"] = {
                **summary.get("sources", {}),
                "purpose": COMPETITION_SOURCE_LABEL,
            }
        result[match] = summary
        linked.add(match)
    return result


def _match(
    summaries: Sequence[Mapping[str, Any]],
    days: Mapping[tuple[str, str], list[int]],
    competition: Mapping[str, Any],
    linked: set[int],
) -> int | None:
    stored = resolve_competition_sport(
        competition.get("sport"), competition.get("environment")
    )
    day = str(competition.get("event_date") or "")[:10]
    if stored is None or not day:
        return None
    indoor = _indoor(stored.environment.value)
    candidates = [
        index
        for index in days.get((day, stored.sport.value), ())
        if summaries[index].get("purpose") not in _NOT_RACE_CANDIDATES
        and (
            indoor is None
            or _indoor(summaries[index].get("environment")) in {None, indoor}
        )
    ]
    start = _competition_start(competition.get("starts_at_local"))
    races = [
        index
        for index in candidates
        if summaries[index].get("purpose") == ActivityPurpose.RACE.value
    ]
    if races:
        # A day with provider races never gets a hint; each competition takes
        # the nearest race not yet linked.
        free = [index for index in races if index not in linked]
        return min(free, key=lambda i: _rank(summaries[i], start)) if free else None
    planned = _number(competition.get("planned_duration_s"))
    plausible = [
        index
        for index in candidates
        if index not in linked
        and (
            planned is None
            or (summary_duration_s(summaries[index]) or 0.0)
            >= planned * MIN_HINT_SHARE_OF_PLANNED
        )
    ]
    if not plausible:
        return None
    return min(plausible, key=lambda i: _rank(summaries[i], start))


def _rank(
    summary: Mapping[str, Any], start: datetime | None
) -> tuple[float, float, str]:
    began = _local_start(summary.get("started_at_local"))
    if start is None:
        distance = 0.0
    elif began is None:
        distance = math.inf
    else:
        distance = abs((began - start).total_seconds())
    return (
        distance,
        -(summary_duration_s(summary) or 0.0),
        str(summary.get("started_at") or ""),
    )


def _competition_start(value: Any) -> datetime | None:
    """Return the competition's local start; a stored midnight means unknown."""
    start = _local_start(value)
    return None if start is None or start.time() == time() else start


def _local_start(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) < 16:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def _indoor(environment: Any) -> bool | None:
    if environment in _INDOOR:
        return True
    return False if environment == Environment.OUTDOOR.value else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    return float(value)


def _competition_order(competition: Mapping[str, Any]) -> tuple[str, str]:
    return str(competition.get("event_date") or ""), str(competition.get("id") or "")
