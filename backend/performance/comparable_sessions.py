"""One session's execution against comparable earlier sessions of the athlete.

Comparable: earlier runs or rides of the last ``COMPARE_DAYS`` days with the
same sport, environment (indoor or outdoor) and structure, and a similar shape:
a continuous main part within ``DURATION_SHARE`` of this one, or interval
sessions within ``REP_COUNT_SPREAD`` reps whose median rep lasts within
``DURATION_SHARE`` of this one's. Fewer than ``MIN_PEERS`` of them is
``not_covered``. Values come from each session's own execution, the median of
the peers is the reference; nothing is scored, temperature is named so heat is
not read as fitness. Pure: no I/O, inputs unchanged.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Final

METHOD: Final = "comparable-sessions-v1"
COMPARE_DAYS: Final = 84
MIN_PEERS: Final = 3
MAX_LISTED: Final = 6
DURATION_SHARE: Final = 0.35
REP_COUNT_SPREAD: Final = 2
SCOPE: Final = (
    f"This session against earlier comparable sessions of the last {COMPARE_DAYS} "
    "days: same sport, indoor or outdoor and structure, a continuous main part "
    "within 35 % of this one's duration or intervals within 2 reps and 35 % of "
    "the median rep duration. difference is this session minus the peers' median, "
    "in the metric's unit (pace s/km: negative is faster). Temperatures are listed "
    "so heat is not read as a fitness change. Descriptive; at least 3 peers."
)
_METRICS: Final = {
    "continuous": ("output", "heart_rate_avg", "heart_rate_change_bpm", "cadence"),
    "interval": (
        "rep_output_mean",
        "heart_rate_end_mean",
        "recovery_drop_mean",
        "first_to_last_change_pct",
        "cadence_mean",
    ),
}


def comparable_sessions(
    records: Sequence[Mapping[str, Any]], activity_key: str
) -> dict[str, Any]:
    """Compare one session's execution with its comparable earlier sessions."""
    base = {"method": METHOD, "scope": SCOPE}
    own = next((row for row in records if row.get("activity_id") == activity_key), None)
    mine = (own or {}).get("execution_summary")
    if own is None or not isinstance(mine, Mapping):
        return _not_covered(
            base, "Keine Ausführung dieser Einheit in voller Auflösung."
        )
    try:
        day = date.fromisoformat(str(own.get("date") or ""))
    except ValueError:
        return _not_covered(base, "Datum der Einheit unbekannt.")
    first = (day - timedelta(days=COMPARE_DAYS)).isoformat()
    peers = [
        row
        for row in records
        if row is not own
        and first <= str(row.get("date") or "") < day.isoformat()
        and row.get("sport") == own.get("sport")
        and row.get("environment") == own.get("environment")
        and isinstance(row.get("execution_summary"), Mapping)
        and _similar(mine, row["execution_summary"])
    ]
    if len(peers) < MIN_PEERS:
        return _not_covered(
            base,
            f"{len(peers)} vergleichbare Einheiten in {COMPARE_DAYS} Tagen, mindestens {MIN_PEERS} nötig.",
            count=len(peers),
        )
    metrics = _METRICS.get(str(mine.get("structure")), ())
    median: dict[str, float] = {}
    difference: dict[str, float] = {}
    for metric in metrics:
        values = [
            float(row["execution_summary"][metric])
            for row in peers
            if isinstance(row["execution_summary"].get(metric), (int, float))
        ]
        if len(values) < MIN_PEERS:
            continue
        median[metric] = _rounded(statistics.median(values))
        if isinstance(mine.get(metric), (int, float)):
            difference[metric] = _rounded(float(mine[metric]) - median[metric])
    peers.sort(key=lambda row: str(row.get("date")), reverse=True)
    return {
        **base,
        "status": "ok",
        "count": len(peers),
        "window_days": COMPARE_DAYS,
        "this": {**mine, "date": own.get("date"), "avg_temp_c": own.get("avg_temp_c")},
        "median_of_peers": median,
        "difference": difference,
        "peers": [
            {
                "date": row.get("date"),
                "name": row.get("name"),
                "avg_temp_c": row.get("avg_temp_c"),
                **{
                    key: row["execution_summary"][key]
                    for key in metrics
                    if key in row["execution_summary"]
                },
            }
            for row in peers[:MAX_LISTED]
        ],
    }


def _similar(mine: Mapping[str, Any], other: Mapping[str, Any]) -> bool:
    if mine.get("structure") != other.get("structure"):
        return False
    if mine.get("output_unit") != other.get("output_unit"):
        return False
    if mine.get("structure") == "continuous":
        return _close(mine.get("main_part_s"), other.get("main_part_s"))
    count, peer_count = mine.get("rep_count"), other.get("rep_count")
    if not isinstance(count, int) or not isinstance(peer_count, int):
        return False
    return abs(count - peer_count) <= REP_COUNT_SPREAD and _close(
        mine.get("median_rep_s"), other.get("median_rep_s")
    )


def _close(value: Any, other: Any) -> bool:
    if not isinstance(value, (int, float)) or not isinstance(other, (int, float)):
        return False
    if value <= 0:
        return False
    return abs(other - value) <= DURATION_SHARE * value


def _rounded(value: float) -> float:
    return round(value) if abs(value) >= 50 else round(value, 1)


def _not_covered(base: Mapping[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    return {**base, "status": "not_covered", "reason": reason, **extra}
