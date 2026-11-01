"""Read use case of the ``activity_detail.v1`` document of one canonical session.

The document combines the session's stored detail sets, its active activity
records and the stored target and decoupling values of the session analysis. The
analysis is recomputed from the merged streams at read time and withheld while
any merged provider's stored detail is stale. Intervals.icu zone times come from
the current summary row when it carries them. The caller owns the transaction:
``db`` is an open connection and this module only reads from it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, tzinfo
from typing import Any, Final, Protocol

from backend.activities.detail_contract import (
    ProviderStatus,
    activity_detail_contract,
    measured_order,
)
from backend.activities.detail_merge import (
    DetailCandidate,
    MergedDetail,
    merge_details,
)
from backend.activities.detail_store import summary_fingerprint
from backend.activities.detail_summary_metrics import intervals_summary_metrics
from backend.canonical.activity_detail import ZoneDistribution
from backend.canonical.records import ActivityRecord
from backend.canonical.vocabulary import ActivitySessionState, ProviderId
from backend.db import activity_detail_store, canonical_store
from backend.db.activity_detail_store import StoredDetailSet
from backend.performance.analysis_input import analysis_input
from backend.performance.power_profile import power_profile, running_profile
from backend.performance.session_analysis import aerobic_analysis, interval_quality
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.providers.intervals_activity_detail_mapping import (
    MAPPER_VERSION,
    map_intervals_summary_zones,
)

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


class CanonicalDetailReader:
    """Serve the ``activity_detail.v1`` document of a canonical session."""

    def __init__(
        self,
        session_records: SessionRecordReader,
        *,
        refreshable: RefreshableProviders,
        summary_row: SummaryRowReader | None = None,
        failures: FailureReader | None = None,
        envelope: EnvelopeReader | None = None,
        zone: tzinfo = UTC,
    ) -> None:
        self._session_records = session_records
        self._zone = zone
        self._refreshable = refreshable
        self._summary_row = summary_row
        self._failures = failures
        self._envelope = envelope

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
        sets = [candidate.stored for candidate in candidates]
        ordered = measured_order(records)
        analysis_record = next(
            (r for r in ordered if r.provenance.provider is ProviderId.INTERVALS),
            ordered[0],
        )
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
        status = self._status(db, sets, intervals_id, summary)
        stale = any(state.stale for state in status.values())
        analysis = (
            None if stale else self._analysis(db, activity_id, analysis_record, merged)
        )
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
            summary_metrics=None
            if summary is None
            else intervals_summary_metrics(
                summary, recorded_by=analysis_record.provenance.recorded_by
            ),
            zone=self._zone,
        )

    def _analysis(
        self,
        db: Any,
        activity_id: str,
        analysis_record: ActivityRecord,
        merged: MergedDetail,
    ) -> dict[str, Any]:
        """Recompute the session analysis from the merged streams and laps."""
        payload = _stored_payload(db, activity_id, analysis_record)
        adapted = analysis_input(
            analysis_record,
            merged.streams,
            merged.laps,
            decoupling=_decoupling(payload),
        )
        targets = payload.get("target_snapshot")
        # Each analysis credits only the providers of the channels it reads.
        return {
            "interval_quality": interval_quality(
                adapted.activity,
                targets if isinstance(targets, dict) else None,
                source_label=adapted.label_for(
                    "watts", "heartrate", "velocity_smooth", "laps"
                ),
            ),
            "aerobic": aerobic_analysis(
                adapted.activity,
                source_label=adapted.label_for(
                    "watts", "heartrate", "velocity_smooth", "moving"
                ),
            ),
            "power_profile": power_profile(
                adapted.activity, source_label=adapted.label_for("watts", "moving")
            ),
            "running_profile": running_profile(
                adapted.activity,
                source_label=adapted.label_for("velocity_smooth", "distance", "moving"),
            ),
        }

    def _status(
        self,
        db: Any,
        sets: Sequence[StoredDetailSet],
        intervals_id: str | None,
        summary: Mapping[str, Any] | None,
    ) -> dict[ProviderId, ProviderStatus]:
        """Compare each provider's stored sets with its current summary version."""
        fingerprint = None if summary is None else summary_fingerprint(dict(summary))
        status: dict[ProviderId, ProviderStatus] = {}
        for item in sets:
            provider = ProviderId(item.provider)
            if provider is ProviderId.INTERVALS:
                # The summary row belongs to one Intervals.icu record only.
                current = (
                    fingerprint if item.provider_activity_id == intervals_id else None
                )
            else:
                current = canonical_store.active_provider_record_hash(
                    db, item.provider, ACTIVITY_RECORD_KIND, item.provider_activity_id
                )
            if item.summary_sha256 and current and item.summary_sha256 != current:
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
            stored = replace(item, detail=live.pop(detail.metric))
            candidate = replace(candidate, stored=stored)
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
    """Attach the record's provenance label; stored sets do not keep labels."""
    provenance = replace(item.detail.provenance, label=record.provenance.label)
    return StoredDetailSet(
        provider=item.provider,
        provider_activity_id=item.provider_activity_id,
        activity_id=item.activity_id,
        mapper_version=item.mapper_version,
        summary_sha256=item.summary_sha256,
        fetched_at=item.fetched_at,
        detail=replace(item.detail, provenance=provenance),
    )


def _stored_payload(
    db: Any, activity_id: str, record: ActivityRecord
) -> dict[str, Any]:
    """Return the stored analysis of the record's own session, else the session's."""
    provider = _provider_text(record)
    row = (
        None
        if provider is None
        else activity_detail_store.analysis_row_for_record(
            db, provider, record.activity_id
        )
    )
    if row is None:
        row = activity_detail_store.analysis_rows_for(db, [activity_id]).get(
            activity_id
        )
    if row is None:
        return {}
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else {}


def _decoupling(payload: Mapping[str, Any]) -> float | None:
    """Return the stored provider decoupling when it is a finite number."""
    session = payload.get("session_analysis")
    aerobic = session.get("aerobic") if isinstance(session, dict) else None
    provider = aerobic.get("provider_decoupling") if isinstance(aerobic, dict) else None
    value = provider.get("value") if isinstance(provider, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None
