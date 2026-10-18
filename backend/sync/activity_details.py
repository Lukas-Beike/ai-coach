"""Read-only loading of full-resolution Intervals activity data.

The newest activities are prefetched after each Intervals refresh; older ones
load on the athlete's explicit request.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from itertools import pairwise
from typing import Any
from urllib.parse import quote

from backend.activities.activity_reference import (
    ActivityReferenceResolver,
    NoActivityReferences,
)
from backend.activities.detail_projection import (
    COACH_ACTIVITY_DETAIL_STREAM_FIELDS,
    detailed_activity,
)
from backend.activities.detail_store import ActivityDetailStore, summary_fingerprint
from backend.canonical.activity_detail import MAX_STREAM_POINTS
from backend.errors import AppError, public_error_contract
from backend.performance.power_profile import power_profile, running_profile
from backend.performance.session_analysis import aerobic_analysis, interval_quality
from backend.planning.target_snapshot import freeze_targets
from backend.providers.intervals_activity_fields import (
    ACTIVITY_DETAIL_PARAMS,
    activity_detail_laps,
)
from backend.runtime.ports import ActivityRowReader

_LOGGER = logging.getLogger(__name__)

# The analysis tab opens these without a click; older activities load on request.
PREFETCH_RECENT_ACTIVITIES = 10
MAX_DETAIL_BYTES = 24 * 1024 * 1024
ACTIVITY_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,200}")


def normalize_activity_id(value: Any) -> str:
    """Reject path syntax and ambiguous IDs before provider access."""
    if not isinstance(value, str) or not ACTIVITY_ID_PATTERN.fullmatch(value):
        raise ValueError("Die Aktivitäts-ID ist ungültig.")
    return value


def normalize_streams(value: Any) -> dict[str, list[Any]]:
    """Retain full-resolution numeric streams; reject oversized provider data."""
    if not isinstance(value, list) or len(value) > 32:
        raise AppError(502, "Ungültige Messreihen vom Anbieter.")
    streams: dict[str, list[Any]] = {}
    for stream in value:
        normalized = _normalize_stream(stream)
        if normalized is not None:
            name, data = normalized
            streams[name] = data
    _validate_time_axis(streams)
    return streams


class ActivityDetailRefreshService:
    """Validate a locally known activity before fetching and committing details."""

    def __init__(
        self,
        *,
        api_client: Any,
        database_manager: Any,
        row_reader: ActivityRowReader,
        store: ActivityDetailStore,
        utc_now: Callable[[], str],
        configured: bool,
        read_planned_units: Callable[[], list[dict[str, Any]]] = list,
        references: ActivityReferenceResolver | None = None,
    ) -> None:
        self._api_client = api_client
        self._database_manager = database_manager
        self._row_reader = row_reader
        self._store = store
        self._utc_now = utc_now
        self._configured = configured
        self._read_planned_units = read_planned_units
        self._references = NoActivityReferences() if references is None else references

    def refresh(self, activity_id: str) -> dict[str, Any]:
        activity_id = normalize_activity_id(
            self._references.resolve(normalize_activity_id(activity_id))
        )
        with self._database_manager.unit_of_work() as db:
            rows = self._row_reader.activity_rows(db)
        summary = next(
            (row for row in rows if str(row.get("id")) == activity_id),
            None,
        )
        if summary is None:
            raise AppError(
                404,
                "Diese Aktivität ist lokal nicht vorhanden.",
                reason="activity_details_not_found",
            )
        if not self._configured:
            raise AppError(
                503, "Intervals.icu ist nicht konfiguriert.", reason="not_configured"
            )
        path = f"/activity/{quote(activity_id, safe='')}"
        detail = self._api_client.get(path, dict(ACTIVITY_DETAIL_PARAMS))
        if not isinstance(detail, dict) or str(detail.get("id")) != activity_id:
            raise AppError(502, "Der Anbieter hat eine andere Aktivität zurückgegeben.")
        streams = normalize_streams(
            self._api_client.get(
                f"{path}/streams",
                {"types": ",".join(COACH_ACTIVITY_DETAIL_STREAM_FIELDS)},
            )
        )
        projected = detailed_activity({**detail, "laps": activity_detail_laps(detail)})
        projected["streams"] = streams
        observed_at = self._utc_now()
        previous = self._store.get(activity_id) or {}
        targets = previous.get("target_snapshot") or freeze_targets(
            self._read_planned_units(), rows, activity_id, projected, observed_at
        )
        record = {
            "activity_id": activity_id,
            "activity": projected,
            "source": "Intervals.icu",
            "observed_at": observed_at,
            "target_snapshot": targets,
            "session_analysis": {
                "interval_quality": interval_quality(projected, targets),
                "aerobic": aerobic_analysis(projected),
                "power_profile": power_profile(projected),
                "running_profile": running_profile(projected),
            },
            "full_resolution": True,
            "available_streams": sorted(streams),
            "summary_sha256": summary_fingerprint(summary),
            "content_sha256": hashlib.sha256(
                json.dumps(projected, sort_keys=True, allow_nan=False).encode()
            ).hexdigest(),
            "coverage": {
                name: {
                    "points": len(values),
                    "valid_points": sum(value is not None for value in values),
                }
                for name, values in streams.items()
            },
        }
        if len(json.dumps(record, allow_nan=False).encode()) > MAX_DETAIL_BYTES:
            raise AppError(502, "Die Detaildaten überschreiten die unterstützte Größe.")
        self._store.save(activity_id, record)
        return {"status": "completed", "activity_id": activity_id}

    def prefetch_recent(
        self,
        guard: Callable[[], AbstractContextManager[Any]] = nullcontext,
        limit: int = PREFETCH_RECENT_ACTIVITIES,
    ) -> dict[str, int]:
        """Load missing or outdated details of the newest local activities.

        ``guard`` wraps each provider refresh, so a full resync waits for one
        activity rather than the whole run. Invalid or missing data of one
        activity is recorded and not retried until its summary changes or the
        athlete reloads it; a rate limit, outage or authentication failure ends
        the run, so it is not retried per activity and the next refresh tries
        again.
        """
        if not self._configured:
            return {"fetched": 0, "failed": 0}
        with self._database_manager.unit_of_work() as db:
            rows = self._row_reader.activity_rows(db)
        recent = sorted(
            (row for row in rows if row.get("id")),
            key=lambda row: str(row.get("start_date_local") or ""),
            reverse=True,
        )[:limit]
        fetched = failed = 0
        known_failures = self._store.failures(str(row["id"]) for row in recent)
        for row in recent:
            activity_id = str(row["id"])
            fingerprint = summary_fingerprint(row)
            stored = self._store.get(activity_id)
            if stored and stored.get("summary_sha256") == fingerprint:
                continue
            # A recorded failure is retried only for a changed summary or by request.
            if known_failures.get(activity_id, {}).get("summary_sha256") == fingerprint:
                continue
            try:
                with guard():
                    self.refresh(activity_id)
            except Exception as error:  # noqa: BLE001 - prefetch never fails the refresh
                failed += 1
                stops = not _activity_specific_failure(error)
                _LOGGER.warning(
                    "activity detail prefetch stopped"
                    if stops
                    else "activity detail prefetch skipped an activity",
                    extra={
                        "event": "activity_detail_prefetch_failed",
                        "error_class": type(error).__name__,
                        "stopped": stops,
                    },
                )
                if stops:
                    break
                self._store.save_failure(
                    activity_id, fingerprint, _failure_message(error), self._utc_now()
                )
                continue
            fetched += 1
        return {"fetched": fetched, "failed": failed}


def _activity_specific_failure(error: Exception) -> bool:
    """Whether a refresh failed for this activity alone, not the provider."""
    if isinstance(error, ValueError):
        return True
    if not isinstance(error, AppError):
        return False
    status, reason = public_error_contract(error)
    if error.upstream_status is not None:
        return reason in {"upstream_not_found", "upstream_rejected"}
    return status == 502 and reason != "provider_network_error"


def _failure_message(error: Exception) -> str:
    """Fixed text only: provider responses are never echoed to the athlete."""
    if (
        isinstance(error, AppError)
        and public_error_contract(error)[1] == "upstream_not_found"
    ):
        return "Intervals.icu hat für diese Einheit keine Detaildaten geliefert."
    return (
        "Die Detaildaten dieser Einheit waren fehlerhaft und wurden nicht übernommen."
    )


def _validate_time_axis(streams: dict[str, list[Any]]) -> None:
    time = streams.get("time", [])
    if time and (
        any(type(point) not in {int, float} or point < 0 for point in time)
        or time[-1] - time[0] > 172_800
        or any(right <= left for left, right in pairwise(time))
        or any(len(data) != len(time) for data in streams.values())
    ):
        raise AppError(502, "Die Zeitachse der Messreihen ist nicht konsistent.")


def _normalize_stream(stream: Any) -> tuple[str, list[Any]] | None:
    if not isinstance(stream, dict):
        raise AppError(502, "Ungültige Messreihe vom Anbieter.")
    name = stream.get("type")
    if not isinstance(name, str) or name not in COACH_ACTIVITY_DETAIL_STREAM_FIELDS:
        return None
    data = stream.get("data")
    if not isinstance(data, list) or len(data) > MAX_STREAM_POINTS:
        raise AppError(502, "Die Messreihe überschreitet die unterstützte Größe.")
    normalized = [
        point if type(point) in {int, float, bool} and math.isfinite(point) else None
        for point in data
    ]

    return name, normalized
