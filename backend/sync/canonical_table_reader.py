"""Canonical reader over the canonical tables, without any provider client or sync.

Reads the stored rows only, so the last stored data stays readable with no provider
configured and no sync performed. Served records are the ones the legacy projection
would return for the same data:

- activities: ``active`` activity records whose session is not ``deleted``. Invalid
  and deleted records are never served.
- activity rows: the stored raw Intervals.icu payloads of those same activities.
- observations: rows whose ``mapper_version`` equals the current version of their
  provider. Observations have no state column, so a row that an upgraded mapper no
  longer emits is recognised by its old version and is not served. While a
  re-projection is pending (``oldest_versions``) rows that still carry a version
  between the one of the last completed run and the current one are served too: a
  natural key has one row, so each identity is served at the newest version stored
  for it and nothing vanishes meanwhile. Rows retired before the last completed run
  carry an older version and stay hidden. A
  mapper that moves a measurement to a different natural key leaves the old-key row
  next to the new one until the re-projection completes, so that one measurement
  can briefly appear twice.

Results use the same inclusive bounds and the same total order as
``CanonicalSnapshotProjection``. Activity bounds filter the stored athlete-local
date, which the ingest computed with the athlete's zone at write time.

Sleep periods, zone configurations, provider statuses and gear are served from
their active rows; rows a re-projection retired are not served.

Mapping issue counts are not stored in the tables, so this reader does not
implement ``coverage``. It serves ``metric_windows`` from the same rows as
``observations``, as counts and oldest and newest days only. ``CanonicalReadSelector`` serves
coverage from the summaries persisted at ingest.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Any, Final

from backend.canonical.coverage import MetricWindow
from backend.canonical.domain_records import (
    CategoricalObservation,
    GearActivityLink,
    GearItem,
    SleepPeriod,
    ZoneConfiguration,
)
from backend.canonical.ordering import activity_order, observation_order
from backend.canonical.records import (
    FORM_METHOD,
    FORM_METHOD_VERSION,
    ActivityRecord,
    MetricValue,
    Observation,
    Provenance,
    fingerprint_inputs,
)
from backend.canonical.vocabulary import (
    CategoricalDomain,
    Environment,
    LoadModel,
    MetricKind,
    ObservationAggregation,
    ProviderId,
    RecordingOrigin,
    SleepKind,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
    ZonePercentBasis,
)
from backend.db import canonical_domain_store, canonical_store
from backend.providers.canonical_plans import (
    ACTIVITY_RECORD_KIND,
    current_observation_mapper_versions,
)
from backend.providers.garmin_activity_mapping import GARMIN_LABEL
from backend.providers.intervals_activity_mapping import INTERVALS_LABEL
from backend.providers.wahoo_activity_mapping import WAHOO_LABEL
from backend.runtime.ports import (
    ActivityReader,
    ActivityRowReader,
    ActivitySessionReader,
    ObservationReader,
    SessionRecords,
)

_ACTIVITY_LABELS: Final[Mapping[ProviderId, str]] = {
    ProviderId.INTERVALS: INTERVALS_LABEL,
    ProviderId.GARMIN: GARMIN_LABEL,
    ProviderId.WAHOO: WAHOO_LABEL,
}


class CanonicalTableReader(
    ActivityReader, ActivityRowReader, ActivitySessionReader, ObservationReader
):
    """Serves canonical activities, raw activity rows and observations from the tables."""

    def __init__(
        self, *, oldest_versions: Callable[[Any], Mapping[str, int]] | None = None
    ) -> None:
        self._oldest_versions = oldest_versions

    def activities(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[ActivityRecord, ...]:
        rows = canonical_store.active_activity_rows(
            db, start=_iso(start), end=_iso(end)
        )
        return tuple(sorted((_activity(row) for row in rows), key=activity_order))

    def activity_max_hr(
        self, db: Any, provider: ProviderId, *, low: float, high: float
    ) -> tuple[tuple[Sport, float, date], ...]:
        """Return each sport's highest stored max heart rate and its newest day."""
        return tuple(
            (
                Sport(row["sport"]),
                float(row["max_hr"]),
                date.fromisoformat(row["local_date"]),
            )
            for row in canonical_store.activity_max_hr_rows(
                db, provider.value, low=low, high=high
            )
        )

    def session_activities(
        self, db: Any, activity_id: str
    ) -> tuple[ActivityRecord, ...]:
        """Return the active records of one session and of sessions merged into it.

        Same mapping and order as ``activities``. A deleted session returns nothing.
        """
        rows = canonical_store.session_activity_rows(db, activity_id)
        return tuple(sorted((_activity(row) for row in rows), key=activity_order))

    def activity_sessions(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        newest: int | None = None,
    ) -> tuple[SessionRecords, ...]:
        """Return each live session's id and its active records of every provider.

        Records of sessions merged into another are listed under the survivor.
        Records are in ``activity_order``; sessions in order of first record.
        Records of a provider that is not a known ``ProviderId`` are skipped.
        ``newest`` bounds the read to the days of at least the newest that many
        sessions (a day earlier, so their merged copies stay); the caller still
        keeps only as many as it needs.
        """
        if newest is not None:
            bound = canonical_store.newest_sessions_start(db, newest)
            if bound is not None:
                earliest = date.fromisoformat(bound) - timedelta(days=1)
                start = earliest if start is None else max(start, earliest)
        grouped: dict[str, list[ActivityRecord]] = {}
        for session_id, row in canonical_store.active_session_activity_rows(
            db, start=_iso(start), end=_iso(end)
        ):
            if _provider_or_none(row["provider"]) is not None:
                grouped.setdefault(session_id, []).append(_activity(row))
        return tuple(
            (session_id, tuple(sorted(records, key=activity_order)))
            for session_id, records in grouped.items()
        )

    def activity_rows(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return the stored raw Intervals.icu payloads of live activities.

        Newest first, like the stored snapshot (activity start, then provider
        activity id, both descending). The stored payload
        is the ingest-sanitized one: credential-like keys and signed URLs are
        already removed. ``limit`` is applied in SQL before any payload is read.
        A payload that does not parse as a JSON object is skipped; its content
        is never logged.
        """
        texts = canonical_store.active_activity_payload_texts(
            db,
            provider=ProviderId.INTERVALS.value,
            record_kind=ACTIVITY_RECORD_KIND,
            start=_iso(start),
            end=_iso(end),
            limit=limit,
        )
        parsed = (_payload_object(text) for text in texts)
        return tuple(row for row in parsed if row is not None)

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        rows = canonical_store.current_observation_rows(
            db,
            kind.value,
            current_observation_mapper_versions(),
            start=_iso(start),
            end=_iso(end),
            sport=None if sport is None else sport.value,
            oldest_versions=(
                None if self._oldest_versions is None else self._oldest_versions(db)
            ),
        )
        return tuple(sorted((_observation(row) for row in rows), key=observation_order))

    def metric_windows(self, db: Any) -> tuple[MetricWindow, ...]:
        """Return the count and newest day of each provider metric.

        The same version window as ``observations`` applies, so a pending
        re-projection counts the rows it still serves. Rows whose provider is not
        a known ``ProviderId`` are skipped.
        """
        rows = canonical_store.observation_metric_windows(
            db,
            current_observation_mapper_versions(),
            oldest_versions=(
                None if self._oldest_versions is None else self._oldest_versions(db)
            ),
        )
        windows = (_metric_window(row) for row in rows)
        return tuple(window for window in windows if window is not None)

    def sleep_periods(
        self, db: Any, *, start: date | None = None, end: date | None = None
    ) -> tuple[SleepPeriod, ...]:
        """Return sleep periods by inclusive wake date, oldest first."""
        rows = canonical_domain_store.active_sleep_period_rows(
            db, start=_iso(start), end=_iso(end)
        )
        return tuple(_sleep_period(row) for row in rows)

    def categorical_observations(
        self,
        db: Any,
        domain: CategoricalDomain,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[CategoricalObservation, ...]:
        """Return the provider statuses of one domain by inclusive day, oldest first."""
        rows = canonical_domain_store.active_categorical_rows(
            db, domain.value, start=_iso(start), end=_iso(end)
        )
        return tuple(_categorical_observation(row) for row in rows)

    def zone_configurations(self, db: Any) -> tuple[ZoneConfiguration, ...]:
        """Return local and provider zone configurations by configuration key."""
        rows = canonical_domain_store.active_zone_configuration_rows(db)
        return tuple(_zone_configuration(row) for row in rows)

    def gear_items(self, db: Any) -> tuple[GearItem, ...]:
        rows = canonical_domain_store.active_gear_item_rows(db)
        return tuple(_gear_item(row) for row in rows)

    def gear_activity_links(self, db: Any) -> tuple[GearActivityLink, ...]:
        rows = canonical_domain_store.active_gear_link_rows(db)
        return tuple(_gear_activity_link(row) for row in rows)


def _payload_object(text: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(text)
    except ValueError, RecursionError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _iso(day: date | None) -> str | None:
    return None if day is None else day.isoformat()


def _optional_datetime(text: object) -> datetime | None:
    return None if text is None else datetime.fromisoformat(str(text))


def _activity(row: Mapping[str, Any]) -> ActivityRecord:
    provider = ProviderId(row["provider"])
    return ActivityRecord(
        activity_id=str(row["provider_activity_id"]),
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind(row["source_kind"]),
            source_record_id=row["source_record_id"],
            recorded_by=RecordingOrigin(row["recorded_by"]),
            # The row's own fetch time. Garmin sections keep their own fetch time.
            retrieved_at=datetime.fromisoformat(str(row["fetched_at"])),
            label=_ACTIVITY_LABELS[provider],
            context=canonical_store.measurement_context(row["details"]),
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
        **canonical_store.activity_summary_values(row["details"]),
    )


def _observation(row: Mapping[str, Any]) -> Observation:
    provider = row["provider"]
    kind = MetricKind(row["metric"])
    source_kind = SourceKind(row["source_kind"])
    derivation = canonical_store.observation_derivation(row["details"])
    method = row["method"]
    method_version = derivation.method_version
    input_fingerprint = derivation.input_fingerprint
    if source_kind is SourceKind.DERIVED and method is None and kind is MetricKind.FORM:
        # A derived FORM stored before schema version 15 has no metadata. It was
        # CTL minus ATL; its fingerprint is fixed by the row, as its inputs are
        # not stored with it. Re-projection replaces it with the full metadata.
        method, method_version = FORM_METHOD, FORM_METHOD_VERSION
        input_fingerprint = fingerprint_inputs(
            {
                "unversioned_row": provider,
                "source_record_id": row["source_record_id"],
                "observed_on": str(row["observed_on"]),
                "value": row["value"],
            }
        )
    aggregation = row["aggregation"]
    return Observation(
        kind=kind,
        value=MetricValue(value=row["value"], unit=row["unit"]),
        observed_on=date.fromisoformat(str(row["observed_on"])),
        observed_at=_optional_datetime(row["observed_at"]),
        provenance=Provenance(
            provider=None if provider is None else ProviderId(provider),
            source_kind=source_kind,
            source_record_id=row["source_record_id"],
            recorded_by=RecordingOrigin(row["recorded_by"]),
            retrieved_at=_optional_datetime(row["retrieved_at"]),
            label=row["label"],
            context=canonical_store.measurement_context(row["details"]),
        ),
        sport=None if row["sport"] is None else Sport(row["sport"]),
        method=method,
        aggregation=(
            None if aggregation is None else ObservationAggregation(aggregation)
        ),
        method_version=method_version,
        input_fingerprint=input_fingerprint,
        period=derivation.period,
    )


def _metric_window(row: Mapping[str, Any]) -> MetricWindow | None:
    provider = _provider_or_none(row["provider"])
    if provider is None:
        return None
    return MetricWindow(
        provider=provider,
        metric=str(row["metric"]),
        observations=int(row["observations"]),
        oldest_observed_on=date.fromisoformat(str(row["oldest"])),
        newest_observed_on=date.fromisoformat(str(row["newest"])),
    )


def _provider_or_none(value: object) -> ProviderId | None:
    try:
        return ProviderId(str(value))
    except ValueError:
        return None


def _optional_date(text: object) -> date | None:
    return None if text is None else date.fromisoformat(str(text))


def _domain_provenance(row: Mapping[str, Any]) -> Provenance:
    provider = row["provider"]
    return Provenance(
        provider=None if provider is None else ProviderId(provider),
        source_kind=SourceKind(row["source_kind"]),
        source_record_id=row["source_record_id"],
        recorded_by=RecordingOrigin(row["recorded_by"]),
        retrieved_at=_optional_datetime(row["retrieved_at"]),
        label=row["label"],
        context=canonical_store.measurement_context(row.get("details")),
    )


def _sleep_period(row: Mapping[str, Any]) -> SleepPeriod:
    return SleepPeriod(
        start=datetime.fromisoformat(str(row["started_at"])),
        end=datetime.fromisoformat(str(row["ended_at"])),
        wake_date=date.fromisoformat(str(row["wake_date"])),
        kind=SleepKind(row["kind"]),
        timezone=row["timezone"],
        reported_duration_s=row["reported_duration_s"],
        bounds_method=row["bounds_method"],
        provenance=_domain_provenance(row),
    )


def _categorical_observation(row: Mapping[str, Any]) -> CategoricalObservation:
    return CategoricalObservation(
        domain=CategoricalDomain(row["domain"]),
        code=row["code"],
        observed_on=date.fromisoformat(str(row["observed_on"])),
        observed_at=_optional_datetime(row["observed_at"]),
        provenance=_domain_provenance(row),
        sport=None if row["sport"] is None else Sport(row["sport"]),
    )


def _zone_limits(text: object) -> tuple[float, ...] | None:
    return None if text is None else tuple(json.loads(str(text)))


def _zone_configuration(row: Mapping[str, Any]) -> ZoneConfiguration:
    details = _payload_object(str(row["details"])) or {}
    environment = row["environment"]
    basis = row["percent_basis"]
    return ZoneConfiguration(
        metric=ZoneConfigurationMetric(row["metric"]),
        sport=None if row["sport"] is None else Sport(row["sport"]),
        environment=None if environment is None else Environment(environment),
        valid_from=_optional_date(row["valid_from"]),
        valid_until=_optional_date(row["valid_until"]),
        threshold=row["threshold"],
        maximum=row["maximum"],
        resting=row["resting"],
        limits=_zone_limits(row["limits"]),
        percent_limits=_zone_limits(row["percent_limits"]),
        percent_basis=None if basis is None else ZonePercentBasis(basis),
        provenance=_domain_provenance(row),
        model=details.get(canonical_domain_store.ZONE_MODEL_KEY),
    )


def _gear_item(row: Mapping[str, Any]) -> GearItem:
    details = _payload_object(str(row["details"])) or {}
    return GearItem(
        gear_id=row["gear_id"],
        name=row["name"],
        type_label=row["type_label"],
        activity_type_label=row["activity_type_label"],
        status_label=row["status_label"],
        maximum_distance_m=row["maximum_distance_m"],
        total_distance_m=row["total_distance_m"],
        total_activities=row["total_activities"],
        provenance=_domain_provenance(row),
        activity_list_partial=details.get(canonical_domain_store.GEAR_LIST_PARTIAL_KEY),
    )


def _gear_activity_link(row: Mapping[str, Any]) -> GearActivityLink:
    return GearActivityLink(
        gear_id=row["gear_id"],
        provider_activity_id=row["provider_activity_id"],
        provenance=_domain_provenance(row),
    )
