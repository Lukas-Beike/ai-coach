"""Store the weather during outdoor rides and runs as derived observations (#1868).

``ActivityWeatherStage`` is a follow-up stage of the canonical backfill worker.
Per session it fingerprints the stream content hashes, the session times, the
location kind and, for the home location, its rounded coordinates before any
stream is decoded. Only sessions whose stored rows carry another fingerprint are
looked up, so a stored result is never fetched again and a pass without changes
decodes and requests nothing. The fingerprint is the cache.

The requests are made in ``prefetch``, before the writer transaction of the
worker: at most ``batch_size`` sessions per batch, newest first, with the
coordinates rounded to 2 decimals. The first failure ends the pass, writes
nothing and delays that session with a growing backoff (kept in memory, so a
restart tries again). ``run_batch`` then writes the fetched values; coordinates
live only in local variables of ``prefetch`` and never reach a row, the stage
state, a log or a diagnostic. An outdoor session without a stored position is
looked up at the saved home location and labelled so; a session of unknown
environment only with a stored position. Without a location it is remembered as
empty. Rows of sessions that are gone are retired.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any, Final

from backend.activities.activity_summary import activity_summaries
from backend.activities.routes import valid_position
from backend.canonical.activity_detail import ActivityStreamSet
from backend.canonical.activity_summary import summary_duration_s, summary_local_date
from backend.canonical.records import (
    MetricValue,
    Observation,
    Provenance,
    fingerprint_inputs,
)
from backend.canonical.sports import is_outdoor_endurance
from backend.canonical.vocabulary import (
    PROVIDER_PRECEDENCE,
    Environment,
    RecordingOrigin,
    SourceKind,
    Sport,
    StreamChannel,
)
from backend.db import activity_detail_store, canonical_store
from backend.db.repositories import KeyValueRepository
from backend.providers.activity_weather import rounded_coordinates
from backend.sync.canonical_backfill import BatchReport
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.weather.activity_weather import (
    FIRST_DAY,
    SETTLE,
    ActivityWeather,
    activity_window,
    reduce_hourly,
    utc_days,
)
from backend.weather.activity_weather_store import (
    LOCATION_HOME,
    LOCATION_LABELS,
    LOCATION_START,
    METHOD_ID,
    METHOD_VERSION,
    VALUES,
    stored_activity_weather,
)

# The application logger: only it has handlers (see observability.configure_logging).
_LOGGER = logging.getLogger("intervals_coach")
STAGE: Final = "activity_weather"
STATE_KEY: Final = "activity_weather_state"
DEFAULT_BATCH_SIZE: Final = 20
RETRY_BASE: Final = timedelta(minutes=30)
RETRY_MAX: Final = timedelta(hours=24)
# A session with neither a stored position nor a home location.
_NO_LOCATION: Final = "none"
_RANK: Final = {
    provider.value: index for index, provider in enumerate(PROVIDER_PRECEDENCE)
}

type Fetch = Callable[[float, float, date, date], Mapping[str, Any]]
type HomeLocation = Callable[[Any], tuple[float, float] | None]
type Coordinates = tuple[float, float]


def _cheap_fingerprint(summary: Mapping[str, Any], stream_hashes: Sequence[str]) -> str:
    """Every input but the location, known without decoding a stream."""
    return fingerprint_inputs(
        {
            "method": METHOD_ID,
            "method_version": METHOD_VERSION,
            "started_at": summary.get("started_at"),
            "elapsed_duration_s": summary.get("elapsed_duration_s"),
            "moving_duration_s": summary.get("moving_duration_s"),
            "streams": sorted(stream_hashes),
        }
    )


def _fingerprint(cheap: str, kind: str, home_key: str) -> str:
    """A start position is part of the streams; the other kinds depend on the home."""
    return fingerprint_inputs(
        {
            "inputs": cheap,
            "location_kind": kind,
            "home": "" if kind == LOCATION_START else home_key,
        }
    )


def _start_position(db: Any, session_id: str) -> Coordinates | None:
    """The first valid stored position of the session's own streams."""
    sets = sorted(
        activity_detail_store.full_stream_sets_for_session(db, session_id),
        key=lambda item: _RANK.get(item.provider, len(_RANK)),
    )
    for item in sets:
        detail = item.detail
        if not isinstance(detail, ActivityStreamSet):
            continue
        latitudes = detail.channels.get(StreamChannel.LATITUDE_DEG, ())
        longitudes = detail.channels.get(StreamChannel.LONGITUDE_DEG, ())
        for latitude, longitude in zip(latitudes, longitudes, strict=False):
            if (position := valid_position(latitude, longitude)) is not None:
                return position
    return None


@dataclass(frozen=True, slots=True)
class _Fetched:
    """One looked-up session; the kind of location, never the coordinates."""

    cheap: str
    kind: str
    home_key: str
    weather: ActivityWeather | None


@dataclass(slots=True)
class _Plan:
    """Which sessions keep their stored state and which need a look-up."""

    keep: set[str] = field(default_factory=set)
    stored: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    empty: dict[str, Any] = field(default_factory=dict)
    changed: list[tuple[Mapping[str, Any], str]] = field(default_factory=list)
    wanted: int = 0
    waiting: int = 0


def _window(summary: Mapping[str, Any]) -> tuple[datetime, datetime]:
    """The UTC start and end of the session; the elapsed time is what is exposed."""
    return activity_window(
        datetime.fromisoformat(str(summary["started_at"])),
        summary.get("elapsed_duration_s") or summary_duration_s(summary),
    )


def _wants(summary: Mapping[str, Any], now: datetime) -> bool:
    """Rides and runs not known to be indoor on or after 2022-01-01, settled.

    An unknown environment is kept; ``_locate`` then needs a stored position.
    """
    if not is_outdoor_endurance(
        str(summary.get("sport")), str(summary.get("environment"))
    ):
        return False
    start, end = _window(summary)
    return (start - timedelta(minutes=30)).date() >= FIRST_DAY and end + SETTLE <= now


class ActivityWeatherStage:
    """Backfill follow-up that keeps the stored activity weather current."""

    def __init__(
        self,
        *,
        key_values: KeyValueRepository,
        zone_provider: Callable[[], tzinfo | None],
        clock: Callable[[], str],
        fetch: Fetch,
        home_location: HomeLocation,
        reader: CanonicalTableReader | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._key_values = key_values
        self._zone_provider = zone_provider
        self._clock = clock
        self._fetch = fetch
        self._home_location = home_location
        self._reader = reader or CanonicalTableReader()
        self._batch_size = batch_size
        self._fetched: dict[str, _Fetched] = {}
        self._halted = False
        # Session id -> (failures, earliest next attempt); in memory on purpose.
        self._retry: dict[str, tuple[int, datetime]] = {}

    @property
    def stage(self) -> str:
        return STAGE

    def _now(self) -> datetime:
        moment = datetime.fromisoformat(self._clock())
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)

    def prefetch(self, database: Callable[[], Any]) -> None:
        """Look up one batch of sessions; no writer is held while requests run."""
        self._fetched, self._halted = {}, False
        now = self._now()
        with database().reader() as db:
            plan = self._plan(db, now)
            home = self._home_location(db)
            batch = [
                (summary, cheap, self._locate(db, summary, home))
                for summary, cheap in self._eligible(plan, now)[: self._batch_size]
            ]
        home_key = self._home_key(home)
        for summary, cheap, (kind, position) in batch:
            session_id = str(summary["id"])
            weather = None
            if position is not None:
                try:
                    weather = self._look_up(summary, position)
                except Exception as exc:  # noqa: BLE001 - logged by type only
                    self._failed(session_id, now, exc)
                    return
                self._retry.pop(session_id, None)
            self._fetched[session_id] = _Fetched(cheap, kind, home_key, weather)

    def run_batch(self, db: Any) -> BatchReport:
        """Write the values fetched by ``prefetch`` in the caller's transaction."""
        now = self._now()
        stamp = now.isoformat()
        plan = self._plan(db, now)
        fetched, self._fetched = self._fetched, {}
        state = self._state(db)
        # A session not looked up yet keeps its earlier memo until a later batch.
        remembered = state.get("empty") or {}
        next_empty = {
            str(summary["id"]): remembered[str(summary["id"])]
            for summary, _ in plan.changed
            if str(summary["id"]) in remembered
        } | plan.empty
        keep = plan.keep
        written = values = pending = 0
        retried = sum(1 for summary, _ in plan.changed if self._waiting(summary, now))
        for summary, cheap in plan.changed:
            session_id = str(summary["id"])
            item = fetched.get(session_id)
            if item is None or item.cheap != cheap:
                # Not looked up yet: the stored rows stay until a later batch.
                keep.update(
                    row["natural_key"]
                    for row in plan.stored.get(session_id, {}).values()
                )
                pending += not self._waiting(summary, now)
                continue
            fingerprint = _fingerprint(cheap, item.kind, item.home_key)
            keys = self._write_session(db, summary, item, fingerprint, stamp)
            written += 1
            if keys:
                values += 1
                keep.update(keys)
                next_empty.pop(session_id, None)
            else:
                next_empty[session_id] = {"kind": item.kind, "fingerprint": fingerprint}
        retired = canonical_store.retire_derived_observations(
            db, METHOD_ID, keep=keep, now=stamp
        )
        done = self._halted or written == 0 or pending == 0
        counts = {
            "sessions": plan.wanted,
            "looked_up": written,
            "with_values": values,
            "remaining": pending,
            "retrying": retried,
            "retired": retired,
        }
        if self._halted:
            status = "retry"
        else:
            status = "complete" if done else "running"
        self._save(
            db,
            {
                "status": status,
                "method_version": METHOD_VERSION,
                "completed_at": stamp if done else state.get("completed_at"),
                "counts": counts,
                "empty": next_empty,
            },
        )
        # Counts only: never a position, a value or a session id.
        _LOGGER.info(
            "Activity weather reconciled",
            extra={"event": "activity_weather_reconciled", "context": counts},
        )
        return BatchReport(items=written, done=done)

    def mark_failed(self, db: Any) -> None:
        state = self._state(db)
        state["status"] = "failed"
        self._save(db, state)

    def summary(self, db: Any) -> dict[str, Any]:
        """Return the content-free status and counts of the last batch."""
        return summarize_activity_weather(self._key_values, db)

    def _plan(self, db: Any, now: datetime) -> _Plan:
        """Fingerprint every wanted session before any stream is decoded."""
        sessions = {
            session_id: records
            for session_id, records in self._reader.activity_sessions(db)
            if records
        }
        summaries = [
            summary
            for summary in activity_summaries(
                sessions.items(), self._zone_provider() or UTC
            )
            if _wants(summary, now)
        ]
        keys = activity_detail_store.full_stream_keys(
            db, [str(summary["id"]) for summary in summaries]
        )
        stored = stored_activity_weather(db)
        empty = self._state(db).get("empty") or {}
        home_key = self._home_key(self._home_location(db))
        plan = _Plan(stored=stored, wanted=len(summaries))
        for summary in summaries:
            session_id = str(summary["id"])
            cheap = _cheap_fingerprint(
                summary,
                [key.content_sha256 for key in keys.get(session_id, ())],
            )
            rows = stored.get(session_id, {})
            if rows:
                kind = next(iter(rows.values()))["derivation"].get("location_kind")
                current = _fingerprint(cheap, str(kind), home_key)
                if all(
                    row.get("input_fingerprint") == current for row in rows.values()
                ):
                    plan.keep.update(row["natural_key"] for row in rows.values())
                    continue
            elif (
                (entry := empty.get(session_id))
                and isinstance(entry, dict)
                and entry.get("fingerprint")
                == _fingerprint(cheap, str(entry.get("kind")), home_key)
            ):
                plan.empty[session_id] = entry
                continue
            plan.changed.append((summary, cheap))
        return plan

    def _eligible(
        self, plan: _Plan, now: datetime
    ) -> list[tuple[Mapping[str, Any], str]]:
        return [item for item in plan.changed if not self._waiting(item[0], now)]

    def _waiting(self, summary: Mapping[str, Any], now: datetime) -> bool:
        retry = self._retry.get(str(summary["id"]))
        return retry is not None and now < retry[1]

    @staticmethod
    def _home_key(home: Coordinates | None) -> str:
        if home is None:
            return ""
        return fingerprint_inputs({"home": [round(home[0], 2), round(home[1], 2)]})

    @staticmethod
    def _locate(
        db: Any, summary: Mapping[str, Any], home: Coordinates | None
    ) -> tuple[str, Coordinates | None]:
        """The kind of location and its coordinates; the start position first."""
        if (position := _start_position(db, str(summary["id"]))) is not None:
            return LOCATION_START, position
        # A position proves an unknown environment was outdoors; the home does not.
        if home is not None and summary.get("environment") == Environment.OUTDOOR:
            return LOCATION_HOME, home
        return _NO_LOCATION, None

    def _look_up(
        self, summary: Mapping[str, Any], position: Coordinates
    ) -> ActivityWeather | None:
        start, end = _window(summary)
        first, last = utc_days(start, end)
        return reduce_hourly(
            self._fetch(*rounded_coordinates(*position), first, last), start, end
        )

    def _failed(self, session_id: str, now: datetime, error: Exception) -> None:
        """End the pass and delay the session; the error type is all that is kept."""
        failures = self._retry.get(session_id, (0, now))[0] + 1
        delay = min(RETRY_BASE * 2 ** min(failures - 1, 6), RETRY_MAX)
        self._retry[session_id] = (failures, now + delay)
        self._halted = True
        _LOGGER.warning(
            "Activity weather look-up failed",
            extra={
                "event": "activity_weather_failed",
                "context": {
                    "error_type": type(error).__name__,
                    "failures": failures,
                },
            },
        )

    @staticmethod
    def _write_session(
        db: Any,
        summary: Mapping[str, Any],
        item: _Fetched,
        fingerprint: str,
        stamp: str,
    ) -> set[str]:
        """Upsert the session's values; return their natural keys (empty: none)."""
        if item.weather is None or item.kind not in LOCATION_LABELS:
            return set()
        try:
            observations = [
                _observation(
                    summary,
                    kind,
                    getattr(item.weather, attribute),
                    item.kind,
                    fingerprint,
                )
                for _key, kind, attribute in VALUES
                if getattr(item.weather, attribute) is not None
            ]
        except TypeError, ValueError:
            # Outside the canonical bounds: this session keeps no value.
            return set()
        keys = set()
        for observation in observations:
            keys.add(canonical_store.observation_natural_key(observation))
            canonical_store.upsert_observation(
                db,
                observation,
                mapper_version=METHOD_VERSION,
                now=stamp,
                owner=str(summary["id"]),
                derivation={"location_kind": item.kind},
            )
        return keys

    def _state(self, db: Any) -> dict[str, Any]:
        return _load_state(self._key_values, db)

    def _save(self, db: Any, state: Mapping[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )


def _observation(
    summary: Mapping[str, Any],
    kind: Any,
    value: float,
    location_kind: str,
    fingerprint: str,
) -> Observation:
    try:
        recorded_by = RecordingOrigin(str(summary.get("recorded_by")))
    except ValueError:
        recorded_by = RecordingOrigin.UNKNOWN
    return Observation(
        kind=kind,
        value=MetricValue(round(value, 4), kind.unit),
        observed_on=date.fromisoformat(summary_local_date(summary)),
        observed_at=datetime.fromisoformat(str(summary["started_at"])),
        provenance=Provenance(
            provider=None,
            source_kind=SourceKind.DERIVED,
            source_record_id=str(summary["id"]),
            recorded_by=recorded_by,
            retrieved_at=None,
            label=LOCATION_LABELS[location_kind],
        ),
        sport=Sport(str(summary["sport"])),
        method=METHOD_ID,
        method_version=METHOD_VERSION,
        input_fingerprint=fingerprint,
    )


def _load_state(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    raw = key_values.get(db, STATE_KEY)
    try:
        state = json.loads(raw) if raw else {}
    except ValueError:
        state = {}
    return state if isinstance(state, dict) else {}


def summarize_activity_weather(
    key_values: KeyValueRepository, db: Any
) -> dict[str, Any]:
    """Content-free status and counts of the last batch, for diagnostics."""
    state = _load_state(key_values, db)
    return {
        "status": state.get("status", "pending"),
        "method_version": state.get("method_version"),
        "counts": state.get("counts", {}),
    }
