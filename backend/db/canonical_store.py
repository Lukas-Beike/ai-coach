"""Persistence owner for raw provider records and canonical activity and observation rows.

Every function writes through the connection of the caller's unit of work and
never commits. The caller's transaction decides whether these rows and the legacy
snapshot are kept together or rolled back together.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import date
from enum import StrEnum
from typing import Any, Final

from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import (
    ActivityLinkKind,
    ActivityRecordState,
    ActivitySessionState,
    ProviderRecordState,
)

ACTIVITY_ID_PREFIX: Final = "act_"
OBSERVATION_DETAILS: Final = "{}"

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
    values = _activity_values(record, local_date=local_date, mapper_version=mapper_version)
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
                started_at,
                day,
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
        return WriteOutcome.WRITTEN
    if existing["state"] == ActivityRecordState.ACTIVE.value and all(
        existing[column] == values[column] for column in _ACTIVITY_COLUMNS
    ):
        return WriteOutcome.UNCHANGED
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


def observation_natural_key(observation: Observation) -> str:
    """Return provider|metric|sport|method|(observed_at or observed_on).

    NULL parts are empty strings. Canonical observations carry no method, so that
    part is always empty.
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
            "",
            when,
        )
    )


def upsert_observation(
    db: Any, observation: Observation, *, mapper_version: int, now: str
) -> WriteOutcome:
    """Insert or update one observation by its natural key."""
    natural_key = observation_natural_key(observation)
    values = _observation_values(observation, mapper_version=mapper_version)
    existing = _fetch_row(
        db,
        "SELECT " + ", ".join(_OBSERVATION_COLUMNS)
        + " FROM observations WHERE natural_key = ?",
        (natural_key,),
    )
    if existing is None:
        columns = ("natural_key", *_OBSERVATION_COLUMNS, "details", "created_at", "updated_at")
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
        "provider": provenance.provider.value if provenance.provider is not None else None,
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
