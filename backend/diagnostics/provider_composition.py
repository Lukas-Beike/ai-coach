"""Counts-only view of which providers back the canonical sessions and observations.

It shows how much history only Intervals.icu holds: sessions whose every active
record comes from Intervals.icu, by year and by the Intervals.icu ``source`` of
those records, and the observation kinds no other source holds on a given day.

Only provider identifiers, Intervals.icu source enum values, years, metric and
sport identifiers, table names and counts leave this module. Any other stored
text is reported as ``other``, so no ids, names, dates or values are carried.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Final

from backend.canonical.vocabulary import MetricKind, ProviderId, Sport

_INTERVALS: Final = ProviderId.INTERVALS.value
_OTHER: Final = "other"
_UNKNOWN: Final = "unknown"
_PROVIDERS: Final = frozenset(provider.value for provider in ProviderId)
_METRICS: Final = frozenset(metric.value for metric in MetricKind)
_SPORTS: Final = frozenset(sport.value for sport in Sport)
# The ``source`` enum of the Intervals.icu Activity schema (GET /api/v1/docs).
_INTERVALS_SOURCES: Final = frozenset(
    (
        "STRAVA",
        "UPLOAD",
        "MANUAL",
        "GARMIN_CONNECT",
        "OAUTH_CLIENT",
        "DROPBOX",
        "POLAR",
        "SUUNTO",
        "COROS",
        "WAHOO",
        "ZWIFT",
        "ZEPP",
        "CONCEPT2",
        "HUAWEI",
    )
)
# Domain tables projected per provider; each is reported as active rows per
# provider. A NULL provider is a local row.
_DOMAIN_TABLES: Final = ("sleep_periods", "zone_configurations", "power_curve_points")
_DOMAIN_ROWS: Final = {
    table: f"SELECT provider, COUNT(*) AS count FROM {table} "
    "WHERE state = 'active' GROUP BY provider"
    for table in _DOMAIN_TABLES
}

# Active records of surviving sessions. Aliases resolve one level through
# ``merged_into``; aliases never chain. Only Intervals.icu raw payloads are read,
# and only their ``source`` value.
_SESSION_RECORDS: Final = """
    SELECT COALESCE(s.merged_into, s.activity_id) AS session_id,
           substr(COALESCE(t.local_date, t.started_at), 1, 4) AS year,
           r.provider AS provider,
           json_extract(p.payload, '$.source') AS source
    FROM activity_records r
    JOIN activity_sessions s ON s.activity_id = r.activity_id
    JOIN activity_sessions t ON t.activity_id = COALESCE(s.merged_into, s.activity_id)
    LEFT JOIN provider_records p
      ON r.provider = 'intervals' AND p.provider = r.provider
     AND p.record_kind = 'activity' AND p.source_record_id = r.provider_activity_id
    WHERE r.state = 'active' AND t.state <> 'deleted'
"""

# Per metric and sport: the active Intervals.icu observations, and the days on
# which Intervals.icu is their only source. A NULL provider is a local value.
_OBSERVATION_DAYS: Final = """
    SELECT metric, sport, substr(observed_on, 1, 4) AS year,
           SUM(from_intervals) AS intervals_days,
           SUM(from_intervals AND NOT from_other) AS only_days,
           SUM(from_other) AS other_days
    FROM (
        SELECT metric, COALESCE(sport, '') AS sport, observed_on,
               MAX(provider IS 'intervals') AS from_intervals,
               MAX(provider IS NOT 'intervals') AS from_other
        FROM observations WHERE state = 'active'
        GROUP BY metric, COALESCE(sport, ''), observed_on
    )
    GROUP BY metric, sport, year
"""


def summarize_provider_composition(db: Any) -> dict[str, Any]:
    """Return session, observation and domain row counts by providing source."""
    return {
        "sessions": _sessions(db),
        "observations": _observations(db),
        "domain_rows": {table: _domain_rows(db, table) for table in _DOMAIN_TABLES},
    }


def _sessions(db: Any) -> dict[str, Any]:
    providers: dict[str, set[str]] = {}
    sources: dict[str, set[str]] = {}
    years: dict[str, str] = {}
    for row in db.execute(_SESSION_RECORDS).fetchall():
        session_id = row["session_id"]
        provider = _known(row["provider"], _PROVIDERS)
        providers.setdefault(session_id, set()).add(provider)
        years[session_id] = _year(row["year"])
        if provider == _INTERVALS:
            sources.setdefault(session_id, set()).add(_source(row["source"]))
    by_year: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    by_year_and_source: dict[str, Counter[str]] = {}
    for session_id, members in providers.items():
        if members != {_INTERVALS}:
            continue
        source = "+".join(sorted(sources[session_id]))
        by_year[years[session_id]] += 1
        by_source[source] += 1
        by_year_and_source.setdefault(years[session_id], Counter())[source] += 1
    return {
        "total": len(providers),
        "by_providers": _sorted(
            Counter("+".join(sorted(members)) for members in providers.values())
        ),
        "intervals_only": {
            "total": sum(by_year.values()),
            "by_year": _sorted(by_year),
            "by_source": _sorted(by_source),
            "by_year_and_source": {
                year: _sorted(counts)
                for year, counts in sorted(by_year_and_source.items())
            },
        },
    }


def _observations(db: Any) -> dict[str, Any]:
    """Count Intervals.icu observation days, and those no other source holds."""
    totals: dict[str, Counter[str]] = {}
    only_by_year: dict[str, Counter[str]] = {}
    for row in db.execute(_OBSERVATION_DAYS).fetchall():
        kind = _kind(row)
        counts = totals.setdefault(kind, Counter())
        counts["intervals_days"] += row["intervals_days"]
        counts["intervals_only_days"] += row["only_days"]
        counts["other_days"] += row["other_days"]
        if row["only_days"]:
            only_by_year.setdefault(kind, Counter())[_year(row["year"])] += row[
                "only_days"
            ]
    intervals_kinds = {
        kind: counts for kind, counts in totals.items() if counts["intervals_days"]
    }
    return {
        "only_from_intervals": sorted(
            kind for kind, counts in intervals_kinds.items() if not counts["other_days"]
        ),
        "by_kind": {
            kind: {
                "intervals_days": counts["intervals_days"],
                "intervals_only_days": counts["intervals_only_days"],
                "other_days": counts["other_days"],
                "intervals_only_days_by_year": _sorted(only_by_year.get(kind, {})),
            }
            for kind, counts in sorted(intervals_kinds.items())
        },
    }


def _domain_rows(db: Any, table: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in db.execute(_DOMAIN_ROWS[table]).fetchall():
        counts[_known(row["provider"], _PROVIDERS, local=True)] += row["count"]
    return _sorted(counts)


def _kind(row: Any) -> str:
    """Return ``metric`` or ``metric/sport``; unknown text is ``other``."""
    metric = _known(row["metric"], _METRICS)
    sport = row["sport"]
    return metric if not sport else f"{metric}/{_known(sport, _SPORTS)}"


def _known(value: Any, allowed: frozenset[str], *, local: bool = False) -> str:
    if value is None and local:
        return "local"
    return value if value in allowed else _OTHER


def _source(value: Any) -> str:
    if value is None:
        return _UNKNOWN
    if isinstance(value, str) and value.strip().upper() in _INTERVALS_SOURCES:
        return value.strip().upper()
    return _OTHER


def _year(value: Any) -> str:
    if isinstance(value, str) and len(value) == 4 and value.isdigit():
        return value
    return _UNKNOWN


def _sorted(counts: Any) -> dict[str, int]:
    return {key: counts[key] for key in sorted(counts)}
