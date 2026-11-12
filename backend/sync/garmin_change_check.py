"""Light Garmin change check through the Personal API (#2303).

With a Personal API key the automatic Garmin refresh no longer runs every hour.
The daily loop asks this check instead: every 10 minutes by day and every 30
minutes at night (athlete-local time) it reads the newest activity ids and,
until last night is stored, today's sleep entry, and compares them read-only
with the local database. Only a new activity or a newly published night makes
the existing refresh due. A full refresh is still guaranteed once per local
day from noon, for the data only the SDK serves, repeated at most hourly.

An unchanged check queues nothing. By day it also reads today's summary and
Body Battery and writes them only when Garmin changed them. A change that a later
successful refresh still did not store is held back for an hour, so data the
refresh does not keep queues at most an hourly refresh, as before. Throttling
and errors back off in memory; a ``Retry-After`` wait is never undercut. A
rejected key or endpoint makes the refresh due at the backoff pace, so its
failure surfaces and the retry hold can stop the schedule. The cadence state
and the counts live in memory: a restart checks at once.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from typing import Any

from backend.performance.morning_battery_service import MORNING_SLEEP_WAIT_UNTIL_HOUR
from backend.providers.garmin import fetch_daytime_values
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
# A change a successful refresh did not store returns after this wait.
HOLD_SECONDS = 60 * 60
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
        store_daytime: Callable[[date, dict[str, Any]], list[str]] | None = None,
    ) -> None:
        self._store_daytime = store_daytime
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
        # successful refresh still did not store is held back for an hour, so
        # it cannot make the refresh due every check.
        self._awaiting: tuple[frozenset[str], datetime] | None = None
        self._held: dict[str, float] = {}
        self.counts = dict.fromkeys(
            ("checks", "changes", "daytime", "throttled", "failed"), 0
        )

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

    def refresh_due(self, marker_due: Callable[[], bool]) -> bool:
        """Whether a change or the daily guarantee makes the refresh due.

        ``marker_due`` is the hourly attempt marker: the noon guarantee asks
        it, so a refresh that cannot mark today's success repeats hourly.
        """
        local = self._local_now()
        today = local.date()
        if (
            local.hour >= DAILY_REFRESH_HOUR
            and not self._refreshed_today(local)
            and marker_due()
        ):
            return True
        with self._lock:
            now = self._monotonic()
            if self._next_check_at is not None and now < self._next_check_at:
                return False
            delay: float = check_seconds(local)
            # Local reads stay outside the remote error handling, so a
            # maintenance or busy database is never counted as a Garmin failure.
            stored_night = has_night(self._stored_sleep(today), today)
            self.counts["checks"] += 1
            try:
                newest, night = self._read(today, stored_night=stored_night)
            except Exception as error:  # noqa: BLE001 - a failed check must not stop the loop
                self._next_check_at = now + self._failed(delay, error)
                # A rejected key or endpoint queues the refresh at the backoff
                # pace, so its error shows and the retry hold can apply.
                return getattr(error, "status", None) in {401, 403}
            self._next_check_at = now + delay
            changes = set(newest) - set(self._known_activity_ids(ACTIVITY_DAYS))
            if night:
                changes.add(f"night:{today.isoformat()}")
            changes = self._settle(changes, now)
            if not changes:
                return self._refresh_daytime(local, now)
            self._failures = 0
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

    def _read(self, today: date, *, stored_night: bool) -> tuple[list[str], bool]:
        """The newest activity ids and whether Garmin has a night we lack."""
        client = self._personal()
        if client is None:
            return [], False
        newest = client.newest_activity_ids(
            (today - timedelta(days=1)).isoformat(), today.isoformat()
        )
        day = today.isoformat()
        night = not stored_night and has_night(client.get_sleep_daily(day, day), today)
        return newest, night

    def _refresh_daytime(self, local: datetime, now: float) -> bool:
        """By day, store today's summary and Body Battery where Garmin changed them.

        A change makes the full refresh due, which reads them too; at night
        they barely move, so only the day cadence reads them. The backoff
        resets only once this read succeeded too, and a rejected key or
        endpoint makes the refresh due as for the change markers.
        """
        client = self._personal()
        if (
            self._store_daytime is None
            or client is None
            or check_seconds(local) != DAY_CHECK_SECONDS
        ):
            self._failures = 0
            return False
        try:
            values = fetch_daytime_values(client, local.date())
        except Exception as error:  # noqa: BLE001 - a failed read must not stop the loop
            self._next_check_at = now + self._failed(DAY_CHECK_SECONDS, error)
            return getattr(error, "status", None) in {401, 403}
        self._failures = 0
        stored = self._store_daytime(local.date(), values)
        if stored:
            self.counts["daytime"] += 1
            self._log("garmin_daytime_stored", sections=len(stored))
        return False

    def _settle(self, changes: set[str], now: float) -> set[str]:
        """Hold back for an hour what a successful refresh since its trigger left out.

        A partial refresh may miss a read, so the change comes back hourly, the
        pace of the schedule it replaces, instead of every check.
        """
        if self._awaiting is not None:
            keys, since = self._awaiting
            last = self._last_local(since)
            if last is not None and last > since:
                self._held.update(dict.fromkeys(keys & changes, now))
                self._awaiting = None
        self._held = {
            key: held_at
            for key, held_at in self._held.items()
            if key in changes and now - held_at < HOLD_SECONDS
        }
        return changes - set(self._held)

    def _failed(self, delay: float, error: Exception) -> float:
        self._failures += 1
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
