"""Local zone configuration: read, confirmed edits, receipts and undo.

The athlete's local zones and thresholds are canonical zone configurations
without a provider. They win over provider zones wherever zones are chosen
(``backend.activities.zone_settings``); provider configurations stay readable as
alternatives and a provider refresh never touches local rows. Each save or removal
records a change-history row whose undo restores the previous local state.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any, Final, Protocol

from backend import change_history
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    Environment,
    RecordingOrigin,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
    ZonePercentBasis,
)
from backend.db import canonical_domain_store
from backend.errors import AppError

ENTITY_TYPE: Final = "zone_configuration"
LOCAL_LABEL: Final = "Lokal"
MIN_ZONES: Final = 3
MAX_ZONES: Final = 7
# Sports whose planned workouts carry zone targets.
EDITABLE_SPORTS: Final = (Sport.RIDE, Sport.RUN, Sport.SWIM)
_INVALID = "Die Zonen sind ungültig: {}."
# Metrics whose zones are placed relative to the threshold, so it must be given.
_THRESHOLD_REQUIRED: Final = {
    ZoneConfigurationMetric.HEART_RATE: "LTHR fehlt",
    ZoneConfigurationMetric.POWER: "FTP fehlt",
}


class ZoneConfigurationReader(Protocol):
    def zone_configurations(self, db: Any) -> tuple[ZoneConfiguration, ...]: ...


def _local_provenance() -> Provenance:
    return Provenance(
        provider=None,
        source_kind=SourceKind.ATHLETE_ENTERED,
        source_record_id=None,
        recorded_by=RecordingOrigin.MANUAL,
        retrieved_at=None,
        label=LOCAL_LABEL,
    )


def _limits(value: Any) -> list[float] | None:
    return None if value is None else [float(item) for item in value]


def public_configuration(configuration: ZoneConfiguration) -> dict[str, Any]:
    """The JSON view of one configuration with its source and key."""
    provider = configuration.provenance.provider
    return {
        "key": canonical_domain_store.zone_configuration_key(configuration),
        "source": "local" if provider is None else provider.value,
        "label": configuration.provenance.label,
        "sport": None if configuration.sport is None else configuration.sport.value,
        "metric": configuration.metric.value,
        "environment": None
        if configuration.environment is None
        else configuration.environment.value,
        "valid_from": None
        if configuration.valid_from is None
        else configuration.valid_from.isoformat(),
        "valid_until": None
        if configuration.valid_until is None
        else configuration.valid_until.isoformat(),
        "threshold": configuration.threshold,
        "maximum": configuration.maximum,
        "limits": _limits(configuration.limits),
        "percent_limits": _limits(configuration.percent_limits),
        "percent_basis": None
        if configuration.percent_basis is None
        else configuration.percent_basis.value,
    }


def _audit_value(configuration: ZoneConfiguration | None) -> dict[str, Any] | None:
    if configuration is None:
        return None
    view = public_configuration(configuration)
    return {field: view[field] for field in change_history.ZONE_CONFIGURATION_FIELDS}


def _enum(enum: Any, value: Any, field: str) -> Any:
    try:
        return enum(value)
    except ValueError as exc:
        raise AppError(400, _INVALID.format(field)) from exc


def _optional_number(value: Any, field: str) -> float | None:
    if value is None or value == "":
        return None
    if type(value) not in {int, float}:
        raise AppError(400, _INVALID.format(field))
    try:
        number = float(value)
    except OverflowError:
        raise AppError(400, _INVALID.format(field)) from None
    if not math.isfinite(number):
        raise AppError(400, _INVALID.format(field))
    return number


def _zone_list(value: Any, field: str) -> tuple[float, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not MIN_ZONES <= len(value) <= MAX_ZONES:
        raise AppError(400, _INVALID.format(f"{field} braucht 3 bis 7 Werte"))
    numbers = tuple(_optional_number(item, field) for item in value)
    if any(item is None for item in numbers):
        raise AppError(400, _INVALID.format(field))
    return tuple(item for item in numbers if item is not None)


def _optional_day(value: Any) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise AppError(400, _INVALID.format("valid_from")) from exc


def local_configuration(payload: Mapping[str, Any]) -> ZoneConfiguration:
    """Validate one local configuration from the API or a restored history row.

    ``limits`` are absolute upper zone limits in canonical units (bpm, W, m/s)
    and ``percent_limits`` are percent of the threshold; one of them is given,
    the open top zone included.
    """
    sport = _enum(Sport, payload.get("sport"), "sport")
    if sport not in EDITABLE_SPORTS:
        raise AppError(400, _INVALID.format("sport"))
    metric = _enum(ZoneConfigurationMetric, payload.get("metric"), "metric")
    environment = payload.get("environment")
    if environment not in (None, Environment.INDOOR.value):
        raise AppError(400, _INVALID.format("environment"))
    limits = _zone_list(payload.get("limits"), "limits")
    percent_limits = _zone_list(payload.get("percent_limits"), "percent_limits")
    if (limits is None) == (percent_limits is None):
        raise AppError(400, _INVALID.format("limits oder percent_limits"))
    threshold = _optional_number(payload.get("threshold"), "threshold")
    if threshold is None and metric in _THRESHOLD_REQUIRED:
        # Without it the local zones would win but replace the provider's
        # threshold with none and could not place bpm or watt targets.
        raise AppError(400, _INVALID.format(_THRESHOLD_REQUIRED[metric]))
    try:
        return ZoneConfiguration(
            metric=metric,
            sport=sport,
            environment=None if environment is None else Environment.INDOOR,
            valid_from=_optional_day(payload.get("valid_from")),
            valid_until=None,
            threshold=threshold,
            maximum=(
                _optional_number(payload.get("maximum"), "maximum")
                if metric is ZoneConfigurationMetric.HEART_RATE
                else None
            ),
            resting=None,
            limits=limits,
            percent_limits=percent_limits,
            percent_basis=None
            if percent_limits is None
            else ZonePercentBasis.THRESHOLD,
            provenance=_local_provenance(),
        )
    except (TypeError, ValueError) as exc:
        raise AppError(400, _INVALID.format(exc)) from exc


class ZoneConfigurationService:
    """Own local zone edits and the zone configurations other reads choose from."""

    def __init__(
        self,
        database_manager: Any,
        reader: ZoneConfigurationReader,
        now: Callable[[], str],
    ) -> None:
        self._database_manager = database_manager
        self._reader = reader
        self._now = now

    def configurations(self) -> tuple[ZoneConfiguration, ...]:
        """Every active local and provider configuration."""
        with self._database_manager.reader() as db:
            return self._reader.zone_configurations(db)

    def read(self) -> dict[str, Any]:
        configurations = self.configurations()
        return {
            "sports": [sport.value for sport in EDITABLE_SPORTS],
            "configurations": [
                public_configuration(configuration)
                for configuration in configurations
                if configuration.sport in EDITABLE_SPORTS
            ],
        }

    def save(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        configuration = local_configuration(payload)
        key = canonical_domain_store.zone_configuration_key(configuration)
        with self._database_manager.unit_of_work() as db:
            current, _ = self.current(db, key)
            canonical_domain_store.upsert_local_zone_configuration(
                db, configuration, now=self._now()
            )
            change = change_history.record_change(
                db,
                ENTITY_TYPE,
                key,
                "create" if current is None else "update",
                current,
                _audit_value(configuration),
            )
        return self._receipt(public_configuration(configuration), change)

    def remove(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Retire one local configuration; the request must be confirmed."""
        if payload.get("confirmed") is not True:
            raise AppError(400, "Das Entfernen lokaler Zonen muss bestätigt werden.")
        key = str(payload.get("key") or "")
        with self._database_manager.unit_of_work() as db:
            current, _ = self.current(db, key)
            if current is None:
                raise AppError(404, "Lokale Zonen nicht gefunden.")
            canonical_domain_store.retire_local_zone_configuration(
                db, key, now=self._now()
            )
            change = change_history.record_change(
                db, ENTITY_TYPE, key, "delete", current, None
            )
        return self._receipt(None, change)

    def current(
        self, db: Any, key: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The audit value of the active local configuration ``key``."""
        found = next(
            (
                configuration
                for configuration in self._reader.zone_configurations(db)
                if configuration.provenance.provider is None
                and canonical_domain_store.zone_configuration_key(configuration) == key
            ),
            None,
        )
        value = _audit_value(found)
        return value, change_history.audit_projection(ENTITY_TYPE, value)

    def restore_in_transaction(
        self,
        db: Any,
        key: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Restore the local configuration ``key`` to an earlier audit value.

        ``target`` holds the changed fields only; the others keep their current
        value. None removes the local configuration again.
        """
        if target is None:
            canonical_domain_store.retire_local_zone_configuration(
                db, key, now=self._now()
            )
            return None
        configuration = local_configuration({**(current or {}), **target})
        if canonical_domain_store.zone_configuration_key(configuration) != key:
            raise AppError(409, "Die Änderungshistorie ist beschädigt.")
        canonical_domain_store.upsert_local_zone_configuration(
            db, configuration, now=self._now()
        )
        return _audit_value(configuration)

    @staticmethod
    def _receipt(
        configuration: dict[str, Any] | None, change: dict[str, Any] | None
    ) -> dict[str, Any]:
        return {
            "configuration": configuration,
            "change": None
            if change is None
            else {key: change[key] for key in change_history.UNDO_REFERENCE_FIELDS},
        }
