"""Map Wahoo power zones and the user profile to canonical threshold observations.

Both mappers are pure: no I/O, no logging, and no provider values in the returned
issues. Malformed provider input is reported as a ``MappingIssue`` and never
raises. The only exception is a naive ``retrieved_at``, which is a programming
error and raises ``ValueError``.

Power zones
    ``GET /v1/power_zones`` returns zone sets. Only the newest zone set of each
    workout-type family is read, ranked by ``updated_at`` (the later one wins, and
    an equal time keeps the later row). The family id ``workout_type_family_id`` is
    looked up in the Wahoo workout type table; an unknown family is an issue. Each
    chosen zone set yields one FTP observation in watts, dated on the athlete-local
    day of ``updated_at``. Zero means "not set" and yields nothing. Zone boundaries
    are not mapped.

    ``select_power_zone_sets`` returns the chosen zone sets, so the ingest stores
    exactly the raw rows that the mapper reads. Re-mapping one stored row then
    reproduces its original observation.

User profile
    Only ``weight`` (kg) is mapped, to one observation on the caller's
    ``observed_on``. The profile carries no date, so the caller passes the
    athlete-local day of the fetch. Zero means "not set". Height, birth date and
    gender are not mapped and stay in the raw record.

Numbers may arrive as numbers or as text with a dot or comma decimal mark. Values
outside ``METRIC_BOUNDS`` are issues.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from typing import Any, Final

from backend.canonical.local_time import local_date, parse_provider_datetime
from backend.canonical.mapping import (
    IssueReason,
    MappingIssue,
    MappingResult,
    coerce_comma_decimal_number,
)
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.validation import METRIC_BOUNDS, require_aware_datetime
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.providers.wahoo_activity_mapping import WAHOO_LABEL

# One version for both kinds: either mapping change re-projects both.
MAPPER_VERSION: Final = 1
# The profile has no record id of its own, so its observations use this one.
USER_RECORD_ID: Final = "user"
# Longest digit text that can be an id without overflowing the 64-bit id range.
_MAX_ID_DIGITS: Final = 19
_MAX_ID: Final = 2**63 - 1

# Wahoo workout_type_family_id values, which number the sport families and not the
# workout types: 0 is biking and 1 is running. Other families carry no FTP here.
_FAMILY_SPORTS: Final[Mapping[int, Sport]] = {0: Sport.RIDE, 1: Sport.RUN}


@dataclass(frozen=True, slots=True)
class PowerZoneSet:
    """The newest zone set of one workout-type family."""

    record_id: str
    family_id: int
    sport: Sport
    updated_at: datetime
    observed_on: date
    row: Mapping[str, Any]


def _issue(ref: str | None, field: str, reason: IssueReason) -> MappingIssue:
    return MappingIssue(ref, field, reason)


def _identifier(value: object, *, minimum: int = 1) -> int | IssueReason:
    """Return an integer id of at least ``minimum`` from an int or its digit text."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return IssueReason.MISSING
    if isinstance(value, str):
        text = value.strip()
        if not text.isascii() or not text.isdigit():
            return IssueReason.INVALID_TYPE
        if len(text) > _MAX_ID_DIGITS:
            return IssueReason.OUT_OF_RANGE
        value = int(text)
    if isinstance(value, bool) or not isinstance(value, int):
        return IssueReason.INVALID_TYPE
    if not minimum <= value <= _MAX_ID:
        return IssueReason.OUT_OF_RANGE
    return value


def _zone_set(row: object, *, zone: tzinfo) -> PowerZoneSet | MappingIssue:
    """Return the zone set of one row, or the issue that makes it unusable."""
    if not isinstance(row, dict):
        return _issue(None, "row", IssueReason.INVALID_TYPE)
    zone_id = _identifier(row.get("id"))
    if isinstance(zone_id, IssueReason):
        return _issue(None, "id", zone_id)
    ref = str(zone_id)
    family_id = _identifier(row.get("workout_type_family_id"), minimum=0)
    if isinstance(family_id, IssueReason):
        return _issue(ref, "workout_type_family_id", family_id)
    sport = _FAMILY_SPORTS.get(family_id)
    if sport is None:
        return _issue(ref, "workout_type_family_id", IssueReason.UNKNOWN_VALUE)
    updated = parse_provider_datetime(row.get("updated_at"), UTC)
    if updated is None:
        missing = row.get("updated_at") in (None, "")
        reason = IssueReason.MISSING if missing else IssueReason.INVALID_TYPE
        return _issue(ref, "updated_at", reason)
    return PowerZoneSet(
        record_id=ref,
        family_id=family_id,
        sport=sport,
        updated_at=updated,
        observed_on=local_date(updated, zone),
        row=row,
    )


def select_power_zone_sets(
    rows: object, *, zone: tzinfo
) -> tuple[tuple[PowerZoneSet, ...], tuple[MappingIssue, ...]]:
    """Return the newest zone set of each family, in input order, and the rejected rows.

    A row that cannot be read is an issue. A readable row that a newer row of its
    family supersedes is not an issue; it is simply not the current zone set.
    Stored rows reload as lists and fresh client rows arrive as tuples; both are read.
    """
    if not isinstance(rows, list | tuple):
        return (), (_issue(None, "power_zones", IssueReason.INVALID_TYPE),)
    issues: list[MappingIssue] = []
    newest: dict[int, tuple[int, PowerZoneSet]] = {}
    for index, row in enumerate(rows):
        candidate = _zone_set(row, zone=zone)
        if isinstance(candidate, MappingIssue):
            issues.append(candidate)
            continue
        current = newest.get(candidate.family_id)
        if current is None or (candidate.updated_at, index) > (
            current[1].updated_at,
            current[0],
        ):
            newest[candidate.family_id] = (index, candidate)
    ordered = sorted(newest.values(), key=lambda item: item[0])
    return tuple(zone_set for _, zone_set in ordered), tuple(issues)


def _measured(value: object, kind: MetricKind) -> float | IssueReason | None:
    """Return a bounded number, None for "not set", or the reason the value is unusable."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return IssueReason.INVALID_TYPE
    number = coerce_comma_decimal_number(value)
    if number is None:
        return IssueReason.INVALID_NUMBER
    if number == 0:
        return None
    lower, upper = METRIC_BOUNDS[kind]
    if not lower <= number <= upper:
        return IssueReason.OUT_OF_RANGE
    return number


def _provenance(record_id: str, retrieved_at: datetime) -> Provenance:
    return Provenance(
        provider=ProviderId.WAHOO,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=record_id,
        recorded_by=RecordingOrigin.WAHOO,
        retrieved_at=retrieved_at,
        label=WAHOO_LABEL,
    )


def map_wahoo_power_zones(
    rows: object, *, zone: tzinfo, retrieved_at: datetime
) -> MappingResult[Observation]:
    """Map the newest FTP of each workout-type family from the power zone rows."""
    require_aware_datetime(retrieved_at, "retrieved_at")
    chosen, selection_issues = select_power_zone_sets(rows, zone=zone)
    records: list[Observation] = []
    issues: list[MappingIssue] = list(selection_issues)
    for zone_set in chosen:
        measured = _measured(zone_set.row.get("ftp"), MetricKind.FTP)
        if isinstance(measured, IssueReason):
            issues.append(_issue(zone_set.record_id, "ftp", measured))
            continue
        if measured is None:
            continue
        records.append(
            Observation(
                kind=MetricKind.FTP,
                value=MetricValue(measured, MetricKind.FTP.unit),
                observed_on=zone_set.observed_on,
                observed_at=None,
                provenance=_provenance(zone_set.record_id, retrieved_at),
                sport=zone_set.sport,
            )
        )
    return MappingResult(records=tuple(records), issues=tuple(issues))


def map_wahoo_user(
    user: object, *, observed_on: date, retrieved_at: datetime
) -> MappingResult[Observation]:
    """Map the profile weight; no other profile field becomes an observation."""
    require_aware_datetime(retrieved_at, "retrieved_at")
    if not isinstance(user, dict):
        return MappingResult(issues=(_issue(None, "user", IssueReason.INVALID_TYPE),))
    measured = _measured(user.get("weight"), MetricKind.WEIGHT)
    if isinstance(measured, IssueReason):
        return MappingResult(issues=(_issue(USER_RECORD_ID, "weight", measured),))
    if measured is None:
        return MappingResult()
    observation = Observation(
        kind=MetricKind.WEIGHT,
        value=MetricValue(measured, MetricKind.WEIGHT.unit),
        observed_on=observed_on,
        observed_at=None,
        provenance=_provenance(USER_RECORD_ID, retrieved_at),
        sport=None,
    )
    return MappingResult(records=(observation,))


def map_wahoo_threshold_payload(
    power_zones: object | None,
    user: object | None,
    *,
    zone: tzinfo,
    retrieved_at: datetime,
) -> MappingResult[Observation]:
    """Map the power zones and the profile of one fetch; ``None`` means not fetched."""
    require_aware_datetime(retrieved_at, "retrieved_at")
    records: list[Observation] = []
    issues: list[MappingIssue] = []
    if power_zones is not None:
        zones = map_wahoo_power_zones(power_zones, zone=zone, retrieved_at=retrieved_at)
        records.extend(zones.records)
        issues.extend(zones.issues)
    if user is not None:
        profile = map_wahoo_user(
            user,
            observed_on=local_date(retrieved_at, zone),
            retrieved_at=retrieved_at,
        )
        records.extend(profile.records)
        issues.extend(profile.issues)
    return MappingResult(records=tuple(records), issues=tuple(issues))


__all__ = [
    "MAPPER_VERSION",
    "USER_RECORD_ID",
    "PowerZoneSet",
    "map_wahoo_power_zones",
    "map_wahoo_threshold_payload",
    "map_wahoo_user",
    "select_power_zone_sets",
]
