"""Total ordering of canonical records, shared by the legacy projection and the tables.

Both readers must return the same sequence for the same data, so the parity check
can compare them. Every key is total for records with unique identities: activities
by (start, provider, provider activity id), observations by the components of their
natural key (provider, metric, sport, instant or day).
"""

from __future__ import annotations

from datetime import date, datetime

from backend.canonical.records import ActivityRecord, Observation


def activity_order(record: ActivityRecord) -> tuple[datetime, str, str]:
    provenance = record.provenance
    return (
        record.started_at,
        str(provenance.provider or ""),
        provenance.source_record_id or "",
    )


def observation_order(observation: Observation) -> tuple[date, str, str, str, str]:
    provenance = observation.provenance
    sport = observation.sport
    when = (
        observation.observed_at.isoformat()
        if observation.observed_at is not None
        else observation.observed_on.isoformat()
    )
    return (
        observation.observed_on,
        str(provenance.provider or ""),
        str(observation.kind),
        str(sport or ""),
        when,
    )
