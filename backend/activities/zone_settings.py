"""Zone limits and thresholds used to color plan steps and recordings.

Power and pace defaults follow Intervals.icu's standard zones, heart rate
Coggan's five zones. Canonical zone configurations replace them per metric: a
confirmed local configuration valid on the day wins, then the provider's (Garmin's
watch zones before Wahoo's). Absolute bpm, watt or speed limits are used as they
are, whatever calculation basis the provider reports. A metric without any
configuration keeps the sport's canonical thresholds (``from_thresholds``) and
the default limits. ``power_source``, ``hr_source`` and ``pace_source`` name where
the limits come from.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Final

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

# Upper zone limits as percent of the threshold; everything above the last limit is
# the top zone. Power: Z1..Z6, above is Z7 (Intervals.icu). Heart rate: Coggan's five
# zones as percent of LTHR, Z1..Z4, above 105 % is Z5.
POWER_ZONE_LIMITS = (55, 75, 90, 105, 120, 150)
HR_ZONE_LIMITS = (68, 83, 94, 105)
PACE_ZONE_LIMITS = (77.5, 87.7, 94.3, 100, 103.4, 111.5)
# Heart-rate steps are usually written as percent of max HR; threshold HR is
# about 90 % of it.
LTHR_SHARE_OF_MAX_HR = 0.9
_MIN_ZONES = 3
_MAX_ZONES = 7
# A provider configuration valid only after a session day stands in for it when
# its first day is at most this many days later (``local_tss`` uses the same cap
# for thresholds).
ZONE_STAND_IN_MAX_DAYS: Final = 90
DEFAULT_ZONE_SOURCE: Final = "Standardzonen"
_PROVIDER_ZONE_SOURCES: Final = {
    ProviderId.GARMIN: "Garmin-Zonen",
    ProviderId.WAHOO: "Wahoo-Zonen",
    ProviderId.INTERVALS: "Intervals.icu-Zonen",
}
LOCAL_ZONE_SOURCE: Final = "lokale Zonen"


def zone_source_name(configuration: ZoneConfiguration | None) -> str:
    """The name of the source of a configuration's limits, for texts and reports."""
    if configuration is None:
        return DEFAULT_ZONE_SOURCE
    provider = configuration.provenance.provider
    return LOCAL_ZONE_SOURCE if provider is None else _PROVIDER_ZONE_SOURCES[provider]


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
    # Threshold running speed in m/s; pace limits are percent of it.
    threshold_pace: float | None = None
    power_limits: tuple[float, ...] = POWER_ZONE_LIMITS
    hr_limits: tuple[float, ...] = HR_ZONE_LIMITS
    pace_limits: tuple[float, ...] = PACE_ZONE_LIMITS
    # Where the limits come from: names for texts, not part of the zones' identity.
    power_source: str = field(default=DEFAULT_ZONE_SOURCE, compare=False)
    hr_source: str = field(default=DEFAULT_ZONE_SOURCE, compare=False)
    pace_source: str = field(default=DEFAULT_ZONE_SOURCE, compare=False)

    @classmethod
    def from_thresholds(
        cls, observations: Iterable[Observation], sport: Sport
    ) -> ZoneSettings:
        """Thresholds of ``sport`` from its canonical athlete settings, default limits.

        ``observations`` are the sport-scoped FTP, threshold pace, threshold and
        maximum heart rate winners; the first of each kind for ``sport`` is used.
        """
        values: dict[MetricKind, float] = {}
        for observation in observations:
            if observation.sport is sport:
                values.setdefault(observation.kind, float(observation.value.value))
        return cls(
            ftp=values.get(MetricKind.FTP),
            lthr=values.get(MetricKind.THRESHOLD_HR),
            max_hr=values.get(MetricKind.MAX_HR),
            threshold_pace=values.get(MetricKind.THRESHOLD_PACE),
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
        limits and no threshold when there is none. A local configuration's
        threshold wins; a provider configuration only fills a threshold the
        ``fallback`` (the source-policy winners) leaves empty, and gives its limits.
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
        ftp = _threshold(power, base.ftp, "threshold")
        # The watch's own lactate threshold HR (dated Garmin set) leads for heart rate.
        lthr = _threshold(heart_rate, base.lthr, "threshold", watch_first=True)
        threshold_pace = base.threshold_pace
        # Limits are percent of the threshold the settings carry, so the zone of
        # a measured value is the one the provider reported in absolute terms.
        power_limits = _percent_limits(power, ftp)
        hr_limits = _percent_limits(heart_rate, lthr)
        pace_limits = _percent_limits(pace, threshold_pace)
        return cls(
            ftp=ftp,
            lthr=lthr,
            max_hr=_threshold(heart_rate, base.max_hr, "maximum"),
            # The threshold pace comes from the fallback only (resolved upstream).
            threshold_pace=threshold_pace,
            power_limits=power_limits or base.power_limits,
            hr_limits=hr_limits or base.hr_limits,
            pace_limits=pace_limits or base.pace_limits,
            power_source=zone_source_name(power) if power_limits else base.power_source,
            hr_source=zone_source_name(heart_rate) if hr_limits else base.hr_source,
            pace_source=zone_source_name(pace) if pace_limits else base.pace_source,
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


def _threshold(
    configuration: ZoneConfiguration | None,
    fallback: float | None,
    field: str,
    *,
    watch_first: bool = False,
) -> float | None:
    """A local configuration's value, Garmin's dated zone-set threshold, else the fallback.

    The watch's own lactate threshold HR (``lactateThresholdHeartRateUsed`` of the
    dated Garmin zone set valid on the day) leads the source-policy ``fallback``,
    so the watch's automatic updates apply; another provider's value only fills a
    gap the fallback leaves. An Intervals.icu configuration gives its limits
    only, never a threshold.
    """
    if (
        configuration is None
        or configuration.provenance.provider is ProviderId.INTERVALS
    ):
        return fallback
    value: float | None = getattr(configuration, field)
    provider = configuration.provenance.provider
    if provider is None or (provider is ProviderId.GARMIN and watch_first):
        first, second = (value, fallback)
    else:
        first, second = (fallback, value)
    return first if first is not None else second


def _valid_on(configuration: ZoneConfiguration, day: date | None) -> bool:
    if day is None:
        return True
    return (configuration.valid_from is None or configuration.valid_from <= day) and (
        configuration.valid_until is None or day <= configuration.valid_until
    )


# Threshold sources after the confirmed local values: Garmin is curated by the
# athlete, Wahoo follows, and output-only Intervals.icu ranks last.
_PROVIDER_ORDER: Final = (ProviderId.GARMIN, ProviderId.WAHOO, ProviderId.INTERVALS)


def _source_rank(configuration: ZoneConfiguration) -> int:
    """Confirmed local values first, then the provider order."""
    provider = configuration.provenance.provider
    if provider is None:
        return 0
    return 1 + _PROVIDER_ORDER.index(provider)


def effective_zone_configuration(
    configurations: Iterable[ZoneConfiguration],
    metric: ZoneConfigurationMetric,
    sport: Sport,
    *,
    indoor: bool = False,
    day: date | None = None,
) -> ZoneConfiguration | None:
    """The configuration of one metric that applies to ``sport`` on ``day``.

    Local configurations win over every provider. Within one source a
    configuration of the sport wins over Garmin's sport-free (default) set, an
    indoor configuration applies to indoor and virtual sessions, an
    environment-free one to every session, and the latest ``valid_from`` wins.
    A day before every provider configuration is stood in for by the earliest
    one that starts at most ``ZONE_STAND_IN_MAX_DAYS`` days later.
    """
    environments = (Environment.INDOOR, None) if indoor else (None,)
    matching = [
        configuration
        for configuration in configurations
        if configuration.metric is metric
        and configuration.environment in environments
        and (
            configuration.sport is sport
            or (
                configuration.sport is None
                and configuration.provenance.provider is ProviderId.GARMIN
            )
        )
    ]
    candidates = [item for item in matching if _valid_on(item, day)]
    if candidates:
        return min(
            candidates,
            key=lambda configuration: (
                _source_rank(configuration),
                configuration.sport is None,
                environments.index(configuration.environment),
                -(configuration.valid_from or date.min).toordinal(),
            ),
        )
    return _later_stand_in(matching, day) if day is not None else None


def _later_stand_in(
    matching: list[ZoneConfiguration], day: date
) -> ZoneConfiguration | None:
    """The provider configuration starting within the cap after ``day``.

    The source order is the one of a valid day; within it the earliest start wins.
    """
    last = day + timedelta(days=ZONE_STAND_IN_MAX_DAYS)
    later = [
        item
        for item in matching
        if item.provenance.provider is not None
        and item.valid_from is not None
        and day < item.valid_from <= last
    ]
    return min(
        later,
        key=lambda item: (
            _source_rank(item),
            item.sport is None,
            item.environment is None,
            item.valid_from,
        ),
        default=None,
    )


def _percent_limits(
    configuration: ZoneConfiguration | None, reference: float | None = None
) -> tuple[float, ...] | None:
    """Upper limits as percent of the threshold, without the open top entry.

    Percent limits count only with the threshold as their basis. Absolute limits
    are converted with ``reference``, the threshold the settings carry (else the
    configuration's own), whatever calculation basis the provider reports.
    """
    if configuration is None:
        return None
    if (
        configuration.percent_limits is not None
        and configuration.percent_basis is ZonePercentBasis.THRESHOLD
    ):
        limits = configuration.percent_limits[:-1]
    elif configuration.limits is not None and (
        threshold := reference or configuration.threshold
    ):
        # Same operation order as the zone lookup, so a value on a limit stays on it.
        # Garmin's floors are whole bpm; a value rounds to the zone it displays.
        half = 0.5 if configuration.provenance.provider is ProviderId.GARMIN else 0.0
        limits = tuple(
            (limit + half) / threshold * 100 for limit in configuration.limits[:-1]
        )
    else:
        return None
    if len(limits) < _MIN_ZONES - 1:
        return None
    return limits
