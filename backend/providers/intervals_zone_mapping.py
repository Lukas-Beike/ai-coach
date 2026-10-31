"""Map Intervals.icu sport settings to canonical zone configurations.

Each sport takes the first ``sportSettings`` entry (``sport_settings`` as the
fallback) with a ``types`` text that classifies to it, as the plan and calendar
zones choose it (``backend.activities.zone_settings``). Zone lists keep every
entry, the open top included, so nothing is lost:

* ``hr_zones`` are absolute heart-rate limits with ``lthr`` as threshold and
  ``max_hr`` as maximum.
* ``power_zones`` are percent limits of ``ftp``; with an ``indoor_ftp`` the same
  percentages also form an INDOOR configuration with that threshold.
* ``pace_zones`` are percent limits of ``threshold_pace`` in metres per second
  (values of 20 or more are seconds per kilometre, as the threshold mapper reads
  them).

A list needs 3 to 7 positive, ascending numbers; anything else, or a
configuration that fails validation, is left out. Thresholds are kept as reported
and absolute limits are never derived from percentages.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime
from itertools import pairwise
from typing import Any, Final

from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import Provenance
from backend.canonical.sports import classify_sport_text
from backend.canonical.vocabulary import (
    Environment,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
    ZonePercentBasis,
)

INTERVALS_LABEL: Final = "Intervals.icu"
_MIN_ZONES: Final = 3
_MAX_ZONES: Final = 7
_PACE_M_PER_S_LIMIT: Final = 20.0
_METRES_PER_KM: Final = 1000.0


def _number(value: Any) -> float | None:
    if type(value) not in {int, float}:
        return None
    try:
        number = float(value)
    except OverflowError:
        # An integer beyond the float range is malformed, never a limit.
        return None
    return number if math.isfinite(number) and number > 0 else None


def _zone_list(value: Any) -> tuple[float, ...] | None:
    if not isinstance(value, list) or not _MIN_ZONES <= len(value) <= _MAX_ZONES:
        return None
    numbers = [_number(item) for item in value]
    limits = tuple(item for item in numbers if item is not None)
    if len(limits) != len(numbers):
        return None
    return limits if all(a < b for a, b in pairwise(limits)) else None


def _pace_speed(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return number if number < _PACE_M_PER_S_LIMIT else _METRES_PER_KM / number


def _first_settings(athlete: Mapping[str, Any]) -> dict[Sport, Mapping[str, Any]]:
    raw = athlete.get("sportSettings") or athlete.get("sport_settings")
    chosen: dict[Sport, Mapping[str, Any]] = {}
    for setting in raw if isinstance(raw, list) else ():
        if isinstance(setting, Mapping):
            for sport in _setting_sports(setting):
                chosen.setdefault(sport, setting)
    return chosen


def _setting_sports(setting: Mapping[str, Any]) -> Iterator[Sport]:
    types = setting.get("types")
    return type_sports(types if isinstance(types, list) else ())


def type_sports(texts: Iterable[object]) -> Iterator[Sport]:
    """Yield the known sport of each type text, as the legacy readers matched each."""
    for text in texts:
        sport = classify_sport_text(text) if isinstance(text, str) else None
        if sport is not None and sport is not Sport.OTHER:
            yield sport


def _valid(**values: Any) -> Iterator[ZoneConfiguration]:
    """Yield the configuration, or nothing when it fails validation."""
    try:
        configuration = ZoneConfiguration(**values)
    except TypeError, ValueError:
        return
    yield configuration


def _configurations(
    sport: Sport, setting: Mapping[str, Any], provenance: Provenance
) -> Iterator[ZoneConfiguration]:
    common = {
        "sport": sport,
        "valid_from": None,
        "valid_until": None,
        "provenance": provenance,
    }
    hr = _zone_list(setting.get("hr_zones"))
    if hr is not None:
        yield from _valid(
            metric=ZoneConfigurationMetric.HEART_RATE,
            environment=None,
            threshold=_number(setting.get("lthr")),
            maximum=_number(setting.get("max_hr")),
            resting=None,
            limits=hr,
            percent_limits=None,
            percent_basis=None,
            **common,
        )
    power = _zone_list(setting.get("power_zones"))
    if power is not None:
        thresholds: list[tuple[Environment | None, float | None]] = [
            (None, _number(setting.get("ftp")))
        ]
        indoor = _number(setting.get("indoor_ftp"))
        if indoor is not None:
            thresholds.append((Environment.INDOOR, indoor))
        for environment, threshold in thresholds:
            yield from _valid(
                metric=ZoneConfigurationMetric.POWER,
                environment=environment,
                threshold=threshold,
                maximum=None,
                resting=None,
                limits=None,
                percent_limits=power,
                percent_basis=ZonePercentBasis.THRESHOLD,
                **common,
            )
    pace = _zone_list(setting.get("pace_zones"))
    if pace is not None:
        yield from _valid(
            metric=ZoneConfigurationMetric.PACE,
            environment=None,
            threshold=_pace_speed(setting.get("threshold_pace")),
            maximum=None,
            resting=None,
            limits=None,
            percent_limits=pace,
            percent_basis=ZonePercentBasis.THRESHOLD,
            **common,
        )


def map_intervals_zone_configurations(
    athlete: object, *, source_record_id: str, retrieved_at: datetime
) -> tuple[ZoneConfiguration, ...]:
    """Return the zone configurations of one stored Intervals.icu athlete record."""
    if not isinstance(athlete, Mapping):
        return ()
    provenance = Provenance(
        provider=ProviderId.INTERVALS,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=source_record_id,
        recorded_by=RecordingOrigin.UNKNOWN,
        retrieved_at=retrieved_at,
        label=INTERVALS_LABEL,
    )
    configurations: list[ZoneConfiguration] = []
    for sport, setting in _first_settings(athlete).items():
        configurations.extend(_configurations(sport, setting, provenance))
    return tuple(configurations)
