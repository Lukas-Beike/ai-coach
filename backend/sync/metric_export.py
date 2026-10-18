"""Manual and automatic export of canonical body and threshold metrics.

The preview lists, per target field, the newest local value that another
provider supplied, next to the target's current value read live. Execute reads
the target again and writes only what a confirmed request names: the target
provider and every metric with the exact day, value and current target value of
the preview. A value the target itself reported is
never sent back to it; only values another provider reported are offered, so
AI estimates are never exported. Each written field is recorded in
``remote_links`` so the same value is not offered again.

Successful current Garmin synchronization also exports Garmin measurements with
unchanged heart-rate zones and durable comparison baselines protecting later
target-side edits.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final, TypeGuard

from backend.canonical.records import Observation
from backend.canonical.vocabulary import (
    ProviderId,
    RemoteEntityKind,
    RemoteLinkState,
    SourceKind,
)
from backend.db.canonical_store import observation_natural_key
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError, public_error_contract
from backend.providers.descriptors import Capability
from backend.providers.source_labels import SourceView, observation_source_label
from backend.runtime.ports import ObservationReader
from backend.sync.metric_export_port import (
    MetricExportField,
    MetricExportPort,
    MetricWrite,
)
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry

_LOGGER = logging.getLogger(__name__)

DEFAULT_METRIC_EXPORT_TARGET: Final = ProviderId.INTERVALS
# Older values are stale for a current setting and are not offered.
_LOOKBACK_DAYS: Final = 90
_MAX_REQUESTED_METRICS: Final = 32

READY = "ready"
UNCHANGED = "unchanged"
ALREADY_EXPORTED = "already_exported"
EXPORTED = "exported"
FAILED = "failed"


@dataclass(frozen=True, slots=True)
class _Requested:
    key: str
    observed_on: str
    value: float
    remote: float | None


@dataclass(frozen=True, slots=True)
class _Candidate:
    key: str
    field: MetricExportField
    record: str
    source: Observation
    # The target's live value of the field, read for this preview or execute.
    remote: float | None
    status: str

    @property
    def value(self) -> float:
        return self.source.value.value

    @property
    def remote_id(self) -> str:
        return f"{self.record}/{self.field.field}"


def _recency(observation: Observation) -> tuple[date, float, float]:
    observed_at = observation.observed_at
    retrieved_at = observation.provenance.retrieved_at
    return (
        observation.observed_on,
        observed_at.timestamp() if observed_at is not None else 0.0,
        retrieved_at.timestamp() if retrieved_at is not None else 0.0,
    )


def _same_value(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-3, abs_tol=1e-6)


def _is_number(value: object) -> TypeGuard[int | float]:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _same_remote(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return _same_value(left, right)


def _baseline(remote_id: str, value: float) -> str:
    return hashlib.sha256(f"{remote_id}={value!r}".encode()).hexdigest()


def _item_key(field: MetricExportField) -> str:
    return f"{field.kind.value}|{field.sport.value if field.sport else ''}"


class MetricExportService:
    """Own confirmed exports and automatic Garmin measurement synchronization."""

    def __init__(
        self,
        database_manager: Callable[[], Any],
        observation_reader: Callable[[], ObservationReader],
        ports: Mapping[ProviderId, Callable[[], MetricExportPort]],
        *,
        database_lock: AbstractContextManager[Any],
        today: Callable[[], date],
        utc_now: Callable[[], datetime],
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
        links: RemoteLinkRepository | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._observation_reader = observation_reader
        self._ports = dict(ports)
        self._today = today
        self._utc_now = utc_now
        self._registry = registry
        self._links = links or RemoteLinkRepository()
        self._key_values = KeyValueRepository(lambda: self._utc_now().isoformat())
        self._export_lock = threading.Lock()

    def preview(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        raw = (payload or {}).get("provider")
        target = DEFAULT_METRIC_EXPORT_TARGET if raw is None else self._target(raw)
        port = self._port(target)
        candidates = self._candidates(target, port)
        return {
            "provider": target.value,
            "provider_label": self._registry.get(target.value).label,
            "recalc_hr_zones_available": port.supports_hr_zone_recalc,
            "items": [self._preview_item(candidate) for candidate in candidates],
        }

    def export(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._export_lock:
            return self._export(payload)

    def _export(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        target, requested, recalc = self._validated_request(payload)
        port = self._port(target)
        if recalc and not port.supports_hr_zone_recalc:
            raise AppError(
                400,
                "Das Zielsystem kann Herzfrequenzzonen nicht neu berechnen.",
                reason="invalid_metric_export",
            )
        selected = self._selected(target, port, requested)
        if recalc and not any(candidate.field.zone_recalc for candidate in selected):
            raise AppError(
                400,
                "Die Zonen-Option gilt nur für Schwellenwerte.",
                reason="invalid_metric_export",
            )
        groups: dict[str, list[_Candidate]] = {}
        for candidate in selected:
            groups.setdefault(candidate.record, []).append(candidate)
        label = self._registry.get(target.value).label
        items: list[dict[str, Any]] = []
        for group in groups.values():
            failure = self._write(
                port, group, recalc_hr_zones=recalc and group[0].field.zone_recalc
            )
            if failure is None:
                self._record(target, port, group)
            items.extend(self._group_items(group, failure, label))
        exported = sum(1 for item in items if item["status"] == EXPORTED)
        return {
            "ok": exported == len(items),
            "provider": target.value,
            "provider_label": label,
            "recalc_hr_zones": recalc,
            "exported": exported,
            "failed": len(items) - exported,
            "items": items,
        }

    def configure_automatic(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Persist explicit athlete consent for the named automatic export."""
        if (
            not isinstance(payload, Mapping)
            or payload.get("confirmed") is not True
            or payload.get("provider") != ProviderId.INTERVALS.value
            or payload.get("source") != ProviderId.GARMIN.value
            or not isinstance(payload.get("enabled"), bool)
        ):
            raise AppError(
                400,
                "Der automatische Garmin-Abgleich mit Intervals.icu muss ausdrücklich bestätigt werden.",
                reason="confirmation_required",
            )
        with (
            self._export_lock,
            self._database_lock,
            self._database_manager().unit_of_work() as db,
        ):
            self._key_values.set(
                db,
                "garmin_metric_export_enabled",
                "true" if payload["enabled"] else "false",
            )
        return {"enabled": payload["enabled"]}

    def sync_garmin(self) -> dict[str, Any] | None:
        """Apply Garmin measurements, preserving later changes at Intervals.icu.

        This internal sync entry point never accepts HTTP/Coach payloads. The
        first transfer protects unknown existing target values; later transfers compare
        the live target against the last accepted value, including across restarts.
        """
        with self._export_lock:
            with self._database_manager().reader() as db:
                if self._key_values.get(db, "garmin_metric_export_enabled") != "true":
                    return None
            target = ProviderId.INTERVALS
            port = self._port(target)
            candidates = self._candidates(
                target, port, source_provider=ProviderId.GARMIN
            )
            groups: dict[str, list[_Candidate]] = {}
            conflicts = 0
            for candidate in candidates:
                if candidate.status == UNCHANGED:
                    self._record(target, port, [candidate])
                elif candidate.status == ALREADY_EXPORTED or self._automatic_conflict(
                    target, candidate
                ):
                    conflicts += 1
                elif candidate.status == READY:
                    groups.setdefault(candidate.record, []).append(candidate)
            items: list[dict[str, Any]] = []
            for group in groups.values():
                # Re-read immediately before writing, just like the manual preview.
                try:
                    current = self._read_record(
                        target, port, group[0].field, group[0].source
                    )
                except AppError:
                    items.extend(
                        self._group_items(group, "target_unavailable", "Intervals.icu")
                    )
                    continue
                stable = [
                    item
                    for item in group
                    if _same_remote(current.get(item.field.field), item.remote)
                ]
                conflicts += len(group) - len(stable)
                if not stable:
                    continue
                failure = self._write(port, stable, recalc_hr_zones=False)
                if failure is None:
                    self._record(target, port, stable)
                items.extend(self._group_items(stable, failure, "Intervals.icu"))
            exported = sum(item["status"] == EXPORTED for item in items)
            return {
                "exported": exported,
                "failed": len(items) - exported,
                "conflicts": conflicts,
            }

    @staticmethod
    def _baseline_key(target: ProviderId, candidate: _Candidate) -> str:
        return f"metric_export_baseline:{target.value}:{candidate.remote_id}"

    def _automatic_conflict(self, target: ProviderId, candidate: _Candidate) -> bool:
        with self._database_manager().reader() as db:
            raw = self._key_values.get(db, self._baseline_key(target, candidate))
        if raw is None:
            return candidate.remote is not None
        baseline = json.loads(raw)
        return baseline["record"] == candidate.record and not _same_remote(
            candidate.remote, baseline["value"]
        )

    def _validated_request(
        self, payload: Mapping[str, Any]
    ) -> tuple[ProviderId, list[_Requested], bool]:
        if not isinstance(payload, Mapping) or payload.get("confirmed") is not True:
            raise AppError(
                400,
                "Der Export muss ausdrücklich bestätigt werden.",
                reason="confirmation_required",
            )
        raw_target = payload.get("provider")
        if raw_target is None:
            raise AppError(
                400,
                "Der Export muss das Zielsystem nennen.",
                reason="provider_required",
            )
        target = self._target(raw_target)
        requested = self._requested(payload.get("metrics"))
        recalc = payload.get("recalc_hr_zones", False)
        if not isinstance(recalc, bool):
            raise AppError(
                400, "Ungültige Zonen-Option.", reason="invalid_metric_export"
            )
        return target, requested, recalc

    def _selected(
        self,
        target: ProviderId,
        port: MetricExportPort,
        requested: Sequence[_Requested],
    ) -> list[_Candidate]:
        # Candidates are rebuilt from live target values, so a value that changed
        # at the target since the preview is never overwritten unseen.
        ready = {
            candidate.key: candidate
            for candidate in self._candidates(target, port)
            if candidate.status == READY
        }
        selected: list[_Candidate] = []
        for entry in requested:
            candidate = ready.get(entry.key)
            if (
                candidate is None
                or candidate.source.observed_on.isoformat() != entry.observed_on
                or not _same_value(candidate.value, entry.value)
                or not _same_remote(candidate.remote, entry.remote)
            ):
                raise AppError(
                    409,
                    "Die Werte haben sich seit der Vorschau geändert; nichts wurde gesendet.",
                    reason="metric_export_changed",
                )
            selected.append(candidate)
        return selected

    def _group_items(
        self, group: Sequence[_Candidate], failure: str | None, label: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for candidate in group:
            item = self._receipt_item(candidate)
            if failure is None:
                item["status"] = EXPORTED
            else:
                item["status"] = FAILED
                item["reason"] = failure
                item["error"] = f"Senden an {label} fehlgeschlagen."
            items.append(item)
        return items

    def _target(self, raw: Any) -> ProviderId:
        exporting = self._registry.ids_with(Capability.METRIC_EXPORT)
        if not isinstance(raw, str) or raw not in exporting:
            raise AppError(
                400,
                "Dieses Zielsystem unterstützt keinen Kennzahlen-Export.",
                reason="unsupported_provider",
            )
        return ProviderId(raw)

    def _port(self, target: ProviderId) -> MetricExportPort:
        factory = self._ports.get(target)
        if factory is None:
            raise AppError(
                400,
                "Dieses Zielsystem unterstützt keinen Kennzahlen-Export.",
                reason="unsupported_provider",
            )
        return factory()

    @staticmethod
    def _requested(raw: Any) -> list[_Requested]:
        invalid = AppError(
            400,
            "Die Auswahl der Kennzahlen ist ungültig.",
            reason="invalid_metric_export",
        )
        if not isinstance(raw, list) or not 1 <= len(raw) <= _MAX_REQUESTED_METRICS:
            raise invalid
        requested: list[_Requested] = []
        for entry in raw:
            if not isinstance(entry, Mapping) or "current_remote_value" not in entry:
                raise invalid
            key = entry.get("key")
            observed_on = entry.get("observed_on")
            value = entry.get("value")
            remote = entry.get("current_remote_value")
            if (
                not isinstance(key, str)
                or not isinstance(observed_on, str)
                or not _is_number(value)
                or not (remote is None or _is_number(remote))
            ):
                raise invalid
            requested.append(
                _Requested(
                    key,
                    observed_on,
                    float(value),
                    None if remote is None else float(remote),
                )
            )
        if len({entry.key for entry in requested}) != len(requested):
            raise invalid
        return requested

    def _candidates(
        self,
        target: ProviderId,
        port: MetricExportPort,
        *,
        source_provider: ProviderId | None = None,
    ) -> list[_Candidate]:
        kinds = self._registry.get(target.value).metric_exports
        start = self._today() - timedelta(days=_LOOKBACK_DAYS)
        reader = self._observation_reader()
        offered: list[tuple[str, MetricExportField, Observation, bool]] = []
        with self._database_manager().reader() as db:
            for kind in sorted(kinds, key=lambda item: item.value):
                sources = self._sources(
                    (
                        item
                        for item in reader.observations(
                            db, kind, start=start, end=self._today()
                        )
                        if source_provider is None
                        or (
                            item.provenance.provider is source_provider
                            and item.provenance.source_kind
                            in {
                                SourceKind.PROVIDER_REPORTED,
                                SourceKind.DEVICE_MEASURED,
                            }
                        )
                    ),
                    target,
                    port,
                )
                for key, (field, source) in sorted(sources.items()):
                    offered.append(
                        (
                            key,
                            field,
                            source,
                            self._exported(db, target, port, field, source),
                        )
                    )
        # Target values are read live after the database read: cached target
        # observations can be older than the target's current state.
        records: dict[str, Mapping[str, float]] = {}
        candidates: list[_Candidate] = []
        for key, field, source, exported in offered:
            record = port.remote_record(field, source.observed_on)
            if record not in records:
                records[record] = self._read_record(target, port, field, source)
            remote = records[record].get(field.field)
            if remote is not None and _same_value(
                remote, port.normalize_value(field, source.value.value)
            ):
                status = UNCHANGED
            elif exported:
                status = ALREADY_EXPORTED
            else:
                status = READY
            candidates.append(_Candidate(key, field, record, source, remote, status))
        return candidates

    @staticmethod
    def _sources(
        observations: Iterable[Observation],
        target: ProviderId,
        port: MetricExportPort,
    ) -> dict[str, tuple[MetricExportField, Observation]]:
        """Return the newest exportable value per target field."""
        sources: dict[str, tuple[MetricExportField, Observation]] = {}
        for observation in observations:
            provider = observation.provenance.provider
            # Values the target reported are never sent back; provider-less
            # values (AI estimates, athlete entries) have no verifiable origin.
            if provider is None or provider is target:
                continue
            field = port.field_for(observation.kind, observation.sport)
            if field is None:
                continue
            key = _item_key(field)
            current = sources.get(key)
            if current is None or _recency(observation) > _recency(current[1]):
                sources[key] = (field, observation)
        return sources

    def _exported(
        self,
        db: Any,
        target: ProviderId,
        port: MetricExportPort,
        field: MetricExportField,
        source: Observation,
    ) -> bool:
        """Return whether this exact value was already sent to the target field."""
        link = self._links.get(
            db,
            RemoteEntityKind.OBSERVATION,
            observation_natural_key(source),
            target.value,
        )
        remote_id = f"{port.remote_record(field, source.observed_on)}/{field.field}"
        return (
            link is not None
            and link.sync_state is RemoteLinkState.SYNCED
            and link.baseline_hash
            == _baseline(remote_id, port.normalize_value(field, source.value.value))
        )

    def _read_record(
        self,
        target: ProviderId,
        port: MetricExportPort,
        field: MetricExportField,
        source: Observation,
    ) -> Mapping[str, float]:
        try:
            return port.read_record(field, source.observed_on)
        except Exception as exc:  # noqa: BLE001 - reported safely, never raw
            _LOGGER.warning("Metric export read failed (%s)", type(exc).__name__)
            label = self._registry.get(target.value).label
            raise AppError(
                502,
                f"Die aktuellen Werte von {label} konnten nicht gelesen werden; "
                "nichts wurde gesendet.",
                reason="metric_export_remote_unavailable",
            ) from None

    @staticmethod
    def _base_item(candidate: _Candidate) -> dict[str, Any]:
        field = candidate.field
        return {
            "key": candidate.key,
            "metric": field.kind.value,
            "sport": field.sport.value if field.sport else None,
            "value": candidate.value,
            "unit": candidate.source.value.unit,
            "observed_on": candidate.source.observed_on.isoformat(),
            "target_field": field.field,
            "target_label": field.label,
            "remote_record": candidate.record,
        }

    def _preview_item(self, candidate: _Candidate) -> dict[str, Any]:
        provider = candidate.source.provenance.provider
        return {
            **self._base_item(candidate),
            "source_provider": provider.value if provider else None,
            "source_label": observation_source_label(
                candidate.source, SourceView.CURRENT_METRIC
            ),
            "current_remote_value": candidate.remote,
            "zone_recalc": candidate.field.zone_recalc,
            "status": candidate.status,
            "selectable": candidate.status == READY,
        }

    def _receipt_item(self, candidate: _Candidate) -> dict[str, Any]:
        return {
            **self._base_item(candidate),
            "previous_remote_value": candidate.remote,
        }

    @staticmethod
    def _write(
        port: MetricExportPort, group: Sequence[_Candidate], *, recalc_hr_zones: bool
    ) -> str | None:
        """Write one remote record; return a safe failure reason or None."""
        writes = [
            MetricWrite(candidate.field, candidate.value, candidate.source.observed_on)
            for candidate in group
        ]
        try:
            port.write(writes, recalc_hr_zones=recalc_hr_zones)
        except AppError as exc:
            _LOGGER.warning("Metric export failed (%s)", type(exc).__name__)
            return public_error_contract(exc)[1]
        except Exception as exc:  # noqa: BLE001 - reported per record, never raw
            _LOGGER.warning("Metric export failed (%s)", type(exc).__name__)
            return "request_failed"
        return None

    def _record(
        self, target: ProviderId, port: MetricExportPort, group: Sequence[_Candidate]
    ) -> None:
        synced_at = self._utc_now().isoformat()
        with self._database_lock, self._database_manager().unit_of_work() as db:
            for candidate in group:
                sent_value = port.normalize_value(candidate.field, candidate.value)
                self._key_values.set(
                    db,
                    self._baseline_key(target, candidate),
                    json.dumps({"record": candidate.record, "value": sent_value}),
                )
                local_id = observation_natural_key(candidate.source)
                # A field holds one value, so a newer export takes over its link.
                holder = self._links.get_by_remote_id(
                    db, RemoteEntityKind.OBSERVATION, target.value, candidate.remote_id
                )
                if holder is not None and holder.local_id != local_id:
                    self._links.delete(
                        db, RemoteEntityKind.OBSERVATION, holder.local_id, target.value
                    )
                self._links.upsert(
                    db,
                    RemoteLink(
                        entity_kind=RemoteEntityKind.OBSERVATION,
                        local_id=local_id,
                        provider=target.value,
                        sync_state=RemoteLinkState.SYNCED,
                        remote_id=candidate.remote_id,
                        baseline_hash=_baseline(candidate.remote_id, sent_value),
                        last_synced_at=synced_at,
                    ),
                )
