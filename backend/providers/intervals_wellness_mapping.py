"""Map Intervals.icu wellness rows and athlete thresholds to canonical observations.

Both mappers are pure: no I/O, no logging, and no raw provider values in the
returned issues. Malformed input is reported as a ``MappingIssue`` and never
raises. The only exception is a naive ``retrieved_at``, which is a programming
error and raises ``ValueError``.

Alias precedence follows the readers in ``backend.performance`` and
``backend.planning``. For each canonical field the first alias whose value is
neither ``None`` nor an empty string is used, even when that value is invalid.
A rejected value is never replaced by a later alias, so an invalid ``ctl``
does not fall back to ``ctLoad``. Numbers follow ``coerce_comma_decimal_number``,
so text such as ``"80,4"`` is read as 80.4 and ambiguous grouped thousands such
as ``"1,200"`` are rejected, as the readers read them.

Wellness rows
    ``id`` is the ISO calendar date (``YYYY-MM-DD``) and is required. Each
    field listed in ``_WELLNESS_FIELDS`` yields one observation. The athlete's
    own ratings ``fatigue``, ``soreness``, ``stress`` and ``mood`` (1 to 4) become
    SUBJECTIVE_* observations recorded MANUAL: provider-reported, separate from
    local check-ins and from Garmin's physiological STRESS. Every other key,
    including ``rampRate`` and the unlisted wellness keys, is ignored without an
    issue: most wellness keys are deliberately unmapped, so reporting each one
    would only add noise.

    FORM is the reported ``tsb``, ``form`` or ``freshness``. A row without one
    stores its mapped CTL minus its mapped ATL, rounded to two decimals, as a
    DERIVED observation. Storing the derived value keeps one form series per day
    for every consumer instead of each one deriving it again.

    Each ``sportInfo`` (or ``sport_info``) entry yields an EFTP observation with
    the sport that its first ``types`` text, or else its ``type``, classifies to.
    The value is ``mmp_model``'s ``ftp``, ``eftp`` or ``eFTP``, else the entry's
    ``eftp`` or ``eFTP``, as ``performance.eftp`` reads it. Only the first entry
    of each sport is mapped.

Athlete thresholds
    ``sportSettings`` (with the snake_case alias ``sport_settings`` as the
    fallback, the same rule as ``backend.planning.context``) yields observations
    tagged with the sport that the first text in each entry's ``types`` list
    classifies to. Entries are mapped in input order, so two entries for one
    sport both yield observations. ``current_metrics`` uses the first entry.
    Athlete ids that are not short ASCII identifiers are not echoed and yield
    ``source_record_id`` None.

    A zero FTP, lthr, max_hr, pace or VO2max means "not set". It yields nothing,
    and its alias chain does not fall through to a later alias, as in the
    readers. ``threshold_pace`` is mapped for Run entries only, because the
    readers use it only for running. Values below 20 are metres per second.
    Larger values are seconds per kilometre and convert to ``1000 / value`` m/s.
    VO2max is Ride-scoped through ``vo2max``, ``vo2_max`` or ``cycling_vo2max``
    and Run-scoped through ``vo2max``, ``vo2_max`` or ``running_vo2max``. Zero
    VO2max is unset in wellness rows too.

    Top-level ``icu_ftp`` becomes a Ride FTP observation only when no Ride FTP
    observation was mapped. A rejected sportSettings FTP therefore allows the
    fallback, which ``current_metrics`` does not do. Each entry's eFTP is read
    as in wellness ``sportInfo`` and stored with the entry's sport. Its key has
    the athlete series (see ``backend.db.canonical_store``), so it never
    replaces the wellness eFTP of the same day. Warm-up or cool-down times are
    not read.

Athlete record
    ``weight`` (kg) is observed with sport None on the caller's ``observed_on``,
    as ``current_metrics`` reads it after the wellness row. The athlete-wide
    ``lthr`` and ``max_hr`` are observed with sport None. They are the values
    that the readers use when a sport has no value of its own. A consumer applies
    that fallback per sport and must not treat sport None as a sport value.

    Known deviations from the readers, pinned in ``tests/test_intervals_mapping_parity.py``:
    a zero athlete-wide lthr is 0 bpm in ``current_metrics`` but unset here;
    a rejected sport value lets the athlete-wide fallback apply, as the top-level
    FTP does. Text with underscore digit separators or non-ASCII digits is
    rejected by ``coerce_number``'s rules, though the readers accept it. A
    rejected ``tsb`` does not fall back to CTL minus ATL, and the derivation also
    uses ``ctLoad`` and ``atlLoad``. Athlete-wide VO2max, athlete body fat and
    activity-derived max HR are not mapped.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, Final

from backend.canonical.mapping import (
    MAX_ISSUE_TEXT_LENGTH,
    IssueReason,
    MappingIssue,
    MappingResult,
    coerce_comma_decimal_number,
)
from backend.canonical.records import (
    FORM_METHOD,
    FORM_METHOD_VERSION,
    MetricValue,
    Observation,
    Provenance,
    fingerprint_inputs,
)
from backend.canonical.sports import classify_sport_text
from backend.canonical.validation import METRIC_BOUNDS, require_aware_datetime
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)

# Version 4: the athlete-profile weight has its own observation key, so it no
# longer overwrites the wellness weight of the same day. Version 6: wellness rows
# add FORM and the sportInfo EFTP; sport settings add EFTP. Version 7: wellness
# rows also project canonical sleep periods and the subjective ratings, and the
# athlete record its zone configurations. Re-projection
# rewrites rows written at older versions.
MAPPER_VERSION: Final = 7

_PROVIDER_LABEL: Final = "Intervals.icu"
_DAY_PATTERN: Final = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_RECORD_ID_PATTERN: Final = re.compile(r"[\w.-]+", re.ASCII)
# Paces at or above this value are seconds per kilometre; below it, metres per second.
_PACE_M_PER_S_LIMIT: Final = 20.0
_PACE_METRES_PER_KM: Final = 1000.0
# Zero means "not set" for these kinds, as in the readers' ``or`` chains.
_UNSET_WHEN_ZERO: Final = frozenset(
    {
        MetricKind.FTP,
        MetricKind.THRESHOLD_HR,
        MetricKind.MAX_HR,
        MetricKind.THRESHOLD_PACE,
        MetricKind.VO2MAX,
        MetricKind.EFTP,
    }
)

# (canonical kind, provider aliases in precedence order)
_WELLNESS_FIELDS: Final[tuple[tuple[MetricKind, tuple[str, ...]], ...]] = (
    (MetricKind.WEIGHT, ("weight",)),
    (MetricKind.BODY_FAT, ("bodyFat", "body_fat", "body_fat_pct")),
    (MetricKind.RESTING_HR, ("restingHR", "resting_hr")),
    (MetricKind.HRV_RMSSD, ("hrv", "hrv_ms")),
    (MetricKind.HRV_SDNN, ("hrvSDNN",)),
    (MetricKind.SLEEP_DURATION, ("sleepSecs", "sleep_seconds")),
    (MetricKind.SLEEP_SCORE, ("sleepScore",)),
    (
        MetricKind.READINESS,
        (
            "readiness",
            "readinessScore",
            "readiness_score",
            "trainingReadiness",
            "training_readiness",
        ),
    ),
    (MetricKind.VO2MAX, ("vo2max", "vo2_max")),
    (MetricKind.CTL, ("ctl", "ctLoad")),
    (MetricKind.ATL, ("atl", "atlLoad")),
)

# Ratings the athlete entered in Intervals.icu.
_SUBJECTIVE_FIELDS: Final[tuple[tuple[MetricKind, tuple[str, ...]], ...]] = (
    (MetricKind.SUBJECTIVE_FATIGUE, ("fatigue",)),
    (MetricKind.SUBJECTIVE_SORENESS, ("soreness",)),
    (MetricKind.SUBJECTIVE_STRESS, ("stress",)),
    (MetricKind.SUBJECTIVE_MOOD, ("mood",)),
)
_FORM_ALIASES: Final = ("tsb", "form", "freshness")
_SPORT_INFO_KEYS: Final = ("sport_info", "sportInfo")
_MMP_MODEL_KEY: Final = "mmp_model"
_EFTP_MODEL_ALIASES: Final = ("ftp", "eftp", "eFTP")
_EFTP_ALIASES: Final = ("eftp", "eFTP")
_LTHR_ALIASES: Final = ("lthr",)
_MAX_HR_ALIASES: Final = ("max_hr", "maxHR", "maxHeartRate", "max_heartrate")
_SPORT_SETTING_FIELDS: Final[tuple[tuple[MetricKind, tuple[str, ...]], ...]] = (
    (MetricKind.FTP, ("ftp", "indoor_ftp")),
    (MetricKind.THRESHOLD_HR, _LTHR_ALIASES),
    (MetricKind.MAX_HR, _MAX_HR_ALIASES),
)
# The Run entry reads running_vo2max where the Ride entry reads cycling_vo2max,
# as current_metrics does. Other sports have no VO2max observation.
_VO2MAX_ALIASES_BY_SPORT: Final[Mapping[Sport, tuple[str, ...]]] = {
    Sport.RIDE: ("vo2max", "vo2_max", "cycling_vo2max"),
    Sport.RUN: ("vo2max", "vo2_max", "running_vo2max"),
}
_RUN_PACE_ALIASES: Final = ("threshold_pace",)
_TOP_LEVEL_RIDE_FTP_ALIASES: Final = ("icu_ftp",)
# Athlete-wide values: sport None, read after the sport entries.
_ATHLETE_FIELDS: Final[tuple[tuple[MetricKind, tuple[str, ...]], ...]] = (
    (MetricKind.WEIGHT, ("weight",)),
    (MetricKind.THRESHOLD_HR, _LTHR_ALIASES),
    (MetricKind.MAX_HR, _MAX_HR_ALIASES),
)


@dataclass(frozen=True, slots=True)
class _Scope:
    """Identity shared by every observation mapped from one provider record."""

    record_ref: str | None
    observed_on: date
    provenance: Provenance


@dataclass(slots=True)
class _Collector:
    records: list[Observation] = field(default_factory=list)
    issues: list[MappingIssue] = field(default_factory=list)

    def reject(self, record_ref: str | None, name: str, reason: IssueReason) -> None:
        self.issues.append(MappingIssue(record_ref, name, reason))

    def result(self) -> MappingResult[Observation]:
        return MappingResult(records=tuple(self.records), issues=tuple(self.issues))


def map_intervals_wellness(
    rows: object, *, retrieved_at: datetime
) -> MappingResult[Observation]:
    """Map wellness rows, one observation per known field present in each row."""
    require_aware_datetime(retrieved_at, "retrieved_at")
    if not isinstance(rows, list):
        return MappingResult(
            issues=(MappingIssue(None, "rows", IssueReason.INVALID_TYPE),)
        )
    collector = _Collector()
    for row in rows:
        _map_wellness_row(row, retrieved_at, collector)
    return collector.result()


def map_intervals_athlete_thresholds(
    athlete: object, *, observed_on: date, retrieved_at: datetime
) -> MappingResult[Observation]:
    """Map sport thresholds and the top-level Ride FTP fallback from an athlete."""
    require_aware_datetime(retrieved_at, "retrieved_at")
    if not isinstance(athlete, dict):
        return MappingResult(
            issues=(MappingIssue(None, "athlete", IssueReason.INVALID_TYPE),)
        )
    record_id = _athlete_record_id(athlete)
    scope = _Scope(
        record_ref=record_id,
        observed_on=observed_on,
        provenance=_provenance(record_id, retrieved_at),
    )
    collector = _Collector()
    for entry in _sport_settings(athlete, scope, collector):
        _map_sport_setting(entry, scope, collector)
    for kind, aliases in _ATHLETE_FIELDS:
        _add_field(collector, scope, athlete, kind, aliases)
    if not _has_ride_ftp(collector.records):
        _add_field(
            collector,
            scope,
            athlete,
            MetricKind.FTP,
            _TOP_LEVEL_RIDE_FTP_ALIASES,
            sport=Sport.RIDE,
        )
    return collector.result()


def _map_wellness_row(
    row: object, retrieved_at: datetime, collector: _Collector
) -> None:
    if not isinstance(row, dict):
        collector.reject(None, "row", IssueReason.INVALID_TYPE)
        return
    day = _wellness_day(row, collector)
    if day is None:
        return
    record_id, observed_on = day
    scope = _Scope(
        record_ref=record_id,
        observed_on=observed_on,
        provenance=_provenance(record_id, retrieved_at),
    )
    first = len(collector.records)
    for kind, aliases in _WELLNESS_FIELDS:
        _add_field(collector, scope, row, kind, aliases)
    manual = _Scope(
        record_ref=record_id,
        observed_on=observed_on,
        provenance=replace(scope.provenance, recorded_by=RecordingOrigin.MANUAL),
    )
    for kind, aliases in _SUBJECTIVE_FIELDS:
        _add_field(collector, manual, row, kind, aliases)
    _add_form(collector, scope, row, collector.records[first:])
    _map_sport_info(row, scope, collector)


def _add_form(
    collector: _Collector,
    scope: _Scope,
    row: dict[Any, Any],
    mapped: list[Observation],
) -> None:
    """Map the reported form, else derive it from this row's CTL and ATL."""
    if _first_present(row, _FORM_ALIASES) is not None:
        _add_field(collector, scope, row, MetricKind.FORM, _FORM_ALIASES)
        return
    loads = {
        observation.kind: observation.value.value
        for observation in mapped
        if observation.kind in (MetricKind.CTL, MetricKind.ATL)
    }
    if len(loads) != 2:
        return
    # Both loads lie in 0..10000, so their difference is inside the FORM bounds.
    form = round(loads[MetricKind.CTL] - loads[MetricKind.ATL], 2)
    collector.records.append(
        Observation(
            kind=MetricKind.FORM,
            value=MetricValue(form, MetricKind.FORM.unit),
            observed_on=scope.observed_on,
            observed_at=None,
            provenance=replace(scope.provenance, source_kind=SourceKind.DERIVED),
            method=FORM_METHOD,
            method_version=FORM_METHOD_VERSION,
            input_fingerprint=fingerprint_inputs(
                {"ctl": loads[MetricKind.CTL], "atl": loads[MetricKind.ATL]}
            ),
        )
    )


def _map_sport_info(row: dict[Any, Any], scope: _Scope, collector: _Collector) -> None:
    found = _first_present(row, _SPORT_INFO_KEYS)
    if found is None:
        return
    name, entries = found
    if not isinstance(entries, list):
        collector.reject(scope.record_ref, name, IssueReason.INVALID_TYPE)
        return
    seen: set[Sport] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            collector.reject(scope.record_ref, name, IssueReason.INVALID_TYPE)
            continue
        sport = _sport_info_sport(entry)
        if sport is None or sport in seen:
            continue
        seen.add(sport)
        _add_eftp(collector, scope, entry, sport)


def _sport_info_sport(entry: dict[Any, Any]) -> Sport | None:
    types = entry.get("types")
    text = types[0] if isinstance(types, list) and types else entry.get("type")
    return classify_sport_text(text) if isinstance(text, str) else None


def _add_eftp(
    collector: _Collector, scope: _Scope, entry: dict[Any, Any], sport: Sport
) -> None:
    """Read ``mmp_model``'s eFTP first, then the entry's own, as the readers do.

    A zero model value counts as absent, like the legacy reader's ``or`` chain.
    """
    model = entry.get(_MMP_MODEL_KEY)
    found = (
        _first_present(model, _EFTP_MODEL_ALIASES) if isinstance(model, dict) else None
    )
    if (
        isinstance(model, dict)
        and found is not None
        and coerce_comma_decimal_number(found[1]) != 0
    ):
        _add_field(
            collector, scope, model, MetricKind.EFTP, _EFTP_MODEL_ALIASES, sport=sport
        )
        return
    _add_field(collector, scope, entry, MetricKind.EFTP, _EFTP_ALIASES, sport=sport)


def _wellness_day(
    row: dict[Any, Any], collector: _Collector
) -> tuple[str, date] | None:
    raw = row.get("id")
    if raw is None or raw == "":
        collector.reject(None, "id", IssueReason.MISSING)
        return None
    if not isinstance(raw, str):
        collector.reject(None, "id", IssueReason.INVALID_TYPE)
        return None
    day = _parse_day(raw)
    if day is None:
        collector.reject(None, "id", IssueReason.UNKNOWN_VALUE)
        return None
    return raw, day


def _parse_day(text: str) -> date | None:
    """Accept only ``YYYY-MM-DD`` with ASCII digits and a real calendar date."""
    if _DAY_PATTERN.fullmatch(text) is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _athlete_record_id(athlete: dict[Any, Any]) -> str | None:
    """Return the athlete id only when it is a short ASCII identifier.

    The id is copied into issues and provenance, so free text is not echoed.
    """
    raw = athlete.get("id")
    if (
        isinstance(raw, str)
        and len(raw) <= MAX_ISSUE_TEXT_LENGTH
        and _RECORD_ID_PATTERN.fullmatch(raw)
    ):
        return raw
    return None


def _sport_settings(
    athlete: dict[Any, Any], scope: _Scope, collector: _Collector
) -> list[Any]:
    # ``or`` mirrors compact_sport_settings: an empty sportSettings falls back.
    raw = athlete.get("sportSettings") or athlete.get("sport_settings")
    if raw is None:
        return []
    if not isinstance(raw, list):
        collector.reject(scope.record_ref, "sportSettings", IssueReason.INVALID_TYPE)
        return []
    return raw


def _map_sport_setting(entry: object, scope: _Scope, collector: _Collector) -> None:
    if not isinstance(entry, dict):
        collector.reject(scope.record_ref, "sportSettings", IssueReason.INVALID_TYPE)
        return
    sport = _entry_sport(entry, scope, collector)
    if sport is None:
        return
    for kind, aliases in _SPORT_SETTING_FIELDS:
        _add_field(collector, scope, entry, kind, aliases, sport=sport)
    _add_eftp(collector, scope, entry, sport)
    vo2max_aliases = _VO2MAX_ALIASES_BY_SPORT.get(sport)
    if vo2max_aliases is not None:
        _add_field(
            collector, scope, entry, MetricKind.VO2MAX, vo2max_aliases, sport=sport
        )
    if sport is Sport.RUN:
        _add_field(
            collector,
            scope,
            entry,
            MetricKind.THRESHOLD_PACE,
            _RUN_PACE_ALIASES,
            sport=sport,
        )


def _entry_sport(
    entry: dict[Any, Any], scope: _Scope, collector: _Collector
) -> Sport | None:
    """Classify the first ``types`` text; a missing or malformed list is an issue."""
    types = entry.get("types")
    if types is None:
        reason = IssueReason.MISSING
    elif not isinstance(types, list):
        reason = IssueReason.INVALID_TYPE
    elif not types:
        reason = IssueReason.MISSING
    elif not isinstance(types[0], str):
        reason = IssueReason.INVALID_TYPE
    else:
        return classify_sport_text(types[0])
    collector.reject(scope.record_ref, "types", reason)
    return None


def _has_ride_ftp(records: list[Observation]) -> bool:
    return any(
        observation.kind is MetricKind.FTP and observation.sport is Sport.RIDE
        for observation in records
    )


def _add_field(
    collector: _Collector,
    scope: _Scope,
    row: dict[Any, Any],
    kind: MetricKind,
    aliases: tuple[str, ...],
    *,
    sport: Sport | None = None,
) -> None:
    found = _first_present(row, aliases)
    if found is None:
        return
    name, value = found
    if kind in _UNSET_WHEN_ZERO and coerce_comma_decimal_number(value) == 0:
        return
    number = _canonical_number(kind, value)
    if isinstance(number, IssueReason):
        collector.reject(scope.record_ref, name, number)
        return
    collector.records.append(
        Observation(
            kind=kind,
            value=MetricValue(number, kind.unit),
            observed_on=scope.observed_on,
            observed_at=None,
            provenance=scope.provenance,
            sport=sport,
        )
    )


def _first_present(
    row: dict[Any, Any], aliases: tuple[str, ...]
) -> tuple[str, object] | None:
    for name in aliases:
        value = row.get(name)
        if value is not None and value != "":
            return name, value
    return None


def _canonical_number(kind: MetricKind, value: object) -> float | IssueReason:
    number = _raw_number(value)
    if isinstance(number, IssueReason):
        return number
    if kind is MetricKind.THRESHOLD_PACE:
        return _pace_metres_per_second(number)
    return _within_bounds(kind, number)


def _raw_number(value: object) -> float | IssueReason:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return IssueReason.INVALID_TYPE
    number = coerce_comma_decimal_number(value)
    return IssueReason.INVALID_NUMBER if number is None else number


def _pace_metres_per_second(number: float) -> float | IssueReason:
    if number <= 0:
        return IssueReason.OUT_OF_RANGE
    if number < _PACE_M_PER_S_LIMIT:
        return _within_bounds(MetricKind.THRESHOLD_PACE, number)
    speed = _PACE_METRES_PER_KM / number
    return _within_bounds(MetricKind.THRESHOLD_PACE, speed)


def _within_bounds(kind: MetricKind, number: float) -> float | IssueReason:
    lower, upper = METRIC_BOUNDS[kind]
    return number if lower <= number <= upper else IssueReason.OUT_OF_RANGE


def _provenance(record_id: str | None, retrieved_at: datetime) -> Provenance:
    return Provenance(
        provider=ProviderId.INTERVALS,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=record_id,
        recorded_by=RecordingOrigin.UNKNOWN,
        retrieved_at=retrieved_at,
        label=_PROVIDER_LABEL,
    )
