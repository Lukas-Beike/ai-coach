"""Persistence owner for canonical sleep, zone, status, gear and power curve rows.

Every function writes through the connection of the caller's unit of work, which
returns mapping rows, and never commits. A provider re-projection replaces the
rows of one source record: rows it emits are written, updated or left unchanged,
and the active rows of that source record it no longer emits are retired. A
retired row that is emitted again is active again; a row another source record
of the same provider emits moves to that record. Readers return active rows
only. Retired rows are kept for history and export.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any, Final, NamedTuple

from backend.canonical.domain_records import (
    CategoricalObservation,
    GearActivityLink,
    GearItem,
    PowerCurvePoint,
    SleepPeriod,
    ZoneConfiguration,
)
from backend.canonical.records import Provenance
from backend.canonical.validation import require_instance, require_text
from backend.canonical.vocabulary import ProjectionState, ProviderId
from backend.db.canonical_store import WriteOutcome, canonical_json

EMPTY_DETAILS: Final = "{}"
CONTEXT_KEY: Final = "context"
ZONE_MODEL_KEY: Final = "model"
GEAR_LIST_PARTIAL_KEY: Final = "activity_list_partial"
_ACTIVE: Final = ProjectionState.ACTIVE.value
_RETIRED: Final = ProjectionState.RETIRED.value


class ReplaceResult(NamedTuple):
    written: int
    updated: int
    unchanged: int
    retired: int


class _Table(NamedTuple):
    name: str
    keys: tuple[str, ...]
    # Written and compared on every upsert; state and timestamps are separate.
    columns: tuple[str, ...]


_PROVENANCE_COLUMNS: Final = (
    "source_kind",
    "recorded_by",
    "source_record_id",
    "retrieved_at",
    "label",
    "mapper_version",
)
_SLEEP: Final = _Table(
    "sleep_periods",
    ("provider", "started_at"),
    (
        "ended_at",
        "wake_date",
        "timezone",
        "kind",
        "reported_duration_s",
        "bounds_method",
        *_PROVENANCE_COLUMNS,
        "details",
    ),
)
_ZONES: Final = _Table(
    "zone_configurations",
    ("config_key",),
    (
        "provider",
        "sport",
        "metric",
        "environment",
        "valid_from",
        "valid_until",
        "threshold",
        "maximum",
        "resting",
        "limits",
        "percent_limits",
        "percent_basis",
        *_PROVENANCE_COLUMNS,
        "details",
    ),
)
_CATEGORICAL: Final = _Table(
    "categorical_observations",
    ("natural_key",),
    (
        "domain",
        "code",
        "provider",
        "sport",
        "observed_on",
        "observed_at",
        *_PROVENANCE_COLUMNS,
        "details",
    ),
)
_GEAR: Final = _Table(
    "gear_items",
    ("provider", "gear_id"),
    (
        "name",
        "type_label",
        "activity_type_label",
        "status_label",
        "maximum_distance_m",
        "total_distance_m",
        "total_activities",
        *_PROVENANCE_COLUMNS,
        "details",
    ),
)
_GEAR_LINKS: Final = _Table(
    "gear_activity_links",
    ("provider", "gear_id", "provider_activity_id"),
    _PROVENANCE_COLUMNS,
)
_POWER_CURVE: Final = _Table(
    "power_curve_points",
    ("provider", "duration_s"),
    (
        "watts",
        "observed_on",
        "provider_activity_id",
        "window_start",
        "window_end",
        "fetch_status",
        *_PROVENANCE_COLUMNS,
        "details",
    ),
)


def categorical_natural_key(observation: CategoricalObservation) -> str:
    """Return provider|domain|sport|(observed_at or observed_on); NULL parts are empty."""
    provider = observation.provenance.provider
    sport = observation.sport
    when = (
        observation.observed_at.isoformat()
        if observation.observed_at is not None
        else observation.observed_on.isoformat()
    )
    return "|".join(
        (
            "" if provider is None else provider.value,
            observation.domain.value,
            "" if sport is None else sport.value,
            when,
        )
    )


def zone_configuration_key(configuration: ZoneConfiguration) -> str:
    """Return provider|metric|sport|environment|valid_from; NULL parts are empty.

    A local configuration has no provider, so its key starts with ``|``.
    """
    provider = configuration.provenance.provider
    return "|".join(
        (
            "" if provider is None else provider.value,
            configuration.metric.value,
            "" if configuration.sport is None else configuration.sport.value,
            ""
            if configuration.environment is None
            else configuration.environment.value,
            ""
            if configuration.valid_from is None
            else configuration.valid_from.isoformat(),
        )
    )


def replace_sleep_periods(
    db: Any,
    *,
    provider: ProviderId,
    source_record_id: str,
    periods: Sequence[SleepPeriod],
    mapper_version: int,
    now: str,
) -> ReplaceResult:
    """Replace the sleep periods of one provider source record."""
    _require_mapper_version(mapper_version)
    rows = [
        _sleep_row(require_instance(period, SleepPeriod, "period"), mapper_version)
        for period in periods
    ]
    return _replace(
        db, _SLEEP, rows, provider=provider, source_record_id=source_record_id, now=now
    )


def replace_categorical_observations(
    db: Any,
    *,
    provider: ProviderId,
    source_record_id: str,
    observations: Sequence[CategoricalObservation],
    mapper_version: int,
    now: str,
) -> ReplaceResult:
    """Replace the provider statuses of one provider source record."""
    _require_mapper_version(mapper_version)
    rows = [
        _categorical_row(
            require_instance(observation, CategoricalObservation, "observation"),
            mapper_version,
        )
        for observation in observations
    ]
    return _replace(
        db,
        _CATEGORICAL,
        rows,
        provider=provider,
        source_record_id=source_record_id,
        now=now,
    )


def replace_zone_configurations(
    db: Any,
    *,
    provider: ProviderId,
    source_record_id: str,
    configurations: Sequence[ZoneConfiguration],
    mapper_version: int,
    now: str,
) -> ReplaceResult:
    """Replace the zone configurations of one provider source record."""
    _require_mapper_version(mapper_version)
    rows = [
        _zone_row(
            require_instance(configuration, ZoneConfiguration, "configuration"),
            mapper_version,
        )
        for configuration in configurations
    ]
    return _replace(
        db, _ZONES, rows, provider=provider, source_record_id=source_record_id, now=now
    )


def upsert_local_zone_configuration(
    db: Any, configuration: ZoneConfiguration, *, now: str
) -> WriteOutcome:
    """Write one zone configuration the athlete set locally, which has no provider."""
    require_instance(configuration, ZoneConfiguration, "configuration")
    if configuration.provenance.provider is not None:
        raise ValueError("a local zone configuration has no provider")
    return _upsert(db, _ZONES, _zone_row(configuration, None), now=now)


def retire_local_zone_configuration(db: Any, config_key: str, *, now: str) -> bool:
    """Retire one active local zone configuration; False when none is active."""
    cursor = db.execute(
        "UPDATE zone_configurations SET state = ?, updated_at = ? "
        "WHERE config_key = ? AND provider IS NULL AND state = ?",
        (
            _RETIRED,
            now,
            require_text(config_key, "config_key", max_length=512),
            _ACTIVE,
        ),
    )
    return bool(cursor.rowcount == 1)


def replace_gear_items(
    db: Any,
    *,
    provider: ProviderId,
    source_record_id: str,
    items: Sequence[GearItem],
    mapper_version: int,
    now: str,
) -> ReplaceResult:
    """Replace the gear of one provider source record."""
    _require_mapper_version(mapper_version)
    rows = [
        _gear_row(require_instance(item, GearItem, "item"), mapper_version)
        for item in items
    ]
    return _replace(
        db, _GEAR, rows, provider=provider, source_record_id=source_record_id, now=now
    )


def replace_gear_activity_links(
    db: Any,
    *,
    provider: ProviderId,
    source_record_id: str,
    links: Sequence[GearActivityLink],
    mapper_version: int,
    now: str,
) -> ReplaceResult:
    """Replace the gear-to-activity links of one provider source record."""
    _require_mapper_version(mapper_version)
    rows = [
        _gear_link_row(require_instance(link, GearActivityLink, "link"), mapper_version)
        for link in links
    ]
    return _replace(
        db,
        _GEAR_LINKS,
        rows,
        provider=provider,
        source_record_id=source_record_id,
        now=now,
    )


_SOURCE_TABLES: Final = (
    _SLEEP,
    _CATEGORICAL,
    _ZONES,
    _GEAR,
    _GEAR_LINKS,
    _POWER_CURVE,
)


def replace_source_rows(
    db: Any,
    *,
    provider: ProviderId,
    source_record_id: str,
    mapper_version: int,
    now: str,
    sleep_periods: Sequence[SleepPeriod] = (),
    categorical: Sequence[CategoricalObservation] = (),
    zones: Sequence[ZoneConfiguration] = (),
    gear_items: Sequence[GearItem] = (),
    gear_links: Sequence[GearActivityLink] = (),
    power_curve: Sequence[PowerCurvePoint] = (),
) -> ReplaceResult:
    """Replace every domain row of one provider source record, in every table.

    A table the source record no longer emits rows for has its rows retired, so
    an empty call retires all of them.
    """
    _require_mapper_version(mapper_version)
    replacements = (
        (
            _SLEEP,
            [
                _sleep_row(require_instance(p, SleepPeriod, "period"), mapper_version)
                for p in sleep_periods
            ],
        ),
        (
            _CATEGORICAL,
            [
                _categorical_row(
                    require_instance(o, CategoricalObservation, "observation"),
                    mapper_version,
                )
                for o in categorical
            ],
        ),
        (
            _ZONES,
            [
                _zone_row(
                    require_instance(z, ZoneConfiguration, "configuration"),
                    mapper_version,
                )
                for z in zones
            ],
        ),
        (
            _GEAR,
            [
                _gear_row(require_instance(g, GearItem, "item"), mapper_version)
                for g in gear_items
            ],
        ),
        (
            _GEAR_LINKS,
            [
                _gear_link_row(
                    require_instance(link, GearActivityLink, "link"), mapper_version
                )
                for link in gear_links
            ],
        ),
        (
            _POWER_CURVE,
            [
                _power_curve_row(
                    require_instance(point, PowerCurvePoint, "point"), mapper_version
                )
                for point in power_curve
            ],
        ),
    )
    results = [
        _replace(
            db,
            table,
            rows,
            provider=provider,
            source_record_id=source_record_id,
            now=now,
        )
        for table, rows in replacements
    ]
    return ReplaceResult(*(sum(column) for column in zip(*results, strict=True)))


def retire_source_rows(
    db: Any, *, provider: ProviderId, source_record_id: str, now: str
) -> int:
    """Retire every active domain row of a raw record that was deleted; return the count.

    A record emitted again later is replaced as usual, which makes its rows active.
    """
    return sum(
        _replace(
            db, table, [], provider=provider, source_record_id=source_record_id, now=now
        ).retired
        for table in _SOURCE_TABLES
    )


def has_source_rows(db: Any, *, provider: ProviderId, source_record_id: str) -> bool:
    """Return whether any domain table holds a row of this source record, retired ones included."""
    provider_value = require_instance(provider, ProviderId, "provider").value
    return any(
        db.execute(
            f"SELECT 1 FROM {table.name} WHERE provider = ? AND source_record_id = ? "
            "LIMIT 1",
            (provider_value, source_record_id),
        ).fetchone()
        is not None
        for table in _SOURCE_TABLES
    )


def active_sleep_period_rows(
    db: Any, *, start: str | None = None, end: str | None = None
) -> list[dict[str, Any]]:
    """Return active sleep rows by inclusive ISO wake date, oldest first."""
    clauses, params = _date_window("wake_date", start, end)
    return _active_rows(db, _SLEEP, clauses, params, "wake_date, started_at, provider")


def active_zone_configuration_rows(db: Any) -> list[dict[str, Any]]:
    """Return active zone rows, local and provider ones, by configuration key."""
    return _active_rows(db, _ZONES, [], [], "config_key")


def active_categorical_rows(
    db: Any, domain: str, *, start: str | None = None, end: str | None = None
) -> list[dict[str, Any]]:
    """Return active status rows of one domain by inclusive ISO day, oldest first."""
    clauses, params = _date_window("observed_on", start, end)
    return _active_rows(
        db,
        _CATEGORICAL,
        ["domain = ?", *clauses],
        [domain, *params],
        "observed_on, provider, natural_key",
    )


def active_gear_item_rows(db: Any) -> list[dict[str, Any]]:
    return _active_rows(db, _GEAR, [], [], "provider, gear_id")


def active_gear_link_rows(db: Any) -> list[dict[str, Any]]:
    return _active_rows(
        db, _GEAR_LINKS, [], [], "provider, gear_id, provider_activity_id"
    )


def active_power_curve_rows(db: Any) -> list[dict[str, Any]]:
    """Return the active power curve rows by provider and duration."""
    return _active_rows(db, _POWER_CURVE, [], [], "provider, duration_s")


def zone_configuration_export_rows(db: Any) -> Iterable[dict[str, Any]]:
    """Yield every zone row, retired ones included, with decoded limit lists."""
    for exported in _fetch_all(db, f"SELECT * FROM {_ZONES.name} ORDER BY config_key"):
        for column in ("limits", "percent_limits"):
            if exported[column] is not None:
                exported[column] = json.loads(exported[column])
        yield exported


def _replace(
    db: Any,
    table: _Table,
    rows: Sequence[Mapping[str, object]],
    *,
    provider: ProviderId,
    source_record_id: str,
    now: str,
) -> ReplaceResult:
    provider_value = require_instance(provider, ProviderId, "provider").value
    require_text(source_record_id, "source_record_id")
    emitted: set[tuple[object, ...]] = set()
    outcomes: list[WriteOutcome] = []
    for row in rows:
        if (
            row["provider"] != provider_value
            or row["source_record_id"] != source_record_id
        ):
            raise ValueError(f"{table.name} records must come from the replaced source")
        key = tuple(row[column] for column in table.keys)
        if key in emitted:
            raise ValueError(f"{table.name} records repeat a key")
        emitted.add(key)
        outcomes.append(_upsert(db, table, row, now=now))
    stored = _fetch_all(
        db,
        f"SELECT {', '.join(table.keys)} FROM {table.name} "
        "WHERE provider = ? AND source_record_id = ? AND state = ?",
        (provider_value, source_record_id, _ACTIVE),
    )
    stale = [
        key
        for key in (tuple(row[column] for column in table.keys) for row in stored)
        if key not in emitted
    ]
    for key in stale:
        db.execute(
            f"UPDATE {table.name} SET state = ?, updated_at = ? WHERE {_where(table)}",
            (_RETIRED, now, *key),
        )
    return ReplaceResult(
        written=outcomes.count(WriteOutcome.WRITTEN),
        updated=outcomes.count(WriteOutcome.UPDATED),
        unchanged=outcomes.count(WriteOutcome.UNCHANGED),
        retired=len(stale),
    )


def _upsert(
    db: Any, table: _Table, row: Mapping[str, object], *, now: str
) -> WriteOutcome:
    key = tuple(row[column] for column in table.keys)
    found = _fetch_all(
        db,
        f"SELECT state, {', '.join(table.columns)} FROM {table.name} "
        f"WHERE {_where(table)}",
        key,
    )
    existing = found[0] if found else None
    if existing is None:
        columns = (*table.keys, *table.columns)
        db.execute(
            f"INSERT INTO {table.name}({', '.join(columns)}, state, created_at, "
            f"updated_at) VALUES ({', '.join('?' * (len(columns) + 3))})",
            (*(row[column] for column in columns), _ACTIVE, now, now),
        )
        return WriteOutcome.WRITTEN
    if existing["state"] == _ACTIVE and all(
        existing[column] == row[column] for column in table.columns
    ):
        return WriteOutcome.UNCHANGED
    assignments = ", ".join(f"{column} = ?" for column in table.columns)
    db.execute(
        f"UPDATE {table.name} SET {assignments}, state = ?, updated_at = ? "
        f"WHERE {_where(table)}",
        (*(row[column] for column in table.columns), _ACTIVE, now, *key),
    )
    return WriteOutcome.UPDATED


def _active_rows(
    db: Any, table: _Table, clauses: list[str], params: list[object], order: str
) -> list[dict[str, Any]]:
    where = " AND ".join(("state = ?", *clauses))
    return _fetch_all(
        db,
        f"SELECT * FROM {table.name} WHERE {where} ORDER BY {order}",
        (_ACTIVE, *params),
    )


def _fetch_all(
    db: Any, sql: str, params: Sequence[object] = ()
) -> list[dict[str, Any]]:
    """Return rows as dicts whatever row factory the connection uses."""
    cursor = db.execute(sql, tuple(params))
    rows = cursor.fetchall()
    if rows and not isinstance(rows[0], Mapping):
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in rows]
    return [dict(row) for row in rows]


def _date_window(
    column: str, start: str | None, end: str | None
) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if start is not None:
        clauses.append(f"{column} >= ?")
        params.append(start)
    if end is not None:
        clauses.append(f"{column} <= ?")
        params.append(end)
    return clauses, params


def _where(table: _Table) -> str:
    return " AND ".join(f"{column} = ?" for column in table.keys)


def _require_mapper_version(mapper_version: object) -> None:
    if isinstance(mapper_version, bool) or not isinstance(mapper_version, int):
        raise TypeError("mapper_version must be an integer")
    if mapper_version < 1:
        raise ValueError("mapper_version must be at least 1")


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _iso_day(day: date | None) -> str | None:
    return None if day is None else day.isoformat()


def _provenance_values(
    provenance: Provenance, mapper_version: int | None
) -> dict[str, object]:
    provider = provenance.provider
    retrieved_at = provenance.retrieved_at
    return {
        "provider": None if provider is None else provider.value,
        "source_kind": provenance.source_kind.value,
        "recorded_by": provenance.recorded_by.value,
        "source_record_id": provenance.source_record_id,
        "retrieved_at": None if retrieved_at is None else retrieved_at.isoformat(),
        "label": provenance.label,
        "mapper_version": mapper_version,
    }


def _details(provenance: Provenance, *extra: tuple[str, object]) -> str:
    details = {
        key: value
        for key, value in (
            (CONTEXT_KEY, provenance.context.as_details() or None),
            *extra,
        )
        if value is not None
    }
    return canonical_json(details) if details else EMPTY_DETAILS


def _limits(values: tuple[float, ...] | None) -> str | None:
    return None if values is None else json.dumps(list(values), separators=(",", ":"))


def _sleep_row(period: SleepPeriod, mapper_version: int) -> dict[str, object]:
    return {
        **_provenance_values(period.provenance, mapper_version),
        "started_at": _utc(period.start),
        "ended_at": _utc(period.end),
        "wake_date": period.wake_date.isoformat(),
        "timezone": period.timezone,
        "kind": period.kind.value,
        "reported_duration_s": period.reported_duration_s,
        "bounds_method": period.bounds_method,
        "details": _details(period.provenance),
    }


def _categorical_row(
    observation: CategoricalObservation, mapper_version: int
) -> dict[str, object]:
    observed_at = observation.observed_at
    return {
        **_provenance_values(observation.provenance, mapper_version),
        "natural_key": categorical_natural_key(observation),
        "domain": observation.domain.value,
        "code": observation.code,
        "sport": None if observation.sport is None else observation.sport.value,
        "observed_on": observation.observed_on.isoformat(),
        "observed_at": None if observed_at is None else observed_at.isoformat(),
        "details": _details(observation.provenance),
    }


def _zone_row(
    configuration: ZoneConfiguration, mapper_version: int | None
) -> dict[str, object]:
    return {
        **_provenance_values(configuration.provenance, mapper_version),
        "config_key": zone_configuration_key(configuration),
        "sport": None if configuration.sport is None else configuration.sport.value,
        "metric": configuration.metric.value,
        "environment": (
            None
            if configuration.environment is None
            else configuration.environment.value
        ),
        "valid_from": _iso_day(configuration.valid_from),
        "valid_until": _iso_day(configuration.valid_until),
        "threshold": configuration.threshold,
        "maximum": configuration.maximum,
        "resting": configuration.resting,
        "limits": _limits(configuration.limits),
        "percent_limits": _limits(configuration.percent_limits),
        "percent_basis": (
            None
            if configuration.percent_basis is None
            else configuration.percent_basis.value
        ),
        "details": _details(
            configuration.provenance, (ZONE_MODEL_KEY, configuration.model)
        ),
    }


def _gear_row(item: GearItem, mapper_version: int) -> dict[str, object]:
    return {
        **_provenance_values(item.provenance, mapper_version),
        "gear_id": item.gear_id,
        "name": item.name,
        "type_label": item.type_label,
        "activity_type_label": item.activity_type_label,
        "status_label": item.status_label,
        "maximum_distance_m": item.maximum_distance_m,
        "total_distance_m": item.total_distance_m,
        "total_activities": item.total_activities,
        "details": _details(
            item.provenance, (GEAR_LIST_PARTIAL_KEY, item.activity_list_partial)
        ),
    }


def _gear_link_row(link: GearActivityLink, mapper_version: int) -> dict[str, object]:
    return {
        **_provenance_values(link.provenance, mapper_version),
        "gear_id": link.gear_id,
        "provider_activity_id": link.provider_activity_id,
    }


def _power_curve_row(point: PowerCurvePoint, mapper_version: int) -> dict[str, object]:
    return {
        **_provenance_values(point.provenance, mapper_version),
        "duration_s": point.duration_s,
        "watts": point.watts,
        "observed_on": point.observed_on.isoformat(),
        "provider_activity_id": point.provider_activity_id,
        "window_start": point.window_start.isoformat(),
        "window_end": point.window_end.isoformat(),
        "fetch_status": point.fetch_status,
        "details": _details(point.provenance),
    }
