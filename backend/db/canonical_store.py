"""Persistence owner for raw provider records and canonical activity and observation rows.

Every function writes through the connection of the caller's unit of work and
never commits. The caller's transaction decides whether these rows and the legacy
snapshot are kept together or rolled back together.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Collection, Mapping, Sequence
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, Final, NamedTuple

from backend.canonical.local_time import valid_offset_minutes
from backend.canonical.records import (
    MAX_NATIVE_TYPE_LENGTH,
    MAX_TRAINING_EFFECT_LABEL_LENGTH,
    MAX_ZONE_COUNT,
    MAX_ZONE_ID_LENGTH,
    UNKNOWN_CONTEXT,
    ActivityRecord,
    ExternalRef,
    MeasurementContext,
    Observation,
    ObservationPeriod,
)
from backend.canonical.validation import MAX_ACTIVITY_DURATION_S
from backend.canonical.vocabulary import (
    ActivityLinkKind,
    ActivityPurpose,
    ActivityRecordState,
    ActivitySessionState,
    Assist,
    DeviceType,
    MetricKind,
    ProjectionState,
    ProviderId,
    ProviderRecordState,
    SourceKind,
    Terrain,
)

ACTIVITY_ID_PREFIX: Final = "act_"
ATHLETE_SERIES: Final = "athlete"
# Local per-session derived kinds, keyed by their owning session (cards M6, M8,
# activity weather).
SESSION_SERIES_KINDS: Final = frozenset(
    {
        MetricKind.SESSION_LOAD,
        MetricKind.INTENSITY_FACTOR,
        MetricKind.EFFICIENCY_FACTOR,
        MetricKind.VARIABILITY_INDEX,
        MetricKind.MECHANICAL_WORK,
        MetricKind.AEROBIC_DECOUPLING,
        MetricKind.ACTIVITY_WEATHER_TEMPERATURE,
        MetricKind.ACTIVITY_WEATHER_APPARENT_TEMPERATURE,
        MetricKind.ACTIVITY_WEATHER_HUMIDITY,
        MetricKind.ACTIVITY_WEATHER_WIND_SPEED,
        MetricKind.ACTIVITY_WEATHER_PRECIPITATION,
    }
)
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
_PLANNED_EVENT_KEY: Final = "planned_event_id"
_DEVICE_NAME_KEY: Final = "device_name"
_TRAINING_EFFECT_LABEL_KEY: Final = "training_effect_label"
_EXTERNAL_REF_KEY: Final = "external_ref"
_LOCAL_OFFSET_KEY: Final = "local_offset_minutes"
_TERRAIN_KEY: Final = "terrain"
_ASSIST_KEY: Final = "assist"
_NATIVE_TYPE_KEY: Final = "native_type"
_PURPOSE_KEY: Final = "purpose"
# The stored terrain, assist and native type of ``r``, as columns named by key.
_QUALIFIER_COLUMNS: Final = ", ".join(
    f"json_extract(r.details, '$.{key}') AS {key}"
    for key in (_TERRAIN_KEY, _ASSIST_KEY, _NATIVE_TYPE_KEY)
)
# ActivityRecord summary fields stored in the details under their own names.
ACTIVITY_SUMMARY_DETAIL_FIELDS: Final = (
    "intensity",
    "rpe",
    "feel",
    "avg_speed_mps",
    "weighted_avg_speed_mps",
    "grade_adjusted_speed_mps",
    "pace_mps",
    "ftp_w",
    "eftp_w",
    "vo2max",
    "avg_temp_c",
    "min_temp_c",
    "max_temp_c",
    "elevation_loss_m",
    "lap_count",
    "aerobic_training_effect",
    "anaerobic_training_effect",
    "water_estimated_ml",
    "energy_kcal",
    "ground_contact_time_ms",
    "ground_contact_balance_pct",
    "vertical_oscillation_cm",
    "vertical_ratio_pct",
    "step_length_m",
)
ACTIVITY_ZONE_DETAIL_FIELDS: Final = (
    "power_zone_times_s",
    "hr_zone_times_s",
    "pace_zone_times_s",
)
_CONTEXT_KEY: Final = "context"
_METHOD_VERSION_KEY: Final = "method_version"
_INPUT_FINGERPRINT_KEY: Final = "input_fingerprint"
_DERIVATION_KEY: Final = "derivation"
_PERIOD_KEY: Final = "period"
_MAX_MERGE_HOPS: Final = 64

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
    "state",
    "owner_record_id",
)
_ACTIVE_OBSERVATION: Final = f"state = '{ProjectionState.ACTIVE.value}'"
_RETIRE_BATCH: Final = 500


class ObservationScope(NamedTuple):
    """What the latest projection of one owning raw record covers.

    ``days`` are the ISO days whose owned rows the projection speaks for;
    ``emitted`` are the natural keys it produced.
    """

    days: frozenset[str]
    emitted: frozenset[str]


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
    survivor = _revival_survivor(
        db, existing["activity_id"], recorded_by=values["recorded_by"]
    )
    if survivor is not None:
        # A provider-deleted alias of a live session returns as that session's
        # alias, so an athlete-confirmed bundle that linking cannot repair stays
        # one session. The survivor keeps its own confirmation.
        db.execute(
            "UPDATE activity_sessions SET started_at = ?, local_date = ?, "
            "state = ?, merged_into = ?, merged_into_retained = NULL, "
            "athlete_confirmed = 0, updated_at = ? WHERE activity_id = ?",
            (
                started_at,
                day,
                ActivitySessionState.DUPLICATE.value,
                survivor,
                now,
                existing["activity_id"],
            ),
        )
        return WriteOutcome.UPDATED
    db.execute(
        # A revived session is active again, so it no longer keeps the survivor
        # of a merge that its deletion cleared. A session the athlete deleted
        # stays deleted.
        "UPDATE activity_sessions SET started_at = ?, local_date = ?, "
        f"state = CASE WHEN state = ? AND NOT {ATHLETE_DELETED} THEN ? "
        "ELSE state END, "
        f"merged_into_retained = CASE WHEN state = ? AND NOT {ATHLETE_DELETED} "
        "THEN NULL ELSE merged_into_retained END, updated_at = ? "
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


def _revival_survivor(db: Any, activity_id: str, *, recorded_by: str) -> str | None:
    """Return the live session a revived provider-deleted alias goes back to, or None.

    The session must be deleted by a provider (not the athlete) and have retained a
    survivor that is active today, following later merges. A survivor that already
    holds an active record of the revived record's provider and recording origin
    keeps it: one session never takes two copies of one origin.
    """
    row = _fetch_row(
        db,
        "SELECT state, primary_provider, merged_into_retained, "
        f"{ATHLETE_DELETED} AS athlete_deleted "
        "FROM activity_sessions WHERE activity_id = ?",
        (activity_id,),
    )
    if (
        row is None
        or row["state"] != ActivitySessionState.DELETED.value
        or row["athlete_deleted"]
        or not row["merged_into_retained"]
    ):
        return None
    retained = str(row["merged_into_retained"])
    survivor = effective_session_ids(db, [retained]).get(retained)
    if survivor is None or survivor == activity_id:
        return None
    members = session_member_rows(db, survivor)
    if not members:
        return None
    if any(
        member["provider"] == row["primary_provider"]
        and member["recorded_by"] == recorded_by
        for member in members
    ):
        return None
    return survivor


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
        # A merged alias still names its own record's start, so it moves too.
        "UPDATE activity_sessions SET started_at = ?, local_date = ?, updated_at = ? "
        "WHERE activity_id = ? AND state IN (?, ?)",
        (
            values["started_at"],
            values["local_date"],
            now,
            existing["activity_id"],
            ActivitySessionState.ACTIVE.value,
            ActivitySessionState.DUPLICATE.value,
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
    return _fetch_all(
        db,
        f"SELECT {', '.join(_ACTIVITY_READ_COLUMNS)} FROM activity_records AS r "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        f"WHERE {' AND '.join(_bounded_clauses(start, end))} "
        "ORDER BY r.started_at, r.provider, r.provider_activity_id",
        _bounded_params(start, end),
    )


def active_session_activity_rows(
    db: Any, *, start: str | None = None, end: str | None = None
) -> list[tuple[str, dict[str, Any]]]:
    """Return (summary session id, row) for the active records of live sessions.

    A record of a duplicate (merged) session is listed under the session its
    merges lead to, so each activity appears once with all its copies. Records
    whose own or effective session is deleted are left out. Bounds and order are
    those of ``active_activity_rows``.
    """
    rows = _fetch_all(
        db,
        f"SELECT {', '.join(_ACTIVITY_READ_COLUMNS)}, r.activity_id AS session_id "
        "FROM activity_records AS r "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        f"WHERE {' AND '.join(_bounded_clauses(start, end))} "
        "ORDER BY r.started_at, r.provider, r.provider_activity_id",
        _bounded_params(start, end),
    )
    effective = effective_session_ids(db, [row["session_id"] for row in rows])
    targets = {effective.get(row["session_id"], row["session_id"]) for row in rows}
    deleted = {
        activity_id
        for activity_id, session in activity_sessions_by_ids(db, list(targets)).items()
        if session["state"] == ActivitySessionState.DELETED.value
    }
    grouped: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        session_id = effective.get(row["session_id"], row["session_id"])
        if session_id not in deleted:
            grouped.append((session_id, row))
    return grouped


def newest_sessions_start(db: Any, count: int, *, end: str | None = None) -> str | None:
    """Return the local date of the ``count``-th newest live session, or None.

    Live sessions are active or hidden and own an active record; merged aliases
    and deleted sessions do not count. ``end`` counts only sessions up to that
    local date. None means there are at most ``count``.
    """
    end_clause = "" if end is None else "AND s.local_date <= ? "
    rows = _fetch_all(
        db,
        "SELECT s.local_date FROM activity_sessions AS s WHERE s.state IN (?, ?) "
        f"AND s.local_date IS NOT NULL {end_clause}AND EXISTS (SELECT 1 FROM "
        "activity_records AS r WHERE r.activity_id = s.activity_id AND r.state = ?) "
        "ORDER BY s.started_at DESC LIMIT 1 OFFSET ?",
        (
            ActivitySessionState.ACTIVE.value,
            ActivitySessionState.HIDDEN.value,
            *(() if end is None else (end,)),
            ActivityRecordState.ACTIVE.value,
            max(count - 1, 0),
        ),
    )
    return None if not rows else str(rows[0]["local_date"])


def _bounded_clauses(start: str | None, end: str | None) -> list[str]:
    clauses = ["r.state = ?", "s.state <> ?"]
    if start is not None:
        clauses.append("r.local_date >= ?")
    if end is not None:
        clauses.append("r.local_date <= ?")
    return clauses


def _bounded_params(start: str | None, end: str | None) -> tuple[object, ...]:
    params: list[object] = [
        ActivityRecordState.ACTIVE.value,
        ActivitySessionState.DELETED.value,
    ]
    params.extend(bound for bound in (start, end) if bound is not None)
    return tuple(params)


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
    """Return active observation rows of one metric at each provider's current mapper version.

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
    clauses = ["metric = ?", version_clause, _ACTIVE_OBSERVATION]
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
        f"WHERE {version_clause} AND {_ACTIVE_OBSERVATION} GROUP BY provider, metric",
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
        "MAX(observed_on) AS newest FROM observations WHERE provider = ? "
        f"AND {_ACTIVE_OBSERVATION}",
        (provider,),
    )
    return {
        "activities": int(activities["count"]) if activities else 0,
        "observations": int(observations["count"]) if observations else 0,
        "oldest": observations["oldest"] if observations else None,
        "newest": observations["newest"] if observations else None,
    }


def set_mapped_version(
    db: Any, *, record_id: int, mapper_version: int, now: str
) -> None:
    """Record the mapper version that the raw record was last projected with."""
    db.execute(
        "UPDATE provider_records SET mapped_version = ?, updated_at = ? WHERE id = ?",
        (mapper_version, now, record_id),
    )


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
    """Return the series part of an observation's natural key.

    ``athlete`` marks an Intervals.icu athlete-profile value and
    ``session:<id>`` a local per-session derived value (card M6); else empty.

    Weight, eFTP, body fat and the sport-less VO2max come from both records. A
    wellness row is identified by its ISO day, so such a value whose source record
    is anything else comes from the athlete record. The consumers tell the two
    apart by the same rule. Both values are kept: the current-metrics reader shows
    the wellness weight and body fat first and the athlete values as their
    fallbacks; eFTP is stored history that no view reads.
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
    if (
        observation.kind in SESSION_SERIES_KINDS
        and provenance.provider is None
        and provenance.source_record_id
    ):
        # A local per-session value: two sessions may share sport and start.
        return f"session:{provenance.source_record_id}"
    return ""


def upsert_observation(
    db: Any,
    observation: Observation,
    *,
    mapper_version: int,
    now: str,
    fill_only: bool = False,
    owner: str | None = None,
    derivation: Mapping[str, Any] | None = None,
) -> WriteOutcome:
    """Insert or update one observation by its natural key; the row becomes active.

    ``derivation`` is stored under the details key ``derivation`` of a locally
    derived observation (the branch and thresholds of a local method).

    ``owner`` is the source record id of the raw record whose projection emits the
    observation (see ``retire_unemitted_observations``); None keeps the stored
    owner. A ``fill_only`` observation never replaces an active row another
    source record wrote; it inserts, updates its own row, revives a retired row,
    or replaces a row left at an older mapper version, which no stored record
    re-projects any more.
    """
    natural_key = observation_natural_key(observation)
    values = _observation_values(
        observation, mapper_version=mapper_version, owner=owner
    )
    if derivation is not None:
        values["details"] = canonical_json(
            {**json.loads(values["details"]), _DERIVATION_KEY: dict(derivation)}
        )
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
        and existing["state"] == ProjectionState.ACTIVE.value
        and existing["source_record_id"] != values["source_record_id"]
        and existing["mapper_version"] >= values["mapper_version"]
    ):
        return WriteOutcome.UNCHANGED
    if owner is None:
        values["owner_record_id"] = existing["owner_record_id"]
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


def derived_daily_sums(db: Any, method: str, metric: str) -> dict[str, float]:
    """Sum the active local derived ``metric`` values of ``method`` per observed day.

    Only rows owned by a live (active or hidden) session count, so a session that
    was deleted or merged drops out before the next stage pass retires its row.
    """
    rows = _fetch_all(
        db,
        "SELECT o.observed_on, SUM(o.value) AS total FROM observations AS o "
        "WHERE o.provider IS NULL AND o.method = ? AND o.metric = ? "
        "AND o.source_kind = ? AND o.state = ? AND EXISTS (SELECT 1 FROM "
        "activity_sessions AS s WHERE s.activity_id = o.owner_record_id "
        "AND s.state IN (?, ?)) GROUP BY o.observed_on",
        (
            method,
            metric,
            SourceKind.DERIVED.value,
            ProjectionState.ACTIVE.value,
            ActivitySessionState.ACTIVE.value,
            ActivitySessionState.HIDDEN.value,
        ),
    )
    return {str(row["observed_on"]): float(row["total"]) for row in rows}


def derived_observation_rows(
    db: Any, method: str, *, owners: Sequence[str] | None = None
) -> list[dict[str, Any]]:
    """Return the active local derived observations of ``method``.

    Each row has its natural key, metric, value, sport, observed day and instant,
    owner (the canonical session id, or the night of a morning value) and the
    parsed ``derivation`` details. Local
    derived rows carry no provider, so provider reads never return them.
    ``owners`` limits the rows to those owner ids; None returns every row.
    """
    sql = (
        "SELECT natural_key, metric, value, sport, observed_on, observed_at, "
        "owner_record_id, details FROM observations WHERE provider IS NULL "
        "AND method = ? "
        "AND source_kind = ? AND state = ?"
    )
    params: tuple[object, ...] = (
        method,
        SourceKind.DERIVED.value,
        ProjectionState.ACTIVE.value,
    )
    if owners is None:
        rows = _fetch_all(db, sql + " ORDER BY natural_key", params)
    else:
        rows = []
        unique = sorted(set(owners))
        for start in range(0, len(unique), _RETIRE_BATCH):
            batch = unique[start : start + _RETIRE_BATCH]
            rows += _fetch_all(
                db,
                f"{sql} AND owner_record_id IN ({', '.join('?' * len(batch))})",
                (*params, *batch),
            )
    result = []
    for row in rows:
        details = json.loads(row.pop("details") or "{}")
        derivation = details.get(_DERIVATION_KEY)
        row["derivation"] = derivation if isinstance(derivation, dict) else {}
        row[_INPUT_FINGERPRINT_KEY] = details.get(_INPUT_FINGERPRINT_KEY)
        row[_METHOD_VERSION_KEY] = details.get(_METHOD_VERSION_KEY)
        result.append(row)
    return result


def retire_derived_observations(
    db: Any,
    method: str,
    *,
    keep: Collection[str],
    now: str,
    owner: str | None = None,
) -> int:
    """Retire active local derived rows of ``method`` whose key is not in ``keep``.

    ``owner`` limits the retirement to that owner's rows; None covers every row.
    """
    sql = (
        "SELECT natural_key FROM observations WHERE provider IS NULL "
        "AND method = ? AND source_kind = ? AND state = ?"
    )
    params: tuple[object, ...] = (
        method,
        SourceKind.DERIVED.value,
        ProjectionState.ACTIVE.value,
    )
    if owner is not None:
        sql += " AND owner_record_id = ?"
        params = (*params, owner)
    stale = [
        row["natural_key"]
        for row in _fetch_all(db, sql, params)
        if row["natural_key"] not in keep
    ]
    for start in range(0, len(stale), _RETIRE_BATCH):
        batch = stale[start : start + _RETIRE_BATCH]
        db.execute(
            "UPDATE observations SET state = ?, updated_at = ? "
            f"WHERE natural_key IN ({', '.join('?' * len(batch))})",
            (ProjectionState.RETIRED.value, now, *batch),
        )
    return len(stale)


def retire_unemitted_observations(
    db: Any,
    *,
    provider: str,
    scopes: Mapping[str, ObservationScope],
    now: str,
) -> int:
    """Retire the active observations each owner holds on its days but no longer emits.

    ``scopes`` maps the source record id of an owning raw record to what its
    latest projection covers. Rows of other days or other owners are untouched.
    The rows stay in the table, so history, backups and a later projection that
    emits them again (which makes them active) still see them. Returns how many
    rows were retired.
    """
    owners = sorted(scopes)
    stale: list[str] = []
    for start in range(0, len(owners), _RETIRE_BATCH):
        batch = owners[start : start + _RETIRE_BATCH]
        rows = _fetch_all(
            db,
            "SELECT natural_key, owner_record_id, observed_on FROM observations "
            f"WHERE provider = ? AND {_ACTIVE_OBSERVATION} "
            f"AND owner_record_id IN ({', '.join('?' * len(batch))})",
            (provider, *batch),
        )
        for row in rows:
            scope = scopes[str(row["owner_record_id"])]
            if (
                row["observed_on"] in scope.days
                and row["natural_key"] not in scope.emitted
            ):
                stale.append(str(row["natural_key"]))
    for start in range(0, len(stale), _RETIRE_BATCH):
        keys = stale[start : start + _RETIRE_BATCH]
        db.execute(
            "UPDATE observations SET state = ?, updated_at = ? "
            f"WHERE natural_key IN ({', '.join('?' * len(keys))})",
            (ProjectionState.RETIRED.value, now, *keys),
        )
    return len(stale)


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


def mark_placeholder_deleted(
    db: Any,
    provider: str,
    *,
    record_kind: str,
    provider_activity_id: str,
    now: str,
) -> bool:
    """Tombstone one stored activity only while it holds no measured value.

    A provider can list a recording without its values for a while; a stored copy
    that has a duration, a positive distance, heart rate, power or load is a
    recording and is never tombstoned here. Returns True when a placeholder was
    tombstoned.
    """
    found = _fetch_all(
        db,
        "SELECT activity_id FROM activity_records "
        "WHERE provider = ? AND provider_activity_id = ? AND state = ? "
        "AND duration_s IS NULL AND COALESCE(distance_m, 0) = 0 "
        "AND avg_hr IS NULL AND avg_power IS NULL AND load IS NULL",
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


def tombstone_provider_activities(
    db: Any, provider: str, *, record_kind: str, now: str
) -> int:
    """Tombstone every stored activity of one provider, with its raw record and session.

    Each record that is not deleted yet, or whose session is not, takes the
    deletion path of a removed activity, oldest first: a deleted surviving
    session hands its aliases to a new survivor and keeps it as
    ``merged_into_retained``, so its id still resolves. Returns the number of
    records passed.
    """
    rows = _fetch_all(
        db,
        "SELECT r.provider_activity_id, r.activity_id FROM activity_records AS r "
        "LEFT JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        "WHERE r.provider = ? AND (r.state <> ? OR s.state <> ?) "
        "ORDER BY r.started_at, r.provider_activity_id",
        (
            provider,
            ActivityRecordState.DELETED.value,
            ActivitySessionState.DELETED.value,
        ),
    )
    for row in rows:
        _delete_activity(
            db,
            provider,
            record_kind=record_kind,
            provider_activity_id=row["provider_activity_id"],
            activity_id=row["activity_id"],
            now=now,
        )
    return len(rows)


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
    # A session the athlete already deleted is left as it is and hands over no
    # aliases.
    cursor = db.execute(
        "UPDATE activity_sessions SET state = ?, "
        "merged_into_retained = COALESCE(merged_into, merged_into_retained), "
        "merged_into = NULL, updated_at = ? "
        "WHERE activity_id = ? AND primary_provider = ? "
        "AND primary_provider_activity_id = ? "
        f"AND NOT (state = ? AND {ATHLETE_DELETED})",
        (
            ActivitySessionState.DELETED.value,
            now,
            activity_id,
            provider,
            provider_activity_id,
            ActivitySessionState.DELETED.value,
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
    # The new survivor carries on the deleted one's confirmation, so an athlete's
    # merge stays confirmed when the provider deletes its primary copy.
    db.execute(
        "UPDATE activity_sessions SET state = ?, merged_into = NULL, "
        "athlete_confirmed = MAX(athlete_confirmed, (SELECT deleted.athlete_confirmed "
        "FROM activity_sessions AS deleted WHERE deleted.activity_id = ?)), "
        "updated_at = ? WHERE activity_id = ?",
        (ActivitySessionState.ACTIVE.value, deleted_id, now, survivor),
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
            (_PLANNED_EVENT_KEY, record.planned_event_id),
            (_DEVICE_NAME_KEY, record.device_name),
            (_TRAINING_EFFECT_LABEL_KEY, record.training_effect_label),
            (
                _EXTERNAL_REF_KEY,
                None
                if record.external_ref is None
                else [
                    record.external_ref.upstream.value,
                    record.external_ref.upstream_id,
                ],
            ),
            (_CONTEXT_KEY, record.provenance.context.as_details() or None),
            (_LOCAL_OFFSET_KEY, record.local_offset_minutes),
            (_TERRAIN_KEY, _known(record.terrain, Terrain.UNKNOWN)),
            (_ASSIST_KEY, _known(record.assist, Assist.UNKNOWN)),
            (_NATIVE_TYPE_KEY, record.native_type),
            (_PURPOSE_KEY, None if record.purpose is None else record.purpose.value),
            *(
                (field, getattr(record, field))
                for field in ACTIVITY_SUMMARY_DETAIL_FIELDS
            ),
            *(
                (field, _zone_details(getattr(record, field)))
                for field in ACTIVITY_ZONE_DETAIL_FIELDS
            ),
        )
        if value is not None
    }
    if not details:
        return ACTIVITY_DETAILS
    return json.dumps(details, separators=(",", ":"))


def _known(value: StrEnum, unknown: StrEnum) -> str | None:
    return None if value is unknown else value.value


def _zone_details(zones: Any) -> list[list[Any]] | None:
    return None if zones is None else [[zone_id, seconds] for zone_id, seconds in zones]


def activity_summary_values(details: object) -> dict[str, Any]:
    """Return the stored summary values of ``ActivityRecord`` from the details.

    Keys are ``ActivityRecord`` field names. A missing or malformed value is left
    out, so the record keeps its default; it never raises.
    """
    loaded = _activity_details_object(details)
    values: dict[str, Any] = {}
    for field in ACTIVITY_SUMMARY_DETAIL_FIELDS:
        number = loaded.get(field)
        if not isinstance(number, bool) and isinstance(number, int | float):
            values[field] = float(number)
    for field in ACTIVITY_ZONE_DETAIL_FIELDS:
        zones = _stored_zones(loaded.get(field))
        if zones is not None:
            values[field] = zones
    for key in (_PLANNED_EVENT_KEY, _DEVICE_NAME_KEY):
        text = loaded.get(key)
        if isinstance(text, str) and text.strip() and len(text) <= 200:
            values[key] = text
    label = loaded.get(_TRAINING_EFFECT_LABEL_KEY)
    if (
        isinstance(label, str)
        and label.strip()
        and len(label) <= MAX_TRAINING_EFFECT_LABEL_LENGTH
    ):
        values[_TRAINING_EFFECT_LABEL_KEY] = label
    if valid_offset_minutes(offset := loaded.get(_LOCAL_OFFSET_KEY)):
        values[_LOCAL_OFFSET_KEY] = offset
    return values | _stored_purpose(loaded) | _activity_qualifiers(loaded)


def _stored_purpose(loaded: Mapping[str, Any]) -> dict[str, Any]:
    purpose = loaded.get(_PURPOSE_KEY)
    if isinstance(purpose, str) and purpose in ActivityPurpose._value2member_map_:
        return {_PURPOSE_KEY: ActivityPurpose(purpose)}
    return {}


def _activity_qualifiers(loaded: Mapping[str, Any]) -> dict[str, Any]:
    """Return the stored terrain, assist and native type; invalid values are left out."""
    values: dict[str, Any] = {}
    for key, kind in ((_TERRAIN_KEY, Terrain), (_ASSIST_KEY, Assist)):
        text = loaded.get(key)
        if isinstance(text, str) and text in kind._value2member_map_:
            values[key] = kind(text)
    native = loaded.get(_NATIVE_TYPE_KEY)
    if (
        isinstance(native, str)
        and native.strip()
        and len(native) <= MAX_NATIVE_TYPE_LENGTH
    ):
        values[_NATIVE_TYPE_KEY] = native
    return values


def activity_qualifiers(details: object) -> dict[str, Any]:
    """Return the stored terrain, assist and native type of an activity's details.

    Keys are ``ActivityRecord`` field names; a missing or invalid value is left out.
    """
    return _activity_qualifiers(_activity_details_object(details))


def row_qualifiers(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the terrain, assist and native type columns of a member row, if valid."""
    return _activity_qualifiers(row)


def _stored_zones(value: object) -> tuple[tuple[str, float], ...] | None:
    if not isinstance(value, list) or not value or len(value) > MAX_ZONE_COUNT:
        return None
    zones: list[tuple[str, float]] = []
    for item in value:
        if not (isinstance(item, list) and len(item) == 2):
            return None
        zone_id, seconds = item
        if (
            not isinstance(zone_id, str)
            or not zone_id.strip()
            or len(zone_id) > MAX_ZONE_ID_LENGTH
            or isinstance(seconds, bool)
            or not isinstance(seconds, int | float)
            or not math.isfinite(seconds)
            or not 0 <= seconds <= MAX_ACTIVITY_DURATION_S
        ):
            return None
        zones.append((zone_id, float(seconds)))
    return tuple(zones)


def activity_external_ref(details: object) -> ExternalRef | None:
    """Return the upstream activity stored in an activity's details, if valid."""
    value = _activity_details_object(details).get(_EXTERNAL_REF_KEY)
    if not (isinstance(value, list) and len(value) == 2):
        return None
    try:
        return ExternalRef(ProviderId(value[0]), value[1])
    except TypeError, ValueError:
        return None


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
    return _activity_details_object(details).get(key)


def _activity_details_object(details: object) -> dict[str, Any]:
    if not isinstance(details, str):
        return {}
    try:
        loaded = json.loads(details)
    except ValueError, RecursionError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _observation_values(
    observation: Observation, *, mapper_version: int, owner: str | None = None
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
        "state": ProjectionState.ACTIVE.value,
        "owner_record_id": owner,
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
            "state, merged_into, merged_into_retained FROM activity_sessions "
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


def linkable_dates_with_providers(db: Any, providers: Sequence[str]) -> list[str]:
    """Return the ISO local dates where every given provider has an active record
    within the one-day link margin.

    A device and a relayed copy can fall on neighbouring local dates (zone
    fallback), so a date counts when each other provider has a record on it or a
    neighbouring day. Only records session linking may bundle count: their
    session is active or an alias and not athlete-confirmed.
    """
    wanted = set(providers)
    rows = _fetch_all(
        db,
        "SELECT DISTINCT r.local_date AS local_date, r.provider AS provider "
        "FROM activity_records AS r "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        "WHERE r.state = ? AND s.state IN (?, ?) AND s.athlete_confirmed = 0 "
        f"AND r.provider IN ({_placeholders(list(wanted))})",
        (
            ActivityRecordState.ACTIVE.value,
            ActivitySessionState.ACTIVE.value,
            ActivitySessionState.DUPLICATE.value,
            *wanted,
        ),
    )
    by_date: dict[date, set[str]] = {}
    for row in rows:
        try:
            day = date.fromisoformat(str(row["local_date"])[:10])
        except ValueError:
            continue
        by_date.setdefault(day, set()).add(str(row["provider"]))
    margin = timedelta(days=1)
    result = []
    for day in sorted(by_date):
        nearby = by_date[day] | by_date.get(day - margin, set())
        nearby |= by_date.get(day + margin, set())
        if wanted <= nearby:
            result.append(day.isoformat())
    return result


def provider_activity_record_rows(
    db: Any, provider: str, provider_activity_ids: Sequence[str]
) -> list[dict[str, Any]]:
    """Return the active records of the given provider activity ids, linkable columns.

    Unknown and deleted records are absent; the session state is not filtered.
    """
    rows: list[dict[str, Any]] = []
    for chunk in _chunked(list(dict.fromkeys(provider_activity_ids))):
        rows.extend(
            _fetch_all(
                db,
                f"SELECT {', '.join(_LINKABLE_COLUMNS)} FROM activity_records AS r "
                "WHERE r.provider = ? AND r.state = ? "
                f"AND r.provider_activity_id IN ({_placeholders(chunk)})",
                (provider, ActivityRecordState.ACTIVE.value, *chunk),
            )
        )
    return rows


def activity_session_link_rows(
    db: Any, activity_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Return the session columns that linking decides on, keyed by local activity id."""
    rows: dict[str, dict[str, Any]] = {}
    for chunk in _chunked(activity_ids):
        for row in _fetch_all(
            db,
            "SELECT activity_id, link_kind, athlete_confirmed, state, merged_into, "
            "merged_into_retained, created_at FROM activity_sessions "
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


def live_session_id(db: Any, any_id: str) -> str | None:
    """Return the live session a local or provider activity id leads to, or None.

    A local ``act_`` id follows its merges; any other id must be the provider
    activity id of an active record of any provider. The session must hold an
    active record and must not be deleted.
    """
    if any_id.startswith(ACTIVITY_ID_PREFIX):
        candidates = [effective_session_ids(db, [any_id]).get(any_id, any_id)]
    else:
        candidates = [
            session
            for provider in ProviderId
            if (
                session := provider_activity_sessions(db, provider.value, [any_id]).get(
                    any_id
                )
            )
        ]
    return next(
        (session for session in candidates if session_activity_rows(db, session)),
        None,
    )


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


# A session the athlete deleted retains itself; its merged copies retain it.
# Provider deletes never produce a self-retaining session.
ATHLETE_DELETED: Final = (
    "(merged_into_retained IS NOT NULL AND (merged_into_retained = activity_id "
    "OR merged_into_retained IN (SELECT own.activity_id FROM activity_sessions "
    "AS own WHERE own.merged_into_retained = own.activity_id)))"
)

SESSION_CORRECTION_COLUMNS: Final = (
    "activity_id",
    "state",
    "merged_into",
    "merged_into_retained",
    "link_kind",
    "athlete_confirmed",
)


def session_bundle_ids(db: Any, activity_id: str) -> list[str]:
    """Return a session, its merge aliases and the deleted sessions retaining it."""
    return [
        str(row["activity_id"])
        for row in _fetch_all(
            db,
            "SELECT activity_id FROM activity_sessions WHERE activity_id = ? "
            "OR merged_into = ? OR merged_into_retained = ? ORDER BY activity_id",
            (activity_id, activity_id, activity_id),
        )
    ]


def session_correction_rows(
    db: Any, activity_ids: Sequence[str]
) -> list[dict[str, Any]]:
    """Return the bundling columns of the given sessions, ordered by id."""
    rows: list[dict[str, Any]] = []
    for chunk in _chunked(activity_ids):
        rows.extend(
            _fetch_all(
                db,
                f"SELECT {', '.join(SESSION_CORRECTION_COLUMNS)}, created_at, local_date "
                f"FROM activity_sessions WHERE activity_id IN ({_placeholders(chunk)})",
                tuple(chunk),
            )
        )
    return sorted(rows, key=lambda row: str(row["activity_id"]))


def write_session_correction_rows(
    db: Any, rows: Sequence[Mapping[str, Any]], *, now: str
) -> None:
    """Store the bundling columns of existing sessions as given."""
    for row in rows:
        db.execute(
            "UPDATE activity_sessions SET state = ?, merged_into = ?, "
            "merged_into_retained = ?, link_kind = ?, athlete_confirmed = ?, "
            "updated_at = ? WHERE activity_id = ?",
            (
                row["state"],
                row["merged_into"],
                row["merged_into_retained"],
                row["link_kind"],
                1 if row["athlete_confirmed"] else 0,
                now,
                row["activity_id"],
            ),
        )


def sessions_with_active_records(db: Any, activity_ids: Sequence[str]) -> set[str]:
    """Return the given sessions that own an active activity record."""
    found: set[str] = set()
    for chunk in _chunked(activity_ids):
        found.update(
            str(row["activity_id"])
            for row in _fetch_all(
                db,
                "SELECT DISTINCT activity_id FROM activity_records "
                f"WHERE state = ? AND activity_id IN ({_placeholders(chunk)})",
                (ActivityRecordState.ACTIVE.value, *chunk),
            )
        )
    return found


def athlete_deleted_session(db: Any, activity_id: str) -> bool:
    """Whether the athlete deleted the session, directly or with its survivor."""
    return (
        _fetch_row(
            db,
            "SELECT 1 AS present FROM activity_sessions "
            f"WHERE activity_id = ? AND state = ? AND {ATHLETE_DELETED}",
            (activity_id, ActivitySessionState.DELETED.value),
        )
        is not None
    )


def delete_with_athlete_deleted(
    db: Any, *, activity_id: str, deleted: str, now: str
) -> bool:
    """Delete an unconfirmed session without aliases as a copy of an athlete delete."""
    cursor = db.execute(
        "UPDATE activity_sessions SET state = ?, merged_into_retained = ?, "
        "updated_at = ? WHERE activity_id = ? AND state = ? AND athlete_confirmed = 0 "
        "AND NOT EXISTS (SELECT 1 FROM activity_sessions AS alias "
        "WHERE alias.merged_into = activity_sessions.activity_id)",
        (
            ActivitySessionState.DELETED.value,
            deleted,
            now,
            activity_id,
            ActivitySessionState.ACTIVE.value,
        ),
    )
    return cursor.rowcount == 1


def revive_deleted_copies(
    db: Any, survivor: str, *, exclude: Collection[str], now: str
) -> int:
    """Merge deleted sessions that retain ``survivor`` and own an active record into it.

    Linking deletes a provider copy that arrives for an athlete-deleted activity;
    when that delete is undone, the copy joins the restored session again.
    """
    rows = _fetch_all(
        db,
        "SELECT s.activity_id FROM activity_sessions AS s WHERE s.state = ? "
        "AND s.merged_into_retained = ? AND s.activity_id != ? "
        "AND EXISTS (SELECT 1 FROM activity_records AS r "
        "WHERE r.activity_id = s.activity_id AND r.state = ?)",
        (
            ActivitySessionState.DELETED.value,
            survivor,
            survivor,
            ActivityRecordState.ACTIVE.value,
        ),
    )
    revived = 0
    for row in rows:
        if row["activity_id"] in exclude:
            continue
        db.execute(
            "UPDATE activity_sessions SET state = ?, merged_into = ?, "
            "merged_into_retained = NULL, updated_at = ? WHERE activity_id = ?",
            (ActivitySessionState.DUPLICATE.value, survivor, now, row["activity_id"]),
        )
        revived += 1
    return revived


def detach_activity_session(db: Any, *, activity_id: str, now: str) -> bool:
    """Make a merge alias its own active single session; return whether it changed."""
    cursor = db.execute(
        "UPDATE activity_sessions SET state = ?, merged_into = NULL, link_kind = ?, "
        "updated_at = ? WHERE activity_id = ? AND state = ?",
        (
            ActivitySessionState.ACTIVE.value,
            ActivityLinkKind.SINGLE.value,
            now,
            activity_id,
            ActivitySessionState.DUPLICATE.value,
        ),
    )
    return cursor.rowcount == 1


def session_member_rows(db: Any, activity_id: str) -> list[dict[str, Any]]:
    """Return the active records of a live session and its aliases, with their session.

    ``session_id`` is the session each record was created with; a hidden or
    deleted session returns nothing.
    """
    return _fetch_all(
        db,
        "SELECT r.activity_id AS session_id, r.provider, r.recorded_by, r.sport, "
        "r.started_at, r.duration_s, r.distance_m, r.name, "
        + _QUALIFIER_COLUMNS
        + " FROM activity_records AS r "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        "WHERE r.state = ? AND ((s.activity_id = ? AND s.state = ?) "
        "OR (s.state = ? AND s.merged_into = ?)) "
        "AND EXISTS (SELECT 1 FROM activity_sessions AS owner "
        "WHERE owner.activity_id = ? AND owner.state = ?) "
        "ORDER BY r.started_at, r.provider, r.provider_activity_id",
        (
            ActivityRecordState.ACTIVE.value,
            activity_id,
            ActivitySessionState.ACTIVE.value,
            ActivitySessionState.DUPLICATE.value,
            activity_id,
            activity_id,
            ActivitySessionState.ACTIVE.value,
        ),
    )


def merge_candidate_rows(
    db: Any, local_date: str, exclude: str
) -> list[dict[str, Any]]:
    """Return the active records of other live sessions on one athlete-local date.

    ``session_id`` is the live session; records of its aliases are listed under it.
    """
    return _fetch_all(
        db,
        "SELECT s.activity_id AS session_id, r.provider, r.recorded_by, r.sport, "
        "r.started_at, r.duration_s, r.distance_m, r.name, "
        + _QUALIFIER_COLUMNS
        + " FROM activity_sessions AS s "
        "JOIN activity_sessions AS m ON m.activity_id = s.activity_id "
        "OR (m.state = ? AND m.merged_into = s.activity_id) "
        "JOIN activity_records AS r ON r.activity_id = m.activity_id "
        "WHERE s.state = ? AND s.local_date = ? AND s.activity_id != ? AND r.state = ? "
        "ORDER BY s.activity_id, r.started_at, r.provider, r.provider_activity_id",
        (
            ActivitySessionState.DUPLICATE.value,
            ActivitySessionState.ACTIVE.value,
            local_date,
            exclude,
            ActivityRecordState.ACTIVE.value,
        ),
    )


def session_legacy_keys(db: Any, session_ids: Sequence[str]) -> dict[str, list[str]]:
    """Map each session to the other ids athlete data may be stored under.

    Those are the provider activity ids of the records of the session and of every
    alias that merged into it (through ``merged_into`` or, for a deleted alias,
    ``merged_into_retained``, in any record state), and the alias session ids.
    Unknown sessions are absent; ids are sorted.
    """
    found: dict[str, set[str]] = {}
    for chunk in _chunked(session_ids):
        for row in _fetch_all(
            db,
            "WITH RECURSIVE family(root, activity_id, depth) AS ("
            "SELECT activity_id, activity_id, 0 FROM activity_sessions "
            f"WHERE activity_id IN ({_placeholders(chunk)}) "
            "UNION ALL "
            "SELECT family.root, alias.activity_id, family.depth + 1 "
            "FROM activity_sessions AS alias JOIN family "
            "ON COALESCE(alias.merged_into, alias.merged_into_retained) "
            "= family.activity_id WHERE family.depth < ?) "
            "SELECT family.root AS root, family.activity_id AS other FROM family "
            "UNION "
            "SELECT family.root, records.provider_activity_id "
            "FROM family JOIN activity_records AS records "
            "ON records.activity_id = family.activity_id",
            (*chunk, _MAX_MERGE_HOPS),
        ):
            if row["other"] != row["root"]:
                found.setdefault(str(row["root"]), set()).add(str(row["other"]))
    return {root: sorted(ids) for root, ids in found.items()}


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


def active_provider_records(
    db: Any,
    provider: str,
    record_kind: str,
    source_record_ids: Sequence[str],
) -> dict[str, str]:
    """Map source record ids to the payload hash of their active raw record.

    Ids without an active raw record are absent.
    """
    found: dict[str, str] = {}
    for chunk in _chunked(list(dict.fromkeys(source_record_ids))):
        for row in _fetch_all(
            db,
            "SELECT source_record_id, payload_hash AS value FROM provider_records "
            "WHERE provider = ? AND record_kind = ? AND state = ? "
            f"AND source_record_id IN ({_placeholders(chunk)})",
            (provider, record_kind, ProviderRecordState.ACTIVE.value, *chunk),
        ):
            found[str(row["source_record_id"])] = str(row["value"])
    return found


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
