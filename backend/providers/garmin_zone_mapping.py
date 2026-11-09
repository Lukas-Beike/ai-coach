"""Map Garmin heart-rate zone sets (the watch zones) to canonical zone configurations.

One element of the ``heart_rate_zones`` section is the zone set of one sport
(``/biometric-service/heartRateZones/v2``): ``sport`` (``DEFAULT``, ``RUNNING``,
``CYCLING``), the ``zone1Floor`` .. ``zone5Floor`` lower limits in bpm,
``maxHeartRateUsed``, and, depending on the calculation basis the athlete chose
on the watch (``trainingMethod``: percent of max HR, heart-rate reserve, percent
of lactate threshold HR, custom), ``lactateThresholdHeartRateUsed`` and
``restingHeartRateUsed``.

The floors are absolute bpm and are taken as they are, whatever the basis; the
basis is kept as ``model`` and the thresholds as ``threshold`` / ``resting`` /
``maximum``, nothing is derived from percentages. Zone N spans its floor up to
the next floor minus 1 bpm, so the upper limit of zone N is ``zone(N+1)Floor - 1``
and the open top zone ends at ``maxHeartRateUsed``. ``DEFAULT`` becomes the
configuration without a sport, which applies to every sport that has none of its
own. A set that fails validation is left out. A set is valid from the day it was
first fetched (``fetchedOn``, which the sync stamps on a changed set; else the
local day of its retrieval); a changed set (a new threshold or basis) is stored
as a new element and starts a new one. No I/O.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import date, datetime, tzinfo
from typing import Final

from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.local_time import local_date
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
)

GARMIN_LABEL: Final = "Garmin Connect"
_FLOORS: Final = ("zone1Floor", "zone2Floor", "zone3Floor", "zone4Floor", "zone5Floor")
_SPORT_KEYS: Final = ("sport", "sportType", "activityType")
_GENERIC: Final = frozenset({"default", "generic", "all"})


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _sport(node: Mapping[str, object]) -> tuple[bool, Sport | None]:
    """(known, sport): ``DEFAULT`` is known without a sport, unknown sports are not."""
    text = next(
        (str(node[key]).lower() for key in _SPORT_KEYS if node.get(key) is not None),
        "default",
    )
    if text in _GENERIC:
        return True, None
    if any(term in text for term in ("cycl", "bike", "ride")):
        return True, Sport.RIDE
    if "run" in text:
        return True, Sport.RUN
    return False, None


def _model(node: Mapping[str, object]) -> str | None:
    method = node.get("trainingMethod")
    if not isinstance(method, str):
        return None
    slug = method.strip().lower()
    return slug if slug.isidentifier() and slug.isascii() and len(slug) <= 64 else None


def _fetched_on(node: Mapping[str, object]) -> date | None:
    value = node.get("fetchedOn")
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _configuration(
    node: Mapping[str, object], provenance: Provenance, valid_from: date
) -> Iterable[ZoneConfiguration]:
    known, sport = _sport(node)
    floors = [_number(node.get(key)) for key in _FLOORS]
    maximum = _number(node.get("maxHeartRateUsed"))
    if not known or maximum is None or any(floor is None for floor in floors):
        return
    upper = [floor - 1 for floor in floors[1:] if floor is not None]
    try:
        yield ZoneConfiguration(
            metric=ZoneConfigurationMetric.HEART_RATE,
            sport=sport,
            environment=None,
            valid_from=valid_from,
            valid_until=None,
            threshold=_number(node.get("lactateThresholdHeartRateUsed")),
            maximum=maximum,
            resting=_number(node.get("restingHeartRateUsed")),
            limits=(*upper, maximum),
            percent_limits=None,
            percent_basis=None,
            provenance=provenance,
            model=_model(node),
        )
    except TypeError, ValueError:
        return


def map_garmin_heart_rate_zones(
    element: object, *, source_record_id: str, retrieved_at: datetime, zone: tzinfo
) -> tuple[ZoneConfiguration, ...]:
    """The zone configurations of one stored ``heart_rate_zones`` element."""
    nodes = element if isinstance(element, list) else [element]
    provenance = Provenance(
        provider=ProviderId.GARMIN,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=source_record_id,
        recorded_by=RecordingOrigin.GARMIN,
        retrieved_at=retrieved_at,
        label=GARMIN_LABEL,
    )
    fetched = local_date(retrieved_at, zone)
    configurations: dict[str, ZoneConfiguration] = {}
    for node in nodes:
        if isinstance(node, Mapping):
            valid_from = _fetched_on(node) or fetched
            for configuration in _configuration(node, provenance, valid_from):
                sport = configuration.sport
                key = "" if sport is None else sport.value
                configurations.setdefault(key, configuration)
    return tuple(configurations.values())
