"""Persist the per-provider canonical coverage summary at ingest time.

Coverage reports counts only: how many activities and observations a provider
contributed, how many mapping issues of each reason were met, and the observed
date range. The mapper issues exist only while a payload is mapped, so the
ingest stores the summary in the ``canonical_coverage:<provider>`` key of the
same unit of work that stores the payload. The value is JSON with counts, ISO
timestamps and dates, the mapper versions and the time zone it was computed
for. It holds no record references, field names or athlete text.

A stored summary is current only while its mapper versions and time zone equal the
current ones. By default anything else (missing, corrupt, outdated) reads as "not
stored", and a caller before the first completed backfill reports no summary for
that provider. After that backfill the caller loads with
``allow_outdated`` and keeps reporting the last persisted summary until the next
ingest replaces it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import replace
from datetime import date, datetime, tzinfo
from typing import Any, Final

from backend.canonical.coverage import ProviderCoverage, summarize_provider
from backend.canonical.mapping import IssueReason
from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_store
from backend.db.repositories import KeyValueRepository
from backend.providers.canonical_plans import (
    WAHOO_POWER_ZONES_KEY,
    WAHOO_USER_KEY,
    WAHOO_WORKOUTS_KEY,
    current_mapper_versions,
    wahoo_payload_retrieved_at,
)
from backend.providers.snapshot_projection import (
    project_garmin_snapshot,
    project_intervals_snapshot,
    stored_retrieved_at,
)
from backend.providers.wahoo_activity_mapping import map_wahoo_activities
from backend.providers.wahoo_threshold_mapping import map_wahoo_threshold_payload

COVERAGE_KEY_PREFIX: Final = "canonical_coverage:"
# The providers whose ingest persists a coverage summary. A provider without a
# canonical ingest is absent here, so it never blocks the persisted path.
CANONICAL_COVERAGE_PROVIDERS: Final = (ProviderId.INTERVALS, ProviderId.GARMIN)
# Providers ingested live without a stored snapshot. Their persisted summary is
# reported when present, after the snapshot-ingested providers.
LIVE_COVERAGE_PROVIDERS: Final = (ProviderId.WAHOO,)


def coverage_key(provider: ProviderId) -> str:
    return f"{COVERAGE_KEY_PREFIX}{provider.value}"


def intervals_snapshot_coverage(
    snapshot: object, *, zone: tzinfo
) -> ProviderCoverage | None:
    """Summarize a stored Intervals.icu snapshot, or None without a stored sync time."""
    stored_at = stored_retrieved_at(snapshot, zone=zone)
    if stored_at is None:
        return None
    activity_time = (
        stored_retrieved_at(
            {"synced_at": snapshot.get("activities_synced_at")}, zone=zone
        )
        if isinstance(snapshot, Mapping) and "activities_synced_at" in snapshot
        else stored_at
    )
    activities, _activity_observations = project_intervals_snapshot(
        snapshot, zone=zone, retrieved_at=activity_time or stored_at
    )
    _observation_activities, observations = project_intervals_snapshot(
        snapshot, zone=zone, retrieved_at=stored_at
    )
    return summarize_provider(
        ProviderId.INTERVALS,
        stored_at,
        activities,
        observations,
        activities_retrieved_at=activity_time,
        observations_retrieved_at=stored_at,
    )


def garmin_payload_coverage(
    payload: object, *, zone: tzinfo
) -> ProviderCoverage | None:
    """Summarize a stored Garmin payload, or None without a stored sync time."""
    stored_at = stored_retrieved_at(payload, zone=zone)
    if stored_at is None:
        return None
    activities, observations = project_garmin_snapshot(
        payload, zone=zone, retrieved_at=stored_at
    )
    return summarize_provider(ProviderId.GARMIN, stored_at, activities, observations)


def garmin_ingest_coverage(
    db: Any, payload: object, *, zone: tzinfo
) -> ProviderCoverage | None:
    """Summarize Garmin after one ingest: the tables' totals plus this fetch's issues.

    A Garmin write carries only the sections it fetched, so the record counts and
    the observed range come from the tables, which hold everything ingested so far.
    The fetch time and the mapping issue counts are those of the written payload.
    """
    fetched = garmin_payload_coverage(payload, zone=zone)
    if fetched is None:
        return None
    totals = canonical_store.provider_totals(db, ProviderId.GARMIN.value)
    oldest, newest = totals["oldest"], totals["newest"]
    return replace(
        fetched,
        activity_count=totals["activities"],
        observation_count=totals["observations"],
        first_observed_on=None if oldest is None else date.fromisoformat(oldest),
        last_observed_on=None if newest is None else date.fromisoformat(newest),
    )


def wahoo_payload_coverage(payload: object, *, zone: tzinfo) -> ProviderCoverage | None:
    """Summarize a fetched Wahoo payload, or None without a usable fetch time.

    The activities and the threshold observations of this fetch are summarized. A
    threshold key absent from the payload was not fetched and counts as nothing.
    """
    stored_at = wahoo_payload_retrieved_at(payload, zone=zone)
    if stored_at is None or not isinstance(payload, Mapping):
        return None
    activities = map_wahoo_activities(
        payload.get(WAHOO_WORKOUTS_KEY), zone=zone, retrieved_at=stored_at
    )
    thresholds = map_wahoo_threshold_payload(
        payload.get(WAHOO_POWER_ZONES_KEY),
        payload.get(WAHOO_USER_KEY),
        zone=zone,
        retrieved_at=stored_at,
    )
    return summarize_provider(ProviderId.WAHOO, stored_at, activities, thresholds)


class CanonicalCoverageStore:
    """Reads and writes the persisted coverage summaries in the key/value table."""

    def __init__(self, key_values: KeyValueRepository) -> None:
        self._key_values = key_values

    def persist(
        self, db: Any, coverage: ProviderCoverage | None, *, zone: tzinfo
    ) -> None:
        """Store a summary inside the caller's unit of work. None stores nothing."""
        if coverage is None:
            return
        self._key_values.set(
            db,
            coverage_key(coverage.provider),
            json.dumps(_encode(coverage, zone), sort_keys=True, separators=(",", ":")),
        )

    def load(
        self,
        db: Any,
        provider: ProviderId,
        *,
        zone: tzinfo,
        allow_outdated: bool = False,
    ) -> ProviderCoverage | None:
        """Return the stored summary, or None when absent, corrupt or outdated.

        ``allow_outdated`` also returns a summary computed for other mapper
        versions or another zone.
        """
        raw = self._key_values.get(db, coverage_key(provider))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return _decode(data, provider, zone, allow_outdated=allow_outdated)
        except ValueError, TypeError, KeyError, AttributeError:
            return None


def _encode(coverage: ProviderCoverage, zone: tzinfo) -> dict[str, Any]:
    return {
        "provider": coverage.provider.value,
        "mapper_versions": current_mapper_versions(),
        "zone": str(zone),
        "retrieved_at": _iso(coverage.retrieved_at),
        "activities_retrieved_at": _iso(coverage.activities_retrieved_at),
        "observations_retrieved_at": _iso(coverage.observations_retrieved_at),
        "activity_count": coverage.activity_count,
        "observation_count": coverage.observation_count,
        "issue_counts": {
            reason.value: count for reason, count in coverage.issue_counts.items()
        },
        "first_observed_on": _iso(coverage.first_observed_on),
        "last_observed_on": _iso(coverage.last_observed_on),
    }


def _decode(
    data: object, provider: ProviderId, zone: tzinfo, *, allow_outdated: bool
) -> ProviderCoverage | None:
    if not isinstance(data, Mapping) or data["provider"] != provider.value:
        return None
    if not allow_outdated and (
        data["mapper_versions"] != current_mapper_versions()
        or data["zone"] != str(zone)
    ):
        return None
    retrieved_at = data["retrieved_at"]
    activities_retrieved_at = data.get("activities_retrieved_at", retrieved_at)
    observations_retrieved_at = data.get("observations_retrieved_at", retrieved_at)
    first = data["first_observed_on"]
    last = data["last_observed_on"]
    return ProviderCoverage(
        provider=provider,
        retrieved_at=None
        if retrieved_at is None
        else datetime.fromisoformat(retrieved_at),
        activities_retrieved_at=(
            None
            if activities_retrieved_at is None
            else datetime.fromisoformat(activities_retrieved_at)
        ),
        observations_retrieved_at=(
            None
            if observations_retrieved_at is None
            else datetime.fromisoformat(observations_retrieved_at)
        ),
        activity_count=data["activity_count"],
        observation_count=data["observation_count"],
        issue_counts={
            IssueReason(reason): count for reason, count in data["issue_counts"].items()
        },
        first_observed_on=None if first is None else date.fromisoformat(first),
        last_observed_on=None if last is None else date.fromisoformat(last),
    )


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
