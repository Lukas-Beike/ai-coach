"""The zones a session's report zone times are counted with (#1743).

One resolver for the stored report zone times (``SessionAnalysisStage``) and
the activity detail view, so both count the same seconds: the thresholds in
effect on the session's local day (``DatedThresholds``: local, then Garmin,
then Wahoo; indoor rides take the local indoor FTP) and the zone limits of the
effective zone configuration (local first, then Garmin and Wahoo). Intervals.icu
thresholds and configurations are never read. No I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from backend.activities.zone_settings import ZoneSettings
from backend.canonical.activity_summary import summary_local_date
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import Observation
from backend.canonical.vocabulary import Environment, ProviderId, Sport
from backend.performance.local_tss import THRESHOLD_KINDS, DatedThresholds, Threshold
from backend.performance.source_policy import NO_PREFERENCES, SourcePreferences


def own_configurations(
    configurations: Iterable[ZoneConfiguration],
) -> tuple[ZoneConfiguration, ...]:
    """The zone configurations the resolver reads: every non-Intervals one."""
    return tuple(
        item
        for item in configurations
        if item.provenance.provider is not ProviderId.INTERVALS
    )


def dated_thresholds(
    observations: Iterable[Observation],
    configurations: Iterable[ZoneConfiguration],
    preferences: SourcePreferences = NO_PREFERENCES,
) -> DatedThresholds:
    """The thresholds by day from non-Intervals observations and configurations."""
    return DatedThresholds(
        [
            item
            for item in observations
            if item.kind in THRESHOLD_KINDS
            and item.provenance.provider is not ProviderId.INTERVALS
        ],
        own_configurations(configurations),
        preferences=preferences,
    )


def _value(threshold: Threshold | None) -> float | None:
    return None if threshold is None else threshold.value


def session_zone_settings(
    summary: Mapping[str, Any],
    thresholds: DatedThresholds,
    configurations: Iterable[ZoneConfiguration],
) -> ZoneSettings | None:
    """The zones of the session's sport, environment and local day, or None.

    ``configurations`` are the non-Intervals ones (``own_configurations``).
    """
    try:
        sport = Sport(str(summary.get("sport")))
        day = date.fromisoformat(summary_local_date(summary))
        environment = Environment(str(summary.get("environment") or "unknown"))
    except ValueError:
        return None
    return zone_settings_for(sport, environment, day, thresholds, configurations)


def zone_settings_for(
    sport: Sport,
    environment: Environment,
    day: date,
    thresholds: DatedThresholds,
    configurations: Iterable[ZoneConfiguration],
) -> ZoneSettings:
    """The zones of one sport and environment on ``day`` (see the module doc)."""
    indoor = environment in {Environment.INDOOR, Environment.VIRTUAL}
    chosen = thresholds.for_session(sport, day, indoor=indoor)
    return ZoneSettings.from_configurations(
        configurations,
        sport,
        environment,
        day,
        fallback=ZoneSettings(
            ftp=_value(chosen.ftp),
            lthr=_value(chosen.threshold_hr),
            max_hr=_value(chosen.max_hr),
            threshold_pace=_value(chosen.threshold_pace),
        ),
    )


def zone_settings_part(settings: ZoneSettings | None) -> dict[str, Any] | None:
    """The thresholds and limits of ``settings``, for an input fingerprint."""
    if settings is None:
        return None
    return {
        "ftp": settings.ftp,
        "lthr": settings.lthr,
        "hr_reference_bpm": settings.hr_reference_bpm,
        "threshold_pace": settings.threshold_pace,
        "power_limits": list(settings.power_limits),
        "hr_limits": list(settings.hr_limits),
        "pace_limits": list(settings.pace_limits),
        "sources": [settings.power_source, settings.hr_source, settings.pace_source],
    }
