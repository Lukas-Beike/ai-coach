"""Light Garmin change check through the Personal API (#2303).

With a Personal API key the automatic Garmin refresh no longer runs every hour.
The daily loop asks this check instead: every 10 minutes by day and every 30
minutes at night (athlete-local time) it reads the newest activity ids and,
until last night is stored, today's sleep entry, and compares them read-only
with the local database. Only a new activity or a newly published night makes
the existing refresh due. A full refresh is still guaranteed once per local
day, at the latest at noon, for the data only the SDK serves.

An unchanged check writes nothing and queues nothing. A change that a later
successful refresh still did not store is not reported again, so data the
refresh never keeps cannot queue a refresh on every check. Throttling and errors
back off in memory; a ``Retry-After`` wait is never undercut. A rejected key
makes the refresh due once, so its failure surfaces and the retry hold stops
the schedule until the credentials change. The cadence state and the counts
live in memory: a restart checks at once.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from typing import Any

from backend.performance.morning_battery_service import MORNING_SLEEP_WAIT_UNTIL_HOUR
from backend.providers import http as provider_http
from backend.providers.garmin_morning import has_night
from backend.providers.garmin_personal import GarminPersonalClient

NIGHT_START_HOUR = 23
NIGHT_END_HOUR = 5
DAY_CHECK_SECONDS = 10 * 60
NIGHT_CHECK_SECONDS = 30 * 60
# Repeated failures double the cadence up to this factor.
MAX_BACKOFF_FACTOR = 8
# The full refresh of a local day is due from this hour without a change.
DAILY_REFRESH_HOUR = MORNING_SLEEP_WAIT_UNTIL_HOUR
# Stored activities compared with the newest page: today and yesterday.
ACTIVITY_DAYS = 2


def check_seconds(local: datetime) -> int:
    """The cadence at this athlete-local time."""
    night = local.hour >= NIGHT_START_HOUR or local.hour < NIGHT_END_HOUR
    return NIGHT_CHECK_SECONDS if night else DAY_CHECK_SECONDS


class GarminChangeCheck:
    """Decide whether the automatic Garmin refresh is due."""

    def __init__(
        self,
        *,
        personal: Callable[[], GarminPersonalClient | None],
        known_activity_ids: Callable[[int], Iterable[str]],
        stored_sleep: Callable[[date], Any],
        last_refresh: Callable[[], datetime | None],
        local_now: Callable[[], datetime],
        logger: logging.Logger,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._personal = personal
        self._known_activity_ids = known_activity_ids
        self._stored_sleep = stored_sleep
        self._last_refresh = last_refresh
        self._local_now = local_now
        self._logger = logger
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._next_check_at: float | None = None
        self._failures = 0
        # The changes the last due answer named, and when; what a later
        # successful refresh still did not store is ignored, so it cannot make
        # the refresh due every check.
        self._awaiting: tuple[frozenset[str], datetime] | None = None
        self._ignored: set[str] = set()
        self.counts = dict.fromkeys(("checks", "changes", "throttled", "failed"), 0)

    def active(self) -> bool:
        """The check replaces the hourly refresh only with a Personal API key."""
        return self._personal() is not None

    def morning_due(self) -> bool:
        """Whether the daily loop runs the morning reading now.

        Without a key the reading keeps its own polling. With one it waits for
        the night the check found stored, or for noon's final attempt.
        """
        if not self.active():
            return True
        local = self._local_now()
        return local.hour >= MORNING_SLEEP_WAIT_UNTIL_HOUR or has_night(
            self._stored_sleep(local.date()), local.date()
        )

    def refresh_due(self) -> bool:
        """Whether a change or the daily guarantee makes the refresh due."""
        local = self._local_now()
        today = local.date()
        if local.hour >= DAILY_REFRESH_HOUR and not self._refreshed_today(local):
            return True
        with self._lock:
            now = self._monotonic()
            if self._next_check_at is not None and now < self._next_check_at:
                return False
            delay: float = check_seconds(local)
            try:
                changes = self._probe(today)
            except provider_http.ProviderHTTPError as error:
                if error.status in {401, 403}:
                    # The refresh reports the rejected key; the retry hold then
                    # waits for new credentials.
                    self._next_check_at = now + delay
                    return True
                delay = self._failed(delay, error)
                self._next_check_at = now + delay
                return False
            except Exception as error:  # noqa: BLE001 - a failed check must not stop the loop
                delay = self._failed(delay, error)
                self._next_check_at = now + delay
                return False
            self._failures = 0
            self._next_check_at = now + delay
            self.counts["checks"] += 1
            changes = self._settle(changes)
            if not changes:
                return False
            self._awaiting = (frozenset(changes), local)
            self.counts["changes"] += 1
            self._log(
                "garmin_change_found",
                activities=sum(not key.startswith("night:") for key in changes),
                nights=sum(key.startswith("night:") for key in changes),
            )
            return True

    def _last_local(self, local: datetime) -> datetime | None:
        """The last successful refresh in the athlete's zone."""
        last = self._last_refresh()
        if last is None:
            return None
        if last.tzinfo is None:
            return last.replace(tzinfo=local.tzinfo)
        return last.astimezone(local.tzinfo)

    def _refreshed_today(self, local: datetime) -> bool:
        last = self._last_local(local)
        return last is not None and last.date() == local.date()

    def _probe(self, today: date) -> set[str]:
        """The new activity ids and ``night:<day>`` Garmin has and we lack."""
        client = self._personal()
        if client is None:
            return set()
        newest = client.newest_activity_ids(
            (today - timedelta(days=1)).isoformat(), today.isoformat()
        )
        changes = set(newest) - set(self._known_activity_ids(ACTIVITY_DAYS))
        day = today.isoformat()
        if not has_night(self._stored_sleep(today), today) and has_night(
            client.get_sleep_daily(day, day), today
        ):
            changes.add(f"night:{day}")
        return changes

    def _settle(self, changes: set[str]) -> set[str]:
        """Drop the changes a successful refresh since their trigger left out."""
        if self._awaiting is not None:
            keys, since = self._awaiting
            last = self._last_local(since)
            if last is not None and last > since:
                self._ignored |= keys & changes
                self._awaiting = None
        # Forget what Garmin no longer reports.
        self._ignored &= changes
        return changes - self._ignored

    def _failed(self, delay: float, error: Exception) -> float:
        self._failures += 1
        self.counts["checks"] += 1
        factor = min(2**self._failures, MAX_BACKOFF_FACTOR)
        delay *= factor
        retry_after = getattr(error, "retry_after", None)
        if getattr(error, "status", None) == 429:
            self.counts["throttled"] += 1
            if isinstance(retry_after, (int, float)):
                # Garmin named a wait: never check earlier.
                delay = max(delay, float(retry_after))
        else:
            self.counts["failed"] += 1
        self._log(
            "garmin_change_check_failed",
            error_class=type(error).__name__,
            next_check_seconds=round(delay),
        )
        return delay

    def _log(self, event: str, **context: Any) -> None:
        """Log counts only; no provider payload or id leaves the check."""
        self._logger.info(
            "Garmin change check",
            extra={"event": event, "context": {**context, **self.counts}},
        )
