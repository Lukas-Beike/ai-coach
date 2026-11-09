"""Garmin side of the stream backfill (#1763): the file source and the file mapping.

The source downloads the original FIT files through the Garmin transport client
(the Personal API; the SDK serves no file). The mapping is the regular Garmin
detail mapping applied to the file alone, so stored sets are exactly what the
detail fetch of the last 90 days stores for the same file.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final, Protocol

from backend.canonical.mapping import MappingResult
from backend.canonical.vocabulary import RecordingOrigin
from backend.providers.garmin_activity_detail_mapping import (
    MAPPER_VERSION,
    map_garmin_activity_detail,
)
from backend.sync.stream_backfill import (
    FileHandler,
    Guard,
    SkipHandler,
    StreamCandidate,
)

# The Personal API rate limits are undocumented: 30 files, 2 s apart, per job.
STREAM_BATCH_LIMIT: Final = 30


class GarminFileReader(Protocol):
    """The reader that downloads activity files (``GarminRemoteReader``)."""

    def fetch_activity_files(
        self,
        activity_ids: Sequence[str],
        on_file: FileHandler,
        on_skip: SkipHandler,
        guard: Guard,
    ) -> None: ...


class GarminStreamSource:
    """Download the FIT files of one batch through the Garmin reader."""

    def __init__(self, reader: GarminFileReader, guard: Guard) -> None:
        self._reader = reader
        self._guard = guard

    def fetch(
        self,
        batch: Sequence[StreamCandidate],
        on_file: FileHandler,
        on_skip: SkipHandler,
    ) -> None:
        self._reader.fetch_activity_files(
            [item.provider_activity_id for item in batch],
            on_file,
            on_skip,
            self._guard,
        )


class GarminStreamMapping:
    """Map a downloaded file with the Garmin detail mapping (FIT part only)."""

    mapper_version = MAPPER_VERSION

    def map(
        self, candidate: StreamCandidate, data: bytes, retrieved_at: datetime
    ) -> MappingResult[Any]:
        try:
            recorded_by = RecordingOrigin(candidate.recorded_by)
        except ValueError:
            recorded_by = RecordingOrigin.UNKNOWN
        return map_garmin_activity_detail(
            {"activity_id": candidate.provider_activity_id, "fit": data},
            recorded_by=recorded_by,
            retrieved_at=retrieved_at,
        )
