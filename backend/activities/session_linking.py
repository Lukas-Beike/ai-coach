"""Persist the bundling of duplicate provider activities into canonical sessions.

After an ingest wrote activity records, the records near the touched days are
bundled with ``bundle_sessions``. For every duplicate whose session differs from its
primary's session, the younger session becomes an alias of the older one: the older
id stays valid and the other id keeps resolving through ``merged_into``.

Only the session rows change. Records keep their ``activity_id``, sessions keep
their primary provider, and nothing is re-pointed, so provider deletes still find
their own session. Sessions the athlete confirmed, hidden or deleted sessions and
sessions that are already aliases are never merged or reopened, and a merge is never
undone here. The function runs inside the caller's unit of work and is idempotent.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any, Final

from backend.activities.canonical_sessions import ActivitySession, bundle_sessions
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    ActivityLinkKind,
    ActivitySessionState,
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import canonical_store

__all__ = ["link_activity_sessions"]

LINK_MARGIN: Final = timedelta(days=1)
_LINK_STRENGTH: Final = {
    ActivityLinkKind.SINGLE.value: 0,
    ActivityLinkKind.HEURISTIC.value: 1,
    ActivityLinkKind.EXACT.value: 2,
    ActivityLinkKind.CONFIRMED.value: 3,
}
_MAX_ALIAS_DEPTH: Final = 64


def link_activity_sessions(
    db: Any, *, touched_dates: Collection[date], zone: tzinfo, now: str
) -> int:
    """Link the sessions of duplicate records near ``touched_dates``; return the merges.

    ``touched_dates`` are athlete-local dates of the activities an ingest wrote. The
    records within one day of them are bundled on the athlete's wall clock ``zone``.
    """
    if not touched_dates:
        return 0
    rows = canonical_store.linkable_activity_rows(
        db,
        start=(min(touched_dates) - LINK_MARGIN).isoformat(),
        end=(max(touched_dates) + LINK_MARGIN).isoformat(),
    )
    records = _linkable_records(rows)
    if not records:
        return 0
    session_of = {
        (str(row["provider"]), str(row["provider_activity_id"])): str(row["session_id"])
        for row in rows
    }
    sessions = _Sessions(db, set(session_of.values()))
    bundles = bundle_sessions(records, zone=zone)
    linked = 0
    for bundle in bundles:
        for primary_id, duplicate_id, kind in _pairs(bundle, session_of):
            if sessions.merge(primary_id, duplicate_id, kind, now):
                linked += 1
    return linked


def _pairs(
    bundle: ActivitySession, session_of: dict[tuple[str, str], str]
) -> Iterable[tuple[str, str, ActivityLinkKind]]:
    primary_id = session_of[_key(bundle.primary)]
    for duplicate, kind in zip(bundle.duplicates, bundle.link_kinds, strict=True):
        yield primary_id, session_of[_key(duplicate)], kind


def _linkable_records(rows: Iterable[dict[str, Any]]) -> list[ActivityRecord]:
    """Map the stored rows that carry a known vocabulary; skip the others.

    A row from a provider or with a value this build does not know (for example a
    row written by a newer build) is never linked, and it never fails the ingest.
    """
    records = []
    for row in rows:
        try:
            records.append(_record(row))
        except TypeError, ValueError:
            continue
    return records


def _record(row: dict[str, Any]) -> ActivityRecord:
    """Rebuild the record of a stored row; linking reads only the matching fields."""
    return ActivityRecord(
        activity_id=str(row["provider_activity_id"]),
        provenance=Provenance(
            provider=ProviderId(row["provider"]),
            source_kind=SourceKind(row["source_kind"]),
            source_record_id=row["source_record_id"],
            recorded_by=RecordingOrigin(row["recorded_by"]),
            retrieved_at=None,
            label=None,
        ),
        sport=Sport(row["sport"]),
        environment=Environment(row["environment"]),
        started_at=datetime.fromisoformat(str(row["started_at"])),
        duration_s=row["duration_s"],
        distance_m=row["distance_m"],
        load=row["load"],
        load_model=LoadModel(row["load_model"]),
        avg_hr=row["avg_hr"],
        avg_power=row["avg_power"],
        name=row["name"],
        moving_duration_s=row["moving_duration_s"],
        elevation_gain_m=row["elevation_gain_m"],
        normalized_power=row["normalized_power"],
        avg_cadence=row["avg_cadence"],
        energy_kj=row["energy_kj"],
    )


def _key(record: ActivityRecord) -> tuple[str, str]:
    provider = record.provenance.provider
    if provider is None:
        raise ValueError("linked activity records need a provider")
    return provider.value, record.activity_id


class _Sessions:
    """The session rows linking decides on, kept current while merges are applied."""

    def __init__(self, db: Any, session_ids: Collection[str]) -> None:
        self._db = db
        self._rows = canonical_store.activity_session_link_rows(db, sorted(session_ids))

    def merge(
        self, primary_id: str, duplicate_id: str, kind: ActivityLinkKind, now: str
    ) -> bool:
        """Merge the younger of two sessions into the older one when both may merge."""
        first = self._survivor(primary_id)
        second = self._survivor(duplicate_id)
        if first is None or second is None or first is second:
            return False
        if not (_mergeable(first) and _mergeable(second)):
            return False
        keep, drop = sorted((first, second), key=_age)
        if not canonical_store.merge_activity_session(
            self._db, activity_id=drop["activity_id"], into=keep["activity_id"], now=now
        ):
            return False
        drop["state"] = ActivitySessionState.DUPLICATE.value
        drop["merged_into"] = keep["activity_id"]
        strongest = max(
            (keep["link_kind"], drop["link_kind"], kind.value),
            key=_LINK_STRENGTH.__getitem__,
        )
        if strongest != keep["link_kind"]:
            canonical_store.set_activity_session_link_kind(
                self._db, activity_id=keep["activity_id"], link_kind=strongest, now=now
            )
            keep["link_kind"] = strongest
        return True

    def _survivor(self, session_id: str) -> dict[str, Any] | None:
        """Follow ``merged_into`` to the session that stands for ``session_id``."""
        seen: set[str] = set()
        current = session_id
        while current not in seen and len(seen) < _MAX_ALIAS_DEPTH:
            seen.add(current)
            row = self._row(current)
            if row is None:
                return None
            target = row["merged_into"]
            if row["state"] != ActivitySessionState.DUPLICATE.value or not target:
                return row
            current = str(target)
        return None

    def _row(self, session_id: str) -> dict[str, Any] | None:
        if session_id not in self._rows:
            self._rows.update(
                canonical_store.activity_session_link_rows(self._db, [session_id])
            )
        return self._rows.get(session_id)


def _mergeable(row: dict[str, Any]) -> bool:
    return (
        row["state"] == ActivitySessionState.ACTIVE.value
        and not row["athlete_confirmed"]
    )


def _age(row: dict[str, Any]) -> tuple[datetime, str]:
    """Order sessions by creation time, then id: the older one stays valid."""
    created = datetime.fromisoformat(str(row["created_at"]))
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created, str(row["activity_id"])
