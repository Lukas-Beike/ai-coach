"""Wahoo side of the stream backfill (#1763): the file source and the file mapping.

A workout's FIT download link only exists in the Wahoo workout list (it is never
stored), and Wahoo lists newest first without a date filter. So each batch lists
the workouts back to its oldest session, takes the link of every session it needs
from that listing, and downloads the files one by one from the allowlisted CDN with
a pause between them. A file Wahoo no longer lists, or lists without a file, is a
record without a file; a rate limit ends the batch, as does a transient failure.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

from backend.canonical.mapping import MappingResult
from backend.providers.fit_activity_detail_mapping import (
    MAPPER_VERSION,
    map_fit_activity_detail,
)
from backend.providers.garmin_rating_history import (
    FAILED,
    RATE_LIMITED,
    RatingReadStopped,
)
from backend.providers.wahoo_activity_mapping import wahoo_workout_id
from backend.providers.wahoo_client import WahooWorkoutFetch
from backend.providers.wahoo_fit_download import WahooFitUnavailable, wahoo_fit_url
from backend.sync.stream_backfill import (
    FileHandler,
    Guard,
    SkipHandler,
    StreamCandidate,
)
from backend.sync.wahoo_activity_details import wahoo_fit_provenance

# Files per job. The listing is read again for each job, so the batch is larger
# than Garmin's; the CDN downloads are paced.
WAHOO_BATCH_LIMIT: Final = 100
# Pages of 50 workouts: far more than the athlete's whole Wahoo history.
HISTORY_WORKOUT_PAGES: Final = 200
DOWNLOAD_DELAY_SECONDS: Final = 1.0
_RATE_LIMITED: Final = "rate_limited"
_TRANSIENT: Final = "unavailable"


class WahooWorkoutLister(Protocol):
    def list_workouts(
        self, *, since: datetime, until: datetime | None = None, max_pages: int = ...
    ) -> WahooWorkoutFetch: ...


class WahooStreamSource:
    """List the needed workouts, then download their FIT files one by one."""

    def __init__(
        self,
        *,
        client: Callable[[], WahooWorkoutLister],
        download: Callable[[str], bytes],
        sleep: Callable[[float], None] = time.sleep,
        delay_seconds: float = DOWNLOAD_DELAY_SECONDS,
    ) -> None:
        self._client = client
        self._download = download
        self._sleep = sleep
        self._delay_seconds = delay_seconds

    def fetch(
        self,
        batch: Sequence[StreamCandidate],
        on_file: FileHandler,
        on_skip: SkipHandler,
        guard: Guard,  # noqa: ARG002 - writes take the service's own lock
    ) -> None:
        fetch = self._client().list_workouts(
            since=_oldest(batch) - timedelta(days=1),
            until=_newest(batch) + timedelta(days=1),
            max_pages=HISTORY_WORKOUT_PAGES,
        )
        links = _links(fetch.workouts)
        # Only a complete listing vouches that a missing workout is gone; with an
        # incomplete one the workout stays a candidate and is not marked.
        complete = not (fetch.truncated or fetch.skipped)
        downloads = 0
        for item in batch:
            identifier = item.provider_activity_id
            if identifier not in links:
                if complete:
                    on_file(identifier, None)
                continue
            url = links[identifier]
            if url is None:
                on_file(identifier, None)
                continue
            if downloads:
                self._sleep(self._delay_seconds)
            downloads += 1
            self._download_one(identifier, url, on_file, on_skip)

    def _download_one(
        self, identifier: str, url: str, on_file: FileHandler, on_skip: SkipHandler
    ) -> None:
        try:
            data = self._download(url)
        except WahooFitUnavailable as error:
            if error.reason == _RATE_LIMITED:
                raise RatingReadStopped(RATE_LIMITED, identifier) from None
            if error.reason == _TRANSIENT:
                raise RatingReadStopped(FAILED, identifier) from None
            # Rejected, too large or untrusted: nothing a retry in this run fixes.
            on_skip(identifier)
            return
        on_file(identifier, data)


class WahooStreamMapping:
    """Map a downloaded Wahoo file with the FIT mapper under Wahoo provenance."""

    mapper_version = MAPPER_VERSION

    def map(
        self, candidate: StreamCandidate, data: bytes, retrieved_at: datetime
    ) -> MappingResult[Any]:
        identifier = candidate.provider_activity_id
        return map_fit_activity_detail(
            data,
            provider_activity_id=identifier,
            provenance=wahoo_fit_provenance(identifier, retrieved_at),
        )


def _links(workouts: Sequence[Mapping[str, Any]]) -> dict[str, str | None]:
    """Map each listed workout id to its download link (None: it has no file)."""
    links: dict[str, str | None] = {}
    for row in workouts:
        identifier = wahoo_workout_id(row)
        if identifier is not None:
            links[identifier] = wahoo_fit_url(row.get("workout_summary"))
    return links


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.utcoffset() is not None else parsed.replace(tzinfo=UTC)


def _oldest(batch: Sequence[StreamCandidate]) -> datetime:
    return min(_instant(item.started_at) for item in batch)


def _newest(batch: Sequence[StreamCandidate]) -> datetime:
    return max(_instant(item.started_at) for item in batch)
