"""Garmin Personal API transport and per-family routing with a mocked HTTP opener.

The payloads are small synthetic shapes derived from the sanitized Personal API
probe (2026-11-06): flat ``dailySleep`` rows, ``hrvSummaries``, ``data`` daily
summaries, ``dailyWeightSummaries`` and activity list entries. No real account,
key or token is used.
"""

from __future__ import annotations

import io
import json
import unittest
import zipfile
from datetime import UTC, date, datetime
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from support import load_provider_fixture

from backend.canonical.section_items import merge_records, record_identity
from backend.providers import http as provider_http
from backend.providers.garmin import (
    GarminCollectionOptions,
    collect_garmin_activity_detail,
    collect_garmin_data,
)
from backend.providers.garmin_activity_mapping import map_garmin_activities
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.providers.garmin_personal import (
    PERSONAL_BASE_URL,
    PERSONAL_METHODS,
    TOKEN_PATH,
    GarminPersonalClient,
    GarminTransportClient,
    fit_from_archive,
    wrap_daily_sleep,
)
from tests.test_garmin_activity_detail_mapping import _synthetic_fit

SYNTHETIC_KEY = "synthetic-personal-key"
DAY = "2026-11-03"


def _token(label: str) -> str:
    return f"header.{label}.signature"


def _activity(activity_id: int = 900001) -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityName": "Synthetic run",
        "startTimeLocal": f"{DAY} 11:47:18",
        "startTimeGMT": f"{DAY} 10:47:18",
        "activityType": {"typeId": 1, "typeKey": "running", "parentTypeId": 17},
        "distance": 9780.0,
        "duration": 2975.0,
        "elapsedDuration": 2975.0,
        "movingDuration": 2966.0,
        "averageHR": 142.0,
        "maxHR": 169.0,
    }


def _flat_sleep(day: str = DAY, sleep_id: int = 1) -> dict[str, Any]:
    return {
        "id": sleep_id,
        "calendarDate": day,
        "sleepTimeSeconds": 25440,
        "sleepStartTimestampGMT": 1793656244000,
        "sleepEndTimestampGMT": 1793681744000,
        "averageSpO2Value": 96.0,
        "averageRespirationValue": 15.0,
        "avgHeartRate": 49.0,
        "sleepScores": {"overall": {"value": 84}},
    }


def _personal_heart_rate_zones() -> Any:
    return load_provider_fixture("garmin/personal/heart_rate_zones.json")


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


_FIT = _synthetic_fit()
_ARCHIVE = _zip({"900001_ACTIVITY.fit": _FIT})


class _Response(io.BytesIO):
    status = 200


class FakePersonalApi:
    """Answer Personal API paths from synthetic payloads and record the requests."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, list[str]], dict[str, str]]] = []
        self.tokens = iter(_token(f"t{index}") for index in range(1, 100))
        self.reject_bearer: set[str] = set()
        self.activities = [_activity()]

    def __call__(self, request: Any, timeout: float) -> _Response:
        parsed = urlparse(request.full_url)
        headers = {key.lower(): value for key, value in request.header_items()}
        query = parse_qs(parsed.query)
        self.requests.append((request.get_method(), parsed.path, query, headers))
        if parsed.path == TOKEN_PATH:
            if headers.get("authorization") != f"ApiKey {SYNTHETIC_KEY}":
                raise HTTPError(
                    request.full_url, 401, "Unauthorized", Message(), io.BytesIO()
                )
            return _Response(f'"{next(self.tokens)}"'.encode())
        bearer = headers.get("authorization", "").removeprefix("Bearer ")
        if bearer in self.reject_bearer:
            raise HTTPError(
                request.full_url, 401, "Unauthorized", Message(), io.BytesIO()
            )
        payload = self.payload(parsed.path, query)
        if isinstance(payload, bytes):
            return _Response(payload)
        return _Response(json.dumps(payload).encode())

    def payload(self, path: str, query: dict[str, list[str]]) -> Any:
        if path == "/activitylist-service/activities/search/activities":
            start = int(query["start"][0])
            return self.activities if start == 0 else []
        if path == "/download-service/files/activity/900001":
            return _ARCHIVE
        if path == "/activity-service/activity/900001":
            return {
                "activityId": 900001,
                "summaryDTO": {
                    "directWorkoutRpe": 60,
                    "directWorkoutFeel": 75,
                    "minHR": 97,
                },
            }
        if path.startswith("/activity-service/activity/") and path.endswith("/details"):
            return {
                "activityId": 900001,
                "metricDescriptors": [],
                "activityDetailMetrics": [],
            }
        if path == "/sleep-service/sleep/dailySleepSummariesByDate":
            return [_flat_sleep(query["startDate"][0])]
        if path == "/sleep-service/sleep/dailySleep":
            return _flat_sleep(query["date"][0])
        if path.startswith("/hrv-service/hrv/daily/"):
            return {
                "hrvSummaries": [
                    {"calendarDate": DAY, "lastNightAvg": 57, "weeklyAvg": 55}
                ]
            }
        if path == "/usersummary-service/v2/dailysummaries":
            return {
                "data": [
                    {
                        "calendarDate": query["startDate"][0],
                        "heartRate": {"restingHeartRate": 45},
                    }
                ]
            }
        if path == "/usersummary-service/usersummary/daily":
            return {"calendarDate": query["calendarDate"][0], "bmrKilocalories": 1700}
        if path == "/wellness-service/wellness/dailyHeartRate":
            return {"calendarDate": query["date"][0], "restingHeartRate": 45}
        if path == "/biometric-service/heartRateZones/v2":
            return _personal_heart_rate_zones()
        if path == "/wellness-service/wellness/bodyBattery/reports/daily":
            return [{"date": query["startDate"][0], "charged": 71}]
        if path.startswith("/weight-service/weight/range/"):
            return {
                "dailyWeightSummaries": [
                    {
                        "summaryDate": DAY,
                        "latestWeight": {"weight": 75000.0, "calendarDate": DAY},
                    }
                ]
            }
        raise HTTPError(path, 404, "Not Found", Message(), io.BytesIO())

    def data_paths(self) -> list[str]:
        return [
            path
            for _method, path, _query, _headers in self.requests
            if path != TOKEN_PATH
        ]


def _throttled(headers: Message) -> Any:
    """An opener answering every request with HTTP 429 and these headers."""

    def opener(request: Any, timeout: float) -> Any:
        raise HTTPError(request.full_url, 429, "Too Many", headers, io.BytesIO())

    return opener


def _client(
    api: FakePersonalApi, clock: list[float] | None = None
) -> GarminPersonalClient:
    now = clock or [1_000.0]
    return GarminPersonalClient(SYNTHETIC_KEY, opener=api, clock=lambda: now[0])


# SDK methods the app calls that the Personal API does not serve (#1767 probe).
SDK_ONLY_METHODS = frozenset(
    {
        "get_user_profile",
        "get_gear",
        "get_gear_stats",
        "get_gear_activities",
        "get_training_load_activities",
        "get_endurance_score",
        "get_race_predictions",
        "get_running_tolerance",
        "get_training_four_week_load_balance",
        "get_weekly_training_status",
        "get_daily_training_status",
        "get_training_readiness",
        "get_training_readiness_range",
        "get_training_status",
        "get_max_metrics_range",
        "get_cycling_ftp",
        "get_functional_threshold_power_range",
        "get_lactate_threshold",
        "get_activity_splits",
        "get_activity_hr_in_timezones",
        "get_activity_power_in_timezones",
    }
)


class FakeSdk:
    """The unofficial SDK surface: records which methods were called."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def login(self, tokenstore: str | None = None) -> tuple[Any, Any]:
        self.calls.append("login")
        return None, None

    def get_training_readiness(self, day: str) -> list[dict[str, Any]]:
        self.calls.append("get_training_readiness")
        return [{"calendarDate": day, "score": 70}]

    def get_activities_by_date(self, *_args: Any) -> list[dict[str, Any]]:
        self.calls.append("get_activities_by_date")
        return [_activity()]

    def get_heart_rate_zones(self) -> list[dict[str, Any]]:
        self.calls.append("get_heart_rate_zones")
        return [{"sport": "DEFAULT", "maxHeartRateUsed": 190}]

    def __getattr__(self, name: str) -> Any:
        # The other SDK families the app calls are recorded no-ops, so routing
        # can be asserted; any other name stays absent like on the real SDK.
        if name in SDK_ONLY_METHODS:
            method = lambda *_args, **_kwargs: self.calls.append(name)
            self.__dict__[name] = method
            return method
        raise AttributeError(name)


class PersonalClientTests(unittest.TestCase):
    def test_key_is_exchanged_once_and_sent_only_to_the_token_path(self) -> None:
        api = FakePersonalApi()
        client = _client(api)

        client.get_user_summary(DAY)
        client.get_heart_rates(DAY)

        token_requests = [r for r in api.requests if r[1] == TOKEN_PATH]
        self.assertEqual(len(token_requests), 1)
        self.assertEqual(token_requests[0][0], "POST")
        for _method, path, _query, headers in api.requests:
            if path == TOKEN_PATH:
                continue
            self.assertEqual(headers["authorization"], f"Bearer {_token('t1')}")
            self.assertNotIn(SYNTHETIC_KEY, json.dumps(headers))
        self.assertTrue(all(r[1].startswith("/") for r in api.requests))
        self.assertNotIn(SYNTHETIC_KEY, repr(client))

    def test_expired_or_rejected_token_is_exchanged_again(self) -> None:
        api = FakePersonalApi()
        clock = [1_000.0]
        client = _client(api, clock)
        client.get_user_summary(DAY)
        clock[0] += 24 * 3600
        client.get_user_summary(DAY)
        api.reject_bearer.add(_token("t2"))
        client.get_user_summary(DAY)

        self.assertEqual(sum(r[1] == TOKEN_PATH for r in api.requests), 3)

    def test_rejected_key_raises_a_safe_authentication_error(self) -> None:
        api = FakePersonalApi()
        client = GarminPersonalClient("wrong-synthetic-key", opener=api)

        with self.assertRaises(provider_http.ProviderHTTPError) as raised:
            client.get_user_summary(DAY)

        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(raised.exception.category, "authentication")
        self.assertNotIn("wrong-synthetic-key", str(raised.exception))

    def test_throttling_carries_the_named_wait_and_ids_take_one_request(
        self,
    ) -> None:
        api = FakePersonalApi()
        client = _client(api)
        self.assertEqual(["900001"], client.newest_activity_ids(DAY, DAY))
        self.assertEqual(
            ["/activitylist-service/activities/search/activities"], api.data_paths()
        )

        for header, wait in (
            ("120", 120.0),
            ("99999999999", 86400.0),
            ("²", None),
            ("soon", None),
            (None, None),
        ):
            with self.subTest(header=header):
                headers = Message()
                if header is not None:
                    headers["Retry-After"] = header

                with self.assertRaises(provider_http.ProviderHTTPError) as raised:
                    GarminPersonalClient(
                        SYNTHETIC_KEY, opener=_throttled(headers)
                    ).verify_key()
                self.assertEqual("rate_limited", raised.exception.category)
                self.assertEqual(wait, raised.exception.retry_after)
        self.assertEqual(
            30.0,
            provider_http.parse_retry_after(
                "Thu, 12 Nov 2026 10:00:30 GMT",
                now=datetime(2026, 11, 12, 10, tzinfo=UTC).timestamp(),
            ),
        )

    def test_families_use_the_personal_paths(self) -> None:
        api = FakePersonalApi()
        client = _client(api)

        self.assertEqual(client.get_activities_by_date(DAY, DAY), [_activity()])
        client.get_activity_details("900001", maxchart=2000)
        client.get_hrv_data_range(DAY, DAY)
        client.get_body_battery(DAY, DAY)
        client.get_weigh_ins(DAY, DAY)
        client.get_heart_rate_zones()

        self.assertEqual(
            api.data_paths(),
            [
                "/activitylist-service/activities/search/activities",
                "/activitylist-service/activities/search/activities",
                "/activity-service/activity/900001/details",
                f"/hrv-service/hrv/daily/{DAY}/{DAY}",
                "/wellness-service/wellness/bodyBattery/reports/daily",
                f"/weight-service/weight/range/{DAY}/{DAY}",
                "/biometric-service/heartRateZones/v2",
            ],
        )
        self.assertEqual(PERSONAL_BASE_URL, "https://personal.connectapi.garmin.com")

    def test_ranges_are_split_into_the_personal_api_day_limits(self) -> None:
        api = FakePersonalApi()
        client = _client(api)

        summaries = client.get_daily_summaries("2026-01-01", "2026-03-01")
        sleep = client.get_sleep_daily("2026-01-01", "2026-03-01")

        summary_windows = [
            (q["startDate"][0], q["endDate"][0])
            for _m, path, q, _h in api.requests
            if path == "/usersummary-service/v2/dailysummaries"
        ]
        self.assertEqual(
            summary_windows,
            [
                ("2026-01-01", "2026-01-31"),
                ("2026-02-01", "2026-03-01"),
            ],
        )
        self.assertEqual(len(summaries["data"]), 2)
        self.assertEqual(
            [night["calendarDate"] for night in sleep], ["2026-01-01", "2026-02-01"]
        )

    def test_flat_daily_sleep_is_wrapped_like_the_sdk(self) -> None:
        api = FakePersonalApi()
        client = _client(api)

        self.assertEqual(client.get_sleep_data(DAY), {"dailySleepDTO": _flat_sleep()})
        self.assertEqual(
            client.get_sleep_daily(DAY, DAY),
            [{"calendarDate": DAY, "dailySleepDTO": _flat_sleep()}],
        )
        self.assertIsNone(wrap_daily_sleep({"id": 3}))


class TransportRoutingTests(unittest.TestCase):
    def test_personal_families_use_the_personal_api_and_others_the_sdk(self) -> None:
        api = FakePersonalApi()
        sdk = FakeSdk()
        client = GarminTransportClient(_client(api), sdk)

        client.get_activities_by_date(DAY, DAY)
        client.get_training_readiness(DAY)

        self.assertEqual(sdk.calls, ["get_training_readiness"])
        self.assertIn(
            "/activitylist-service/activities/search/activities", api.data_paths()
        )
        self.assertEqual(client.login("synthetic"), (None, None))
        self.assertEqual(sdk.calls[-1], "login")

    def test_heart_rate_zones_use_the_personal_api_when_a_key_exists(self) -> None:
        api = FakePersonalApi()
        sdk = FakeSdk()

        zones = GarminTransportClient(_client(api), sdk).get_heart_rate_zones()

        self.assertEqual(zones, _personal_heart_rate_zones())
        self.assertEqual(api.data_paths(), ["/biometric-service/heartRateZones/v2"])
        self.assertEqual(sdk.calls, [])

    def test_sdk_only_families_stay_on_the_sdk_with_a_key(self) -> None:
        sdk = FakeSdk()
        client = GarminTransportClient(_client(FakePersonalApi()), sdk)

        for name in sorted(SDK_ONLY_METHODS):
            with self.subTest(name=name):
                self.assertEqual(getattr(client, name), getattr(sdk, name))

    def test_sdk_only_names_are_the_collector_calls_and_not_personal(self) -> None:
        collector = (
            Path(__file__).resolve().parents[1] / "backend/providers/garmin.py"
        ).read_text(encoding="utf-8")

        self.assertFalse(SDK_ONLY_METHODS & PERSONAL_METHODS)
        for name in sorted(SDK_ONLY_METHODS | {"get_heart_rate_zones"}):
            with self.subTest(name=name):
                self.assertRegex(collector, rf"\b{name}\b")

    def test_without_the_sdk_its_families_are_absent(self) -> None:
        client = GarminTransportClient(_client(FakePersonalApi()), None)

        self.assertIsNone(getattr(client, "get_training_readiness", None))
        self.assertIsNone(getattr(client, "get_activity_splits", None))
        self.assertEqual(client.login("synthetic"), (None, None))

    def test_without_a_key_every_family_uses_the_sdk(self) -> None:
        sdk = FakeSdk()
        client = GarminTransportClient(None, sdk)

        client.get_activities_by_date(DAY, DAY)
        client.get_heart_rate_zones()

        self.assertEqual(sdk.calls, ["get_activities_by_date", "get_heart_rate_zones"])


def _external_call(_service: str, _operation: str, call: Any, _details: Any) -> Any:
    return call()


class PersonalOnlyCollectionTests(unittest.TestCase):
    def test_personal_key_alone_syncs_every_personal_family_without_errors(
        self,
    ) -> None:
        api = FakePersonalApi()
        client = GarminTransportClient(_client(api), None)
        day = date.fromisoformat(DAY)

        payload = collect_garmin_data(
            client,
            [(day, day)],
            start=day,
            today=day,
            synced_at="2026-11-06T08:00:00Z",
            external_call=_external_call,
            redact=str,
            options=GarminCollectionOptions(),
        )

        self.assertEqual(payload["errors"], [])
        self.assertEqual([row["activityId"] for row in payload["activities"]], [900001])
        self.assertEqual(
            payload["activity_ratings"],
            [
                {
                    "activityId": "900001",
                    "startTimeLocal": f"{DAY} 11:47:18",
                    "directWorkoutRpe": 60,
                    "directWorkoutFeel": 75,
                    "minHR": 97,
                }
            ],
        )
        self.assertEqual(
            payload["sleep"], [{"calendarDate": DAY, "dailySleepDTO": _flat_sleep()}]
        )
        self.assertEqual(payload["hrv"][0]["lastNightAvg"], 57)
        self.assertEqual(payload["daily_stats"][0]["calendarDate"], DAY)
        self.assertEqual(payload["resting_hr"][0]["restingHeartRate"], 45)
        self.assertIn("dailyWeightSummaries", payload["weight"])
        self.assertEqual(payload["heart_rate_zones"], _personal_heart_rate_zones())
        for absent in (
            "readiness",
            "race_predictions",
            "max_metrics",
            "training_status",
        ):
            self.assertNotIn(absent, payload)

    def test_activity_detail_without_the_sdk_is_complete_with_its_details(self) -> None:
        client = GarminTransportClient(_client(FakePersonalApi()), None)

        detail = collect_garmin_activity_detail(
            client, "900001", external_call=_external_call, redact=str
        )

        self.assertEqual(set(detail), {"activity_id", "details", "fit"})
        self.assertEqual(detail["fit"], _FIT)

    def test_activity_detail_with_only_the_sdk_reads_no_fit(self) -> None:
        sdk = FakeSdk()
        client = GarminTransportClient(None, sdk)

        self.assertIsNone(getattr(client, "download_activity_fit", None))


class FitDownloadTests(unittest.TestCase):
    def test_fit_is_extracted_from_the_activity_archive(self) -> None:
        api = FakePersonalApi()

        self.assertEqual(_client(api).download_activity_fit("900001"), _FIT)
        download = [r for r in api.requests if r[1].startswith("/download-service/")]
        self.assertEqual(download[0][3]["accept"], "*/*")

    def test_activity_without_a_fit_file_has_no_fit_part(self) -> None:
        api = FakePersonalApi()
        client = _client(api)
        # 404 (no file) and a GPX upload are not failures of the detail fetch.
        self.assertIsNone(client.download_activity_fit("900002"))
        original = api.payload

        def gpx_upload(path: str, query: dict[str, list[str]]) -> Any:
            if path.startswith("/download-service/"):
                return _zip({"900001_ACTIVITY.gpx": b"<gpx/>"})
            return original(path, query)

        api.payload = gpx_upload  # type: ignore[method-assign]
        detail = collect_garmin_activity_detail(
            GarminTransportClient(client, None),
            "900001",
            external_call=_external_call,
            redact=str,
        )
        self.assertNotIn("errors", detail)
        self.assertIsNone(detail["fit"])

    def test_bare_fit_is_accepted_and_other_archives_are_rejected(self) -> None:
        self.assertEqual(fit_from_archive(_FIT), _FIT)
        for data in (_zip({"notes.txt": b"x"}), _zip({"a.fit": b"not fit"}), b"junk"):
            with (
                self.subTest(data=data[:8]),
                self.assertRaises(provider_http.ProviderInvalidResponse),
            ):
                fit_from_archive(data)


class TransportParityTests(unittest.TestCase):
    def test_one_activity_from_both_transports_maps_to_one_identity(self) -> None:
        sdk_row = {**_activity(), "vO2MaxValue": 55.0, "timeZoneId": 124}
        personal_row = _activity()
        retrieved = datetime(2026, 11, 6, tzinfo=UTC)
        zone = ZoneInfo("Europe/Berlin")

        sdk = map_garmin_activities([sdk_row], zone=zone, retrieved_at=retrieved)
        personal = map_garmin_activities(
            [personal_row], zone=zone, retrieved_at=retrieved
        )

        self.assertEqual(
            {record.activity_id for record in sdk.records},
            {record.activity_id for record in personal.records},
        )
        self.assertEqual(record_identity(sdk_row), record_identity(personal_row))
        self.assertEqual(len(merge_records([personal_row], [sdk_row])), 1)

    def test_one_night_from_both_transports_is_stored_once(self) -> None:
        # The SDK morning read stores the night keyed by its date; the sleep id
        # differs on purpose and must not split the night.
        sdk_night = {"calendarDate": DAY, "dailySleepDTO": _flat_sleep(sleep_id=111)}
        personal_night = wrap_daily_sleep(_flat_sleep(sleep_id=222))

        self.assertEqual(record_identity(sdk_night), record_identity(personal_night))
        merged = merge_records([personal_night], [sdk_night])
        self.assertEqual(merged, [personal_night])

    def test_wrapped_personal_night_maps_sleep_duration_and_score(self) -> None:
        result = map_garmin_health(
            {"sleep": [wrap_daily_sleep(_flat_sleep())]},
            zone=ZoneInfo("Europe/Berlin"),
            retrieved_at=datetime(2026, 11, 6, tzinfo=UTC),
        )

        kinds = {
            observation.kind.value: observation.value.value
            for observation in result.records
        }
        self.assertEqual(kinds.get("sleep_duration"), 25440)
        self.assertEqual(kinds.get("sleep_score"), 84)


if __name__ == "__main__":
    unittest.main()


class RemoteReaderTransportTests(unittest.TestCase):
    """The reader keeps the Personal API families when the SDK login fails."""

    def _reader(self, factory: Any, **changes: Any) -> Any:
        from unittest.mock import Mock

        from support import make_config

        from backend.sync.garmin_service import GarminRemoteReader

        settings: dict[str, Any] = {
            "openai_base_url": "",
            "openai_model": "",
            "intervals_athlete_id": "",
            "data_retention_days": 30,
            "garmin_email": "athlete@example.invalid",
            "garmin_password": "synthetic",
            "garmin_tokenstore": "missing-tokenstore",
            "garmin_personal_api_key": SYNTHETIC_KEY,
        }
        config = make_config(**{**settings, **changes})
        return GarminRemoteReader(
            config,
            factory,
            Mock(),
            Mock(),
            lambda value: value,
            Mock(),
            lambda: "2026-11-06T08:00:00+00:00",
            lambda: date(2026, 11, 6),
            date(2000, 1, 1),
            90,
            -1,
        )

    def _factory(self, login: Any) -> Any:
        from unittest.mock import Mock

        sdk = Mock()
        sdk.login.side_effect = login
        factory = Mock()
        factory.available.return_value = True
        factory.create.return_value = sdk
        return factory

    def test_failed_sdk_login_keeps_the_personal_families(self) -> None:
        def fail(_argument: Any) -> Any:
            raise RuntimeError("synthetic SDK login failure")

        reader = self._reader(self._factory(fail))

        client, _argument = reader._authenticated_client(_external_call)

        self.assertIsNone(client.sdk)
        self.assertIsNotNone(client.personal)

    def test_pending_mfa_keeps_the_personal_families(self) -> None:
        reader = self._reader(self._factory(lambda _argument: ("needs_mfa", {})))

        client, _argument = reader._authenticated_client(_external_call)

        self.assertIsNone(client.sdk)

    def test_cancellation_during_sdk_login_still_stops(self) -> None:
        from backend.errors import AppError

        def cancel(_argument: Any) -> Any:
            raise AppError(499, "cancelled", reason="chat_cancelled")

        reader = self._reader(self._factory(cancel))

        with self.assertRaises(AppError):
            reader._authenticated_client(_external_call)

    def test_key_only_needs_no_sdk_login(self) -> None:
        factory = self._factory(lambda _argument: (None, None))
        reader = self._reader(factory, garmin_email="", garmin_password="")

        client, _argument = reader._authenticated_client(_external_call)

        self.assertTrue(reader.configured())
        self.assertIsNone(client.sdk)
        factory.create.assert_not_called()


class FitCapabilityTests(unittest.TestCase):
    def test_a_personal_only_transport_asks_for_no_sdk_part(self) -> None:
        asked: list[str] = []

        def allowed(capability: str) -> bool:
            asked.append(capability)
            return True

        detail = collect_garmin_activity_detail(
            GarminTransportClient(_client(FakePersonalApi()), None),
            "900001",
            external_call=_external_call,
            redact=str,
            capability_allowed=allowed,
        )

        self.assertEqual(asked, ["activity_details", "activity_fit"])
        self.assertIn("details", detail)
        self.assertNotIn("skipped", detail)

    def test_a_paused_fit_part_does_not_gate_the_other_detail_parts(self) -> None:
        from backend.sync.garmin_activity_details import DETAIL_CAPABILITIES

        self.assertNotIn("activity_fit", DETAIL_CAPABILITIES)
        self.assertEqual(DETAIL_CAPABILITIES, ("activity_details",))
        detail = collect_garmin_activity_detail(
            GarminTransportClient(_client(FakePersonalApi()), None),
            "900001",
            external_call=_external_call,
            redact=str,
            capability_allowed=lambda capability: capability != "activity_fit",
        )
        self.assertIn("details", detail)
        self.assertEqual(detail["skipped"], ["activity_fit"])
