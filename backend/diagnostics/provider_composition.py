"""Counts-only view of which providers back the canonical sessions and domain rows.

Sessions are counted by the set of providers of their active records, domain
rows per provider, and observation kinds outside the vocabulary only as a count.

Only provider identifiers, table names and counts leave this module. Other stored
provider text is reported as ``other``, so no ids, names, dates or values are
carried.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Final

from backend.canonical.vocabulary import MetricKind, ProviderId, Sport

_OTHER: Final = "other"
_PROVIDERS: Final = frozenset(provider.value for provider in ProviderId)
_METRICS: Final = frozenset(metric.value for metric in MetricKind)
_SPORTS: Final = frozenset(sport.value for sport in Sport)
# Domain tables projected per provider; each is reported as active rows per
# provider. A NULL provider is a local row.
_DOMAIN_TABLES: Final = ("sleep_periods", "zone_configurations", "power_curve_points")
_DOMAIN_ROWS: Final = {
    table: f"SELECT provider, COUNT(*) AS count FROM {table} "
    "WHERE state = 'active' GROUP BY provider"
    for table in _DOMAIN_TABLES
}

# Active records of surviving sessions. Aliases resolve one level through
# ``merged_into``; aliases never chain.
_SESSION_RECORDS: Final = """
    SELECT COALESCE(s.merged_into, s.activity_id) AS session_id,
           r.provider AS provider
    FROM activity_records r
    JOIN activity_sessions s ON s.activity_id = r.activity_id
    JOIN activity_sessions t ON t.activity_id = COALESCE(s.merged_into, s.activity_id)
    WHERE r.state = 'active' AND t.state <> 'deleted'
"""

# The stored metric and sport pairs; a NULL sport is the empty text.
_OBSERVATION_KINDS: Final = """
    SELECT DISTINCT metric, COALESCE(sport, '') AS sport
    FROM observations WHERE state = 'active'
"""


def summarize_provider_composition(db: Any) -> dict[str, Any]:
    """Return session, observation and domain row counts by providing source.

    A failing query must not break the diagnostics report, so any failure yields
    ``{"status": "unavailable"}`` and nothing about the failure is kept.
    """
    try:
        return {
            "status": "available",
            "sessions": _sessions(db),
            "observations": _observations(db),
            "domain_rows": {table: _domain_rows(db, table) for table in _DOMAIN_TABLES},
        }
    except Exception:  # noqa: BLE001 - a failing count must not break diagnostics.
        return {"status": "unavailable"}


def _sessions(db: Any) -> dict[str, Any]:
    providers: dict[str, set[str]] = {}
    for row in db.execute(_SESSION_RECORDS).fetchall():
        providers.setdefault(row["session_id"], set()).add(
            _known(row["provider"], _PROVIDERS)
        )
    return {
        "total": len(providers),
        "by_providers": _sorted(
            Counter("+".join(sorted(members)) for members in providers.values())
        ),
    }


def _observations(db: Any) -> dict[str, Any]:
    """Count the stored observation kinds outside the vocabulary, never naming them."""
    unrecognized = sum(
        1 for row in db.execute(_OBSERVATION_KINDS).fetchall() if _kind(row) is None
    )
    return {"unrecognized_kinds": unrecognized}


def _domain_rows(db: Any, table: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in db.execute(_DOMAIN_ROWS[table]).fetchall():
        counts[_known(row["provider"], _PROVIDERS, local=True)] += row["count"]
    return _sorted(counts)


def _kind(row: Any) -> str | None:
    """Return ``metric`` or ``metric/sport``; None for text outside the vocabulary."""
    metric, sport = row["metric"], row["sport"]
    if metric not in _METRICS or (sport and sport not in _SPORTS):
        return None
    return metric if not sport else f"{metric}/{sport}"


def _known(value: Any, allowed: frozenset[str], *, local: bool = False) -> str:
    if value is None and local:
        return "local"
    return value if value in allowed else _OTHER


def _sorted(counts: Any) -> dict[str, int]:
    return {key: counts[key] for key in sorted(counts)}
