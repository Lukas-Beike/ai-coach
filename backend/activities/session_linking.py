"""Persist the bundling of duplicate provider activities into canonical sessions.

After an ingest wrote activity records, the records near the touched days are
bundled with ``bundle_sessions``. For every duplicate whose session differs from its
primary's session, the younger session becomes an alias of the older one: the older
id stays valid and the other id keeps resolving through ``merged_into``.

Only the session rows change. Records keep their ``activity_id``, sessions keep
their primary provider, and nothing is re-pointed, so provider deletes still find
their own session. Sessions the athlete confirmed, hidden or deleted sessions and
sessions that are already aliases are never merged or reopened by linking;
``split_unmatched_sessions`` runs first and splits a copy off an unconfirmed session
the rules no longer bundle it with. An exact link between records already in one session upgrades its
link kind; a contradicting earlier merge is left for the diagnostics to report.
Two sessions never merge when together they would hold two active
records of one provider and recording origin: bundling assigns one to one, but a
merge persisted earlier may pair a record differently from today's bundling. The function runs inside the caller's unit of work and is idempotent.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any, Final

from backend.activities.canonical_sessions import (
    ActivitySession,
    bundle_sessions,
)
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

__all__ = [
    "link_activity_sessions",
    "session_age",
    "split_unmatched_sessions",
]

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
    upstream_rows = _upstream_rows(db, records, rows)
    rows = [*rows, *upstream_rows]
    records.extend(_linkable_records(upstream_rows))
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


def split_unmatched_sessions(
    db: Any, *, touched_dates: Collection[date], zone: tzinfo, now: str
) -> int:
    """Split copies off unconfirmed sessions they no longer match; return the splits.

    The copies of each live, unconfirmed session near ``touched_dates`` are bundled
    again on their own. A copy the rules no longer bundle with the session's own
    record becomes its own active session, for example after a provider edit or a
    mapper change. Confirmed sessions are never split, and a session whose own
    record is outside the window or unreadable is left as it is.
    """
    if not touched_dates:
        return 0
    rows = canonical_store.linkable_activity_rows(
        db,
        start=(min(touched_dates) - LINK_MARGIN).isoformat(),
        end=(max(touched_dates) + LINK_MARGIN).isoformat(),
    )
    sessions = _Sessions(db, {str(row["session_id"]) for row in rows})
    bundles: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        survivor = sessions.survivor(str(row["session_id"]))
        if survivor is not None and _mergeable(survivor):
            bundles.setdefault(str(survivor["activity_id"]), []).append(row)
    split = 0
    for survivor_id, members in bundles.items():
        detached = _unmatched(members, survivor_id, zone)
        for session_id in sorted(detached):
            split += canonical_store.detach_activity_session(
                db, activity_id=session_id, now=now
            )
        if detached and not _still_bundled(db, survivor_id):
            canonical_store.set_activity_session_link_kind(
                db,
                activity_id=survivor_id,
                link_kind=ActivityLinkKind.SINGLE.value,
                now=now,
            )
    return split


def _unmatched(
    members: Sequence[dict[str, Any]], survivor_id: str, zone: tzinfo
) -> set[str]:
    """Return the alias sessions the rules no longer bundle with the survivor."""
    session_of = {
        (str(row["provider"]), str(row["provider_activity_id"])): str(row["session_id"])
        for row in members
    }
    if len(set(session_of.values())) < 2:
        return set()
    records = _linkable_records(members)
    kept = next(
        (
            {
                session_of[_key(record)]
                for record in (bundle.primary, *bundle.duplicates)
            }
            for bundle in bundle_sessions(records, zone=zone)
            if any(
                session_of[_key(record)] == survivor_id
                for record in (bundle.primary, *bundle.duplicates)
            )
        ),
        None,
    )
    if kept is None:
        return set()
    return {session_of[_key(record)] for record in records} - kept


def _still_bundled(db: Any, survivor_id: str) -> bool:
    """Whether the survivor still bundles the record of another session."""
    return (
        len(
            {
                row["session_id"]
                for row in canonical_store.session_member_rows(db, survivor_id)
            }
        )
        > 1
    )


def _upstream_rows(
    db: Any, records: Sequence[ActivityRecord], rows: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return the stored upstream records the copies name but the window missed.

    They join bundling whatever their date or session state, so a copy whose
    upstream sits in a confirmed or hidden session is not left to the heuristics;
    the merge itself still refuses protected sessions.
    """
    loaded = {(str(row["provider"]), str(row["provider_activity_id"])) for row in rows}
    wanted: dict[str, list[str]] = {}
    for record in records:
        ref = record.external_ref
        if ref is not None and (ref.upstream.value, ref.upstream_id) not in loaded:
            wanted.setdefault(ref.upstream.value, []).append(ref.upstream_id)
    return [
        row
        for provider, ids in sorted(wanted.items())
        for row in canonical_store.provider_activity_record_rows(db, provider, ids)
    ]


def _pairs(
    bundle: ActivitySession, session_of: dict[tuple[str, str], str]
) -> Iterable[tuple[str, str, ActivityLinkKind]]:
    """Yield (session, duplicate session, kind); an exact duplicate joins its copy."""
    primary_id = session_of[_key(bundle.primary)]
    members = (bundle.primary, *bundle.duplicates)
    for duplicate, kind in zip(bundle.duplicates, bundle.link_kinds, strict=True):
        target = primary_id
        if kind is ActivityLinkKind.EXACT:
            target = next(
                (
                    session_of[_key(copy)]
                    for copy in members
                    if copy.external_ref is not None
                    and copy.external_ref.upstream is duplicate.provenance.provider
                    and copy.external_ref.upstream_id == duplicate.activity_id
                ),
                primary_id,
            )
        yield target, session_of[_key(duplicate)], kind


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
        elapsed_duration_s=canonical_store.activity_elapsed_duration(row["details"]),
        max_hr=canonical_store.activity_max_hr(row["details"]),
        max_speed_mps=canonical_store.activity_max_speed(row["details"]),
        max_power_w=canonical_store.activity_max_power(row["details"]),
        min_hr=canonical_store.activity_min_hr(row["details"]),
        elevation_high_m=canonical_store.activity_elevation_high(row["details"]),
        elevation_low_m=canonical_store.activity_elevation_low(row["details"]),
        steps=canonical_store.activity_steps(row["details"]),
        device_type=canonical_store.activity_device_type(row["details"]),
        external_ref=canonical_store.activity_external_ref(row["details"]),
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
        self._origins: dict[str, set[tuple[str, str]]] = {}

    def merge(
        self, primary_id: str, duplicate_id: str, kind: ActivityLinkKind, now: str
    ) -> bool:
        """Merge the younger of two sessions into the older one when both may merge.

        Two records already in one session only strengthen its link kind, so an
        exact link confirms an earlier heuristic merge.
        """
        first = self.survivor(primary_id)
        second = self.survivor(duplicate_id)
        if first is None or second is None:
            return False
        if first is second:
            if _mergeable(first):
                self._strengthen(first, kind.value, now)
            return False
        self._follow_athlete_delete(first, second, now)
        if not (_mergeable(first) and _mergeable(second)):
            return False
        if self._origins_of(first) & self._origins_of(second):
            return False
        keep, drop = sorted((first, second), key=session_age)
        if not canonical_store.merge_activity_session(
            self._db, activity_id=drop["activity_id"], into=keep["activity_id"], now=now
        ):
            return False
        self._origins_of(keep).update(self._origins_of(drop))
        drop["state"] = ActivitySessionState.DUPLICATE.value
        drop["merged_into"] = keep["activity_id"]
        self._strengthen(
            keep,
            max((drop["link_kind"], kind.value), key=_LINK_STRENGTH.__getitem__),
            now,
        )
        return True

    def _follow_athlete_delete(
        self, first: dict[str, Any], second: dict[str, Any], now: str
    ) -> None:
        """Delete a new copy of an activity the athlete deleted, as that activity.

        Only an exact link reaches a deleted session (``_upstream_rows``), so a
        provider's copy of a deleted recording does not bring the activity back.
        """
        for gone, other in ((first, second), (second, first)):
            if (
                gone["state"] == ActivitySessionState.DELETED.value
                and _mergeable(other)
                and canonical_store.athlete_deleted_session(
                    self._db, gone["activity_id"]
                )
                and canonical_store.delete_with_athlete_deleted(
                    self._db,
                    activity_id=other["activity_id"],
                    deleted=str(gone["merged_into_retained"]),
                    now=now,
                )
            ):
                other["state"] = ActivitySessionState.DELETED.value
                other["merged_into_retained"] = gone["merged_into_retained"]

    def _strengthen(self, row: dict[str, Any], link_kind: str, now: str) -> None:
        if _LINK_STRENGTH[link_kind] <= _LINK_STRENGTH[row["link_kind"]]:
            return
        canonical_store.set_activity_session_link_kind(
            self._db, activity_id=row["activity_id"], link_kind=link_kind, now=now
        )
        row["link_kind"] = link_kind

    def _origins_of(self, row: dict[str, Any]) -> set[tuple[str, str]]:
        """Return the (provider, recording origin) pairs of a survivor's active records."""
        session_id = str(row["activity_id"])
        if session_id not in self._origins:
            self._origins[session_id] = {
                (str(record["provider"]), str(record["recorded_by"]))
                for record in canonical_store.session_activity_rows(
                    self._db, session_id
                )
            }
        return self._origins[session_id]

    def survivor(self, session_id: str) -> dict[str, Any] | None:
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


def session_age(row: dict[str, Any]) -> tuple[datetime, str]:
    """Order sessions by creation time, then id: the older one stays valid."""
    created = datetime.fromisoformat(str(row["created_at"]))
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created, str(row["activity_id"])
