"""Synthetic provider wire fixtures must parse through the real consumers.

The fixtures under ``tests/fixtures/providers`` mirror the shapes that
Intervals.icu and Garmin deliver today. They are invented data: every athlete,
activity, event and gear name is prefixed with ``Synthetic`` and no value is a
credential. These tests feed them through the production compaction and
collection code using an in-memory fake Garmin client, so no network, real
account or real ``DATA_DIR`` is touched.
"""

import copy
import json
import re
import unittest
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.athlete.local_date import iso_date_prefix
from backend.performance.garmin_weight import garmin_weight_metric
from backend.performance.recovery_context import performance_recovery_context
from backend.planning.context import compact_snapshot
from backend.providers.garmin import collect_garmin_data

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "providers"
INTERVALS_ROOT = FIXTURE_ROOT / "intervals"
GARMIN_ROOT = FIXTURE_ROOT / "garmin"

INTERVALS_FILES = frozenset({"athlete", "activities", "wellness", "events"})
GARMIN_FIXTURE_FILES = frozenset(
    {
        "activities",
        "sleep",
        "hrv",
        "body_battery",
        "daily_stats",
        "resting_hr",
        "training_status",
        "heart_rate_zones",
        "daily_training_status",
        "training_load_balance",
        "readiness",
        "race_predictions",
        "max_metrics",
        "cycling_ftp",
        "running_threshold",
        "weight",
        "user_profile",
        "gear",
        "gear_stats",
        "cycling_ftp_history",
        "endurance_score",
        "running_tolerance",
    }
)
# Payload keys that ``collect_garmin_data`` writes for the fixture client.
# ``body_battery`` is fetched by the morning path, ``user_profile`` and
# ``gear_stats`` are inputs to the gear inventory only.
GARMIN_COLLECTED_KEYS = frozenset(
    {
        "activities",
        "sleep",
        "hrv",
        "daily_stats",
        "resting_hr",
        "training_status",
        "heart_rate_zones",
        "gear",
        "daily_training_status",
        "training_load_balance",
        "readiness",
        "race_predictions",
        "max_metrics",
        "cycling_ftp",
        "running_threshold",
        "weight",
        "cycling_ftp_history",
        "endurance_score",
        "running_tolerance",
    }
)

SYNTHETIC_TODAY = date(2026, 10, 10)
SYNTHETIC_SYNC = "2026-10-10T06:00:00+00:00"
BERLIN = ZoneInfo("Europe/Berlin")

# Local wall-clock times either side of the Europe/Berlin DST transitions.
# Offsets are the UTC offsets in force at those local times.
DST_LOCAL_OFFSETS = {
    "2026-03-29T01:59:00": timedelta(hours=1),
    "2026-03-29T03:01:00": timedelta(hours=2),
    "2026-10-25T01:59:00": timedelta(hours=2),
    "2026-10-25T03:01:00": timedelta(hours=1),
}

SECRET_KEY_PATTERN = re.compile(
    r"(password|passwd|token|secret|api[_-]?key|cookie|authorization|credential)",
    re.IGNORECASE,
)
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def all_keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from all_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_keys(item)


def all_strings(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for item in value.values():
            yield from all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_strings(item)
    elif isinstance(value, str):
        yield value


def external_call(
    provider: str,
    key: str,
    fetch: Callable[[], Any],
    details: dict[str, Any] | None,
) -> Any:
    """Run the fetch in-process; the production wrapper adds only logging."""
    return fetch()


class FixtureGarminClient:
    """In-memory stand-in for the Garmin SDK that serves the wire fixtures.

    Method names and argument shapes match the calls made by
    ``backend.providers.garmin``. Responses are deep copies so collection cannot
    mutate the fixtures on disk.
    """

    def __init__(self) -> None:
        self._fixtures = {
            name: load_json(GARMIN_ROOT / f"{name}.json")
            for name in GARMIN_FIXTURE_FILES
        }

    def _value(self, name: str) -> Any:
        return copy.deepcopy(self._fixtures[name])

    def get_activities_by_date(self, start: str, end: str) -> Any:
        return self._value("activities")

    def get_sleep_daily(self, start: str, end: str) -> Any:
        return self._value("sleep")

    def get_hrv_data_range(self, start: str, end: str) -> Any:
        return self._value("hrv")

    def get_user_summary(self, current: str) -> Any:
        return self._value("daily_stats")

    def get_heart_rates(self, current: str) -> Any:
        return self._value("resting_hr")

    def get_training_status(self, current: str) -> Any:
        return self._value("training_status")

    def get_heart_rate_zones(self) -> Any:
        return self._value("heart_rate_zones")

    def get_user_profile(self) -> Any:
        return self._value("user_profile")

    def get_gear(self, profile_number: int) -> Any:
        return self._value("gear")

    def get_gear_stats(self, gear_uuid: str) -> Any:
        return self._value("gear_stats")

    def get_daily_training_status(self, current: str) -> Any:
        return self._value("daily_training_status")

    def get_training_four_week_load_balance(self, current: str) -> Any:
        return self._value("training_load_balance")

    def get_training_readiness(self, current: str) -> Any:
        return self._value("readiness")

    def get_race_predictions(self) -> Any:
        return self._value("race_predictions")

    def get_max_metrics_range(self, start: str, end: str) -> Any:
        return self._value("max_metrics")

    def get_cycling_ftp(self) -> Any:
        return self._value("cycling_ftp")

    def get_lactate_threshold(self, *, latest: bool = True) -> Any:
        return self._value("running_threshold")

    def get_weigh_ins(self, start: str, end: str) -> Any:
        return self._value("weight")

    def get_functional_threshold_power_range(
        self, start: str, end: str, *, sport: str, aggregation: str
    ) -> Any:
        return self._value("cycling_ftp_history")

    def get_endurance_score(self, start: str, end: str) -> Any:
        return self._value("endurance_score")

    def get_running_tolerance(self, start: str, end: str, *, aggregation: str) -> Any:
        return self._value("running_tolerance")


class IntervalsWireFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.athlete = load_json(INTERVALS_ROOT / "athlete.json")
        self.activities = load_json(INTERVALS_ROOT / "activities.json")
        self.wellness = load_json(INTERVALS_ROOT / "wellness.json")
        self.events = load_json(INTERVALS_ROOT / "events.json")

    def compact(self) -> dict[str, Any]:
        return compact_snapshot(
            self.athlete,
            self.activities,
            self.wellness,
            self.events,
            all_sync_days=42,
            synced_at=SYNTHETIC_SYNC,
        )

    def test_intervals_fixture_files_exist(self) -> None:
        present = {path.stem for path in INTERVALS_ROOT.glob("*.json")}
        self.assertEqual(present, INTERVALS_FILES)

    def test_compact_snapshot_accepts_every_intervals_fixture(self) -> None:
        snapshot = self.compact()

        self.assertEqual(snapshot["synced_at"], SYNTHETIC_SYNC)
        self.assertEqual(len(snapshot["recent_activities"]), len(self.activities))
        self.assertEqual(len(snapshot["recent_wellness"]), len(self.wellness))
        self.assertEqual(len(snapshot["upcoming_calendar"]), len(self.events))

    def test_activities_keep_compacted_fields_and_drop_free_text(self) -> None:
        first = self.compact()["recent_activities"][0]

        self.assertEqual(first["id"], "i-act-001")
        self.assertEqual(first["start_date_local"], "2026-10-08T07:15:00")
        self.assertEqual(first["icu_training_load"], 72)
        self.assertEqual(first["icu_eftp"], 258)
        self.assertEqual(first["external_id"], "synthetic-ext-001")
        self.assertNotIn("private_comment", first)

    def test_sport_settings_are_read_from_camel_case_alias(self) -> None:
        athlete = self.compact()["athlete"]
        settings = athlete["sport_settings"]

        self.assertEqual(athlete["name"], "Synthetic Athlete")
        self.assertEqual(len(settings), 2)
        self.assertEqual(settings[0]["types"], ["Ride"])
        self.assertEqual(settings[0]["ftp"], 260)
        self.assertEqual(settings[1]["types"], ["Run"])

    def test_wellness_keeps_both_load_alias_pairs(self) -> None:
        rows = self.compact()["recent_wellness"]

        for row in rows:
            self.assertEqual(row["ctl"], row["ctLoad"])
            self.assertEqual(row["atl"], row["atlLoad"])
        self.assertEqual(rows[-1]["id"], "2026-10-10")
        self.assertEqual(rows[-1]["readiness"], 79)
        self.assertEqual(rows[-1]["sleepSecs"], 27900)

    def test_wellness_sport_info_is_compacted(self) -> None:
        row = self.compact()["recent_wellness"][0]

        self.assertEqual(row["sport_info"][0]["type"], "Ride")
        self.assertNotIn("sportInfo", row)

    def test_events_keep_calendar_fields_only(self) -> None:
        events = self.compact()["upcoming_calendar"]

        self.assertEqual(
            [event["category"] for event in events], ["WORKOUT", "NOTE", "RACE_A"]
        )
        self.assertEqual(events[0]["external_id"], "synthetic-plan-001")
        self.assertNotIn("owner_note", events[0])

    def test_tzdata_resolves_dst_boundary_local_times(self) -> None:
        # Sanity check on the installed tzdata, independent of the compaction code.
        by_local_time = {
            item["start_date_local"]: item
            for item in self.activities
            if item["start_date_local"] in DST_LOCAL_OFFSETS
        }

        self.assertEqual(set(by_local_time), set(DST_LOCAL_OFFSETS))
        for local_time, expected_offset in DST_LOCAL_OFFSETS.items():
            with self.subTest(local_time=local_time):
                aware = datetime.fromisoformat(local_time).replace(tzinfo=BERLIN)
                self.assertEqual(aware.utcoffset(), expected_offset)

    def test_dst_boundary_local_strings_survive_compaction_verbatim(self) -> None:
        compacted = {
            item["start_date_local"] for item in self.compact()["recent_activities"]
        }

        self.assertTrue(set(DST_LOCAL_OFFSETS) <= compacted)

    def test_dst_boundary_activities_keep_their_local_calendar_date(self) -> None:
        rows = {
            item["start_date_local"]: item
            for item in self.compact()["recent_activities"]
        }

        for local_time in DST_LOCAL_OFFSETS:
            with self.subTest(local_time=local_time):
                self.assertIn(local_time[:10], {"2026-03-29", "2026-10-25"})
                self.assertEqual(
                    iso_date_prefix(rows[local_time]["start_date_local"]),
                    local_time[:10],
                )


class GarminWireFixtureTests(unittest.TestCase):
    def collect(self) -> dict[str, Any]:
        return collect_garmin_data(
            FixtureGarminClient(),
            [(SYNTHETIC_TODAY, SYNTHETIC_TODAY)],
            start=SYNTHETIC_TODAY,
            today=SYNTHETIC_TODAY,
            synced_at=SYNTHETIC_SYNC,
            external_call=external_call,
            redact=lambda text: text,
        )

    def test_one_fixture_file_per_garmin_section(self) -> None:
        present = {path.stem for path in GARMIN_ROOT.glob("*.json")}

        self.assertEqual(present, GARMIN_FIXTURE_FILES)

    def test_collection_consumes_fixture_shapes_without_errors(self) -> None:
        payload = self.collect()

        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["start"], SYNTHETIC_TODAY.isoformat())
        self.assertEqual(payload["end"], SYNTHETIC_TODAY.isoformat())
        metadata_keys = {"start", "end", "synced_at", "errors", "provider_sync"}
        self.assertEqual(GARMIN_COLLECTED_KEYS, set(payload) - metadata_keys)
        self.assertIn("provider_sync", payload)

    def test_weight_fixture_normalises_grams_to_kilograms(self) -> None:
        payload = self.collect()

        metric = garmin_weight_metric(payload)

        self.assertEqual(metric["value"], 71.5)
        self.assertEqual(metric["unit"], "kg")
        self.assertEqual(metric["source"], "Garmin Connect")

    def test_recovery_context_reads_fixture_sleep_and_resting_hr(self) -> None:
        payload = self.collect()

        context = performance_recovery_context(payload, {}, [], SYNTHETIC_TODAY)

        # 27900 seconds of sleep from the latest dated Garmin sleep record.
        self.assertEqual(context["sleep_hours"], 7.8)
        self.assertEqual(context["sleep_score"], 86)
        self.assertEqual(context["sleep_source"], "Garmin Connect")
        self.assertEqual(context["resting_hr"], 49)
        self.assertEqual(context["resting_hr_source"], "Garmin Connect")
        self.assertEqual(context["readiness"], 75)
        self.assertEqual(context["readiness_source"], "Garmin Connect")

    def test_body_battery_fixture_has_bounded_charge_and_drain(self) -> None:
        records = load_json(GARMIN_ROOT / "body_battery.json")

        self.assertEqual(len(records), 2)
        for record in records:
            with self.subTest(date=record["calendarDate"]):
                self.assertTrue(0 <= record["charged"] <= 100)
                self.assertTrue(0 <= record["drained"] <= 100)


class ProviderFixtureHygieneTests(unittest.TestCase):
    def fixture_documents(self) -> Iterator[tuple[Path, Any]]:
        for path in sorted(FIXTURE_ROOT.rglob("*.json")):
            yield path, load_json(path)

    def test_no_fixture_key_looks_like_a_credential(self) -> None:
        for path, document in self.fixture_documents():
            with self.subTest(fixture=path.name):
                for key in all_keys(document):
                    self.assertIsNone(SECRET_KEY_PATTERN.search(key), key)

    def test_no_fixture_value_contains_an_email_address(self) -> None:
        for path, document in self.fixture_documents():
            with self.subTest(fixture=path.name):
                for value in all_strings(document):
                    self.assertIsNone(EMAIL_PATTERN.search(value))

    def test_athlete_and_named_records_are_marked_synthetic(self) -> None:
        athlete = load_json(INTERVALS_ROOT / "athlete.json")
        self.assertTrue(athlete["name"].startswith("Synthetic"))

        named_records = (
            load_json(INTERVALS_ROOT / "activities.json")
            + load_json(INTERVALS_ROOT / "events.json")
            + load_json(GARMIN_ROOT / "activities.json")
        )
        for record in named_records:
            name = record.get("name") or record.get("activityName")
            with self.subTest(name=name):
                self.assertTrue(str(name).startswith("Synthetic"))


if __name__ == "__main__":
    unittest.main()
