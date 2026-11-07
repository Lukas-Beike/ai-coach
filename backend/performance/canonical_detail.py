"""Read use case of the ``activity_detail.v1`` document of one canonical session.

The document combines the detail sets of the session's Garmin, Wahoo and local
records, its active activity records, the local session metrics (card M8) and
the one canonical session analysis (#1685), computed at read time with the
stored target snapshot and withheld while a merged provider's detail is stale.
Intervals.icu detail sets and summary rows are never read. The caller owns the
transaction: ``db`` is an open connection and this module only reads from it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, tzinfo
from typing import Any, Final, Protocol, cast

from backend.activities.detail_contract import (
    ProviderStatus,
    activity_detail_contract,
    measured_order,
)
from backend.activities.detail_merge import (
    DetailCandidate,
    merge_details,
)
from backend.activities.stream_zones import with_stream_zones
from backend.activities.zone_settings import ZoneSettings
from backend.canonical.activity_detail import (
    ActivityDetailSet,
)
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    ActivitySessionState,
    ProviderId,
)
from backend.db import activity_detail_store, canonical_store
from backend.db.activity_detail_store import StoredDetailSet
from backend.performance.canonical_session_analysis import (
    analysis_records,
    session_analysis,
)
from backend.performance.session_metrics_reads import (
    detail_metric_entries,
    stored_session_metrics,
)
from backend.runtime.ports import ActivityFingerprintReader

_MAX_MERGE_DEPTH: Final = 64


class SessionRecordReader(Protocol):
    """Return the active activity records of one canonical session."""

    def __call__(self, db: Any, activity_id: str) -> Sequence[ActivityRecord]: ...


class EnvelopeReader(Protocol):
    """Return the feedback, equipment and activity validation of one session.

    ``provider_activity_id`` is the session's Intervals.icu activity id, the key
    older feedback is stored under, when it holds one.
    """

    def __call__(
        self, db: Any, activity_id: str, provider_activity_id: str | None, /
    ) -> Mapping[str, Any]: ...


RefreshableProviders = Callable[[], frozenset[ProviderId]]


def read_reference(db: Any, any_id: str) -> str | None:
    """Return the canonical session id of a local or Intervals.icu activity id.

    A local ``act_`` id is used directly, any other id is looked up as an
    Intervals.icu provider activity id. A duplicate session resolves to the
    session it was merged into. An unknown id returns None.
    """
    text = any_id.strip()
    if text.startswith(canonical_store.ACTIVITY_ID_PREFIX):
        current: str | None = text
    else:
        current = canonical_store.activity_local_ids(
            db, ProviderId.INTERVALS.value, [text]
        ).get(text)
    seen: set[str] = set()
    while current is not None and current not in seen and len(seen) < _MAX_MERGE_DEPTH:
        seen.add(current)
        session = canonical_store.activity_sessions_by_ids(db, [current]).get(current)
        if session is None:
            return None
        merged_into = session["merged_into"]
        if session["state"] != ActivitySessionState.DUPLICATE.value or not merged_into:
            return current
        current = str(merged_into)
    return None


# The zone settings in effect for one session's primary record, or None.
type ZoneSettingsReader = Callable[[Any, ActivityRecord], ZoneSettings | None]


class CanonicalDetailReader:
    """Serve the ``activity_detail.v1`` document of a canonical session."""

    def __init__(
        self,
        session_records: SessionRecordReader,
        *,
        refreshable: RefreshableProviders,
        fingerprints: ActivityFingerprintReader | None = None,
        envelope: EnvelopeReader | None = None,
        zone: tzinfo = UTC,
        zone_settings: ZoneSettingsReader | None = None,
    ) -> None:
        self._session_records = session_records
        self._zone = zone
        self._refreshable = refreshable
        # Without it no stored set is reported stale.
        self._fingerprints = fingerprints
        self._envelope = envelope
        # Without it no zone distribution is derived from the streams.
        self._zone_settings = zone_settings

    def read(self, db: Any, any_id: str) -> dict[str, Any] | None:
        """Return the document, or None when the session has no readable records.

        ``any_id`` is a local session id or an Intervals.icu activity id. Detail
        sets come from the session's Garmin, Wahoo and local records only; the
        Intervals.icu copies are never read (#1685).
        """
        activity_id = read_reference(db, any_id)
        if activity_id is None:
            return None
        records = tuple(self._session_records(db, activity_id))
        if not records:
            return None
        own = analysis_records(records)
        stored = activity_detail_store.detail_sets_for_session(db, activity_id)
        candidates = detail_candidates(own, stored)
        sets = [candidate.stored for candidate in candidates]
        merged = merge_details(candidates)
        zone_settings = self._zone_settings
        if zone_settings is not None:
            merged = with_stream_zones(
                merged, lambda: zone_settings(db, measured_order(own)[0])
            )
        status = self._status(db, sets)
        stale = any(state.stale for state in status.values())
        analysis = (
            None
            if stale or not own
            else session_analysis(own, merged, stored_targets(db, activity_id, records))
        )
        intervals_id = next(
            (
                record.activity_id
                for record in records
                if record.provenance.provider is ProviderId.INTERVALS
            ),
            None,
        )
        envelope = (
            None
            if self._envelope is None
            else self._envelope(db, activity_id, intervals_id)
        )
        return activity_detail_contract(
            activity_id,
            records,
            merged,
            sets,
            analysis=analysis,
            # Intervals.icu details are never served, so they are never offered.
            refreshable=self._refreshable() - {ProviderId.INTERVALS},
            status=status,
            envelope=envelope,
            summary_metrics=detail_metric_entries(
                stored_session_metrics(db, [activity_id]).get(activity_id, {})
            ),
            zone=self._zone,
        )

    def _status(
        self, db: Any, sets: Sequence[StoredDetailSet]
    ) -> dict[ProviderId, ProviderStatus]:
        """Compare each provider's stored sets with its current summary version."""
        keys = [(item.provider, item.provider_activity_id) for item in sets]
        current = (
            {}
            if self._fingerprints is None or not keys
            else self._fingerprints.summary_fingerprints(db, keys)
        )
        status: dict[ProviderId, ProviderStatus] = {}
        for item in sets:
            latest = current.get((item.provider, item.provider_activity_id))
            if item.summary_sha256 and latest and item.summary_sha256 != latest:
                status[ProviderId(item.provider)] = ProviderStatus(stale=True)
        return status


def detail_candidates(
    records: Sequence[ActivityRecord], stored: Iterable[StoredDetailSet]
) -> list[DetailCandidate]:
    """Pair each stored set with its session record; sets without one are dropped."""
    by_key = {
        (_provider_text(record), record.activity_id): record for record in records
    }
    candidates = []
    for item in stored:
        record = by_key.get((item.provider, item.provider_activity_id))
        if record is not None:
            candidates.append(
                DetailCandidate(
                    stored=_labelled(item, record),
                    started_at=record.started_at,
                    device_type=record.device_type,
                )
            )
    return candidates


def primary_analysis_record(records: Sequence[ActivityRecord]) -> ActivityRecord:
    """The record whose sport and environment the session analysis uses."""
    ordered = measured_order(records)
    return next(
        (r for r in ordered if r.provenance.provider is ProviderId.INTERVALS),
        ordered[0],
    )


def _provider_text(record: ActivityRecord) -> str | None:
    provider = record.provenance.provider
    return None if provider is None else provider.value


def _labelled(item: StoredDetailSet, record: ActivityRecord) -> StoredDetailSet:
    """Attach the record's label and origin; stored sets do not keep labels.

    The origin follows the current record, so a set stored before a mapper
    re-named the origin (a Wahoo ride relayed through Garmin Connect, #1686)
    ranks like its record without a re-fetch.
    """
    provenance = cast(
        Provenance,
        replace(
            item.detail.provenance,
            label=record.provenance.label,
            recorded_by=record.provenance.recorded_by,
        ),
    )
    return StoredDetailSet(
        provider=item.provider,
        provider_activity_id=item.provider_activity_id,
        activity_id=item.activity_id,
        mapper_version=item.mapper_version,
        summary_sha256=item.summary_sha256,
        fetched_at=item.fetched_at,
        detail=cast(ActivityDetailSet, replace(item.detail, provenance=provenance)),
    )


def stored_targets(
    db: Any, activity_id: str, records: Sequence[ActivityRecord]
) -> dict[str, Any] | None:
    """The frozen target snapshot of the session, else of a session merged into it.

    Snapshots are athlete-plan context, so a row kept under any record's own
    session counts, Intervals.icu records included.
    """
    rows = [activity_detail_store.analysis_rows_for(db, [activity_id]).get(activity_id)]
    rows.extend(
        activity_detail_store.analysis_row_for_record(db, provider, record.activity_id)
        for record in records
        if (provider := _provider_text(record)) is not None
    )
    for row in rows:
        payload = None if row is None else row.get("payload")
        targets = payload.get("target_snapshot") if isinstance(payload, dict) else None
        if isinstance(targets, dict):
            return targets
    return None
