"""Automatic export of canonical body and threshold metrics.

Each sent field is recorded in ``remote_links`` so the same value is not offered
again, and each written record in the change history (no undo: the write is
remote). Entries an earlier release recorded for a manual export stay readable.

Thresholds (FTP, threshold and maximum heart rate, threshold pace) are the current
resolved values of ``thresholds``: the local zone configuration, else Garmin, else
Wahoo (#1729). Body metrics are the newest value another provider reported. A
value the target itself reported is never sent back to it, and AI estimates are
never exported.

``sync_automatic`` sends only the consented fields. For
thresholds the resolved value wins: a different target value is overwritten, and
heart-rate thresholds are written with the target's zone recalculation. Body
metrics come from Garmin measurements only, and durable comparison baselines
protect existing and later target-side edits.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Final

from backend.canonical.records import Observation
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RemoteEntityKind,
    RemoteLinkState,
    SourceKind,
    Sport,
)
from backend.change_history import METRIC_EXPORT_ENTITY, record_change
from backend.db.canonical_store import observation_natural_key
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError, public_error_contract
from backend.runtime.ports import ObservationReader
from backend.sync.metric_export_consent import (
    DEFAULT_FIELDS,
    EXPORT_FIELDS,
    consent_key,
    enabled_fields,
    fields_view,
    store_fields,
)
from backend.sync.metric_export_port import (
    MetricExportField,
    MetricExportPort,
    MetricWrite,
)
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY

_LOGGER = logging.getLogger("intervals_coach")

# The current resolved thresholds per (metric, sport), read inside a unit of work.
type ThresholdSource = Callable[[Any], Mapping[tuple[MetricKind, Sport], Observation]]

STATUS_KEY: Final = "last_garmin_metric_export_status"
# Heart-rate settings make the target recalculate its heart-rate zones.
_HR_ZONE_KINDS: Final = frozenset({MetricKind.THRESHOLD_HR, MetricKind.MAX_HR})

# Older values are stale for a current setting and are not offered.
_LOOKBACK_DAYS: Final = 90

READY = "ready"
UNCHANGED = "unchanged"
ALREADY_EXPORTED = "already_exported"
EXPORTED = "exported"
FAILED = "failed"


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


def _same_remote(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return _same_value(left, right)


def _baseline(remote_id: str, value: float) -> str:
    return hashlib.sha256(f"{remote_id}={value!r}".encode()).hexdigest()


def _item_key(field: MetricExportField) -> str:
    return f"{field.kind.value}|{field.sport.value if field.sport else ''}"


def _consent(candidate: _Candidate) -> str:
    return consent_key(candidate.field.kind, candidate.field.sport)


def automatic_export_message(receipt: Mapping[str, int]) -> str:
    """Return the athlete-facing status line of one automatic export."""
    return (
        f"Intervals.icu: {receipt['exported']} Werte gesendet, "
        f"{receipt['conflicts']} Konflikte, {receipt['failed']} fehlgeschlagen."
    )


class MetricExportService:
    """Own the automatic Garmin measurement export and its stored consent."""

    def __init__(
        self,
        database_manager: Callable[[], Any],
        observation_reader: Callable[[], ObservationReader],
        ports: Mapping[ProviderId, Callable[[], MetricExportPort]],
        *,
        thresholds: ThresholdSource,
        database_lock: AbstractContextManager[Any],
        today: Callable[[], date],
        utc_now: Callable[[], datetime],
        links: RemoteLinkRepository | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._observation_reader = observation_reader
        self._thresholds = thresholds
        self._ports = dict(ports)
        self._today = today
        self._utc_now = utc_now
        self._links = links or RemoteLinkRepository()
        self._key_values = KeyValueRepository(lambda: self._utc_now().isoformat())
        self._export_lock = threading.Lock()

    def configure_automatic(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Persist explicit athlete consent for the named automatic export.

        ``fields`` names the consented fields (``EXPORT_FIELDS`` keys); ``field``
        with ``field_enabled`` changes one field against the stored consent, so a
        stale page never reverts another change. Enabling without either keeps
        the current fields, or starts with ``DEFAULT_FIELDS``; disabling revokes
        every field. The receipt lists each changed field.
        """
        if (
            not isinstance(payload, Mapping)
            or payload.get("confirmed") is not True
            or payload.get("provider") != ProviderId.INTERVALS.value
            or payload.get("source") != ProviderId.GARMIN.value
            or not isinstance(payload.get("enabled"), bool)
        ):
            raise AppError(
                400,
                "Der automatische Abgleich mit Intervals.icu muss ausdrücklich bestätigt werden.",
                reason="confirmation_required",
            )
        requested = self._requested_fields(payload)
        change = self._field_change(payload)
        with (
            self._export_lock,
            self._database_lock,
            self._database_manager().unit_of_work() as db,
        ):
            before = enabled_fields(lambda key: self._key_values.get(db, key))
            if not payload["enabled"]:
                after: frozenset[str] = frozenset()
            elif requested is not None:
                after = requested
            elif change is not None:
                key, enabled = change
                after = before | {key} if enabled else before - {key}
            else:
                after = before or DEFAULT_FIELDS
            store_fields(lambda key, value: self._key_values.set(db, key, value), after)
        return {
            "enabled": bool(after),
            "fields": fields_view(after),
            "changes": [
                item
                for item in fields_view(after)
                if (item["key"] in before) != item["enabled"]
            ],
        }

    @staticmethod
    def _field_change(payload: Mapping[str, Any]) -> tuple[str, bool] | None:
        key = payload.get("field")
        if key is None:
            return None
        enabled = payload.get("field_enabled")
        if (
            not isinstance(key, str)
            or key not in EXPORT_FIELDS
            or not isinstance(enabled, bool)
            or "fields" in payload
        ):
            raise AppError(
                400,
                "Die Auswahl der Werte ist ungültig.",
                reason="invalid_metric_export",
            )
        return key, enabled

    @staticmethod
    def _requested_fields(payload: Mapping[str, Any]) -> frozenset[str] | None:
        raw = payload.get("fields")
        if raw is None:
            return None
        if (
            not isinstance(raw, list)
            or not raw
            or any(
                not isinstance(item, str) or item not in EXPORT_FIELDS for item in raw
            )
        ):
            raise AppError(
                400,
                "Die Auswahl der Werte ist ungültig.",
                reason="invalid_metric_export",
            )
        return frozenset(raw)

    def sync_automatic(self) -> dict[str, Any] | None:
        """Send the consented fields' new values to Intervals.icu.

        This internal entry point never accepts HTTP/Coach payloads; a Garmin sync,
        a local zone change and a Wahoo sync start it. Thresholds send the
        resolved value over a different target value. Body metrics send Garmin
        measurements only: the first transfer protects unknown existing target
        values, later transfers compare the live target against the last accepted
        value, including across restarts.
        """
        with self._export_lock:
            with self._database_manager().reader() as db:
                consented = enabled_fields(lambda key: self._key_values.get(db, key))
            if not consented:
                return None
            target = ProviderId.INTERVALS
            port = self._port(target)
            groups, conflicts = self._automatic_groups(
                target, port, self._candidates(target, port, consented=consented)
            )
            items: list[dict[str, Any]] = []
            for group in groups.values():
                # Re-read the target immediately before writing.
                try:
                    current = self._read_record(
                        target, port, group[0].field, group[0].source
                    )
                except AppError:
                    items.extend(
                        self._group_items(group, "target_unavailable", "Intervals.icu")
                    )
                    continue
                stable, changed = self._still_writable(target, port, group, current)
                conflicts += changed
                if stable:
                    items.extend(self._automatic_write(target, port, stable))
            exported = sum(item["status"] == EXPORTED for item in items)
            return {
                "exported": exported,
                "failed": len(items) - exported,
                "conflicts": conflicts,
            }

    def _automatic_groups(
        self,
        target: ProviderId,
        port: MetricExportPort,
        candidates: Sequence[_Candidate],
    ) -> tuple[dict[str, list[_Candidate]], int]:
        """Group the values to write per remote record; count wellness conflicts.

        An unchanged value only records its baseline. Thresholds are always
        written; a wellness value waits while its target changed independently.
        """
        groups: dict[str, list[_Candidate]] = {}
        conflicts = 0
        for candidate in candidates:
            if candidate.status == UNCHANGED:
                self._record(target, port, [candidate])
            elif not candidate.field.dated:
                groups.setdefault(candidate.record, []).append(candidate)
            elif candidate.status == ALREADY_EXPORTED or self._automatic_conflict(
                target, candidate
            ):
                conflicts += 1
            elif candidate.status == READY:
                groups.setdefault(candidate.record, []).append(candidate)
        return groups, conflicts

    def _still_writable(
        self,
        target: ProviderId,
        port: MetricExportPort,
        group: Sequence[_Candidate],
        current: Mapping[str, float],
    ) -> tuple[list[_Candidate], int]:
        """Return the group's values to write after the re-read, and new conflicts.

        A threshold carries the re-read value as its previous value; one that
        already matches records its baseline instead. A wellness value whose
        target changed since the first read is a conflict.
        """
        stable: list[_Candidate] = []
        conflicts = 0
        for item in group:
            live = current.get(item.field.field)
            if item.field.dated:
                if _same_remote(live, item.remote):
                    stable.append(item)
                else:
                    conflicts += 1
                continue
            fresh = replace(item, remote=live)
            if live is not None and _same_value(
                live, port.normalize_value(item.field, item.value)
            ):
                self._record(target, port, [fresh])
            else:
                stable.append(fresh)
        return stable, conflicts

    def _automatic_write(
        self, target: ProviderId, port: MetricExportPort, stable: Sequence[_Candidate]
    ) -> list[dict[str, Any]]:
        """Write one record; heart-rate thresholds recalculate the target zones."""
        recalc = port.supports_hr_zone_recalc and any(
            item.field.kind in _HR_ZONE_KINDS for item in stable
        )
        failure = self._write(port, stable, recalc_hr_zones=recalc)
        if failure is None:
            self._record(target, port, stable, history="automatic")
        return self._group_items(stable, failure, "Intervals.icu")

    def record_status(self, message: str) -> None:
        """Store the athlete-facing status line of the last automatic export."""
        with self._database_lock, self._database_manager().unit_of_work() as db:
            self._key_values.set(
                db, STATUS_KEY, f"{self._utc_now().isoformat()}: {message}"
            )

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

    def _port(self, target: ProviderId) -> MetricExportPort:
        factory = self._ports.get(target)
        if factory is None:
            raise AppError(
                400,
                "Dieses Zielsystem unterstützt keinen Kennzahlen-Export.",
                reason="unsupported_provider",
            )
        return factory()

    def _candidates(
        self,
        target: ProviderId,
        port: MetricExportPort,
        *,
        consented: frozenset[str] | None = None,
    ) -> list[_Candidate]:
        """Return the body-metric and threshold candidates with their live status.

        ``consented`` (automatic runs) keeps only those fields, so only their
        records are read, and offers Garmin measurements only for body metrics.
        """
        automatic = consented is not None
        kinds = DEFAULT_PROVIDER_REGISTRY.get(target.value).metric_exports
        start = self._today() - timedelta(days=_LOOKBACK_DAYS)
        reader = self._observation_reader()
        offered: list[tuple[str, MetricExportField, Observation, bool]] = []
        with self._database_manager().reader() as db:
            sources: dict[str, tuple[MetricExportField, Observation]] = {}
            for kind in sorted(kinds, key=lambda item: item.value):
                sources |= self._sources(
                    (
                        item
                        for item in reader.observations(
                            db, kind, start=start, end=self._today()
                        )
                        if not automatic
                        or (
                            item.provenance.provider is ProviderId.GARMIN
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
            sources |= self._threshold_sources(db, kinds, target, port)
            for key, (field, source) in sorted(sources.items()):
                if (
                    consented is not None
                    and consent_key(field.kind, field.sport) not in consented
                ):
                    continue
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

    def _threshold_sources(
        self,
        db: Any,
        kinds: frozenset[MetricKind],
        target: ProviderId,
        port: MetricExportPort,
    ) -> dict[str, tuple[MetricExportField, Observation]]:
        """Return the resolved threshold per target setting; the target's own never."""
        sources: dict[str, tuple[MetricExportField, Observation]] = {}
        for (kind, sport), observation in self._thresholds(db).items():
            if (
                kind not in kinds
                or observation.provenance.provider is target
                or observation.provenance.source_kind is SourceKind.AI_ESTIMATE
            ):
                continue
            field = port.field_for(kind, sport)
            if field is not None and not field.dated:
                sources[_item_key(field)] = (field, observation)
        return sources

    @staticmethod
    def _sources(
        observations: Iterable[Observation],
        target: ProviderId,
        port: MetricExportPort,
    ) -> dict[str, tuple[MetricExportField, Observation]]:
        """Return the newest exportable body metric per target field."""
        sources: dict[str, tuple[MetricExportField, Observation]] = {}
        for observation in observations:
            provider = observation.provenance.provider
            # Values the target reported are never sent back; provider-less
            # values (AI estimates, athlete entries) have no verifiable origin.
            if provider is None or provider is target:
                continue
            field = port.field_for(observation.kind, observation.sport)
            # Thresholds come from the resolver (``_threshold_sources``).
            if field is None or not field.dated:
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
            label = DEFAULT_PROVIDER_REGISTRY.get(target.value).label
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
        self,
        target: ProviderId,
        port: MetricExportPort,
        group: Sequence[_Candidate],
        *,
        history: str | None = None,
    ) -> None:
        """Persist the accepted values; ``history`` names a write's change source."""
        synced_at = self._utc_now().isoformat()
        with self._database_lock, self._database_manager().unit_of_work() as db:
            if history is not None:
                record_change(
                    db,
                    METRIC_EXPORT_ENTITY,
                    f"{target.value}:{group[0].record}",
                    "update",
                    {_consent(item): item.remote for item in group},
                    {
                        _consent(item): port.normalize_value(item.field, item.value)
                        for item in group
                    },
                    source=history,
                )
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
