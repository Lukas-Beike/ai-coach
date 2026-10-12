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
from datetime import date
from enum import StrEnum
from typing import Any, Final

from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import (
    ActivityLinkKind,
    ActivityRecordState,
    ActivitySessionState,
    MetricKind,
    ProviderId,
    ProviderRecordState,
)

ACTIVITY_ID_PREFIX: Final = "act_"
ATHLETE_SERIES: Final = "athlete"
OBSERVATION_DETAILS: Final = "{}"
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
    "name",
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
) -> WriteOutcome:
    """Store one sanitized raw record; an unchanged hash and version is not rewritten."""
    text = canonical_json(payload)
    digest = payload_hash(text)
    existing = _fetch_row(
        db,
        "SELECT payload_hash, mapped_version, state FROM provider_records "
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
        )
        return WriteOutcome.WRITTEN
    if (
        existing["payload_hash"] == digest
        and existing["mapped_version"] == mapper_version
        and existing["state"] == ProviderRecordState.ACTIVE.value
    ):
        return WriteOutcome.UNCHANGED
    db.execute(
        "UPDATE provider_records SET payload = ?, payload_hash = ?, fetched_at = ?, "
        "mapped_version = ?, state = ?, updated_at = ? "
        "WHERE provider = ? AND record_kind = ? AND source_record_id = ?",
        (
            text,
            digest,
            fetched_at,
            mapper_version,
            ProviderRecordState.ACTIVE.value,
            now,
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
        "UPDATE activity_sessions SET started_at = ?, local_date = ?, "
        "state = CASE WHEN state = ? THEN ? ELSE state END, updated_at = ? "
        "WHERE activity_id = ?",
        (
            started_at,
            day,
            ActivitySessionState.DELETED.value,
            ActivitySessionState.ACTIVE.value,
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
    "r.name",
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


def active_activity_payload_texts(
    db: Any,
    *,
    provider: str,
    record_kind: str,
    start: str | None = None,
    end: str | None = None,
) -> list[str]:
    """Return the stored raw payload text of one provider's live activities.

    Only active raw records whose activity record is active and whose session is
    not deleted are returned, so tombstoned activities are never served. ``start``
    and ``end`` are inclusive ISO dates on the stored athlete-local date. Order is
    the activity start time, then the provider activity id.
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
    rows = _fetch_all(
        db,
        "SELECT p.payload FROM provider_records AS p "
        "JOIN activity_records AS r ON r.provider = p.provider "
        "AND r.provider_activity_id = p.source_record_id "
        "JOIN activity_sessions AS s ON s.activity_id = r.activity_id "
        f"WHERE {' AND '.join(clauses)} ORDER BY r.started_at, "
        "r.provider_activity_id",
        tuple(params),
    )
    return [str(row["payload"]) for row in rows]


def current_observation_rows(
    db: Any,
    metric: str,
    versions: Mapping[str, int],
    *,
    start: str | None = None,
    end: str | None = None,
    sport: str | None = None,
) -> list[dict[str, Any]]:
    """Return observation rows of one metric at each provider's current mapper version.

    ``versions`` maps a provider value to its current observation mapper version;
    rows of any other version, or of no provider, are not returned. Bounds are
    inclusive ISO dates on ``observed_on``.
    """
    provider_clause = " OR ".join(
        "(provider = ? AND mapper_version = ?)" for _ in versions
    )
    clauses = ["metric = ?", f"({provider_clause})"]
    params: list[object] = [metric]
    for provider, version in versions.items():
        params.extend((provider, version))
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
    that the Intervals.icu athlete profile reports (see ``_observation_series``),
    which therefore never shares a key with the wellness weight of the same day.
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
    """Return ``athlete`` for an Intervals.icu athlete-profile weight, else empty.

    A wellness row is identified by its ISO day, so a weight whose source record
    is anything else comes from the athlete record. The consumers tell the two
    apart by the same rule. Both values are kept: the current-metrics reader
    shows the wellness weight first and the athlete weight as its fallback.
    """
    provenance = observation.provenance
    if (
        provenance.provider is ProviderId.INTERVALS
        and observation.kind is MetricKind.WEIGHT
        and provenance.source_record_id != observation.observed_on.isoformat()
    ):
        return ATHLETE_SERIES
    return ""


def upsert_observation(
    db: Any, observation: Observation, *, mapper_version: int, now: str
) -> WriteOutcome:
    """Insert or update one observation by its natural key."""
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
        db.execute(
            "UPDATE activity_sessions SET state = ?, updated_at = ? "
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
        deleted += 1
    return deleted


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
) -> None:
    db.execute(
        "INSERT INTO provider_records (provider, record_kind, source_record_id, "
        "payload, payload_hash, fetched_at, mapped_version, state, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        "details",
        "created_at",
        "updated_at",
    )
    db.execute(
        f"INSERT INTO observations ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' * len(columns))})",
        (
            natural_key,
            *(values[column] for column in _OBSERVATION_COLUMNS),
            OBSERVATION_DETAILS,
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
        "name": record.name,
        "mapper_version": mapper_version,
    }


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
    }


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


def _chunked(values: Sequence[str]) -> list[list[str]]:
    unique = list(dict.fromkeys(value for value in values if value))
    return [
        unique[start : start + _READ_CHUNK_SIZE]
        for start in range(0, len(unique), _READ_CHUNK_SIZE)
    ]


def _placeholders(values: Sequence[object]) -> str:
    return ", ".join("?" * len(values))
