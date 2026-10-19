"""Read-only import of full-resolution FIT detail for Wahoo workouts.

After a Wahoo sync, each workout of the window with a download link and an
active activity record is fetched once per summary hash. Its FIT file is mapped
with Wahoo provenance and stored as stream, lap and zone sets. Failed and empty
downloads are counted per summary hash and stop after a bounded number of
attempts. The download link is never stored, logged or returned, and nothing is
written to Wahoo.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityRecordState,
    ProviderId,
    RecordingOrigin,
    SourceKind,
)
from backend.db.activity_detail_store import (
    StoredDetailSet,
    detail_sets_for,
    replace_detail_set,
)
from backend.db.canonical_store import (
    active_provider_record_hash,
    activity_record_link,
)
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.providers.descriptors import WAHOO_ID
from backend.providers.fit_activity_detail_mapping import (
    MAPPER_VERSION,
    map_fit_activity_detail,
)
from backend.providers.wahoo_activity_mapping import WAHOO_LABEL, wahoo_workout_id
from backend.providers.wahoo_fit_download import WahooFitUnavailable, wahoo_fit_url

STATE_KEY: Final = "wahoo_activity_detail_state"
MAX_DETAIL_ATTEMPTS: Final = 3
MAX_DETAIL_DOWNLOADS_PER_RUN: Final = 10
DETAIL_IMPORT_BUDGET_SECONDS: Final = 120

_RATE_LIMITED: Final = "rate_limited"


@dataclass(frozen=True, slots=True)
class _Pending:
    """One workout whose current FIT file still has to be imported."""

    workout_id: str
    url: str
    summary_sha256: str
    attempts: int


class WahooActivityDetailImport:
    """Download, map and store the FIT detail of the workouts of one sync run."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], DatabaseManager],
        database_lock: AbstractContextManager[Any],
        key_values: KeyValueRepository,
        download: Callable[[str], bytes],
        monotonic: Callable[[], float],
        logger: logging.Logger,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._download = download
        self._monotonic = monotonic
        self._logger = logger

    def import_details(
        self, workouts: Sequence[object], *, retrieved_at: datetime
    ) -> dict[str, Any]:
        """Import detail for the given workouts, newest first; never raises for data."""
        if retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        started = self._monotonic()
        loaded = self._load_state()
        current_ids = _ids(workouts)
        state = {key: value for key, value in loaded.items() if key in current_ids}
        counts = {"stored": 0, "failed": 0, "skipped": 0, "empty": 0}
        issues = 0
        downloads = 0
        status = "ok"
        seen: set[str] = set()
        for row in workouts:
            pending = self._pending(row, state, seen)
            if pending is None:
                counts["skipped"] += 1
                continue
            if downloads >= MAX_DETAIL_DOWNLOADS_PER_RUN:
                break
            if self._monotonic() - started >= DETAIL_IMPORT_BUDGET_SECONDS:
                status = "budget"
                break
            downloads += 1
            outcome, found = self._import_one(pending, state, retrieved_at)
            issues += found
            if outcome == _RATE_LIMITED:
                status = _RATE_LIMITED
                break
            counts[outcome] += 1
        if state != loaded:
            self._save_state(state)
        self._logger.info(
            "Wahoo activity detail import finished",
            extra={
                "event": "wahoo_activity_detail_import",
                "context": {
                    **counts,
                    "status": status,
                    "downloads": downloads,
                    "issues": issues,
                },
            },
        )
        return {"status": status, **counts}

    def _pending(
        self, row: object, state: dict[str, dict[str, Any]], seen: set[str]
    ) -> _Pending | None:
        """Return the download a workout still needs, or None when it is skipped."""
        candidate = _candidate(row)
        if candidate is None or candidate[0] in seen:
            return None
        workout_id, url = candidate
        seen.add(workout_id)
        with self._database_manager().reader() as db:
            link = activity_record_link(db, WAHOO_ID, workout_id)
            summary_sha256 = active_provider_record_hash(
                db, WAHOO_ID, ACTIVITY_RECORD_KIND, workout_id
            )
            stored = detail_sets_for(db, WAHOO_ID, workout_id)
        if (
            link is None
            or link["state"] != ActivityRecordState.ACTIVE.value
            or summary_sha256 is None
            or _already_stored(stored, summary_sha256)
        ):
            return None
        entry = state.get(workout_id)
        if entry is None or entry["summary_sha256"] != summary_sha256:
            return _Pending(workout_id, url, summary_sha256, 0)
        if entry["empty"] or entry["attempts"] >= MAX_DETAIL_ATTEMPTS:
            return None
        return _Pending(workout_id, url, summary_sha256, entry["attempts"])

    def _import_one(
        self,
        pending: _Pending,
        state: dict[str, dict[str, Any]],
        retrieved_at: datetime,
    ) -> tuple[str, int]:
        """Download, map and store one workout; return its outcome and issue count."""
        workout_id = pending.workout_id
        try:
            data = self._download(pending.url)
        except WahooFitUnavailable as error:
            self._log_failure(error.reason)
            if error.reason == _RATE_LIMITED:
                return _RATE_LIMITED, 0
            state[workout_id] = _entry(
                pending.summary_sha256, pending.attempts + 1, empty=False
            )
            return "failed", 0
        mapped = map_fit_activity_detail(
            data,
            provider_activity_id=workout_id,
            provenance=_provenance(workout_id, retrieved_at),
        )
        found = len(mapped.issues)
        if mapped.records:
            if not self._store(
                workout_id, pending.summary_sha256, mapped.records, retrieved_at
            ):
                return "skipped", found
            state.pop(workout_id, None)
            return "stored", found
        if mapped.issues:
            state[workout_id] = _entry(
                pending.summary_sha256, pending.attempts + 1, empty=False
            )
            self._log_failure("no_records")
            return "failed", found
        state[workout_id] = _entry(pending.summary_sha256, 0, empty=True)
        return "empty", found

    def _store(
        self,
        workout_id: str,
        summary_sha256: str,
        records: Sequence[Any],
        retrieved_at: datetime,
    ) -> bool:
        """Store the sets in one transaction, but only if the record is still current."""
        with self._database_lock, self._database_manager().unit_of_work() as db:
            link = activity_record_link(db, WAHOO_ID, workout_id)
            if link is None or link["state"] != ActivityRecordState.ACTIVE.value:
                return False
            current = active_provider_record_hash(
                db, WAHOO_ID, ACTIVITY_RECORD_KIND, workout_id
            )
            if current != summary_sha256:
                return False
            for item in records:
                replace_detail_set(
                    db,
                    item,
                    mapper_version=MAPPER_VERSION,
                    summary_sha256=summary_sha256,
                    now=retrieved_at.isoformat(),
                )
        return True

    def _load_state(self) -> dict[str, dict[str, Any]]:
        with self._database_manager().reader() as db:
            text = self._key_values.get(db, STATE_KEY)
        return _parse_state(text)

    def _save_state(self, state: dict[str, dict[str, Any]]) -> None:
        text = json.dumps(state, sort_keys=True, separators=(",", ":"))
        with self._database_lock, self._database_manager().unit_of_work() as db:
            self._key_values.set(db, STATE_KEY, text)

    def _log_failure(self, reason: str) -> None:
        self._logger.warning(
            "Wahoo activity detail could not be imported",
            extra={
                "event": "wahoo_activity_detail_failed",
                "context": {"reason": reason},
            },
        )


def _ids(workouts: Sequence[object]) -> set[str]:
    ids: set[str] = set()
    for row in workouts:
        if isinstance(row, dict):
            workout_id = wahoo_workout_id(row)
            if workout_id is not None:
                ids.add(workout_id)
    return ids


def _candidate(row: object) -> tuple[str, str] | None:
    """Return the workout id and its download link, or None when either is missing."""
    if not isinstance(row, dict):
        return None
    workout_id = wahoo_workout_id(row)
    url = wahoo_fit_url(row.get("workout_summary"))
    if workout_id is None or not url:
        return None
    return workout_id, url


def _already_stored(stored: list[StoredDetailSet], summary_sha256: str) -> bool:
    """Return whether the current file was stored; one download gives every kind.

    A set of a kind the current file lacks keeps its older hash, so any current
    set means the current summary was already imported.
    """
    return any(
        item.summary_sha256 == summary_sha256 and item.mapper_version == MAPPER_VERSION
        for item in stored
    )


def _entry(summary_sha256: str, attempts: int, *, empty: bool) -> dict[str, Any]:
    return {"summary_sha256": summary_sha256, "attempts": attempts, "empty": empty}


def _provenance(workout_id: str, retrieved_at: datetime) -> Provenance:
    return Provenance(
        provider=ProviderId.WAHOO,
        source_kind=SourceKind.DEVICE_MEASURED,
        source_record_id=workout_id,
        recorded_by=RecordingOrigin.WAHOO,
        retrieved_at=retrieved_at,
        label=WAHOO_LABEL,
    )


def _parse_state(text: str | None) -> dict[str, dict[str, Any]]:
    """Return the valid entries of the stored state; malformed entries are dropped."""
    if text is None:
        return {}
    try:
        raw = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(raw, dict):
        return {}
    state: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        digest = value.get("summary_sha256")
        attempts = value.get("attempts")
        empty = value.get("empty")
        if (
            isinstance(digest, str)
            and isinstance(attempts, int)
            and not isinstance(attempts, bool)
            and isinstance(empty, bool)
        ):
            state[key] = {
                "summary_sha256": digest,
                "attempts": attempts,
                "empty": empty,
            }
    return state
