"""Warnings for stale load thresholds and a failing Garmin SDK (#1768).

Garmin FTP and lactate threshold come only through the unofficial Garmin SDK,
eFTP was removed and Intervals.icu thresholds are no longer read. A threshold
that stops updating silently changes the local session load (card M6) and the
zones, so the athlete gets one hint naming the value, its source and age.

The active value per threshold follows the export order: the local zone
configuration in effect, then the Garmin watch zone set (lactate threshold heart
rate), then Garmin and Wahoo observations (``read_export_thresholds``). A value
is stale once it is older than ``STALE_AFTER_DAYS`` on the athlete-local day. A
local value is dated by its ``valid_from``, else by its last save; a watch zone
set by its ``valid_from``; a provider observation by the day the provider
reports for it. A provider value beyond
its source-policy age limit is no longer used and is reported as expired. While
the Garmin SDK fails, Garmin values stop updating, so each active Garmin value
is listed even when it is still fresh. Indoor rides read the ride FTP unless the
athlete set a local indoor FTP; only that explicit value can be reported stale.

No value is estimated here. This module must not import ``server.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from backend.activities.zone_settings import (
    configured_threshold,
    effective_zone_configuration,
)
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.labels import PROVIDER_SHORT_LABELS
from backend.canonical.records import Observation
from backend.canonical.vocabulary import (
    Environment,
    MetricKind,
    ProviderId,
    Sport,
    ZoneConfigurationMetric,
)
from backend.db import canonical_domain_store
from backend.performance.canonical_current import (
    newest_wahoo_ftp,
    read_export_thresholds,
)
from backend.performance.current_thresholds import ThresholdKey
from backend.performance.garmin_canonical import read_garmin_thresholds
from backend.performance.source_policy import SourcePreferences

_LOGGER = logging.getLogger("intervals_coach")

# Athlete decision 2026-11-07: eight weeks.
STALE_AFTER_DAYS: Final = 56

REASON_STALE: Final = "stale"
REASON_EXPIRED: Final = "expired"
REASON_SDK_FAILED: Final = "sdk_failed"

# The thresholds the local load and the zones read, with their German label.
CHECKED_THRESHOLDS: Final[tuple[tuple[ThresholdKey, str], ...]] = (
    ((MetricKind.FTP, Sport.RIDE), "FTP Rad"),
    ((MetricKind.FTP, Sport.RUN), "FTP Laufen"),
    ((MetricKind.THRESHOLD_HR, Sport.RIDE), "Schwellenpuls (LSHF) Rad"),
    ((MetricKind.THRESHOLD_HR, Sport.RUN), "Schwellenpuls (LSHF) Laufen"),
    ((MetricKind.THRESHOLD_PACE, Sport.RUN), "Schwellenpace"),
)
INDOOR_LABEL: Final = "Indoor-FTP"
# The item key of the local indoor FTP; no provider indoor FTP is read here.
INDOOR_METRIC: Final = "indoor_ftp"
_LOCAL_LABEL: Final = "Lokal"


@dataclass(frozen=True, slots=True)
class DatedThreshold:
    """One threshold value with its source and the day it dates from."""

    value: float
    provider: ProviderId | None
    dated_on: date | None


def value_text(kind: MetricKind, value: float) -> str:
    """The value as the athlete reads it: watts, bpm or pace per kilometre."""
    if kind is MetricKind.THRESHOLD_PACE:
        if value <= 0:
            return "–"
        seconds = round(1000 / value)
        return f"{seconds // 60}:{seconds % 60:02d} /km"
    unit = "W" if kind is MetricKind.FTP else "bpm"
    return f"{round(value)} {unit}"


def _item(
    kind: MetricKind,
    sport: Sport,
    label: str,
    threshold: DatedThreshold,
    reason: str,
    today: date,
) -> dict[str, Any]:
    dated_on = threshold.dated_on
    return {
        "metric": kind.value,
        "sport": sport.value,
        "label": label,
        "value": threshold.value,
        "value_text": value_text(kind, threshold.value),
        "source": "local" if threshold.provider is None else threshold.provider.value,
        "source_label": _LOCAL_LABEL
        if threshold.provider is None
        else PROVIDER_SHORT_LABELS.get(threshold.provider, "Anbieter"),
        "dated_on": None if dated_on is None else dated_on.isoformat(),
        "age_days": None if dated_on is None else (today - dated_on).days,
        "reason": reason,
    }


def _stale(threshold: DatedThreshold, today: date) -> bool:
    return (
        threshold.dated_on is not None
        and (today - threshold.dated_on).days > STALE_AFTER_DAYS
    )


def _threshold_item(
    key: ThresholdKey,
    label: str,
    current: DatedThreshold | None,
    expired: DatedThreshold | None,
    *,
    today: date,
    sdk_failed: bool,
) -> dict[str, Any] | None:
    """The item of one checked threshold, or None when it needs no hint."""
    kind, sport = key
    if current is None:
        return (
            None
            if expired is None
            else _item(kind, sport, label, expired, REASON_EXPIRED, today)
        )
    if _stale(current, today):
        return _item(kind, sport, label, current, REASON_STALE, today)
    if sdk_failed and current.provider is ProviderId.GARMIN:
        return _item(kind, sport, label, current, REASON_SDK_FAILED, today)
    return None


def _indoor_item(
    indoor_local: DatedThreshold | None, today: date
) -> dict[str, Any] | None:
    """The stale item of an explicitly set local indoor FTP; none otherwise."""
    if indoor_local is None or not _stale(indoor_local, today):
        return None
    item = _item(
        MetricKind.FTP, Sport.RIDE, INDOOR_LABEL, indoor_local, REASON_STALE, today
    )
    return {**item, "metric": INDOOR_METRIC}


def assess_thresholds(
    active: Mapping[ThresholdKey, DatedThreshold],
    last_provider: Mapping[ThresholdKey, DatedThreshold],
    *,
    today: date,
    sdk_failure: Mapping[str, Any] | None = None,
    indoor_local: DatedThreshold | None = None,
    local_undated: frozenset[ThresholdKey] = frozenset(),
) -> dict[str, Any] | None:
    """Return the warning, or None when every checked threshold is fresh.

    ``active`` holds the value in effect per threshold, ``last_provider`` the
    newest provider value per threshold whatever its age. ``indoor_local`` is the
    local indoor FTP in effect, if the athlete set one. ``local_undated`` names thresholds whose local value
    is in effect without a date; they are not judged.
    """
    checked = [
        (key, label, active.get(key), last_provider.get(key))
        for key, label in CHECKED_THRESHOLDS
        if key not in local_undated or key in active
    ]
    items = [
        item
        for key, label, current, expired in checked
        if (
            item := _threshold_item(
                key,
                label,
                current,
                expired,
                today=today,
                sdk_failed=bool(sdk_failure),
            )
        )
    ]
    if indoor := _indoor_item(indoor_local, today):
        items.append(indoor)
    if not items:
        return None
    garmin_involved = any(
        value.provider is ProviderId.GARMIN
        for _, _, current, expired in checked
        if (value := current or expired) is not None
    )
    return {
        "stale_after_days": STALE_AFTER_DAYS,
        "sdk_failure": dict(sdk_failure) if sdk_failure and garmin_involved else None,
        "items": items,
    }


def _local_dated(
    configuration: ZoneConfiguration, saved_on: Mapping[str, date]
) -> DatedThreshold | None:
    value = configuration.threshold
    if not value:
        return None
    dated_on = configuration.valid_from or saved_on.get(
        canonical_domain_store.zone_configuration_key(configuration)
    )
    return DatedThreshold(float(value), None, dated_on)


def _configured_dated(
    configuration: ZoneConfiguration,
    value: float,
    saved_on: Mapping[str, date],
    reported: DatedThreshold | None,
) -> DatedThreshold | None:
    """A configured threshold with its date.

    A local one is dated by its start or save. A watch zone set is dated by its
    start, or by the day Garmin last reported the same value when that is later,
    so an unchanged threshold the watch keeps confirming is not stale.
    """
    provider = configuration.provenance.provider
    if provider is None:
        return _local_dated(configuration, saved_on)
    days = [configuration.valid_from]
    if (
        reported is not None
        and reported.provider is provider
        and reported.value == value
    ):
        days.append(reported.dated_on)
    return DatedThreshold(
        value, provider, max((day for day in days if day), default=None)
    )


def _provider_dated(observation: Observation) -> DatedThreshold:
    return DatedThreshold(
        float(observation.value.value),
        observation.provenance.provider,
        observation.observed_on,
    )


def _newest_by_key(
    observations: Iterable[Observation],
) -> dict[ThresholdKey, Observation]:
    newest: dict[ThresholdKey, Observation] = {}
    for observation in observations:
        sport = observation.sport
        if sport is None:
            continue
        key = (observation.kind, sport)
        held = newest.get(key)
        if held is None or observation.observed_on > held.observed_on:
            newest[key] = observation
    return newest


def _active_thresholds(
    winners: Mapping[ThresholdKey, Observation],
    configurations: Iterable[ZoneConfiguration],
    last_provider: Mapping[ThresholdKey, DatedThreshold],
    saved_on: Mapping[str, date],
    today: date,
) -> tuple[dict[ThresholdKey, DatedThreshold], frozenset[ThresholdKey]]:
    """The dated value in effect per threshold, and the undated configured ones."""
    configurations = list(configurations)
    active: dict[ThresholdKey, DatedThreshold] = {}
    undated: set[ThresholdKey] = set()
    for key, _ in CHECKED_THRESHOLDS:
        winner = winners.get(key)
        if winner is None:
            continue
        kind, sport = key
        # A configured value (local, or the watch zone set) leads the observations.
        configured = configured_threshold(configurations, kind, sport, today)
        if configured is None or configured[0] != float(winner.value.value):
            active[key] = _provider_dated(winner)
            continue
        dated = _configured_dated(
            configured[1], configured[0], saved_on, last_provider.get(key)
        )
        if dated is None:
            undated.add(key)
        else:
            active[key] = dated
    return active, frozenset(undated)


class ThresholdStalenessService:
    """Read the thresholds in effect and assess them for one athlete-local day."""

    def __init__(
        self,
        database_manager: Callable[[], Any],
        reader: Callable[[], Any],
        today: Callable[[], date],
        *,
        zone_configurations: Callable[[Any], tuple[ZoneConfiguration, ...]],
        preferences: Callable[[Any], SourcePreferences],
        sdk_failure: Callable[[], Mapping[str, Any] | None] = lambda: None,
    ) -> None:
        """``reader`` serves observations; the stored zone configurations come from ``zone_configurations``."""
        self._database_manager = database_manager
        self._reader = reader
        self._zone_configurations = zone_configurations
        self._today = today
        self._preferences = preferences
        self._sdk_failure = sdk_failure

    def read(self) -> dict[str, Any] | None:
        """The warning for today; None when fresh or unreadable (never raises)."""
        try:
            return self._read()
        except Exception as error:  # noqa: BLE001 - a hint never fails its page
            _LOGGER.warning(
                "Threshold staleness unavailable",
                extra={
                    "event": "threshold_staleness_failed",
                    "context": {"error_type": type(error).__name__},
                },
            )
            return None

    def _read(self) -> dict[str, Any] | None:
        today = self._today()
        reader = self._reader()
        with self._database_manager().reader() as db:
            configurations = self._zone_configurations(db)
            winners = read_export_thresholds(
                reader,
                db,
                as_of=today,
                preferences=self._preferences(db),
                configurations=configurations,
            )
            providers = (
                *read_garmin_thresholds(reader, db),
                *((wahoo,) if (wahoo := newest_wahoo_ftp(reader, db)) else ()),
            )
            saved_on = canonical_domain_store.local_zone_saved_days(db)
        local = [item for item in configurations if item.provenance.provider is None]
        last_provider = {
            key: _provider_dated(observation)
            for key, observation in _newest_by_key(providers).items()
        }
        active, local_undated = _active_thresholds(
            winners, configurations, last_provider, saved_on, today
        )
        indoor = effective_zone_configuration(
            local, ZoneConfigurationMetric.POWER, Sport.RIDE, indoor=True, day=today
        )
        indoor_local = (
            _local_dated(indoor, saved_on)
            if indoor is not None and indoor.environment is Environment.INDOOR
            else None
        )
        return assess_thresholds(
            active,
            last_provider,
            today=today,
            sdk_failure=self._sdk_failure(),
            indoor_local=indoor_local,
            local_undated=local_undated,
        )
