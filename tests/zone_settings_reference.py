"""The retired snapshot sport-settings zone reader, kept as a parity reference.

Production reads the plan zones from canonical zone configurations and the
canonical sport thresholds (#1416). ``legacy_zone_settings`` is a copy of the
former ``ZoneSettings.from_sport_settings`` (plus the former calendar rule that
configurations override it per metric), and ``canonical_zone_settings`` runs the
same Intervals.icu settings through the mappers and the canonical path. This is
a helper module, not a test module.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from itertools import pairwise
from typing import Any

from backend.activities.zone_settings import (
    HR_ZONE_LIMITS,
    PACE_ZONE_LIMITS,
    POWER_ZONE_LIMITS,
    ZoneSettings,
)
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import Observation
from backend.canonical.sports import classify_sport_text
from backend.canonical.vocabulary import Environment, MetricKind, Sport
from backend.providers.intervals_wellness_mapping import (
    map_intervals_athlete_thresholds,
)
from backend.providers.intervals_zone_mapping import map_intervals_zone_configurations

RETRIEVED_AT = datetime(2026, 10, 11, 6, tzinfo=UTC)
_MIN_ZONES = 3
_MAX_ZONES = 7
_THRESHOLD_KINDS = frozenset(
    {MetricKind.FTP, MetricKind.THRESHOLD_HR, MetricKind.MAX_HR}
)


def _number(value: Any) -> float | None:
    return (
        float(value)
        if type(value) in {int, float} and math.isfinite(value) and value > 0
        else None
    )


def _limits(value: Any, divisor: float = 1.0) -> tuple[float, ...] | None:
    """The ascending zone limits of an Intervals.icu zone list, or None."""
    if not isinstance(value, list) or not _MIN_ZONES <= len(value) <= _MAX_ZONES:
        return None
    numbers = [_number(item) for item in value[:-1]]
    if any(item is None for item in numbers):
        return None
    limits = tuple(item / divisor for item in numbers if item is not None)
    ascending = all(left < right for left, right in pairwise(limits))
    return limits if ascending else None


def _from_setting(setting: dict[str, Any], environment: Environment) -> ZoneSettings:
    lthr = _number(setting.get("lthr"))
    indoor = environment in {Environment.INDOOR, Environment.VIRTUAL}
    ftp = (_number(setting.get("indoor_ftp")) if indoor else None) or _number(
        setting.get("ftp")
    )
    hr_limits = _limits(setting.get("hr_zones"), lthr / 100) if lthr else None
    return ZoneSettings(
        ftp=ftp,
        lthr=lthr,
        max_hr=_number(setting.get("max_hr")),
        power_limits=_limits(setting.get("power_zones")) or POWER_ZONE_LIMITS,
        hr_limits=hr_limits or HR_ZONE_LIMITS,
        pace_limits=_limits(setting.get("pace_zones")) or PACE_ZONE_LIMITS,
    )


def legacy_sport_settings(
    settings: Any, sport: Sport, environment: Environment = Environment.UNKNOWN
) -> ZoneSettings:
    """Zone settings of the first Intervals.icu sport setting for ``sport``."""
    for setting in settings if isinstance(settings, list) else ():
        types = setting.get("types") if isinstance(setting, dict) else None
        if isinstance(types, list) and any(
            isinstance(item, str) and classify_sport_text(item) == sport
            for item in types
        ):
            return _from_setting(setting, environment)
    return ZoneSettings()


def legacy_zone_settings(
    settings: Any,
    configurations: tuple[ZoneConfiguration, ...],
    sport: Sport,
    environment: Environment = Environment.UNKNOWN,
    day: date | None = None,
) -> ZoneSettings:
    """The former calendar rule: configurations per metric over the snapshot settings."""
    legacy = legacy_sport_settings(settings, sport, environment)
    if any(configuration.sport is sport for configuration in configurations):
        return ZoneSettings.from_configurations(
            configurations, sport, environment, day, fallback=legacy
        )
    return legacy


def canonical_sport_inputs(
    athlete: dict[str, Any],
) -> tuple[tuple[ZoneConfiguration, ...], tuple[Observation, ...]]:
    """The zone configurations and sport thresholds the mappers store for an athlete."""
    configurations = map_intervals_zone_configurations(
        athlete, source_record_id="i1", retrieved_at=RETRIEVED_AT
    )
    thresholds = tuple(
        observation
        for observation in map_intervals_athlete_thresholds(
            {"id": "i1", **athlete},
            observed_on=RETRIEVED_AT.date(),
            retrieved_at=RETRIEVED_AT,
        ).records
        if observation.sport is not None and observation.kind in _THRESHOLD_KINDS
    )
    return configurations, thresholds


def canonical_zone_settings(
    settings: Any, sport: Sport, environment: Environment = Environment.UNKNOWN
) -> ZoneSettings:
    """Zone settings of ``sport`` from the canonical form of Intervals.icu settings."""
    configurations, thresholds = canonical_sport_inputs({"sportSettings": settings})
    return ZoneSettings.from_configurations(
        configurations,
        sport,
        environment,
        fallback=ZoneSettings.from_thresholds(thresholds, sport),
    )
