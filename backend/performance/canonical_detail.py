"""Read use case of the ``activity_detail.v1`` document of one canonical session.

The document combines the session's stored detail sets, its active activity
records and the stored target and decoupling values of the session analysis. The
analysis is recomputed from the merged streams at read time and withheld while
any merged provider's stored detail is stale. Intervals.icu zone times come from
the current summary row when it carries them. The caller owns the transaction:
``db`` is an open connection and this module only reads from it.
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
from backend.activities.detail_store import summary_fingerprint
from backend.activities.detail_summary_metrics import intervals_summary_metrics
from backend.activities.stream_zones import with_stream_zones
from backend.activities.zone_settings import ZoneSettings
from backend.canonical.activity_detail import (
    ActivityDetailSet,
    ZoneDistribution,
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
from backend.providers.intervals_activity_detail_mapping import (
    MAPPER_VERSION,
    map_intervals_summary_zones,
)
from backend.runtime.ports import ActivityFingerprintReader

_MAX_MERGE_DEPTH: Final = 64


class SessionRecordReader(Protocol):
    """Return the active activity records of one canonical session."""

    def __call__(self, db: Any, activity_id: str) -> Sequence[ActivityRecord]: ...


class SummaryRowReader(Protocol):
    """Return the current Intervals.icu summary row of a provider activity id."""

    def __call__(
        self, db: Any, provider_activity_id: str, /
    ) -> Mapping[str, Any] | None: ...


class EnvelopeReader(Protocol):
    """Return the feedback, equipment and activity validation of one session.

    ``summary`` is the current Intervals.icu summary row, when there is one.
    """

    def __call__(
        self,
        db: Any,
        activity_id: str,
        provider_activity_id: str | None,
        summary: Mapping[str, Any] | None,
        /,
    ) -> Mapping[str, Any]: ...


FailureReader = Callable[[Iterable[str]], Mapping[str, Mapping[str, Any]]]
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
        summary_row: SummaryRowReader | None = None,
        fingerprints: ActivityFingerprintReader | None = None,
        failures: FailureReader | None = None,
        envelope: EnvelopeReader | None = None,
        zone: tzinfo = UTC,
        zone_settings: ZoneSettingsReader | None = None,
    ) -> None:
        self._session_records = session_records
        self._zone = zone
        self._refreshable = refreshable
        self._summary_row = summary_row
        # Without it no stored set is reported stale.
        self._fingerprints = fingerprints
        self._failures = failures
        self._envelope = envelope
        # Without it no zone distribution is derived from the streams.
        self._zone_settings = zone_settings

    def read(self, db: Any, any_id: str) -> dict[str, Any] | None:
        """Return the document, or None when the session has no readable records.

        ``any_id`` is a local session id or an Intervals.icu activity id.
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
        analysis_record = primary_analysis_record(records)
        intervals_id = (
            analysis_record.activity_id
            if analysis_record.provenance.provider is ProviderId.INTERVALS
            else None
        )
        summary = (
            self._summary_row(db, intervals_id)
            if self._summary_row is not None and intervals_id is not None
            else None
        )
        if summary is not None:
            candidates = _with_live_zones(
                candidates, activity_id, analysis_record, summary
            )
        merged = merge_details(candidates)
        zone_settings = self._zone_settings
        if zone_settings is not None:
            merged = with_stream_zones(
                merged, lambda: zone_settings(db, analysis_record)
            )
        status = self._status(db, sets, intervals_id, summary)
        # Intervals.icu detail is no analysis input (#1685), so its staleness
        # withholds nothing.
        stale = any(
            state.stale
            for provider, state in status.items()
            if provider is not ProviderId.INTERVALS
        )
        analysis = None if stale else self._analysis(db, activity_id, stored, records)
        envelope = (
            None
            if self._envelope is None
            else self._envelope(db, activity_id, intervals_id, summary)
        )
        return activity_detail_contract(
            activity_id,
            records,
            merged,
            sets,
            analysis=analysis,
            refreshable=self._refreshable(),
            status=status,
            envelope=envelope,
            summary_metrics=_summary_metrics(
                None
                if summary is None
                else intervals_summary_metrics(
                    summary, recorded_by=analysis_record.provenance.recorded_by
                ),
                stored_session_metrics(db, [activity_id]).get(activity_id, {}),
            ),
            zone=self._zone,
        )

    def _analysis(
        self,
        db: Any,
        activity_id: str,
        stored: Sequence[StoredDetailSet],
        records: Sequence[ActivityRecord],
    ) -> dict[str, Any] | None:
        """The canonical session analysis of the session's non-Intervals detail.

        The same computation as the stored analysis (#1685); without Garmin,
        Wahoo or local records the session has none.
        """
        own = analysis_records(records)
        if not own:
            return None
        merged = merge_details(detail_candidates(own, stored))
        targets = stored_targets(db, activity_id, records)
        return session_analysis(
            own, merged, targets if isinstance(targets, dict) else None
        )

    def _status(
        self,
        db: Any,
        sets: Sequence[StoredDetailSet],
        intervals_id: str | None,
        summary: Mapping[str, Any] | None,
    ) -> dict[ProviderId, ProviderStatus]:
        """Compare each provider's stored sets with its current summary version.

        The loaded Intervals.icu summary row belongs to one record only, so only
        that record's sets are compared for Intervals.icu; other providers'
        fingerprints come from the port.
        """
        fingerprint = None if summary is None else summary_fingerprint(dict(summary))
        others = [
            (item.provider, item.provider_activity_id)
            for item in sets
            if item.provider != ProviderId.INTERVALS.value
        ]
        current = (
            {}
            if self._fingerprints is None or not others
            else self._fingerprints.summary_fingerprints(db, others)
        )
        status: dict[ProviderId, ProviderStatus] = {}
        for item in sets:
            provider = ProviderId(item.provider)
            if provider is ProviderId.INTERVALS:
                latest = (
                    fingerprint if item.provider_activity_id == intervals_id else None
                )
            else:
                latest = current.get((item.provider, item.provider_activity_id))
            if item.summary_sha256 and latest and item.summary_sha256 != latest:
                status[provider] = ProviderStatus(stale=True)
        load_error = self._load_error(intervals_id, fingerprint)
        if load_error is not None:
            status[ProviderId.INTERVALS] = ProviderStatus(
                stale=status.get(ProviderId.INTERVALS, ProviderStatus()).stale,
                load_error=load_error,
            )
        return status

    def _load_error(
        self, intervals_id: str | None, fingerprint: str | None
    ) -> dict[str, Any] | None:
        """Return the failure note of the current Intervals.icu summary, if any."""
        if intervals_id is None or fingerprint is None or not self._failures:
            return None
        note = self._failures([intervals_id]).get(intervals_id)
        # A note left by another summary version no longer describes this one.
        if not note or note.get("summary_sha256") != fingerprint:
            return None
        return {"message": note.get("message"), "observed_at": note.get("observed_at")}


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


def _with_live_zones(
    candidates: Sequence[DetailCandidate],
    activity_id: str,
    record: ActivityRecord,
    summary: Mapping[str, Any],
) -> list[DetailCandidate]:
    """Replace the record's stored zone sets by the summary row's zone times.

    A replaced set keeps its stored bookkeeping; a zone metric without a stored
    set is added with the record's retrieval time.
    """
    live = {
        zone.metric: zone
        for zone in map_intervals_summary_zones(
            summary,
            provider_activity_id=record.activity_id,
            provenance=record.provenance,
        ).records
    }
    result: list[DetailCandidate] = []
    for candidate in candidates:
        item = candidate.stored
        detail = item.detail
        own = (
            item.provider == ProviderId.INTERVALS.value
            and item.provider_activity_id == record.activity_id
        )
        if own and isinstance(detail, ZoneDistribution) and detail.metric in live:
            stored = cast(
                StoredDetailSet, replace(item, detail=live.pop(detail.metric))
            )
            candidate = cast(DetailCandidate, replace(candidate, stored=stored))
        result.append(candidate)
    retrieved = record.provenance.retrieved_at
    for zone in live.values():
        result.append(
            DetailCandidate(
                stored=StoredDetailSet(
                    provider=ProviderId.INTERVALS.value,
                    provider_activity_id=record.activity_id,
                    activity_id=activity_id,
                    mapper_version=MAPPER_VERSION,
                    summary_sha256=None,
                    fetched_at="" if retrieved is None else retrieved.isoformat(),
                    detail=zone,
                ),
                started_at=record.started_at,
                device_type=record.device_type,
            )
        )
    return result


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


def _summary_metrics(
    provider: Mapping[str, Mapping[str, Any]] | None,
    stored: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Local session metrics (card M8) win; a provider value of the same key stays an alternative."""
    metrics = {key: dict(entry) for key, entry in (provider or {}).items()}
    for key, entry in detail_metric_entries(stored).items():
        other = metrics.get(key)
        if other is not None:
            entry["alternatives"] = [
                {"value": other.get("value"), "source": other.get("source")}
            ]
        metrics[key] = entry
    return metrics


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
