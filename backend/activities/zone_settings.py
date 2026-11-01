"""Zone limits and thresholds used to color plan steps and recordings.

Defaults follow Intervals.icu's standard zones. Canonical zone configurations
replace them per metric: a confirmed local configuration valid on the day wins,
then the provider's. A metric without a configuration keeps the sport's canonical
thresholds (``from_thresholds``) and the default limits.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import Observation
from backend.canonical.vocabulary import (
    Environment,
    MetricKind,
    ProviderId,
    Sport,
    ZoneConfigurationMetric,
    ZonePercentBasis,
)

# Upper zone limits (Z1..Z6; everything above is Z7) as percent of the threshold.
POWER_ZONE_LIMITS = (55, 75, 90, 105, 120, 150)
HR_ZONE_LIMITS = (68, 83, 94, 105, 120, 150)
PACE_ZONE_LIMITS = (77.5, 87.7, 94.3, 100, 103.4, 111.5)
# Heart-rate steps are usually written as percent of max HR; threshold HR is
# about 90 % of it.
LTHR_SHARE_OF_MAX_HR = 0.9
_MIN_ZONES = 3
_MAX_ZONES = 7


def percent_zone(percent: float, limits: tuple[float, ...]) -> int:
    """Zone number for ``percent``; everything above the last limit is the top zone."""
    return next(
        (index for index, limit in enumerate(limits, 1) if percent <= limit),
        len(limits) + 1,
    )


@dataclass(frozen=True)
class ZoneSettings:
    """Thresholds and zone limits (percent of threshold) of one sport."""

    ftp: float | None = None
    lthr: float | None = None
    max_hr: float | None = None
    power_limits: tuple[float, ...] = POWER_ZONE_LIMITS
    hr_limits: tuple[float, ...] = HR_ZONE_LIMITS
    pace_limits: tuple[float, ...] = PACE_ZONE_LIMITS

    @classmethod
    def from_thresholds(
        cls,
        observations: Iterable[Observation],
        sport: Sport,
        environment: Environment = Environment.UNKNOWN,
    ) -> ZoneSettings:
        """Thresholds of ``sport`` from its canonical athlete settings, default limits.

        ``observations`` are the sport-scoped FTP, indoor FTP, threshold and maximum
        heart rate of the latest provider sync; the first of each kind for ``sport``
        is used. Indoor and virtual workouts use the indoor FTP when there is one.
        """
        values: dict[MetricKind, float] = {}
        for observation in observations:
            if observation.sport is sport:
                values.setdefault(observation.kind, float(observation.value.value))
        indoor = environment in {Environment.INDOOR, Environment.VIRTUAL}
        return cls(
            ftp=(values.get(MetricKind.INDOOR_FTP) if indoor else None)
            or values.get(MetricKind.FTP),
            lthr=values.get(MetricKind.THRESHOLD_HR),
            max_hr=values.get(MetricKind.MAX_HR),
        )

    @classmethod
    def from_configurations(
        cls,
        configurations: Iterable[ZoneConfiguration],
        sport: Sport,
        environment: Environment = Environment.UNKNOWN,
        day: date | None = None,
        *,
        fallback: ZoneSettings | None = None,
    ) -> ZoneSettings:
        """Zone settings of ``sport`` from the effective canonical configurations.

        Lists keep the open top entry, which the percent limits leave out, as the
        sport settings do. Each metric is decided on its own: one without an
        applicable configuration keeps the ``fallback`` value, or the default
        limits and no threshold when there is none.
        """
        chosen = list(configurations)
        indoor = environment in {Environment.INDOOR, Environment.VIRTUAL}
        base = fallback or cls()
        power = effective_zone_configuration(
            chosen, ZoneConfigurationMetric.POWER, sport, indoor=indoor, day=day
        )
        heart_rate = effective_zone_configuration(
            chosen, ZoneConfigurationMetric.HEART_RATE, sport, indoor=indoor, day=day
        )
        pace = effective_zone_configuration(
            chosen, ZoneConfigurationMetric.PACE, sport, indoor=indoor, day=day
        )
        return cls(
            ftp=base.ftp if power is None else power.threshold,
            lthr=base.lthr if heart_rate is None else heart_rate.threshold,
            max_hr=base.max_hr if heart_rate is None else heart_rate.maximum,
            power_limits=_percent_limits(power) or base.power_limits,
            hr_limits=_percent_limits(heart_rate) or base.hr_limits,
            pace_limits=_percent_limits(pace) or base.pace_limits,
        )

    def power_zone(self, percent_of_ftp: float) -> int:
        return percent_zone(percent_of_ftp, self.power_limits)

    def pace_zone(self, percent_of_threshold: float) -> int:
        return percent_zone(percent_of_threshold, self.pace_limits)

    def hr_zone_of_lthr(self, percent_of_lthr: float) -> int:
        return percent_zone(percent_of_lthr, self.hr_limits)

    def hr_zone_of_max(self, percent_of_max_hr: float) -> int:
        """Zone of a percent-of-max-HR target, via bpm when the athlete's HR is known."""
        if self.max_hr:
            threshold = self.lthr or self.max_hr * LTHR_SHARE_OF_MAX_HR
            return self.hr_zone_of_lthr(percent_of_max_hr * self.max_hr / threshold)
        return self.hr_zone_of_lthr(percent_of_max_hr / LTHR_SHARE_OF_MAX_HR)

    def absolute_zone(self, unit: str, value: float) -> int | None:
        """Zone of an absolute watt or bpm target; needs the matching threshold."""
        if unit == "W" and self.ftp:
            return self.power_zone(value / self.ftp * 100)
        if unit == "bpm" and self.lthr:
            return self.hr_zone_of_lthr(value / self.lthr * 100)
        return None


def _valid_on(configuration: ZoneConfiguration, day: date | None) -> bool:
    if day is None:
        return True
    return (configuration.valid_from is None or configuration.valid_from <= day) and (
        configuration.valid_until is None or day <= configuration.valid_until
    )


def _source_rank(configuration: ZoneConfiguration) -> int:
    """Confirmed local values first, then the provider order."""
    provider = configuration.provenance.provider
    if provider is None:
        return 0
    return 1 + list(ProviderId).index(provider)


def effective_zone_configuration(
    configurations: Iterable[ZoneConfiguration],
    metric: ZoneConfigurationMetric,
    sport: Sport,
    *,
    indoor: bool = False,
    day: date | None = None,
) -> ZoneConfiguration | None:
    """The configuration of one metric that applies to ``sport`` on ``day``.

    Local configurations win over every provider. Within one source an indoor
    configuration applies to indoor and virtual sessions, an environment-free one
    to every session, and the latest ``valid_from`` wins.
    """
    environments = (Environment.INDOOR, None) if indoor else (None,)
    candidates = [
        configuration
        for configuration in configurations
        if configuration.metric is metric
        and configuration.sport is sport
        and configuration.environment in environments
        and _valid_on(configuration, day)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda configuration: (
            _source_rank(configuration),
            environments.index(configuration.environment),
            -(configuration.valid_from or date.min).toordinal(),
        ),
    )


def _percent_limits(
    configuration: ZoneConfiguration | None,
) -> tuple[float, ...] | None:
    """Upper limits as percent of the threshold, without the open top entry."""
    if configuration is None:
        return None
    if configuration.percent_limits is not None:
        if configuration.percent_basis is not ZonePercentBasis.THRESHOLD:
            return None
        limits = configuration.percent_limits[:-1]
    elif configuration.limits is not None and configuration.threshold:
        threshold = configuration.threshold
        limits = tuple(limit / (threshold / 100) for limit in configuration.limits[:-1])
    else:
        return None
    if len(limits) < _MIN_ZONES - 1:
        return None
    return limits
