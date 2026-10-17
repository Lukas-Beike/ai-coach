"""Explicit, previewed export of canonical body and threshold metrics.

The preview lists, per target field, the newest local value that another
provider supplied, next to the value the target last reported. Execute writes
only what a confirmed request names: the target provider and every metric with
the exact day and value of the preview. A value the target itself reported is
never sent back to it; only values another provider reported are offered, so
AI estimates are never exported. Each written field is recorded in
``remote_links`` so the same value is not offered again.
"""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final

from backend.canonical.records import Observation
from backend.canonical.vocabulary import (
    ProviderId,
    RemoteEntityKind,
    RemoteLinkState,
)
from backend.db.canonical_store import observation_natural_key
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
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
REMOTE_NEWER = "remote_newer"
EXPORTED = "exported"
FAILED = "failed"


@dataclass(frozen=True, slots=True)
class _Candidate:
    key: str
    field: MetricExportField
    record: str
    source: Observation
    remote: Observation | None
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


def _baseline(remote_id: str, value: float) -> str:
    return hashlib.sha256(f"{remote_id}={value!r}".encode()).hexdigest()


def _item_key(field: MetricExportField) -> str:
    return f"{field.kind.value}|{field.sport.value if field.sport else ''}"


class MetricExportService:
    """Preview and execute confirmed metric exports to one provider."""

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
        target, requested, recalc = self._validated_request(payload)
        port = self._port(target)
        if recalc and not port.supports_hr_zone_recalc:
            raise AppError(
                400,
                "Das Zielsystem kann Herzfrequenzzonen nicht neu berechnen.",
                reason="invalid_metric_export",
            )
        selected = self._selected(target, port, requested)
        groups: dict[str, list[_Candidate]] = {}
        for candidate in selected:
            groups.setdefault(candidate.record, []).append(candidate)
        label = self._registry.get(target.value).label
        items: list[dict[str, Any]] = []
        for group in groups.values():
            failure = self._write(port, group, recalc_hr_zones=recalc)
            if failure is None:
                self._record(target, group)
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

    def _validated_request(
        self, payload: Mapping[str, Any]
    ) -> tuple[ProviderId, list[tuple[str, str, float]], bool]:
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
        requested: Sequence[tuple[str, str, float]],
    ) -> list[_Candidate]:
        ready = {
            candidate.key: candidate
            for candidate in self._candidates(target, port)
            if candidate.status == READY
        }
        selected: list[_Candidate] = []
        for key, observed_on, value in requested:
            candidate = ready.get(key)
            if (
                candidate is None
                or candidate.source.observed_on.isoformat() != observed_on
                or not _same_value(candidate.value, value)
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
    def _requested(raw: Any) -> list[tuple[str, str, float]]:
        invalid = AppError(
            400,
            "Die Auswahl der Kennzahlen ist ungültig.",
            reason="invalid_metric_export",
        )
        if not isinstance(raw, list) or not 1 <= len(raw) <= _MAX_REQUESTED_METRICS:
            raise invalid
        requested: list[tuple[str, str, float]] = []
        for entry in raw:
            if not isinstance(entry, Mapping):
                raise invalid
            key = entry.get("key")
            observed_on = entry.get("observed_on")
            value = entry.get("value")
            if (
                not isinstance(key, str)
                or not isinstance(observed_on, str)
                or isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
            ):
                raise invalid
            requested.append((key, observed_on, float(value)))
        if len({key for key, _, _ in requested}) != len(requested):
            raise invalid
        return requested

    def _candidates(
        self, target: ProviderId, port: MetricExportPort
    ) -> list[_Candidate]:
        kinds = self._registry.get(target.value).metric_exports
        start = self._today() - timedelta(days=_LOOKBACK_DAYS)
        reader = self._observation_reader()
        candidates: list[_Candidate] = []
        with self._database_manager().reader() as db:
            for kind in sorted(kinds, key=lambda item: item.value):
                sources, remotes = self._partition(
                    reader.observations(db, kind, start=start), target, port
                )
                for key, (field, source) in sorted(sources.items()):
                    candidates.append(
                        self._candidate(
                            db, target, port, key, field, source, remotes.get(key, [])
                        )
                    )
        return candidates

    @staticmethod
    def _partition(
        observations: Iterable[Observation],
        target: ProviderId,
        port: MetricExportPort,
    ) -> tuple[
        dict[str, tuple[MetricExportField, Observation]], dict[str, list[Observation]]
    ]:
        """Split observations into the newest export source and target values."""
        sources: dict[str, tuple[MetricExportField, Observation]] = {}
        remotes: dict[str, list[Observation]] = {}
        for observation in observations:
            field = port.field_for(observation.kind, observation.sport)
            if field is None:
                continue
            key = _item_key(field)
            provider = observation.provenance.provider
            if provider is target:
                remotes.setdefault(key, []).append(observation)
            elif provider is not None:
                # Provider-less values (AI estimates, athlete entries)
                # have no verifiable origin and are not offered.
                current = sources.get(key)
                if current is None or _recency(observation) > _recency(current[1]):
                    sources[key] = (field, observation)
        return sources, remotes

    def _candidate(
        self,
        db: Any,
        target: ProviderId,
        port: MetricExportPort,
        key: str,
        field: MetricExportField,
        source: Observation,
        remotes: Sequence[Observation],
    ) -> _Candidate:
        # A dated field compares with the target's value of the same day; a
        # setting compares with the target's newest value.
        matching = [
            remote
            for remote in remotes
            if not field.dated or remote.observed_on == source.observed_on
        ]
        remote = max(matching, key=_recency) if matching else None
        record = port.remote_record(field, source.observed_on)
        candidate = _Candidate(key, field, record, source, remote, READY)
        link = self._links.get(
            db,
            RemoteEntityKind.OBSERVATION,
            observation_natural_key(source),
            target.value,
        )
        if remote is not None and _same_value(remote.value.value, source.value.value):
            status = UNCHANGED
        elif (
            link is not None
            and link.sync_state is RemoteLinkState.SYNCED
            and link.baseline_hash == _baseline(candidate.remote_id, candidate.value)
        ):
            status = ALREADY_EXPORTED
        elif (
            remote is not None
            and not field.dated
            and remote.observed_on > source.observed_on
        ):
            status = REMOTE_NEWER
        else:
            return candidate
        return _Candidate(key, field, record, source, remote, status)

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
        remote = candidate.remote
        provider = candidate.source.provenance.provider
        return {
            **self._base_item(candidate),
            "source_provider": provider.value if provider else None,
            "source_label": observation_source_label(
                candidate.source, SourceView.CURRENT_METRIC
            ),
            "current_remote_value": remote.value.value if remote else None,
            "current_remote_observed_on": (
                remote.observed_on.isoformat() if remote else None
            ),
            "status": candidate.status,
            "selectable": candidate.status == READY,
        }

    def _receipt_item(self, candidate: _Candidate) -> dict[str, Any]:
        remote = candidate.remote
        return {
            **self._base_item(candidate),
            "previous_remote_value": remote.value.value if remote else None,
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

    def _record(self, target: ProviderId, group: Sequence[_Candidate]) -> None:
        synced_at = self._utc_now().isoformat()
        with self._database_lock, self._database_manager().unit_of_work() as db:
            for candidate in group:
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
                        baseline_hash=_baseline(candidate.remote_id, candidate.value),
                        last_synced_at=synced_at,
                    ),
                )
