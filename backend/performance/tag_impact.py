"""Observed tagged-day associations, requiring explicit comparison-group answers."""

from datetime import date, timedelta
from statistics import median, quantiles
from typing import Any

from backend.athlete.checkins import CHECKIN_TAGS
from backend.performance.training_report import activity_day, canonical_rows, number


def tag_impact(
    checkins: list[dict[str, Any]],
    recovery: dict[str, Any],
    snapshot: dict[str, Any],
    today: date,
    timezone: str = "UTC",
) -> dict[str, Any]:
    loads = _day_loads(snapshot, timezone)
    reports = []
    for baseline in recovery.get("baselines", []):
        history = {row["date"]: row["value"] for row in baseline["history"]}
        for tag in CHECKIN_TAGS:
            groups = _tag_groups(checkins, history, loads, tag, today)
            sufficient = all(len(group) >= 10 for group in groups.values())
            result: dict[str, Any] = {
                "tag": tag,
                "metric": baseline["metric"],
                "source": baseline["source"],
                "measurement": baseline["measurement"],
                "unit": baseline["unit"],
                "status": "observed_association" if sufficient else "insufficient_data",
                "groups": {},
            }
            for answer, group in groups.items():
                result["groups"]["with" if answer else "without"] = _group_summary(
                    group, sufficient
                )
            reports.append(result)
    measured_dates = [
        row["date"]
        for baseline in recovery.get("baselines", [])
        for row in baseline.get("history", [])
    ]
    return {
        "method": "explicit-tags-next-night-v1",
        "days": 90,
        "timezone": timezone,
        "measurement_start": min(measured_dates) if measured_dates else None,
        "measurement_end": max(measured_dates) if measured_dates else None,
        "reports": reports,
        "note": "At least 10 explicitly answered, measured days per group. Unanswered days are excluded. Day is paired with the following provider-dated night; sleep labeling must be consistent. Associations are not causal, and training load, concurrent tags and selective recording can confound results.",
    }


def _day_loads(snapshot: dict, timezone: str) -> dict[str, list[float | None]]:
    rows, _ = canonical_rows(snapshot)
    loads: dict[str, list[float | None]] = {}
    for row in rows:
        loads.setdefault(activity_day(row, timezone), []).append(
            number(row.get("icu_training_load"))
        )

    return loads


def _tag_groups(
    checkins: list[dict], history: dict, loads: dict, tag: str, today: date
) -> dict[bool, list[dict[str, Any]]]:
    cutoff = (today - timedelta(days=89)).isoformat()
    groups: dict[bool, list[dict[str, Any]]] = {True: [], False: []}
    for checkin in checkins:
        day = str(checkin.get("checkin_date") or "")
        answer = (checkin.get("tag_answers") or {}).get(tag)
        if type(answer) is not bool or not cutoff <= day < today.isoformat():
            continue
        following = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        if following not in history:
            continue
        measured = loads.get(day, [])
        groups[answer].append(
            {
                "date": day,
                "night_date": following,
                "value": history[following],
                "load": sum(measured)
                if measured and all(value is not None for value in measured)
                else None,
                "co_tags": [
                    key
                    for key, value in (checkin.get("tag_answers") or {}).items()
                    if key != tag and value is True
                ],
            }
        )

    return groups


def _group_summary(group: list[dict], sufficient: bool) -> dict[str, Any]:
    values = [row["value"] for row in group]
    load_values = [row["load"] for row in group if row["load"] is not None]
    return {
        "days": len(group),
        "median": median(values) if sufficient else None,
        "quartiles": [
            quantiles(values, n=4, method="inclusive")[0],
            quantiles(values, n=4, method="inclusive")[2],
        ]
        if sufficient
        else None,
        "load_median": median(load_values) if load_values else None,
        "load_known_days": len(load_values),
        "co_tag_days": sum(bool(row["co_tags"]) for row in group),
        "evidence": group[:50],
    }
