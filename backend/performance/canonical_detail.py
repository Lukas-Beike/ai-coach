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
from typing import Any, Protocol, cast

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
    ActivityStrengthSetSet,
)
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    ProviderId,
)
from backend.db import activity_detail_store, canonical_store
from backend.db.activity_detail_store import StoredDetailSet
from backend.performance.canonical_session_analysis import (
    session_analysis,
)
from backend.performance.session_metrics_reads import (
    detail_metric_entries,
    stored_session_metrics,
)
from backend.runtime.ports import ActivityFingerprintReader


class SessionRecordReader(Protocol):
    """Return the active activity records of one canonical session."""

    def __call__(self, db: Any, activity_id: str) -> Sequence[ActivityRecord]: ...


class EnvelopeReader(Protocol):
    """Return the feedback, equipment and activity validation of one session."""

    def __call__(self, db: Any, activity_id: str, /) -> Mapping[str, Any]: ...


RefreshableProviders = Callable[[], frozenset[ProviderId]]


def read_reference(db: Any, any_id: str) -> str | None:
    """Return the canonical session id of a local or provider activity id.

    A local ``act_`` id is used directly, any other id is looked up as the
    activity id of the only provider record carrying it. An alias session
    resolves to the session its merge led to, also after its own deletion kept
    the survivor (``merged_into_retained``). An unknown or ambiguous id returns
    None.
    """
    text = any_id.strip()
    # An id that names records of several sessions is not a reference.
    current = canonical_store.feedback_origin_sessions(db, [(text, None)]).get(text)
    if current is None:
        return None
    return canonical_store.effective_session_ids(db, [current]).get(current)


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

        ``any_id`` is a local session id or a provider activity id. Detail sets
        come from the session's served records; the readers serve no stored
        Intervals.icu copy, so none of its sets is read (#1685, #2148).
        """
        activity_id = read_reference(db, any_id)
        if activity_id is None:
            return None
        records = tuple(self._session_records(db, activity_id))
        if not records:
            return None
        stored = activity_detail_store.detail_sets_for_session(db, activity_id)
        candidates = detail_candidates(records, stored)
        sets = [candidate.stored for candidate in candidates]
        merged = merge_details(candidates)
        zone_settings = self._zone_settings
        if zone_settings is not None:
            merged = with_stream_zones(
                merged, lambda: zone_settings(db, measured_order(records)[0])
            )
        status = self._status(db, sets)
        stale = any(state.stale for state in status.values())
        analysis = (
            None
            if stale
            else session_analysis(
                records, merged, stored_targets(db, activity_id, records)
            )
        )
        envelope = None if self._envelope is None else self._envelope(db, activity_id)
        return activity_detail_contract(
            activity_id,
            records,
            merged,
            sets,
            analysis=analysis,
            refreshable=self._refreshable(),
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
        sets = _analysed_sets(sets)
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
    return measured_order(records)[0]


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


def _analysed_sets(sets: Sequence[StoredDetailSet]) -> list[StoredDetailSet]:
    """The sets whose freshness decides the session analysis.

    Strength sets feed no stream analysis; a fetch that cannot rewrite them must
    not hold back the session's analysis.
    """
    return [
        item for item in sets if not isinstance(item.detail, ActivityStrengthSetSet)
    ]
