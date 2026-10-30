"""Persistence owner for raw provider records and canonical activity and observation rows.

Every function writes through the connection of the caller's unit of work and
never commits. The caller's transaction decides whether these rows and the legacy
snapshot are kept together or rolled back together.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final, NamedTuple

from backend.canonical.records import (
    UNKNOWN_CONTEXT,
    ActivityRecord,
    MeasurementContext,
    Observation,
    ObservationPeriod,
)
from backend.canonical.vocabulary import (
    ActivityLinkKind,
    ActivityRecordState,
    ActivitySessionState,
    DeviceType,
    MetricKind,
    ProviderId,
    ProviderRecordState,
)

ACTIVITY_ID_PREFIX: Final = "act_"
ATHLETE_SERIES: Final = "athlete"
_ATHLETE_SERIES_KINDS: Final = frozenset(
    {MetricKind.WEIGHT, MetricKind.EFTP, MetricKind.BODY_FAT}
)
# Kinds whose athlete value collides with a wellness value only without a sport:
# the athlete's sport VO2max keeps the daily key it had before mapper version 9.
_ATHLETE_SPORTLESS_SERIES_KINDS: Final = frozenset({MetricKind.VO2MAX})
OBSERVATION_DETAILS: Final = "{}"
ACTIVITY_DETAILS: Final = "{}"
_ELAPSED_DURATION_KEY: Final = "elapsed_duration_s"
_MAX_HR_KEY: Final = "max_hr"
_MAX_SPEED_KEY: Final = "max_speed_mps"
_MAX_POWER_KEY: Final = "max_power_w"
_MIN_HR_KEY: Final = "min_hr"
_ELEVATION_HIGH_KEY: Final = "elevation_high_m"
_ELEVATION_LOW_KEY: Final = "elevation_low_m"
_STEPS_KEY: Final = "steps"
_DEVICE_TYPE_KEY: Final = "device_type"
_CONTEXT_KEY: Final = "context"
_METHOD_VERSION_KEY: Final = "method_version"
_INPUT_FINGERPRINT_KEY: Final = "input_fingerprint"
_PERIOD_KEY: Final = "period"
_MAX_MERGE_HOPS: Final = 64
_PROVIDER_RECORD_EXISTS: Final = (
    "SELECT 1 AS present FROM provider_records "
    "WHERE provider = ? AND record_kind = ? AND source_record_id = ?"
)
_ACTIVITY_RECORD_EXISTS: Final = "SELECT 1 AS present FROM activity_records WHERE provider = ? AND provider_activity_id = ?"
_OBSERVATION_EXISTS: Final = (
    "SELECT 1 AS present FROM observations WHERE natural_key = ?"
)

_ACTIVITY_COLUMNS: Final = (
    "source_kind",
    "recorded_by",
    "source_record_id",
    "sport",
    "environment",
    "started_at",
    "local_date",
    "duration_s",
    "distance_m",
    "load",
    "load_model",
    "avg_hr",
    "avg_power",
    "moving_duration_s",
    "elevation_gain_m",
    "normalized_power",
    "avg_cadence",
    "energy_kj",
    "name",
    "details",
    "mapper_version",
)
_OBSERVATION_COLUMNS: Final = (
    "metric",
    "value",
    "unit",
    "source_kind",
    "recorded_by",
    "provider",
    "source_record_id",
    "sport",
    "observed_on",
    "observed_at",
    "retrieved_at",
    "label",
    "mapper_version",
    "method",
    "aggregation",
    "details",
)


class WriteOutcome(StrEnum):
    WRITTEN = "written"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    # A deleted row was left as it is; only re-projection returns this.
    PRESERVED = "preserved"


def canonical_json(value: Mapping[str, Any]) -> str:
    """Return the deterministic JSON text that is stored and hashed."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def upsert_provider_record(
    db: Any,
    *,
    provider: str,
    record_kind: str,
    source_record_id: str,
    payload: Mapping[str, Any],
    mapper_version: int,
    fetched_at: str,
    now: str,
    observed_on: str | None = None,
) -> WriteOutcome:
    """Store one sanitized raw record; an unchanged hash and version is not rewritten.

    ``observed_on`` is the ISO day the record belongs to, for windowed reads.
    """
    text = canonical_json(payload)
    digest = payload_hash(text)
    existing = _fetch_row(
        db,
        "SELECT payload_hash, mapped_version, state, observed_on FROM provider_records "
        "WHERE provider = ? AND record_kind = ? AND source_record_id = ?",
        (provider, record_kind, source_record_id),
    )
    if existing is None:
        _insert_provider_record(
            db,
            provider=provider,
            record_kind=record_kind,
            source_record_id=source_record_id,
            text=text,
            digest=digest,
            mapper_version=mapper_version,
            fetched_at=fetched_at,
            now=now,
            observed_on=observed_on,
        )
        return WriteOutcome.WRITTEN
    if (
        existing["payload_hash"] == digest
        and existing["mapped_version"] == mapper_version
        and existing["state"] == ProviderRecordState.ACTIVE.value
        and existing["observed_on"] == observed_on
    ):
        return WriteOutcome.UNCHANGED
    db.execute(
        "UPDATE provider_records SET payload = ?, payload_hash = ?, fetched_at = ?, "
        "mapped_version = ?, state = ?, updated_at = ?, observed_on = ? "
        "WHERE provider = ? AND record_kind = ? AND source_record_id = ?",
        (
            text,
            digest,
            fetched_at,
            mapper_version,
            ProviderRecordState.ACTIVE.value,
            now,
            observed_on,
            provider,
            record_kind,
            source_record_id,
        ),
    )
    return WriteOutcome.UPDATED


def upsert_activity_record(
    db: Any,
    record: ActivityRecord,
    *,
    local_date: date,
    mapper_version: int,
    fetched_at: str,
    now: str,
) -> WriteOutcome:
    """Insert or update one activity by (provider, provider_activity_id).

    A new activity gets a new single-link session. An existing activity keeps its
    ``activity_id`` and is updated in place.
    """
    provider, provider_activity_id = _activity_identity(record)
    values = _activity_values(
        record, local_date=local_date, mapper_version=mapper_version
    )
    existing = _fetch_row(
        db,
        "SELECT activity_id, state, "
        + ", ".join(_ACTIVITY_COLUMNS)
        + " FROM activity_records WHERE provider = ? AND provider_activity_id = ?",
        (provider, provider_activity_id),
    )
    started_at = values["started_at"]
    day = values["local_date"]
    if existing is None:
        _insert_activity(
            db,
            provider=provider,
            provider_activity_id=provider_activity_id,
            values=values,
            fetched_at=fetched_at,
            now=now,
        )
        return WriteOutcome.WRITTEN
    if existing["state"] == ActivityRecordState.ACTIVE.value and all(
        existing[column] == values[column] for column in _ACTIVITY_COLUMNS
    ):
        _refresh_fetch_time(
            db,
            provider=provider,
            provider_activity_id=provider_activity_id,
            fetched_at=fetched_at,
        )
        return WriteOutcome.UNCHANGED
    _update_activity_columns(
        db,
        provider=provider,
        provider_activity_id=provider_activity_id,
        values=values,
        fetched_at=fetched_at,
        now=now,
    )
    db.execute(
        # A revived session is active again, so it no longer keeps the survivor
        # of a merge that its deletion cleared.
        "UPDATE activity_sessions SET started_at = ?, local_date = ?, "
        "state = CASE WHEN state = ? THEN ? ELSE state END, "
        "merged_into_retained = CASE WHEN state = ? THEN NULL "
        "ELSE merged_into_retained END, updated_at = ? "
        "WHERE activity_id = ?",
        (
            started_at,
            day,
            ActivitySessionState.DELETED.value,
            ActivitySessionState.ACTIVE.value,
            ActivitySessionState.DELETED.value,
            now,
            existing["activity_id"],
        ),
    )
    return WriteOutcome.UPDATED


def reproject_activity_record(
    db: Any,
    record: ActivityRecord,
    *,
    local_date: date,
    mapper_version: int,
    fetched_at: str,
    now: str,
) -> WriteOutcome:
    """Project one activity for re-projection without reviving a tombstone.

    A missing activity is inserted with a new single-link session. A deleted activity,
    or one whose session is deleted, is left untouched and returns PRESERVED. An active
    or invalid activity is updated in place and becomes active again; its session dates
    are updated only while that session is active, and its state is never changed here.
    """
    provider, provider_activity_id = _activity_identity(record)
    values = _activity_values(
        record, local_date=local_date, mapper_version=mapper_version
    )
    columns = ", ".join(_ACTIVITY_COLUMNS)
    existing = _fetch_row(
        db,
        "SELECT activity_id, state, "
        "(SELECT state FROM activity_sessions "
        "WHERE activity_sessions.activity_id = activity_records.activity_id) "
        f"AS session_state, {columns} FROM activity_records "
        "WHERE provider = ? AND provider_activity_id = ?",
        (provider, provider_activity_id),
    )
    if existing is None:
        _insert_activity(
            db,
            provider=provider,
            provider_activity_id=provider_activity_id,
            values=values,
            fetched_at=fetched_at,
            now=now,
        )
        return WriteOutcome.WRITTEN
    if (
        existing["state"] == ActivityRecordState.DELETED.value
        or existing["session_state"] == ActivitySessionState.DELETED.value
    ):
        return WriteOutcome.PRESERVED
    if existing["state"] == ActivityRecordState.ACTIVE.value and all(
        existing[column] == values[column] for column in _ACTIVITY_COLUMNS
    ):
        _refresh_fetch_time(
            db,
            provider=provider,
            provider_activity_id=provider_activity_id,
            fetched_at=fetched_at,
        )
        return WriteOutcome.UNCHANGED
    _update_activity_columns(
        db,
        provider=provider,
        provider_activity_id=provider_activity_id,
        values=values,
        fetched_at=fetched_at,
        now=now,
    )
    db.execute(
        "UPDATE activity_sessions SET started_at = ?, local_date = ?, updated_at = ? "
        "WHERE activity_id = ? AND state = ?",
        (
            values["started_at"],
            values["local_date"],
            now,
            existing["activity_id"],
            ActivitySessionState.ACTIVE.value,
        ),
    )
    return WriteOutcome.UPDATED


def retire_unemitted_activity(
    db: Any, *, provider: str, provider_activity_id: str, now: str
) -> bool:
    """Mark an active activity that a re-projection no longer emits as invalid.

    Only the activity record changes. Its session keeps its state, because the session
    state has no mapper-owned value and must not be confused with deletion. A missing,
    deleted, or already invalid record is left untouched and returns False.
    """
    existing = _fetch_row(
        db,
        "SELECT state FROM activity_records WHERE provider = ? AND provider_activity_id = ?",
        (provider, provider_activity_id),
    )
    if existing is None or existing["state"] != ActivityRecordState.ACTIVE.value:
        return False
    db.execute(
        "UPDATE activity_records SET state = ?, updated_at = ? "
        "WHERE provider = ? AND provider_activity_id = ?",
        (ActivityRecordState.INVALID.value, now, provider, provider_activity_id),
    )
    return True


def insert_provider_record_if_absent(
    db: Any,
    *,
    provider: str,
    record_kind: str,
    source_record_id: str,
    payload: Mapping[str, Any],
    mapper_version: int,
    fetched_at: str,
    now: str,
) -> bool:
    """Insert one sanitized raw record when no row exists; return True when inserted.

    A row that exists, live or deleted, is never changed or revived.
    """
    if (
        _fetch_row(
            db, _PROVIDER_RECORD_EXISTS, (provider, record_kind, source_record_id)
        )
        is not None
    ):
        return False
    text = canonical_json(payload)
    _insert_provider_record(
        db,
        provider=provider,
        record_kind=record_kind,
        source_record_id=source_record_id,
        text=text,
        digest=payload_hash(text),
        mapper_version=mapper_version,
        fetched_at=fetched_at,
        now=now,
    )
    return True


def insert_activity_record_if_absent(
    db: Any,
    record: ActivityRecord,
    *,
    local_date: date,
    mapper_version: int,
    fetched_at: str,
    now: str,
) -> bool:
    """Insert one activity with its single-link session when absent; return True when inserted.

    An existing activity, live or deleted, is never changed or revived.
    """
    provider, provider_activity_id = _activity_identity(record)
    if (
        _fetch_row(db, _ACTIVITY_RECORD_EXISTS, (provider, provider_activity_id))
        is not None
    ):
        return False
    _insert_activity(
        db,
        provider=provider,
        provider_activity_id=provider_activity_id,
        values=_activity_values(
            record, local_date=local_date, mapper_version=mapper_version
        ),
        fetched_at=fetched_at,
        now=now,
    )
    return True


def insert_observation_if_absent(
    db: Any, observation: Observation, *, mapper_version: int, now: str
) -> bool:
    """Insert one observation when its natural key is absent; return True when inserted."""
    natural_key = observation_natural_key(observation)
    if _fetch_row(db, _OBSERVATION_EXISTS, (natural_key,)) is not None:
        return False
    _insert_observation(
        db,
        natural_key=natural_key,
        values=_observation_values(observation, mapper_version=mapper_version),
        now=now,
    )
    return True


def provider_records_after(
    db: Any, *, after_id: int, limit: int
) -> list[dict[str, Any]]:
    """Return active raw records after one row id, in id order, for re-projection."""
    return _fetch_all(
        db,
        "SELECT id, provider, record_kind, source_record_id, payload, fetched_at, "
        "mapped_version FROM provider_records WHERE id > ? AND state = ? "
        "ORDER BY id LIMIT ?",
        (after_id, ProviderRecordState.ACTIVE.value, limit),
    )


_ACTIVITY_READ_COLUMNS: Final = (
    "r.provider",
    "r.provider_activity_id",
    "r.source_kind",
    "r.recorded_by",
    "r.source_record_id",
    "r.sport",
    "r.environment",
    "r.started_at",
    "r.duration_s",
    "r.distance_m",
    "r.load",
    "r.load_model",
    "r.avg_hr",
    "r.avg_power",
    "r.moving_duration_s",
    "r.elevation_gain_m",
    "r.normalized_power",
    "r.avg_cadence",
    "r.energy_kj",
    "r.name",
    "r.details",
    "r.fetched_at",
)
_OBSERVATION_READ_COLUMNS: Final = (
    "metric",
    "value",
    "unit",
    "source_kind",
    "recorded_by",
    "provider",
    "source_record_id",
    "sport",
    "observed_on",
    "observed_at",
    "retrieved_at",
    "label",
    "method",
    "aggregation",
    "details",
)


def active_activity_rows(
    db: Any, *, start: str | None = None, end: str | None = None
) -> list[dict[str, Any]]:
    """Return active activity rows whose session is not deleted, by ISO local date bounds.

    Invalid and deleted activity records are never returned. ``start`` and ``end``
    are inclusive ISO dates on the stored athlete-local date.
    """
    clauses = ["r.state = ?", "s.state <> ?"]
    params: list[object] = [
        ActivityRecordState.ACTIVE.value,
        ActivitySessionState.DELETED.value,
    ]
    if start is not None:
        clauses.append("r.local_date >= ?")
        params.append(start)
    if end is not None:
        clauses.append("r.local_date <= ?")
        params.append(end)
    return _fetch_all(
        db,
        f"SELECT {', '.join(_ACTIVITY_READ_COLUMNS)} FROM activity_records AS r "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        f"WHERE {' AND '.join(clauses)} ORDER BY r.started_at, r.provider, "
        "r.provider_activity_id",
        tuple(params),
    )


def activity_max_hr_rows(
    db: Any, provider: str, *, low: float, high: float
) -> list[dict[str, Any]]:
    """Return each sport's highest max heart rate within bounds and its newest day.

    The maximum heart rate is read from the details object. Rows have ``sport``,
    ``max_hr`` and ``local_date``; only active records of sessions that are not
    deleted count.
    """
    return _fetch_all(
        db,
        "WITH hr AS (SELECT r.sport AS sport, r.local_date AS local_date, "
        f"json_extract(CASE WHEN json_valid(r.details) THEN r.details END, '$.{_MAX_HR_KEY}') "
        "AS max_hr FROM activity_records AS r "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        "WHERE r.provider = ? AND r.state = ? AND s.state <> ? "
        "AND r.local_date IS NOT NULL), "
        "bounded AS (SELECT * FROM hr WHERE typeof(max_hr) IN ('integer', 'real') "
        "AND max_hr BETWEEN ? AND ?) "
        "SELECT b.sport AS sport, b.max_hr AS max_hr, MAX(b.local_date) AS local_date "
        "FROM bounded AS b JOIN (SELECT sport, MAX(max_hr) AS top FROM bounded "
        "GROUP BY sport) AS t ON t.sport = b.sport AND b.max_hr = t.top "
        "GROUP BY b.sport ORDER BY b.sport",
        (
            provider,
            ActivityRecordState.ACTIVE.value,
            ActivitySessionState.DELETED.value,
            low,
            high,
        ),
    )


def session_activity_rows(db: Any, activity_id: str) -> list[dict[str, Any]]:
    """Return the active activity rows bundled in one session, for detail reads.

    The record set mirrors ``activity_detail_store.detail_sets_for_session``: rows
    of the session itself and of sessions merged into it. A deleted session returns
    nothing. Invalid and deleted records are never returned.
    """
    return _fetch_all(
        db,
        f"SELECT {', '.join(_ACTIVITY_READ_COLUMNS)} FROM activity_records AS r "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        "WHERE r.state = ? AND "
        "(s.activity_id = ? OR (s.state = ? AND s.merged_into = ?)) "
        "AND NOT EXISTS (SELECT 1 FROM activity_sessions AS owner "
        "WHERE owner.activity_id = ? AND owner.state = ?) "
        "ORDER BY r.started_at, r.provider, r.provider_activity_id",
        (
            ActivityRecordState.ACTIVE.value,
            activity_id,
            ActivitySessionState.DUPLICATE.value,
            activity_id,
            activity_id,
            ActivitySessionState.DELETED.value,
        ),
    )


def active_activity_payload_texts(
    db: Any,
    *,
    provider: str,
    record_kind: str,
    start: str | None = None,
    end: str | None = None,
    limit: int | None = None,
) -> list[str]:
    """Return the stored raw payload text of one provider's live activities.

    Only active raw records whose activity record is active and whose session is
    not deleted are returned, so tombstoned activities are never served. ``start``
    and ``end`` are inclusive ISO dates on the stored athlete-local date. Newest
    first, like the stored snapshot: activity start time, then provider activity
    id, both descending. ``limit`` bounds the rows in SQL.
    """
    clauses = [
        "p.provider = ?",
        "p.record_kind = ?",
        "p.state = ?",
        "r.state = ?",
        "s.state <> ?",
    ]
    params: list[object] = [
        provider,
        record_kind,
        ProviderRecordState.ACTIVE.value,
        ActivityRecordState.ACTIVE.value,
        ActivitySessionState.DELETED.value,
    ]
    if start is not None:
        clauses.append("r.local_date >= ?")
        params.append(start)
    if end is not None:
        clauses.append("r.local_date <= ?")
        params.append(end)
    limit_clause = ""
    if limit is not None:
        limit_clause = " LIMIT ?"
        params.append(limit)
    rows = _fetch_all(
        db,
        "SELECT p.payload FROM provider_records AS p "
        "JOIN activity_records AS r ON r.provider = p.provider "
        "AND r.provider_activity_id = p.source_record_id "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        f"WHERE {' AND '.join(clauses)} ORDER BY r.started_at DESC, "
        f"r.provider_activity_id DESC{limit_clause}",
        tuple(params),
    )
    return [str(row["payload"]) for row in rows]


def _current_version_clause(
    versions: Mapping[str, int], oldest_versions: Mapping[str, int] | None
) -> tuple[str, list[object]]:
    """Return the parenthesised provider and version-window clause with its parameters.

    A provider's rows count from the lower of its oldest pending version and its
    current version up to the current one. Without ``oldest_versions`` the window
    is the current version alone.
    """
    lowest = oldest_versions or {}
    provider_clause = " OR ".join(
        "(provider = ? AND mapper_version BETWEEN ? AND ?)" for _ in versions
    )
    params: list[object] = []
    for provider, version in versions.items():
        params.extend((provider, min(lowest.get(provider, version), version), version))
    return f"({provider_clause})", params


def current_observation_rows(
    db: Any,
    metric: str,
    versions: Mapping[str, int],
    *,
    start: str | None = None,
    end: str | None = None,
    sport: str | None = None,
    oldest_versions: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Return observation rows of one metric at each provider's current mapper version.

    ``versions`` maps a provider value to its current observation mapper version;
    rows of any other version, or of no provider, are not returned. Bounds are
    inclusive ISO dates on ``observed_on``. A natural key has one row, which a
    re-projection rewrites in place, so ``oldest_versions`` also returns the rows
    that still carry a version from that provider's oldest version up to the
    current one: the newest stored version of each identity while a re-projection
    is pending. Rows below the oldest version were retired by an earlier mapper
    and stay hidden.
    """
    version_clause, version_params = _current_version_clause(versions, oldest_versions)
    params: list[object] = [metric, *version_params]
    clauses = ["metric = ?", version_clause]
    if start is not None:
        clauses.append("observed_on >= ?")
        params.append(start)
    if end is not None:
        clauses.append("observed_on <= ?")
        params.append(end)
    if sport is not None:
        clauses.append("sport = ?")
        params.append(sport)
    return _fetch_all(
        db,
        f"SELECT {', '.join(_OBSERVATION_READ_COLUMNS)} FROM observations "
        f"WHERE {' AND '.join(clauses)} ORDER BY observed_on, id",
        tuple(params),
    )


def observation_metric_windows(
    db: Any,
    versions: Mapping[str, int],
    *,
    oldest_versions: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Return the count and newest observed day of each provider metric, without values.

    The rows are the ones ``current_observation_rows`` serves for the same
    ``versions`` and ``oldest_versions``, so the counts match what the tables serve.
    Each dict holds ``provider``, ``metric``, ``observations``, ``oldest`` and
    ``newest`` (the earliest and latest ``observed_on`` as ISO text) and no other
    column.
    """
    if not versions:
        return []
    version_clause, params = _current_version_clause(versions, oldest_versions)
    return _fetch_all(
        db,
        "SELECT provider, metric, COUNT(*) AS observations, "
        "MIN(observed_on) AS oldest, MAX(observed_on) AS newest FROM observations "
        f"WHERE {version_clause} GROUP BY provider, metric",
        tuple(params),
    )


def provider_totals(db: Any, provider: str) -> dict[str, Any]:
    """Return how many active activities and observations one provider holds in the tables.

    The dict holds ``activities``, ``observations`` and the earliest and latest
    observed day as ISO text (``oldest``, ``newest``; None without observations).
    """
    activities = _fetch_row(
        db,
        "SELECT COUNT(*) AS count FROM activity_records WHERE provider = ? "
        "AND state = 'active'",
        (provider,),
    )
    observations = _fetch_row(
        db,
        "SELECT COUNT(*) AS count, MIN(observed_on) AS oldest, "
        "MAX(observed_on) AS newest FROM observations WHERE provider = ?",
        (provider,),
    )
    return {
        "activities": int(activities["count"]) if activities else 0,
        "observations": int(observations["count"]) if observations else 0,
        "oldest": observations["oldest"] if observations else None,
        "newest": observations["newest"] if observations else None,
    }


def active_record_payloads(
    db: Any, *, provider: str, record_kind: str
) -> dict[str, str]:
    """Return the stored payload text of each active raw record, by source record id."""
    rows = _fetch_all(
        db,
        "SELECT source_record_id, payload FROM provider_records "
        "WHERE provider = ? AND record_kind = ? AND state = ?",
        (provider, record_kind, ProviderRecordState.ACTIVE.value),
    )
    return {str(row["source_record_id"]): str(row["payload"]) for row in rows}


def set_mapped_version(
    db: Any, *, record_id: int, mapper_version: int, now: str
) -> None:
    """Record the mapper version that the raw record was last projected with."""
    db.execute(
        "UPDATE provider_records SET mapped_version = ?, updated_at = ? WHERE id = ?",
        (mapper_version, now, record_id),
    )


def count_unresolved_feedback(db: Any, provider: str) -> int:
    """Count feedback rows whose activity has no activity row of the given provider.

    Feedback rows are only read here and are never changed.
    """
    row = _fetch_row(
        db,
        "SELECT COUNT(*) AS count FROM activity_feedback AS feedback WHERE NOT EXISTS "
        "(SELECT 1 FROM activity_records AS record WHERE record.provider = ? "
        "AND record.provider_activity_id = feedback.activity_id)",
        (provider,),
    )
    return int(row["count"]) if row is not None else 0


def observation_natural_key(observation: Observation) -> str:
    """Return provider|metric|sport|series|(observed_at or observed_on).

    NULL parts are empty strings. The series part is empty except for a weight
    or eFTP that the Intervals.icu athlete profile reports (see
    ``_observation_series``), which therefore never shares a key with the
    wellness value of the same day.
    """
    provider = observation.provenance.provider
    sport = observation.sport
    when = (
        observation.observed_at.isoformat()
        if observation.observed_at is not None
        else observation.observed_on.isoformat()
    )
    return "|".join(
        (
            provider.value if provider is not None else "",
            observation.kind.value,
            sport.value if sport is not None else "",
            _observation_series(observation),
            when,
        )
    )


def _observation_series(observation: Observation) -> str:
    """Return ``athlete`` for an Intervals.icu athlete-profile value, else empty.

    Weight, eFTP, body fat and the sport-less VO2max come from both records. A
    wellness row is identified by its ISO day, so such a value whose source record
    is anything else comes from the athlete record. The consumers tell the two
    apart by the same rule. Both values are kept: the current-metrics reader shows
    the wellness weight and body fat first and the athlete values as their
    fallbacks, and the athlete eFTP before the wellness eFTP.
    """
    provenance = observation.provenance
    shared = observation.kind in _ATHLETE_SERIES_KINDS or (
        observation.kind in _ATHLETE_SPORTLESS_SERIES_KINDS
        and observation.sport is None
    )
    if (
        provenance.provider is ProviderId.INTERVALS
        and shared
        and provenance.source_record_id != observation.observed_on.isoformat()
    ):
        return ATHLETE_SERIES
    return ""


def upsert_observation(
    db: Any,
    observation: Observation,
    *,
    mapper_version: int,
    now: str,
    fill_only: bool = False,
) -> WriteOutcome:
    """Insert or update one observation by its natural key.

    A ``fill_only`` observation never replaces a current row another source
    record wrote; it inserts, updates its own row, or replaces a row left at an
    older mapper version, which no stored record re-projects any more.
    """
    natural_key = observation_natural_key(observation)
    values = _observation_values(observation, mapper_version=mapper_version)
    existing = _fetch_row(
        db,
        "SELECT "
        + ", ".join(_OBSERVATION_COLUMNS)
        + " FROM observations WHERE natural_key = ?",
        (natural_key,),
    )
    if existing is None:
        _insert_observation(db, natural_key=natural_key, values=values, now=now)
        return WriteOutcome.WRITTEN
    if (
        fill_only
        and existing["source_record_id"] != values["source_record_id"]
        and existing["mapper_version"] >= values["mapper_version"]
    ):
        return WriteOutcome.UNCHANGED
    if all(existing[column] == values[column] for column in _OBSERVATION_COLUMNS):
        return WriteOutcome.UNCHANGED
    assignments = ", ".join(f"{column} = ?" for column in _OBSERVATION_COLUMNS)
    db.execute(
        f"UPDATE observations SET {assignments}, updated_at = ? WHERE natural_key = ?",
        (
            *(values[column] for column in _OBSERVATION_COLUMNS),
            now,
            natural_key,
        ),
    )
    return WriteOutcome.UPDATED


def mark_missing_deleted(
    db: Any,
    provider: str,
    *,
    record_kind: str,
    window_start: date,
    window_end: date,
    present_ids: frozenset[str],
    now: str,
) -> int:
    """Mark active activities of one fully fetched window that the provider no longer returns.

    The window is matched on the athlete-local date of the activity. Each deleted
    activity also deletes its raw record and the session it is the primary of.
    Returns the number of activities marked deleted.
    """
    candidates = _fetch_all(
        db,
        "SELECT provider_activity_id, activity_id FROM activity_records "
        "WHERE provider = ? AND state = ? AND local_date BETWEEN ? AND ?",
        (
            provider,
            ActivityRecordState.ACTIVE.value,
            window_start.isoformat(),
            window_end.isoformat(),
        ),
    )
    deleted = 0
    for candidate in candidates:
        provider_activity_id = candidate["provider_activity_id"]
        activity_id = candidate["activity_id"]
        if provider_activity_id in present_ids:
            continue
        _delete_activity(
            db,
            provider,
            record_kind=record_kind,
            provider_activity_id=provider_activity_id,
            activity_id=activity_id,
            now=now,
        )
        deleted += 1
    return deleted


def mark_activity_deleted(
    db: Any,
    provider: str,
    *,
    record_kind: str,
    provider_activity_id: str,
    now: str,
) -> bool:
    """Tombstone one activity the provider removed, with its raw record and session.

    Table-served readers stop returning it. Returns False when the activity was
    never stored or is already deleted, and then changes nothing.
    """
    found = _fetch_all(
        db,
        "SELECT activity_id FROM activity_records "
        "WHERE provider = ? AND provider_activity_id = ? AND state = ?",
        (provider, provider_activity_id, ActivityRecordState.ACTIVE.value),
    )
    if not found:
        return False
    _delete_activity(
        db,
        provider,
        record_kind=record_kind,
        provider_activity_id=provider_activity_id,
        activity_id=found[0]["activity_id"],
        now=now,
    )
    return True


def _delete_activity(
    db: Any,
    provider: str,
    *,
    record_kind: str,
    provider_activity_id: str,
    activity_id: str,
    now: str,
) -> None:
    db.execute(
        "UPDATE activity_records SET state = ?, updated_at = ? "
        "WHERE provider = ? AND provider_activity_id = ?",
        (ActivityRecordState.DELETED.value, now, provider, provider_activity_id),
    )
    db.execute(
        "UPDATE provider_records SET state = ?, updated_at = ? "
        "WHERE provider = ? AND record_kind = ? AND source_record_id = ?",
        (
            ProviderRecordState.DELETED.value,
            now,
            provider,
            record_kind,
            provider_activity_id,
        ),
    )
    # A deleted merged alias also leaves its merge: the schema allows merged_into
    # only on duplicate sessions. merged_into_retained keeps the survivor, so
    # feedback written for the alias still resolves (effective_session_ids).
    cursor = db.execute(
        "UPDATE activity_sessions SET state = ?, "
        "merged_into_retained = COALESCE(merged_into, merged_into_retained), "
        "merged_into = NULL, updated_at = ? "
        "WHERE activity_id = ? AND primary_provider = ? "
        "AND primary_provider_activity_id = ?",
        (
            ActivitySessionState.DELETED.value,
            now,
            activity_id,
            provider,
            provider_activity_id,
        ),
    )
    if cursor.rowcount == 1:
        _repoint_aliases(db, activity_id, now=now)


def _repoint_aliases(db: Any, deleted_id: str, *, now: str) -> None:
    """Hand the live aliases of a deleted surviving session to a new survivor.

    The oldest alias (by creation, then id) becomes the active survivor and the
    other aliases merge into it, so no live session points at a deleted one. The
    deleted session and every deleted alias that retained it now retain the new
    survivor, so feedback written for them keeps resolving to a live session.
    """
    aliases = _fetch_all(
        db,
        "SELECT activity_id FROM activity_sessions WHERE merged_into = ? AND state = ? "
        "ORDER BY created_at, activity_id",
        (deleted_id, ActivitySessionState.DUPLICATE.value),
    )
    if not aliases:
        return
    survivor, *others = (str(row["activity_id"]) for row in aliases)
    db.execute(
        "UPDATE activity_sessions SET state = ?, merged_into = NULL, updated_at = ? "
        "WHERE activity_id = ?",
        (ActivitySessionState.ACTIVE.value, now, survivor),
    )
    for activity_id in others:
        db.execute(
            "UPDATE activity_sessions SET merged_into = ?, updated_at = ? "
            "WHERE activity_id = ?",
            (survivor, now, activity_id),
        )
    db.execute(
        "UPDATE activity_sessions SET merged_into_retained = ?, updated_at = ? "
        "WHERE merged_into_retained = ?",
        (survivor, now, deleted_id),
    )
    db.execute(
        "UPDATE activity_sessions SET merged_into_retained = ?, updated_at = ? "
        "WHERE activity_id = ?",
        (survivor, now, deleted_id),
    )


def _insert_provider_record(
    db: Any,
    *,
    provider: str,
    record_kind: str,
    source_record_id: str,
    text: str,
    digest: str,
    mapper_version: int,
    fetched_at: str,
    now: str,
    observed_on: str | None = None,
) -> None:
    db.execute(
        "INSERT INTO provider_records (provider, record_kind, source_record_id, "
        "payload, payload_hash, fetched_at, mapped_version, state, created_at, "
        "updated_at, observed_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            provider,
            record_kind,
            source_record_id,
            text,
            digest,
            fetched_at,
            mapper_version,
            ProviderRecordState.ACTIVE.value,
            now,
            now,
            observed_on,
        ),
    )


def _insert_activity(
    db: Any,
    *,
    provider: str,
    provider_activity_id: str,
    values: dict[str, Any],
    fetched_at: str,
    now: str,
) -> None:
    """Insert an activity with a new single-link session. The caller checked absence."""
    activity_id = ACTIVITY_ID_PREFIX + uuid.uuid4().hex
    db.execute(
        "INSERT INTO activity_sessions (activity_id, primary_provider, "
        "primary_provider_activity_id, link_kind, athlete_confirmed, state, "
        "started_at, local_date, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?)",
        (
            activity_id,
            provider,
            provider_activity_id,
            ActivityLinkKind.SINGLE.value,
            ActivitySessionState.ACTIVE.value,
            values["started_at"],
            values["local_date"],
            now,
            now,
        ),
    )
    columns = (
        "provider",
        "provider_activity_id",
        "activity_id",
        "state",
        *_ACTIVITY_COLUMNS,
        "fetched_at",
        "created_at",
        "updated_at",
    )
    db.execute(
        f"INSERT INTO activity_records ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' * len(columns))})",
        (
            provider,
            provider_activity_id,
            activity_id,
            ActivityRecordState.ACTIVE.value,
            *(values[column] for column in _ACTIVITY_COLUMNS),
            fetched_at,
            now,
            now,
        ),
    )


def _refresh_fetch_time(
    db: Any, *, provider: str, provider_activity_id: str, fetched_at: str
) -> None:
    """Record the latest fetch time on an unchanged activity; its content is untouched."""
    db.execute(
        "UPDATE activity_records SET fetched_at = ? "
        "WHERE provider = ? AND provider_activity_id = ?",
        (fetched_at, provider, provider_activity_id),
    )


def _update_activity_columns(
    db: Any,
    *,
    provider: str,
    provider_activity_id: str,
    values: dict[str, Any],
    fetched_at: str,
    now: str,
) -> None:
    """Overwrite an activity's projected columns and make the record active again."""
    assignments = ", ".join(f"{column} = ?" for column in _ACTIVITY_COLUMNS)
    db.execute(
        f"UPDATE activity_records SET {assignments}, fetched_at = ?, state = ?, "
        "updated_at = ? WHERE provider = ? AND provider_activity_id = ?",
        (
            *(values[column] for column in _ACTIVITY_COLUMNS),
            fetched_at,
            ActivityRecordState.ACTIVE.value,
            now,
            provider,
            provider_activity_id,
        ),
    )


def _insert_observation(
    db: Any, *, natural_key: str, values: dict[str, Any], now: str
) -> None:
    columns = (
        "natural_key",
        *_OBSERVATION_COLUMNS,
        "created_at",
        "updated_at",
    )
    db.execute(
        f"INSERT INTO observations ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' * len(columns))})",
        (
            natural_key,
            *(values[column] for column in _OBSERVATION_COLUMNS),
            now,
            now,
        ),
    )


def _activity_identity(record: ActivityRecord) -> tuple[str, str]:
    provider = record.provenance.provider
    provider_activity_id = record.provenance.source_record_id
    if provider is None or provider_activity_id is None:
        raise ValueError("activity records need a provider and a provider activity id")
    return provider.value, provider_activity_id


def _activity_values(
    record: ActivityRecord, *, local_date: date, mapper_version: int
) -> dict[str, Any]:
    provenance = record.provenance
    return {
        "source_kind": provenance.source_kind.value,
        "recorded_by": provenance.recorded_by.value,
        "source_record_id": provenance.source_record_id,
        "sport": record.sport.value,
        "environment": record.environment.value,
        "started_at": record.started_at.isoformat(),
        "local_date": local_date.isoformat(),
        "duration_s": record.duration_s,
        "distance_m": record.distance_m,
        "load": record.load,
        "load_model": record.load_model.value,
        "avg_hr": record.avg_hr,
        "avg_power": record.avg_power,
        "moving_duration_s": record.moving_duration_s,
        "elevation_gain_m": record.elevation_gain_m,
        "normalized_power": record.normalized_power,
        "avg_cadence": record.avg_cadence,
        "energy_kj": record.energy_kj,
        "name": record.name,
        "details": _activity_details(record),
        "mapper_version": mapper_version,
    }


def _activity_details(record: ActivityRecord) -> str:
    # The projection owns the whole details object; no other writer adds keys.
    # Values without a column of their own live here, so no migration is needed.
    details = {
        key: value
        for key, value in (
            (_ELAPSED_DURATION_KEY, record.elapsed_duration_s),
            (_MAX_HR_KEY, record.max_hr),
            (_MAX_SPEED_KEY, record.max_speed_mps),
            (_MAX_POWER_KEY, record.max_power_w),
            (_MIN_HR_KEY, record.min_hr),
            (_ELEVATION_HIGH_KEY, record.elevation_high_m),
            (_ELEVATION_LOW_KEY, record.elevation_low_m),
            (_STEPS_KEY, record.steps),
            (
                _DEVICE_TYPE_KEY,
                None if record.device_type is None else record.device_type.value,
            ),
            (_CONTEXT_KEY, record.provenance.context.as_details() or None),
        )
        if value is not None
    }
    if not details:
        return ACTIVITY_DETAILS
    return json.dumps(details, separators=(",", ":"))


def activity_elapsed_duration(details: object) -> float | None:
    """Return the elapsed duration stored in an activity's details, if any."""
    return _activity_detail_number(details, _ELAPSED_DURATION_KEY)


def activity_max_hr(details: object) -> float | None:
    """Return the maximum heart rate stored in an activity's details, if any."""
    return _activity_detail_number(details, _MAX_HR_KEY)


def activity_max_speed(details: object) -> float | None:
    """Return the maximum speed in metres per second stored in the details, if any."""
    return _activity_detail_number(details, _MAX_SPEED_KEY)


def activity_max_power(details: object) -> float | None:
    """Return the maximum power in watts stored in an activity's details, if any."""
    return _activity_detail_number(details, _MAX_POWER_KEY)


def activity_min_hr(details: object) -> float | None:
    """Return the minimum heart rate stored in an activity's details, if any."""
    return _activity_detail_number(details, _MIN_HR_KEY)


def activity_elevation_high(details: object) -> float | None:
    """Return the highest elevation in metres stored in the details, if any."""
    return _activity_detail_number(details, _ELEVATION_HIGH_KEY)


def activity_elevation_low(details: object) -> float | None:
    """Return the lowest elevation in metres stored in an activity's details, if any."""
    return _activity_detail_number(details, _ELEVATION_LOW_KEY)


def activity_steps(details: object) -> float | None:
    """Return the step count stored in an activity's details, if any."""
    return _activity_detail_number(details, _STEPS_KEY)


def activity_device_type(details: object) -> DeviceType | None:
    """Return the recording device type stored in an activity's details, if any.

    A missing, non-text or unknown value is None; it never raises.
    """
    value = _activity_detail_value(details, _DEVICE_TYPE_KEY)
    if not isinstance(value, str):
        return None
    try:
        return DeviceType(value)
    except ValueError:
        return None


def measurement_context(details: object) -> MeasurementContext:
    """Return the measurement context stored in activity or observation details.

    A missing or invalid stored context is unknown; it never raises.
    """
    value = _activity_detail_value(details, _CONTEXT_KEY)
    if value is None:
        return UNKNOWN_CONTEXT
    try:
        return MeasurementContext.from_details(value)
    except TypeError, ValueError:
        return UNKNOWN_CONTEXT


class ObservationDerivation(NamedTuple):
    method_version: int | None
    input_fingerprint: str | None
    period: ObservationPeriod | None


def observation_derivation(details: object) -> ObservationDerivation:
    """Return the method version, input fingerprint and period stored in details.

    Missing values are None. A stored value of the wrong type raises ValueError,
    because only validated observations are written.
    """
    version = _activity_detail_value(details, _METHOD_VERSION_KEY)
    fingerprint = _activity_detail_value(details, _INPUT_FINGERPRINT_KEY)
    period = _activity_detail_value(details, _PERIOD_KEY)
    if version is not None and (
        isinstance(version, bool) or not isinstance(version, int)
    ):
        raise ValueError("stored method_version must be an integer")
    if fingerprint is not None and not isinstance(fingerprint, str):
        raise ValueError("stored input_fingerprint must be text")
    if period is None:
        return ObservationDerivation(version, fingerprint, None)
    if not isinstance(period, dict) or set(period) != {"start", "end"}:
        raise ValueError("stored period must have a start and an end")
    return ObservationDerivation(
        version,
        fingerprint,
        ObservationPeriod(
            start=datetime.fromisoformat(str(period["start"])),
            end=datetime.fromisoformat(str(period["end"])),
        ),
    )


def _activity_detail_number(details: object, key: str) -> float | None:
    value = _activity_detail_value(details, key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _activity_detail_value(details: object, key: str) -> object:
    if not isinstance(details, str):
        return None
    try:
        loaded = json.loads(details)
    except ValueError, RecursionError:
        return None
    return loaded.get(key) if isinstance(loaded, dict) else None


def _observation_values(
    observation: Observation, *, mapper_version: int
) -> dict[str, Any]:
    provenance = observation.provenance
    return {
        "metric": observation.kind.value,
        "value": observation.value.value,
        "unit": observation.value.unit,
        "source_kind": provenance.source_kind.value,
        "recorded_by": provenance.recorded_by.value,
        "provider": provenance.provider.value
        if provenance.provider is not None
        else None,
        "source_record_id": provenance.source_record_id,
        "sport": observation.sport.value if observation.sport is not None else None,
        "observed_on": observation.observed_on.isoformat(),
        "observed_at": (
            observation.observed_at.isoformat()
            if observation.observed_at is not None
            else None
        ),
        "retrieved_at": (
            provenance.retrieved_at.isoformat()
            if provenance.retrieved_at is not None
            else None
        ),
        "label": provenance.label,
        "mapper_version": mapper_version,
        "method": observation.method,
        "aggregation": (
            observation.aggregation.value
            if observation.aggregation is not None
            else None
        ),
        "details": _observation_details(observation),
    }


def _observation_details(observation: Observation) -> str:
    # Metadata without a column of its own. A row without any keeps "{}", so
    # stored rows written before schema version 15 compare unchanged.
    period = observation.period
    details = {
        key: value
        for key, value in (
            (_CONTEXT_KEY, observation.provenance.context.as_details() or None),
            (_METHOD_VERSION_KEY, observation.method_version),
            (_INPUT_FINGERPRINT_KEY, observation.input_fingerprint),
            (
                _PERIOD_KEY,
                None
                if period is None
                else {"start": period.start.isoformat(), "end": period.end.isoformat()},
            ),
        )
        if value is not None
    }
    return canonical_json(details) if details else OBSERVATION_DETAILS


def _fetch_row(db: Any, sql: str, params: tuple[object, ...]) -> dict[str, Any] | None:
    """Return the first row as a dict whatever row factory the connection uses."""
    cursor = db.execute(sql, params)
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    names = [column[0] for column in cursor.description]
    return dict(zip(names, row, strict=True))


def _fetch_all(db: Any, sql: str, params: tuple[object, ...]) -> list[dict[str, Any]]:
    """Return every row as a dict whatever row factory the connection uses."""
    cursor = db.execute(sql, params)
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], Mapping):
        return [dict(row) for row in rows]
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in rows]


_READ_CHUNK_SIZE: Final = 500


def activity_sessions_by_ids(
    db: Any, activity_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Return session rows keyed by local activity id; unknown ids are absent."""
    rows: dict[str, dict[str, Any]] = {}
    for chunk in _chunked(activity_ids):
        for row in _fetch_all(
            db,
            "SELECT activity_id, primary_provider, primary_provider_activity_id, "
            "state, merged_into FROM activity_sessions "
            f"WHERE activity_id IN ({_placeholders(chunk)})",
            tuple(chunk),
        ):
            rows[row["activity_id"]] = row
    return rows


_LINKABLE_COLUMNS: Final = (
    *_ACTIVITY_READ_COLUMNS,
    "r.activity_id AS session_id",
)


def linkable_activity_rows(db: Any, *, start: str, end: str) -> list[dict[str, Any]]:
    """Return active activity rows that session linking may bundle, by ISO local date.

    A record qualifies when its session is active or an alias (``duplicate``) and
    not athlete-confirmed. Hidden, deleted and confirmed sessions are never linked.
    ``start`` and ``end`` are inclusive ISO dates on the stored athlete-local date.
    """
    return _fetch_all(
        db,
        f"SELECT {', '.join(_LINKABLE_COLUMNS)} FROM activity_records AS r "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        "WHERE r.state = ? AND s.state IN (?, ?) AND s.athlete_confirmed = 0 "
        "AND r.local_date >= ? AND r.local_date <= ? "
        "ORDER BY r.started_at, r.provider, r.provider_activity_id",
        (
            ActivityRecordState.ACTIVE.value,
            ActivitySessionState.ACTIVE.value,
            ActivitySessionState.DUPLICATE.value,
            start,
            end,
        ),
    )


def activity_session_link_rows(
    db: Any, activity_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Return the session columns that linking decides on, keyed by local activity id."""
    rows: dict[str, dict[str, Any]] = {}
    for chunk in _chunked(activity_ids):
        for row in _fetch_all(
            db,
            "SELECT activity_id, link_kind, athlete_confirmed, state, merged_into, "
            "created_at FROM activity_sessions "
            f"WHERE activity_id IN ({_placeholders(chunk)})",
            tuple(chunk),
        ):
            rows[row["activity_id"]] = row
    return rows


def merge_activity_session(db: Any, *, activity_id: str, into: str, now: str) -> bool:
    """Make an active, unconfirmed session an alias of ``into``; return whether it changed.

    Sessions that were already aliases of this one now point at ``into`` directly.
    Records keep their ``activity_id`` and the session keeps its primary provider.
    """
    cursor = db.execute(
        "UPDATE activity_sessions SET state = ?, merged_into = ?, updated_at = ? "
        "WHERE activity_id = ? AND state = ? AND athlete_confirmed = 0",
        (
            ActivitySessionState.DUPLICATE.value,
            into,
            now,
            activity_id,
            ActivitySessionState.ACTIVE.value,
        ),
    )
    if cursor.rowcount != 1:
        return False
    db.execute(
        "UPDATE activity_sessions SET merged_into = ?, updated_at = ? "
        "WHERE merged_into = ? AND state = ?",
        (into, now, activity_id, ActivitySessionState.DUPLICATE.value),
    )
    db.execute(
        "UPDATE activity_sessions SET merged_into_retained = ?, updated_at = ? "
        "WHERE merged_into_retained = ?",
        (into, now, activity_id),
    )
    return True


def provider_activity_sessions(
    db: Any, provider: str, provider_activity_ids: Sequence[str]
) -> dict[str, str]:
    """Map active provider activity ids to the session their merges lead to.

    Unknown, invalid and deleted records are absent.
    """
    sessions: dict[str, str] = {}
    for chunk in _chunked(list(dict.fromkeys(provider_activity_ids))):
        for row in _fetch_all(
            db,
            "SELECT provider_activity_id, activity_id FROM activity_records "
            f"WHERE provider = ? AND state = ? AND provider_activity_id IN "
            f"({_placeholders(chunk)})",
            (provider, ActivityRecordState.ACTIVE.value, *chunk),
        ):
            sessions[str(row["provider_activity_id"])] = str(row["activity_id"])
    effective = effective_session_ids(db, list(sessions.values()))
    return {
        activity_id: effective.get(session, session)
        for activity_id, session in sessions.items()
    }


def effective_session_ids(db: Any, activity_ids: Sequence[str]) -> dict[str, str]:
    """Map stored session ids to the session their merges lead to; unknown ids are absent.

    A chain follows ``merged_into``, or for a deleted alias the survivor its
    deletion retained. It stops at a session without either, at a cycle or after
    64 merges. An unmerged session maps to itself. Feedback keeps the session it
    was written for and is shown on the session this returns.
    """
    targets = _merge_targets(db, activity_ids)
    return {
        activity_id: _follow_merges(targets, activity_id)
        for activity_id in dict.fromkeys(activity_ids)
        if activity_id in targets
    }


def _merge_targets(db: Any, activity_ids: Sequence[str]) -> dict[str, str | None]:
    """Read each session's merge target along the chains, up to the hop limit."""
    targets: dict[str, str | None] = {}
    pending = list(activity_ids)
    for _ in range(_MAX_MERGE_HOPS + 1):
        pending = [activity_id for activity_id in pending if activity_id not in targets]
        if not pending:
            break
        for chunk in _chunked(pending):
            for row in _fetch_all(
                db,
                "SELECT activity_id, COALESCE(merged_into, merged_into_retained) "
                "AS target FROM activity_sessions "
                f"WHERE activity_id IN ({_placeholders(chunk)})",
                tuple(chunk),
            ):
                targets[row["activity_id"]] = row["target"]
        pending = [
            target
            for activity_id in pending
            if (target := targets.get(activity_id)) is not None
        ]
    return targets


def _follow_merges(targets: dict[str, str | None], activity_id: str) -> str:
    current, seen = activity_id, {activity_id}
    while len(seen) <= _MAX_MERGE_HOPS:
        target = targets.get(current)
        if target is None or target not in targets or target in seen:
            break
        seen.add(target)
        current = target
    return current


def set_activity_session_link_kind(
    db: Any, *, activity_id: str, link_kind: str, now: str
) -> None:
    """Store the link kind of an active session."""
    db.execute(
        "UPDATE activity_sessions SET link_kind = ?, updated_at = ? "
        "WHERE activity_id = ? AND state = ?",
        (link_kind, now, activity_id, ActivitySessionState.ACTIVE.value),
    )


def feedback_origin_sessions(
    db: Any, references: Sequence[tuple[str, str | None]]
) -> dict[str, str]:
    """Map feedback keys to the session they were written for.

    A local session id is its own session. Any other key is the provider activity
    id of the only activity record that carries it, of the named provider when one
    is given. Ambiguous and unknown keys are absent, as in the schema v15 backfill.
    """
    keys = list(dict.fromkeys(key for key, _ in references))
    providers = dict(references)
    sessions = {key: key for key in activity_sessions_by_ids(db, keys)}
    matches: dict[str, set[str]] = {}
    for chunk in _chunked([key for key in keys if key not in sessions]):
        for row in _fetch_all(
            db,
            "SELECT provider, provider_activity_id, activity_id FROM activity_records "
            f"WHERE provider_activity_id IN ({_placeholders(chunk)})",
            tuple(chunk),
        ):
            key = str(row["provider_activity_id"])
            provider = providers.get(key)
            if provider is None or row["provider"] == provider:
                matches.setdefault(key, set()).add(str(row["activity_id"]))
    for key, found in matches.items():
        if len(found) == 1:
            (sessions[key],) = found
    return sessions


def deleted_activity_ids(db: Any, provider: str) -> frozenset[str]:
    """Return the provider activity ids whose record is tombstoned (state ``deleted``)."""
    return frozenset(
        str(row["provider_activity_id"])
        for row in _fetch_all(
            db,
            "SELECT provider_activity_id FROM activity_records "
            "WHERE provider = ? AND state = ?",
            (provider, ActivityRecordState.DELETED.value),
        )
    )


def activity_local_ids(
    db: Any, provider: str, provider_activity_ids: Sequence[str]
) -> dict[str, str]:
    """Map provider activity ids to the local session id of their record."""
    local_ids: dict[str, str] = {}
    for chunk in _chunked(provider_activity_ids):
        for row in _fetch_all(
            db,
            "SELECT provider_activity_id, activity_id FROM activity_records "
            f"WHERE provider = ? AND provider_activity_id IN ({_placeholders(chunk)})",
            (provider, *chunk),
        ):
            local_ids[row["provider_activity_id"]] = row["activity_id"]
    return local_ids


def activity_record_link(
    db: Any, provider: str, provider_activity_id: str
) -> dict[str, Any] | None:
    """Return the local session id, origin and state of one provider activity record."""
    return _fetch_row(
        db,
        "SELECT activity_id, recorded_by, state FROM activity_records "
        "WHERE provider = ? AND provider_activity_id = ?",
        (provider, provider_activity_id),
    )


def active_provider_record_hash(
    db: Any, provider: str, record_kind: str, source_record_id: str
) -> str | None:
    """Return the payload hash of one active raw provider record, if stored."""
    row = _fetch_row(
        db,
        "SELECT payload_hash FROM provider_records "
        "WHERE provider = ? AND record_kind = ? AND source_record_id = ? "
        "AND state = ?",
        (provider, record_kind, source_record_id, ProviderRecordState.ACTIVE.value),
    )
    return None if row is None else str(row["payload_hash"])


def activity_record_for_session(
    db: Any, provider: str, activity_id: str
) -> dict[str, Any] | None:
    """Return the active provider record behind a session id or its merge alias.

    The session must itself be active, or be a duplicate merged into
    ``activity_id``; deleted sessions and non-active records never match.
    """
    return _fetch_row(
        db,
        "SELECT r.provider_activity_id, r.activity_id, r.recorded_by, r.state "
        "FROM activity_records AS r "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        "WHERE r.provider = ? AND r.state = ? "
        "AND ((s.activity_id = ? AND s.state = ?) "
        "OR (s.merged_into = ? AND s.state = ?)) "
        "ORDER BY r.provider_activity_id LIMIT 1",
        (
            provider,
            ActivityRecordState.ACTIVE.value,
            activity_id,
            ActivitySessionState.ACTIVE.value,
            activity_id,
            ActivitySessionState.DUPLICATE.value,
        ),
    )


def _chunked(values: Sequence[str]) -> list[list[str]]:
    unique = list(dict.fromkeys(value for value in values if value))
    return [
        unique[start : start + _READ_CHUNK_SIZE]
        for start in range(0, len(unique), _READ_CHUNK_SIZE)
    ]


def _placeholders(values: Sequence[object]) -> str:
    return ", ".join("?" * len(values))
