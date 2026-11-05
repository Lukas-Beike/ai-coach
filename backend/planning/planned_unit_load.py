"""Intensity, 3-zone time and load of a planned unit, derived at read time."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

from backend.activities.workout_load import (
    AthleteThresholds,
    WorkoutEstimate,
    estimate_workout,
)
from backend.activities.zone_settings import ZoneSettings, effective_zone_configuration
from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import Observation
from backend.canonical.vocabulary import (
    Environment,
    MetricKind,
    Sport,
    ZoneConfigurationMetric,
)
from backend.performance.canonical_current import read_zone_thresholds
from backend.performance.canonical_inputs import resolve_reader
from backend.performance.source_policy import NO_PREFERENCES, SourcePreferences
from backend.planning.sport import planned_sport_environment


def estimate_planned_unit(
    unit: Mapping[str, Any], thresholds: AthleteThresholds
) -> WorkoutEstimate:
    """Estimate a planned unit from its ``description`` workout text.

    The unit's own planned duration is only used when its steps cannot be parsed.
    """
    seconds = number(unit.get("planned_duration_s"))
    minutes = number(unit.get("duration_minutes"))
    if seconds is None and minutes is not None:
        seconds = minutes * 60
    return estimate_workout(
        str(unit.get("description") or ""),
        planned_sport_environment(unit)[0],
        thresholds,
        fallback_duration_s=seconds,
    )


def sport_threshold_speed(
    observations: Sequence[Observation], sport: Sport
) -> float | None:
    """Threshold running speed (m/s) of ``sport`` from the current thresholds."""
    return next(
        (
            float(item.value.value)
            for item in observations
            if item.kind is MetricKind.THRESHOLD_PACE and item.sport is sport
        ),
        None,
    )


def resolve_thresholds(
    sport_thresholds: Sequence[Observation],
    zone_configurations: Sequence[ZoneConfiguration],
    sport: Sport,
    environment: Environment,
    day: date | None,
) -> AthleteThresholds:
    """Thresholds and zone limits of a sport, locally confirmed values first.

    Same precedence as the Coach context: a local zone configuration in effect on
    ``day`` wins, then the source-policy provider winners (``sport_thresholds``),
    then a provider zone configuration; zone limits come from the effective one.
    """
    pace = effective_zone_configuration(
        zone_configurations, ZoneConfigurationMetric.PACE, sport, day=day
    )
    # A local pace configuration first, then the source-policy winner, then a
    # provider configuration, as for the other thresholds.
    local = (
        pace.threshold
        if pace is not None and pace.provenance.provider is None
        else None
    )
    provider = pace.threshold if pace is not None and local is None else None
    return AthleteThresholds(
        zones=ZoneSettings.from_configurations(
            zone_configurations,
            sport,
            environment,
            day,
            fallback=ZoneSettings.from_thresholds(sport_thresholds, sport, environment),
        ),
        threshold_speed_mps=local
        or sport_threshold_speed(sport_thresholds, sport)
        or provider,
    )


def unit_thresholds(
    unit: Mapping[str, Any],
    sport_thresholds: Sequence[Observation],
    zone_configurations: Sequence[ZoneConfiguration],
) -> AthleteThresholds:
    """Current thresholds and zone limits of a unit's sport, as the plan profiles use.

    The threshold running speed comes from the same current thresholds; without
    it absolute pace targets stay unknown.
    """
    sport, environment = planned_sport_environment(unit)
    try:
        day = date.fromisoformat(
            iso_date_prefix(unit.get("date") or unit.get("starts_at_local") or "")
        )
    except ValueError:
        day = None
    return resolve_thresholds(
        sport_thresholds, zone_configurations, sport, environment, day
    )


class PlannedUnitEstimator:
    """Estimate planned units with thresholds read once, on first use."""

    def __init__(
        self,
        database_manager: Callable[[], Any],
        observation_reader: Callable[[], Any],
        zone_configurations: Callable[[], Sequence[ZoneConfiguration]],
        today: Callable[[], date] = date.today,
        source_preferences: Callable[[Any], SourcePreferences] | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._source_preferences = source_preferences
        self._today = today
        self._observation_reader = observation_reader
        self._read_configurations = zone_configurations
        self._inputs: (
            tuple[Sequence[Observation], Sequence[ZoneConfiguration]] | None
        ) = None

    def _read_inputs(
        self,
    ) -> tuple[Sequence[Observation], Sequence[ZoneConfiguration]]:
        with self._database_manager().reader() as db:
            thresholds = read_zone_thresholds(
                resolve_reader(self._observation_reader(), db),
                db,
                as_of=self._today(),
                preferences=(
                    NO_PREFERENCES
                    if self._source_preferences is None
                    else self._source_preferences(db)
                ),
            )
        return thresholds, self._read_configurations()

    def __call__(self, unit: Mapping[str, Any]) -> WorkoutEstimate:
        return estimate_planned_unit(unit, self.thresholds(unit))

    def thresholds(self, unit: Mapping[str, Any]) -> AthleteThresholds:
        """The current thresholds of the unit's sport, as its estimate uses."""
        if self._inputs is None:
            self._inputs = self._read_inputs()
        return unit_thresholds(unit, *self._inputs)
