"""Explicit read-only loading of full-resolution Intervals activity data."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from itertools import pairwise
from typing import Any
from urllib.parse import quote

from backend.activities.detail_projection import (
    COACH_ACTIVITY_DETAIL_STREAM_FIELDS,
    detailed_activity,
)
from backend.activities.detail_store import ActivityDetailStore, summary_fingerprint
from backend.activities.target_snapshot import freeze_targets
from backend.errors import AppError
from backend.performance.power_profile import power_profile
from backend.performance.session_analysis import aerobic_analysis, interval_quality

MAX_STREAM_POINTS = 172_800
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
        state_repository: Any,
        store: ActivityDetailStore,
        utc_now: Callable[[], str],
        configured: bool,
        read_planned_units: Callable[[], list[dict[str, Any]]] = list,
    ) -> None:
        self._api_client = api_client
        self._state_repository = state_repository
        self._store = store
        self._utc_now = utc_now
        self._configured = configured
        self._read_planned_units = read_planned_units

    def refresh(self, activity_id: str) -> dict[str, Any]:
        activity_id = normalize_activity_id(activity_id)
        snapshot = self._state_repository.latest_snapshot() or {}
        rows = (snapshot.get("raw_provider_data") or {}).get("activities") or []
        summary = next(
            (
                row
                for row in rows
                if isinstance(row, dict) and str(row.get("id")) == activity_id
            ),
            None,
        )
        if summary is None:
            raise AppError(
                404,
                "Diese Aktivität ist lokal nicht vorhanden.",
                reason="activity_details_not_found",
            )
        if not self._configured:
            raise AppError(503, "Intervals.icu ist nicht konfiguriert.")
        path = f"/activity/{quote(activity_id, safe='')}"
        detail = self._api_client.get(path, {"intervals": "true"})
        if not isinstance(detail, dict) or str(detail.get("id")) != activity_id:
            raise AppError(502, "Der Anbieter hat eine andere Aktivität zurückgegeben.")
        streams = normalize_streams(
            self._api_client.get(
                f"{path}/streams",
                {"types": ",".join(COACH_ACTIVITY_DETAIL_STREAM_FIELDS)},
            )
        )
        projected = detailed_activity(
            {**detail, "laps": detail.get("icu_intervals", [])}
        )
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
