"""Weather during outdoor sessions: request, reduction, cache, fallback and privacy."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Self, cast
from urllib.parse import parse_qs, urlparse

from canonical_detail_support import add_session_record, open_manager

from backend.canonical.activity_detail import ActivityStreamSet
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StreamChannel,
    StreamResolution,
)
from backend.db.activity_detail_store import delete_stored_tracks, replace_detail_set
from backend.db.repositories import KeyValueRepository
from backend.observability import Redactor
from backend.performance.canonical_detail import CanonicalDetailReader
from backend.providers.activity_weather import (
    SERVICE,
    ActivityWeatherClient,
    activity_weather_params,
)
from backend.providers.http import JsonHttpClient
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.activity_weather import (
    ActivityWeatherStage,
    summarize_activity_weather,
)
from backend.sync.canonical_backfill import BatchReport
from backend.sync.canonical_backfill_worker import CanonicalBackfillWorker
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.weather import cache as weather_cache
from backend.weather.activity_weather import (
    activity_window,
    heat_note,
    reduce_hourly,
    utc_days,
)
from backend.weather.activity_weather_store import (
    home_coordinates,
    stored_activity_weather,
    weather_block,
)

ZONE = UTC
# The session starts at 05:00 UTC and lasts an hour.
START = datetime(2026, 9, 10, 5, 0, tzinfo=UTC)
LATITUDE, LONGITUDE = 52.51234, 13.40567
RAW_COORDINATES = ("52.51234", "13.40567", "52.5123", "13.4056")
HOURS = [f"2026-09-10T{hour:02d}:00" for hour in range(4, 8)]


def payload(**overrides: Any) -> dict[str, Any]:
    """Four hours around the session; the response also names its grid cell."""
    hourly: dict[str, Any] = {
        "time": HOURS,
        "temperature_2m": [8.0, 10.0, 14.0, 15.0],
        "apparent_temperature": [20.0, 24.0, 28.0, 30.0],
        "relative_humidity_2m": [90.0, 80.0, 60.0, 50.0],
        "wind_speed_10m": [1.0, 2.0, 4.0, 5.0],
        "precipitation": [0.0, 0.5, 2.0, 1.0],
    }
    hourly.update(overrides)
    return {"latitude": 52.52, "longitude": 13.4, "hourly": hourly}


class RequestTests(unittest.TestCase):
    def test_params_round_the_position_to_two_decimals(self) -> None:
        params = activity_weather_params(
            LATITUDE, LONGITUDE, date(2026, 9, 10), date(2026, 9, 11)
        )
        self.assertEqual(
            params,
            {
                "latitude": 52.51,
                "longitude": 13.41,
                "start_date": "2026-09-10",
                "end_date": "2026-09-11",
                "hourly": "temperature_2m,apparent_temperature,"
                "relative_humidity_2m,wind_speed_10m,precipitation",
                "timezone": "GMT",
                "wind_speed_unit": "ms",
            },
        )

    def test_client_requests_the_historical_forecast_with_rounded_coordinates(
        self,
    ) -> None:
        calls = []

        def request(method: str, url: str, **options: Any) -> dict[str, Any]:
            calls.append((method, url, options))
            return payload()

        result = ActivityWeatherClient(request).fetch(
            LATITUDE, LONGITUDE, date(2026, 9, 10), date(2026, 9, 10)
        )
        ((method, url, options),) = calls
        parsed = urlparse(url)
        self.assertEqual("GET", method)
        self.assertEqual("historical-forecast-api.open-meteo.com", parsed.netloc)
        self.assertEqual("/v1/forecast", parsed.path)
        self.assertEqual(SERVICE, options["service"])
        self.assertEqual(["52.51"], parse_qs(parsed.query)["latitude"])
        self.assertEqual(["13.41"], parse_qs(parsed.query)["longitude"])
        for needle in RAW_COORDINATES:
            self.assertNotIn(needle, url)
        # The response's own grid coordinates are not passed on.
        self.assertEqual({"hourly"}, set(result))

    def test_client_rejects_a_response_without_hourly_data(self) -> None:
        client = ActivityWeatherClient(lambda *_a, **_k: {"error": True})
        with self.assertRaises(TypeError):
            client.fetch(1.0, 2.0, date(2026, 9, 10), date(2026, 9, 10))

    def test_window_and_days_cross_midnight(self) -> None:
        start, end = activity_window(datetime(2026, 9, 10, 23, 30, tzinfo=UTC), 3600)
        self.assertEqual(datetime(2026, 9, 11, 0, 30, tzinfo=UTC), end)
        self.assertEqual((date(2026, 9, 10), date(2026, 9, 11)), utc_days(start, end))
        # A local start with an offset is converted to UTC.
        local = datetime.fromisoformat("2026-09-10T01:00:00+02:00")
        self.assertEqual(
            datetime(2026, 9, 9, 23, 0, tzinfo=UTC), activity_window(local, 60)[0]
        )


class ReductionTests(unittest.TestCase):
    def test_hours_around_a_full_hour_are_averaged_by_overlap(self) -> None:
        start, end = activity_window(START, 3600)
        weather = reduce_hourly(payload(), start, end)
        assert weather is not None
        # 05:00 and 06:00 each cover half the hour: (10 + 14) / 2 and so on.
        self.assertEqual(12.0, weather.temperature_c)
        self.assertEqual(26.0, weather.apparent_temperature_c)
        self.assertEqual(70.0, weather.relative_humidity_pct)
        self.assertEqual(3.0, weather.wind_speed_mps)
        # The 06:00 value is the rain of 05:00 to 06:00.
        self.assertEqual(2.0, weather.precipitation_mm)

    def test_a_short_activity_takes_its_share_of_the_precipitation(self) -> None:
        start, end = activity_window(START + timedelta(minutes=30), 1800)
        weather = reduce_hourly(payload(), start, end)
        assert weather is not None
        self.assertEqual(14.0, weather.temperature_c)
        self.assertEqual(1.0, weather.precipitation_mm)

    def test_missing_hours_are_skipped_and_no_value_is_none(self) -> None:
        start, end = activity_window(START, 3600)
        partial = reduce_hourly(
            payload(temperature_2m=[8.0, None, 14.0, 15.0]), start, end
        )
        assert partial is not None
        self.assertEqual(14.0, partial.temperature_c)
        empty = {
            key: [None] * 4
            for key in (
                "temperature_2m",
                "apparent_temperature",
                "relative_humidity_2m",
                "wind_speed_10m",
                "precipitation",
            )
        }
        self.assertIsNone(reduce_hourly(payload(**empty), start, end))
        self.assertIsNone(reduce_hourly({"hourly": {}}, start, end))

    def test_heat_note_starts_at_25_degrees_apparent(self) -> None:
        self.assertIsNone(heat_note(24.9))
        self.assertIsNone(heat_note(None))
        note = heat_note(25.0)
        assert note is not None
        self.assertIn("25,0", note)
        self.assertIn("Hitze", note)


class FakeFetch:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float, date, date]] = []
        self.fail = False
        self.response = payload()
        self.in_transaction = lambda: False
        self.inside = False

    def __call__(
        self, latitude: float, longitude: float, first: date, last: date
    ) -> dict[str, Any]:
        self.inside = self.inside or self.in_transaction()
        self.calls.append((latitude, longitude, first, last))
        if self.fail:
            raise RuntimeError("upstream is down")
        return self.response


def store_track(manager: Any, provider_activity_id: str = "g1") -> None:
    with manager.unit_of_work() as db:
        replace_detail_set(
            db,
            ActivityStreamSet(
                provider_activity_id=provider_activity_id,
                provenance=Provenance(
                    provider=ProviderId.GARMIN,
                    source_kind=SourceKind.PROVIDER_REPORTED,
                    source_record_id=None,
                    recorded_by=RecordingOrigin.GARMIN,
                    retrieved_at=START,
                    label="Garmin Connect",
                ),
                origin=ActivityDetailOrigin.FETCH,
                resolution=StreamResolution.FULL,
                channels={
                    StreamChannel.TIME_S: (0.0, 1.0, 2.0),
                    StreamChannel.HEART_RATE_BPM: (120.0, 121.0, 122.0),
                    StreamChannel.LATITUDE_DEG: (None, LATITUDE, 52.5124),
                    StreamChannel.LONGITUDE_DEG: (None, LONGITUDE, 13.4058),
                },
            ),
            mapper_version=1,
            summary_sha256=None,
            now=START.isoformat(),
        )


class StageCase(unittest.TestCase):
    batch_size = 20

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        self.now: datetime = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)
        self.key_values = KeyValueRepository(lambda: self.now.isoformat())
        self.home: tuple[float, float] | None = (51.1234, 6.5678)
        self.fetch = FakeFetch()
        self.transaction = False
        self.fetch.in_transaction = lambda: self.transaction
        original = self.manager.unit_of_work

        @contextmanager
        def tracked(*args: Any, **kwargs: Any) -> Any:
            with original(*args, **kwargs) as db:
                self.transaction = True
                try:
                    yield db
                finally:
                    self.transaction = False

        self.manager.unit_of_work = tracked  # type: ignore[method-assign]
        self.stage = ActivityWeatherStage(
            key_values=self.key_values,
            zone_provider=lambda: ZONE,
            clock=lambda: self.now.isoformat(),
            fetch=self.fetch,
            home_location=lambda _db: self.home,
            batch_size=self.batch_size,
        )
        add_session_record(
            self.manager,
            ProviderId.GARMIN,
            "g1",
            "act_g1",
            moving_duration_s=3600.0,
        )

    def _run_once(self) -> BatchReport:
        self.stage.prefetch(lambda: self.manager)
        with self.manager.unit_of_work() as db:
            return self.stage.run_batch(db)

    def _rows(self) -> list[dict[str, Any]]:
        with self.manager.reader() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM observations WHERE method = ? AND state = 'active' "
                    "ORDER BY metric",
                    ("open-meteo-activity-weather",),
                )
            ]

    def block(self, session: str = "act_g1") -> dict[str, Any]:
        with self.manager.reader() as db:
            found = weather_block(stored_activity_weather(db).get(session, {}))
        assert found is not None
        return found


class StageTests(StageCase):
    def test_start_position_is_fetched_rounded_and_stored(self) -> None:
        store_track(self.manager)
        report = self._run_once()
        self.assertTrue(report.done)
        self.assertEqual(
            [(52.51, 13.41, date(2026, 9, 10), date(2026, 9, 10))], self.fetch.calls
        )
        self.assertEqual(
            {
                "temperature_c": 12.0,
                "apparent_temperature_c": 26.0,
                "relative_humidity_pct": 70.0,
                "wind_speed_mps": 3.0,
                "precipitation_mm": 2.0,
                "location_kind": "activity_start",
                "source": "Open-Meteo Modell, Startposition",
            },
            {k: v for k, v in self.block().items() if k != "heat_note"},
        )
        self.assertIn("Hitze", self.block()["heat_note"])
        rows = self._rows()
        self.assertEqual(
            {
                "activity_weather_temperature": "C",
                "activity_weather_apparent_temperature": "C",
                "activity_weather_humidity": "%",
                "activity_weather_wind_speed": "m/s",
                "activity_weather_precipitation": "mm",
            },
            {row["metric"]: row["unit"] for row in rows},
        )
        self.assertEqual(
            {"Open-Meteo Modell, Startposition"}, {r["label"] for r in rows}
        )
        self.assertEqual({"act_g1"}, {r["owner_record_id"] for r in rows})

    def test_a_stored_result_is_never_fetched_again(self) -> None:
        store_track(self.manager)
        self._run_once()
        second = self._run_once()
        self.assertEqual(1, len(self.fetch.calls))
        self.assertEqual(0, second.items)
        self.now += timedelta(days=3)
        self._run_once()
        self.assertEqual(1, len(self.fetch.calls))

    def test_without_a_position_the_home_location_is_used_and_labelled(self) -> None:
        self._run_once()
        self.assertEqual(
            [(51.12, 6.57, date(2026, 9, 10), date(2026, 9, 10))], self.fetch.calls
        )
        block = self.block()
        assert block is not None
        self.assertEqual("home", block["location_kind"])
        self.assertEqual("Open-Meteo Modell, Wohnort", block["source"])
        self.assertEqual(
            {"Open-Meteo Modell, Wohnort"}, {r["label"] for r in self._rows()}
        )

    def test_without_position_and_home_nothing_is_fetched_until_a_home_exists(
        self,
    ) -> None:
        self.home = None
        self._run_once()
        self._run_once()
        self.assertEqual([], self.fetch.calls)
        self.assertEqual([], self._rows())
        self.home = (51.1234, 6.5678)
        self._run_once()
        self.assertEqual(1, len(self.fetch.calls))
        self.assertEqual(5, len(self._rows()))

    def test_a_moved_home_looks_up_a_home_session_again_but_not_a_start(self) -> None:
        add_session_record(
            self.manager, ProviderId.GARMIN, "g2", "act_g2", moving_duration_s=3600.0
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET started_at = ? WHERE provider_activity_id = ?",
                ("2026-09-11T05:00:00+00:00", "g2"),
            )
            db.execute(
                "UPDATE activity_sessions SET started_at = ? WHERE activity_id = ?",
                ("2026-09-11T05:00:00+00:00", "act_g2"),
            )
        store_track(self.manager, "g2")
        self.fetch.response = payload()
        self._run_once()
        self.assertEqual(2, len(self.fetch.calls))
        self.home = (48.1374, 11.5755)
        self._run_once()
        # Only the session without a position follows the home location.
        self.assertEqual(3, len(self.fetch.calls))
        self.assertEqual((48.14, 11.58), self.fetch.calls[-1][:2])

    def test_deleting_the_tracks_looks_the_session_up_at_home(self) -> None:
        store_track(self.manager)
        self._run_once()
        with self.manager.unit_of_work() as db:
            delete_stored_tracks(db)
        self._run_once()
        self.assertEqual(2, len(self.fetch.calls))
        self.assertEqual("home", self.block()["location_kind"])
        self.assertEqual(5, len(self._rows()))

    def test_a_failed_fetch_writes_nothing_and_backs_off(self) -> None:
        store_track(self.manager)
        self.fetch.fail = True
        with self.assertLogs("intervals_coach", level="WARNING"):
            report = self._run_once()
        self.assertTrue(report.done)
        self.assertEqual([], self._rows())
        with self.manager.reader() as db:
            self.assertEqual(
                {},
                json.loads(self.key_values.get(db, "activity_weather_state") or "{}")[
                    "empty"
                ],
            )
        self._run_once()
        self.assertEqual(1, len(self.fetch.calls), "no retry before the backoff ends")
        self.now += timedelta(minutes=31)
        with self.assertLogs("intervals_coach", level="WARNING"):
            self._run_once()
        self.assertEqual(2, len(self.fetch.calls))
        # The second failure doubles the delay.
        self.now += timedelta(minutes=31)
        self._run_once()
        self.assertEqual(2, len(self.fetch.calls))
        self.fetch.fail = False
        self.now += timedelta(hours=2)
        self._run_once()
        self.assertEqual(5, len(self._rows()))

    def test_only_outdoor_rides_and_runs_since_2022_are_looked_up(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE activity_records SET environment = 'indoor'")
        self._run_once()
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET environment = 'outdoor', sport = 'swim'"
            )
        self._run_once()
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET sport = 'ride', started_at = ?",
                ("2021-12-31T23:00:00+00:00",),
            )
        self._run_once()
        self.assertEqual([], self.fetch.calls)

    def test_an_unknown_environment_needs_a_stored_start_position(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE activity_records SET environment = 'unknown'")
        # Never the home fallback: without a position the session stays out.
        self._run_once()
        self._run_once()
        self.assertEqual([], self.fetch.calls)
        self.assertEqual([], self._rows())
        store_track(self.manager)
        self._run_once()
        self.assertEqual(
            [(52.51, 13.41, date(2026, 9, 10), date(2026, 9, 10))], self.fetch.calls
        )
        self.assertEqual("activity_start", self.block()["location_kind"])
        self.assertEqual(5, len(self._rows()))

    def test_a_session_that_just_ended_waits_for_its_forecast(self) -> None:
        self.now = START + timedelta(hours=2)
        self._run_once()
        self.assertEqual([], self.fetch.calls)
        self.now = START + timedelta(hours=50)
        self._run_once()
        self.assertEqual(1, len(self.fetch.calls))

    def test_a_response_without_values_is_remembered_not_refetched(self) -> None:
        self.fetch.response = payload(
            **{
                key: [None] * 4
                for key in (
                    "temperature_2m",
                    "apparent_temperature",
                    "relative_humidity_2m",
                    "wind_speed_10m",
                    "precipitation",
                )
            }
        )
        self._run_once()
        self._run_once()
        self.assertEqual(1, len(self.fetch.calls))
        self.assertEqual([], self._rows())

    def test_gone_sessions_retire_their_rows(self) -> None:
        self._run_once()
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE activity_sessions SET state = 'deleted'")
        self._run_once()
        self.assertEqual([], self._rows())
        with self.manager.reader() as db:
            self.assertEqual({}, stored_activity_weather(db))

    def test_the_summary_is_content_free(self) -> None:
        store_track(self.manager)
        self._run_once()
        with self.manager.reader() as db:
            summary = summarize_activity_weather(self.key_values, db)
        self.assertEqual("complete", summary["status"])
        self.assertEqual(1, summary["counts"]["with_values"])


class BoundedBatchTests(StageCase):
    batch_size = 1

    def test_one_session_is_looked_up_per_batch(self) -> None:
        add_session_record(
            self.manager, ProviderId.GARMIN, "g2", "act_g2", moving_duration_s=3600.0
        )
        first = self._run_once()
        self.assertFalse(first.done)
        self.assertEqual(1, len(self.fetch.calls))
        second = self._run_once()
        self.assertTrue(second.done)
        self.assertEqual(2, len(self.fetch.calls))
        self.assertEqual(10, len(self._rows()))


class WorkerTests(StageCase):
    def test_no_request_is_made_inside_the_writer_transaction(self) -> None:
        class Canonical:
            def run_batch(self, _db: Any) -> BatchReport:
                return BatchReport(items=0, done=True)

            def mark_failed(self, _db: Any) -> None:
                raise AssertionError

        worker = CanonicalBackfillWorker(
            backfill=Canonical(),  # type: ignore[arg-type]
            database=lambda: self.manager,
            maintenance_gate=MaintenanceGate(),
            poll_seconds=0,
            followups=(self.stage,),
        )
        worker.run_loop()
        self.assertEqual(1, len(self.fetch.calls))
        self.assertFalse(self.fetch.inside)
        self.assertEqual(5, len(self._rows()))


class ReadTests(StageCase):
    def test_the_heat_note_follows_the_stored_apparent_temperature(self) -> None:
        self.fetch.response = payload(apparent_temperature=[20.0, 24.9, 24.9, 30.0])
        self._run_once()
        self.assertNotIn("heat_note", self.block())

    def test_home_coordinates_come_from_the_cached_geocoding(self) -> None:
        cached = {
            "query": "Berlin",
            "location": {"latitude": 52.52, "longitude": 13.405},
        }
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, weather_cache.CACHE_KEY, json.dumps(cached))
        with self.manager.reader() as db:
            self.assertEqual(
                (52.52, 13.405), home_coordinates(self.key_values, db, " Berlin ")
            )
            self.assertIsNone(home_coordinates(self.key_values, db, "Hamburg"))
            self.assertIsNone(home_coordinates(self.key_values, db, ""))


class _Logger:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def info(self, message: str, **kwargs: Any) -> None:
        self.records.append((message, kwargs))

    def warning(self, message: str, **kwargs: Any) -> None:
        self.records.append((message, kwargs))

    exception = warning


class _Capture:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    def capture(self, event: str, details: Any) -> None:
        redactor = Redactor(cast(Any, lambda: SimpleNamespace()))
        self.entries.append((event, redactor.sanitize_diagnostic_value(details)))


class _Response:
    status = 200

    def __init__(self, body: dict[str, Any]) -> None:
        self.headers = {"Content-Type": "application/json"}
        self.body = json.dumps(body).encode()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int) -> bytes:
        return self.body

    def close(self) -> None:
        return None


class PrivacyTests(StageCase):
    def test_no_raw_coordinate_leaves_the_stored_streams(self) -> None:
        store_track(self.manager)
        logger, capture, opened = _Logger(), _Capture(), []

        def opener(request: Any, timeout: float) -> _Response:
            opened.append(request.full_url)
            # Open-Meteo names the grid cell it used.
            return _Response({**payload(), "latitude": 52.5234, "longitude": 13.4115})

        client = JsonHttpClient(
            "1.0.0",
            1_000_000,
            logger,
            capture,
            lambda value: str(value),
            lambda headers: {},
            lambda: {"operation_id": "op-1", "trigger": "test"},
            opener=opener,
            monotonic=lambda: 1.0,
        )
        self.stage = ActivityWeatherStage(
            key_values=self.key_values,
            zone_provider=lambda: ZONE,
            clock=lambda: self.now.isoformat(),
            fetch=ActivityWeatherClient(client.request).fetch,
            home_location=lambda _db: self.home,
        )
        with self.assertLogs("intervals_coach", level="DEBUG") as stage_logs:
            self._run_once()

        # The request carries only the rounded position.
        (url,) = opened
        self.assertEqual(["52.51"], parse_qs(urlparse(url).query)["latitude"])

        surfaces: dict[str, str] = {}
        with self.manager.reader() as db:
            surfaces["observations"] = json.dumps(
                [dict(row) for row in db.execute("SELECT * FROM observations")],
                default=str,
            )
            surfaces["kv"] = json.dumps(
                [dict(row) for row in db.execute("SELECT * FROM kv")], default=str
            )
            surfaces["diagnostics"] = json.dumps(
                summarize_activity_weather(self.key_values, db)
            )
            surfaces["block"] = json.dumps(
                weather_block(stored_activity_weather(db).get("act_g1", {}))
            )
            document = CanonicalDetailReader(
                CanonicalTableReader().session_activities, refreshable=frozenset
            ).read(db, "act_g1")
            surfaces["detail"] = json.dumps(document, default=str)
        surfaces["stage log"] = json.dumps(
            [(r.getMessage(), r.__dict__) for r in stage_logs.records], default=str
        )
        surfaces["transport log"] = json.dumps(logger.records, default=str)
        surfaces["debug capture"] = json.dumps(capture.entries, default=str)
        for name, text in surfaces.items():
            for needle in RAW_COORDINATES:
                with self.subTest(surface=name, value=needle):
                    self.assertNotIn(needle, text)
        # The streams do hold the position: the surfaces above are the guard.
        with self.manager.reader() as db:
            stored = json.dumps(
                [
                    dict(row)
                    for row in db.execute(
                        "SELECT channel FROM activity_stream_channels"
                    )
                ]
            )
        self.assertIn("latitude_deg", stored)


if __name__ == "__main__":
    unittest.main()
