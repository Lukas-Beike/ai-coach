"""Resume history backfill chains that stopped before the history floor.

Each backfill chain walks its own sync-state cursor back to the floor, one chunk
per job. A failed or partial chunk, an exhausted retry budget or a provider
connected while the app runs ends the chain without moving the cursor to the
floor. The startup scheduler resumes such a chain at the next process start; this
module resumes it while the app keeps running, from the scheduler's periodic
pass and from the moment a provider is connected.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any, Final

from backend.athlete.local_date import iso_date_prefix
from backend.sync.jobs import BACKFILL_CURSOR_STREAMS
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.provider_runtime import ProviderSchedulePolicy
from backend.sync.queue import SyncJobQueueService
from backend.sync.state import SyncStateRepository

# A chain without an active job is queued again at most this often.
RESUME_INTERVAL: Final = timedelta(hours=6)
SCHEDULER_REQUESTER: Final = "scheduler"


def historical_backfill_payload(
    sync_state: SyncStateRepository,
    provider: str,
    job_type: str,
    *,
    chunk_days: int,
    earliest_date: date,
    reason: str,
) -> dict[str, Any] | None:
    """Return the payload that resumes a chain below its cursor, or None at the floor."""
    stream = BACKFILL_CURSOR_STREAMS[job_type]
    cursor = sync_state.cursor(provider, stream).get("cursor")
    if cursor and str(cursor) <= earliest_date.isoformat():
        return None
    try:
        resume_end = (
            date.fromisoformat(iso_date_prefix(str(cursor))) - timedelta(days=1)
            if cursor
            else None
        )
    except ValueError:
        resume_end = None
    payload: dict[str, Any] = {"days": chunk_days, "reason": reason}
    if resume_end is not None:
        payload["end_date"] = resume_end.isoformat()
    return payload


class BackfillChainResumer:
    """Queue every configured backfill chain that has no active job."""

    def __init__(
        self,
        queue: SyncJobQueueService,
        sync_state: SyncStateRepository,
        policies: Mapping[str, ProviderSchedulePolicy],
        *,
        chunk_days: int,
        earliest_date: date,
        registry: ProviderRegistry | None = None,
        interval: timedelta = RESUME_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._queue = queue
        self._sync_state = sync_state
        self._policies = policies
        self._chunk_days = chunk_days
        self._earliest_date = earliest_date
        self._registry = DEFAULT_PROVIDER_REGISTRY if registry is None else registry
        self._interval = interval.total_seconds()
        self._clock = clock
        self._last_queued: dict[tuple[str, str], float] = {}

    def resume(self) -> None:
        """Re-queue stopped chains of all providers, each at most once per interval."""
        for provider_id in self._registry.startup_order():
            policy = self._policies.get(provider_id)
            if policy is not None and policy.configured() and not policy.blocked():
                self._queue_chains(provider_id, requested_by=SCHEDULER_REQUESTER)

    def resume_provider(self, provider_id: str, *, requested_by: str) -> None:
        """Queue one provider's chains now, as soon as the athlete connected it."""
        policy = self._policies.get(provider_id)
        if policy is not None and policy.configured():
            self._queue_chains(provider_id, requested_by=requested_by, throttle=False)

    def _queue_chains(
        self, provider_id: str, *, requested_by: str, throttle: bool = True
    ) -> None:
        for job_type in BACKFILL_CURSOR_STREAMS:
            if not self._registry.supports_job(provider_id, job_type):
                continue
            key = (provider_id, job_type)
            last = self._last_queued.get(key)
            if throttle and last is not None and self._clock() - last < self._interval:
                continue
            if self._queue.active(provider_id, job_type):
                continue
            payload = historical_backfill_payload(
                self._sync_state,
                provider_id,
                job_type,
                chunk_days=self._chunk_days,
                earliest_date=self._earliest_date,
                reason=f"resumed {job_type.replace('_', ' ')}",
            )
            if payload is None:
                continue
            self._queue.enqueue(
                provider_id, job_type, payload, requested_by=requested_by
            )
            self._last_queued[key] = self._clock()
