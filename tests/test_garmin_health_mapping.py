"""Tests for the pure Garmin health mapper.

Fixtures are read from tests/fixtures/providers/garmin with the standard library
only. No provider, network, database or real data directory is involved.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.canonical.mapping import IssueReason, MappingResult
from backend.canonical.records import Observation
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.providers.garmin_health_mapping import (
    GARMIN_LABEL,
    MAPPER_VERSION,
    map_garmin_health,
)

type Triple = tuple[str | None, str, IssueReason]

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "providers" / "garmin"
ZONE = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 10, 11, 6, 0, tzinfo=ZONE)
DAY = "2026-10-10"

SNAPSHOT_SECTIONS = (
    "sleep",
    "hrv",
    "resting_hr",
    "readiness",
    "max_metrics",
    "running_threshold",
    "cycling_ftp",
    "cycling_ftp_history",
    "weight",
    "body_battery",
    "daily_training_status",
    "training_load_balance",
)

# (kind, value, observed_on, sport or "-") for every observation in the fixtures.
EXPECTED_FIXTURE_ROWS: list[tuple[str, float, str, str]] = [
    ("sleep_duration", 25200.0, "2026-10-09", "-"),
    ("sleep_score", 78.0, "2026-10-09", "-"),
    ("sleep_duration", 27900.0, "2026-10-10", "-"),
    ("sleep_score", 86.0, "2026-10-10", "-"),
    ("hrv_rmssd", 61.0, "2026-10-10", "-"),
    ("resting_hr", 49.0, "2026-10-10", "-"),
    ("readiness", 75.0, "2026-10-10", "-"),
    ("vo2max", 57.4, "2026-10-10", "-"),
    ("vo2max", 59.0, "2026-10-10", "ride"),
    ("vo2max", 57.8, "2026-10-10", "run"),
    ("threshold_pace", 3.6, "2026-10-11", "run"),
    ("threshold_hr", 168.0, "2026-10-11", "run"),
    ("threshold_hr", 160.0, "2026-10-11", "ride"),
    ("ftp", 260.0, "2026-10-10", "ride"),
    ("ftp", 258.0, "2026-10-05", "ride"),
    ("ftp", 260.0, "2026-10-10", "ride"),
    ("weight", 72.1, "2026-10-08", "-"),
    ("weight", 71.5, "2026-10-10", "-"),
]

EXPECTED_FIXTURE_ISSUES: list[Triple] = [
    (
        "running_threshold[0]",
        "power.functionalThresholdPower",
        IssueReason.UNSUPPORTED,
    ),
    (None, "body_battery", IssueReason.UNSUPPORTED),
    (None, "daily_training_status", IssueReason.UNSUPPORTED),
    (None, "training_load_balance", IssueReason.UNSUPPORTED),
]

# (label, sections, expected issues, expected observation count)
GARBAGE_CASES: list[tuple[str, dict[str, object], list[Triple], int]] = [
    (
        "section is a number",
        {"sleep": 5},
        [(None, "sleep", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "record is text",
        {"sleep": ["x"]},
        [("sleep[0]", "sleep", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "record has no date",
        {"sleep": [{"sleepTimeSeconds": 25200}]},
        [("sleep[0]", "calendarDate", IssueReason.MISSING)],
        0,
    ),
    (
        "date is a number",
        {"sleep": [{"calendarDate": 20261010, "sleepTimeSeconds": 25200}]},
        [("sleep[0]", "calendarDate", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "date does not exist",
        {"sleep": [{"calendarDate": "2026-02-30", "sleepTimeSeconds": 25200}]},
        [("sleep[0]", "calendarDate", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "date has a time part",
        {"sleep": [{"calendarDate": "2026-10-10T00:00", "sleepTimeSeconds": 1}]},
        [("sleep[0]", "calendarDate", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "duration is text",
        {"sleep": [{"calendarDate": DAY, "sleepTimeSeconds": "abc"}]},
        [("sleep[0]", "sleepTimeSeconds", IssueReason.INVALID_NUMBER)],
        0,
    ),
    (
        "duration is a boolean",
        {"sleep": [{"calendarDate": DAY, "sleepTimeSeconds": True}]},
        [("sleep[0]", "sleepTimeSeconds", IssueReason.INVALID_NUMBER)],
        0,
    ),
    (
        "score is NaN",
        {"sleep": [{"calendarDate": DAY, "sleepScore": float("nan")}]},
        [("sleep[0]", "sleepScore", IssueReason.INVALID_NUMBER)],
        0,
    ),
    (
        "duration is zero",
        {"sleep": [{"calendarDate": DAY, "sleepTimeSeconds": 0}]},
        [("sleep[0]", "sleepTimeSeconds", IssueReason.OUT_OF_RANGE)],
        0,
    ),
    (
        "duration is over a day",
        {"sleep": [{"calendarDate": DAY, "sleepTimeSeconds": 90000}]},
        [("sleep[0]", "sleepTimeSeconds", IssueReason.OUT_OF_RANGE)],
        0,
    ),
    (
        "hrv is negative",
        {"hrv": [{"calendarDate": DAY, "lastNightAvg": -4}]},
        [("hrv[0]", "hrvLastNight", IssueReason.OUT_OF_RANGE)],
        0,
    ),
    (
        "resting heart rate is infinite",
        {"resting_hr": {"calendarDate": DAY, "restingHeartRate": float("inf")}},
        [("resting_hr[0]", "restingHeartRate", IssueReason.INVALID_NUMBER)],
        0,
    ),
    (
        "readiness above 100",
        {"readiness": {"calendarDate": DAY, "score": 150}},
        [("readiness[0]", "score", IssueReason.OUT_OF_RANGE)],
        0,
    ),
    (
        "readiness list has a null item",
        {"readiness": [None]},
        [("readiness[0]", "readiness", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "cycling VO2max is text",
        {"max_metrics": {"calendarDate": DAY, "cycling": "x"}},
        [("max_metrics[0]", "cycling", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "generic VO2max out of range",
        {"max_metrics": {"calendarDate": DAY, "generic": {"vo2MaxPreciseValue": 500}}},
        [("max_metrics[0]", "vo2MaxPreciseValue", IssueReason.OUT_OF_RANGE)],
        0,
    ),
    (
        "threshold object is a list",
        {"running_threshold": {"speed_and_heart_rate": []}},
        [
            (
                "running_threshold[0]",
                "speed_and_heart_rate",
                IssueReason.INVALID_TYPE,
            )
        ],
        0,
    ),
    (
        "threshold speed is zero",
        {"running_threshold": {"speed_and_heart_rate": {"speed": 0}}},
        [("running_threshold[0]", "speed", IssueReason.OUT_OF_RANGE)],
        0,
    ),
    (
        "threshold power is text",
        {"running_threshold": {"power": "x"}},
        [("running_threshold[0]", "power", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "threshold date is invalid and is not replaced by the sync day",
        {
            "running_threshold": {
                "calendarDate": "soon",
                "speed_and_heart_rate": {"speed": 3.6},
            }
        },
        [("running_threshold[0]", "calendarDate", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "weight is a boolean",
        {"weight": {"calendarDate": DAY, "weight": True, "unitKey": "kg"}},
        [("weight[0]", "weight", IssueReason.INVALID_NUMBER)],
        0,
    ),
    (
        "weight declared in kilograms is not reinterpreted as grams",
        {"weight": {"calendarDate": DAY, "weight": 72100, "unitKey": "kg"}},
        [("weight[0]", "weight", IssueReason.OUT_OF_RANGE)],
        0,
    ),
    (
        "weight has an unknown unit",
        {"weight": {"calendarDate": DAY, "weight": 72, "unitKey": "stone"}},
        [("weight[0]", "weight", IssueReason.UNKNOWN_VALUE)],
        0,
    ),
    (
        "weight unit is not text",
        {"weight": {"calendarDate": DAY, "weight": 72, "unitKey": 5}},
        [("weight[0]", "weight", IssueReason.UNKNOWN_VALUE)],
        0,
    ),
    (
        "weight record has no date",
        {"weight": [{"weight": 72100, "unitKey": "gram"}]},
        [("weight[0]", "calendarDate", IssueReason.MISSING)],
        0,
    ),
    (
        "body fat above 80 keeps the weight",
        {
            "weight": {
                "calendarDate": DAY,
                "weight": 72100,
                "unitKey": "gram",
                "bodyFat": 150,
            }
        },
        [("weight[0]", "bodyFat", IssueReason.OUT_OF_RANGE)],
        1,
    ),
    (
        "body fat is text",
        {
            "weight": {
                "calendarDate": DAY,
                "weight": 72100,
                "unitKey": "gram",
                "bodyFat": "lots",
            }
        },
        [("weight[0]", "bodyFat", IssueReason.INVALID_NUMBER)],
        1,
    ),
    (
        "weight is text but body fat is kept",
        {
            "weight": {
                "calendarDate": DAY,
                "weight": "heavy",
                "unitKey": "kg",
                "bodyFat": 18.5,
            }
        },
        [("weight[0]", "weight", IssueReason.INVALID_NUMBER)],
        1,
    ),
    (
        "FTP is text",
        {"cycling_ftp": {"calendarDate": DAY, "functionalThresholdPower": "n/a"}},
        [("cycling_ftp[0]", "functionalThresholdPower", IssueReason.INVALID_NUMBER)],
        0,
    ),
    (
        "FTP history item is a number",
        {"cycling_ftp_history": [5]},
        [("cycling_ftp_history[0]", "cycling_ftp_history", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "body battery is unsupported",
        {"body_battery": [{"calendarDate": DAY, "charged": 72, "drained": 55}]},
        [(None, "body_battery", IssueReason.UNSUPPORTED)],
        0,
    ),
    (
        "device-keyed training status is unsupported",
        {"daily_training_status": {"mostRecentTrainingStatus": {}}},
        [(None, "daily_training_status", IssueReason.UNSUPPORTED)],
        0,
    ),
    (
        "weight date does not exist",
        {"weight": [{"calendarDate": "2026-02-30", "weight": 72, "unitKey": "kg"}]},
        [("weight[0]", "calendarDate", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "weight and body fat record has no date and is reported once",
        {"weight": [{"weight": 72, "unitKey": "kg", "bodyFat": 18}]},
        [("weight[0]", "calendarDate", IssueReason.MISSING)],
        0,
    ),
    (
        "body fat record has no date",
        {"weight": [{"bodyFat": 18.5}]},
        [("weight[0]", "calendarDate", IssueReason.MISSING)],
        0,
    ),
    (
        "weight has only an unreadable epoch",
        {"weight": [{"timestampGMT": 1e300, "weight": 72, "unitKey": "kg"}]},
        [("weight[0]", "calendarDate", IssueReason.MISSING)],
        0,
    ),
    (
        "body fat unit is unknown",
        {"weight": {"calendarDate": DAY, "bodyFat": 18, "bodyFatUnit": "stone"}},
        [("weight[0]", "bodyFat", IssueReason.UNKNOWN_VALUE)],
        0,
    ),
    (
        "body fat unit is not text",
        {"weight": {"calendarDate": DAY, "bodyFat": 18, "bodyFatUnit": 5}},
        [("weight[0]", "bodyFat", IssueReason.UNKNOWN_VALUE)],
        0,
    ),
    (
        "scalar weight section is reported once",
        {"weight": 72.5},
        [(None, "weight", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "scalar weight entries are reported by index",
        {"weight": ["x", 5, None]},
        [
            ("weight[0]", "weight", IssueReason.INVALID_TYPE),
            ("weight[1]", "weight", IssueReason.INVALID_TYPE),
        ],
        0,
    ),
    (
        "weight unit made only of symbols is unknown",
        {"weight": {"calendarDate": DAY, "weight": 72, "unitKey": "%"}},
        [("weight[0]", "weight", IssueReason.UNKNOWN_VALUE)],
        0,
    ),
    (
        "body fat unit made only of symbols is unknown",
        {"weight": {"calendarDate": DAY, "bodyFat": 18, "bodyFatUnit": "-"}},
        [("weight[0]", "bodyFat", IssueReason.UNKNOWN_VALUE)],
        0,
    ),
    (
        "invalid date on a weight object without a value is reported",
        {"weight": {"calendarDate": "soon", "weight": {"unitKey": "kg"}}},
        [("weight[0]", "calendarDate", IssueReason.INVALID_TYPE)],
        0,
    ),
    (
        "epoch too large for a float has no readable day",
        {"weight": {"timestampGMT": 10**400, "weight": 72, "unitKey": "kg"}},
        [("weight[0]", "calendarDate", IssueReason.MISSING)],
        0,
    ),
]


def _fixture(name: str) -> object:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _fixture_sections() -> dict[str, object]:
    return {name: _fixture(name) for name in SNAPSHOT_SECTIONS}


def _map(
    sections: object,
    *,
    retrieved_at: datetime = RETRIEVED_AT,
    zone: tzinfo = ZONE,
) -> MappingResult[Observation]:
    return map_garmin_health(sections, zone=zone, retrieved_at=retrieved_at)


def _rows(result: MappingResult[Observation]) -> list[tuple[str, float, str, str]]:
    return sorted(
        (
            obs.kind.value,
            obs.value.value,
            obs.observed_on.isoformat(),
            "-" if obs.sport is None else obs.sport.value,
        )
        for obs in result.records
    )


def _issues(result: MappingResult[Observation]) -> list[Triple]:
    return [(issue.record_ref, issue.field, issue.reason) for issue in result.issues]


def _find(
    result: MappingResult[Observation],
    kind: MetricKind,
    sport: Sport | None = None,
) -> Observation:
    matches = [obs for obs in result.records if obs.kind is kind and obs.sport is sport]
    if len(matches) != 1:
        raise AssertionError(f"expected one {kind} observation, found {len(matches)}")
    return matches[0]


class FixtureSnapshotTests(unittest.TestCase):
    def test_fixture_snapshot_maps_expected_observations(self) -> None:
        result = _map(_fixture_sections())

        self.assertEqual(_rows(result), sorted(EXPECTED_FIXTURE_ROWS))
        self.assertEqual(_issues(result), EXPECTED_FIXTURE_ISSUES)

    def test_fixture_observations_carry_no_timestamp(self) -> None:
        result = _map(_fixture_sections())

        self.assertTrue(result.records)
        for obs in result.records:
            self.assertIsNone(obs.observed_at)
            self.assertEqual(obs.value.unit, obs.kind.unit)


class AliasAndUnitTests(unittest.TestCase):
    def test_sleep_duration_uses_first_present_non_empty_alias(self) -> None:
        cases: list[tuple[dict[str, object], float]] = [
            ({"sleepTimeSeconds": "", "sleepDuration": 100}, 100.0),
            ({"sleepTimeSeconds": None, "sleepDuration": 100}, 100.0),
            ({"sleepTimeSeconds": 200, "sleepDuration": 100}, 200.0),
        ]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                result = _map({"sleep": {"calendarDate": DAY, **fields}})
                self.assertEqual(
                    _rows(result), [("sleep_duration", expected, DAY, "-")]
                )

    def test_sleep_score_accepts_overall_alias(self) -> None:
        result = _map({"sleep": {"calendarDate": DAY, "overallSleepScore": 80}})

        self.assertEqual(_rows(result), [("sleep_score", 80.0, DAY, "-")])

    def test_hrv_prefers_last_night_and_ignores_weekly_average(self) -> None:
        last_night = _map(
            {"hrv": {"calendarDate": DAY, "hrvLastNight": 70, "lastNightAvg": 61}}
        )
        fallback = _map({"hrv": {"calendarDate": DAY, "lastNightAvg": 61}})
        weekly_only = _map({"hrv": {"calendarDate": DAY, "weeklyAvg": 58}})

        self.assertEqual(_rows(last_night), [("hrv_rmssd", 70.0, DAY, "-")])
        self.assertEqual(_rows(fallback), [("hrv_rmssd", 61.0, DAY, "-")])
        self.assertEqual(_rows(weekly_only), [])

    def test_resting_heart_rate_accepts_every_alias(self) -> None:
        for alias in ("restingHeartRate", "restingHR", "resting_heart_rate"):
            with self.subTest(alias=alias):
                result = _map({"resting_hr": {"calendarDate": DAY, alias: 48}})
                self.assertEqual(_rows(result), [("resting_hr", 48.0, DAY, "-")])

    def test_numeric_text_is_accepted(self) -> None:
        result = _map({"readiness": {"calendarDate": DAY, "score": "75"}})

        self.assertEqual(_rows(result), [("readiness", 75.0, DAY, "-")])

    def test_ftp_accepts_short_alias(self) -> None:
        result = _map({"cycling_ftp": {"calendarDate": DAY, "ftp": 255}})

        self.assertEqual(_rows(result), [("ftp", 255.0, DAY, "ride")])

    def test_missing_nested_objects_are_skipped(self) -> None:
        result = _map(
            {
                "max_metrics": {
                    "calendarDate": DAY,
                    "generic": {"vo2MaxPreciseValue": 57.4},
                }
            }
        )

        self.assertEqual(_rows(result), [("vo2max", 57.4, DAY, "-")])
        self.assertEqual(_issues(result), [])

    def test_multiple_records_in_a_list_each_map(self) -> None:
        result = _map(
            {
                "sleep": [
                    {"calendarDate": "2026-10-09", "sleepTimeSeconds": 25200},
                    {"calendarDate": "2026-10-10", "sleepTimeSeconds": 27900},
                ]
            }
        )

        self.assertEqual(
            _rows(result),
            [
                ("sleep_duration", 25200.0, "2026-10-09", "-"),
                ("sleep_duration", 27900.0, "2026-10-10", "-"),
            ],
        )

    def test_weight_converts_declared_units_to_kilograms(self) -> None:
        cases: list[tuple[str, float, float]] = [
            ("gram", 72100, 72.1),
            ("g", 72100, 72.1),
            (" Gram ", 72100, 72.1),
            ("kilogram", 72.4, 72.4),
            ("kg", 72.4, 72.4),
            ("lb", 160, 72.57),
            ("Pounds", 160, 72.57),
        ]
        for unit, raw, expected in cases:
            with self.subTest(unit=unit):
                result = _map(
                    {"weight": {"calendarDate": DAY, "weight": raw, "unitKey": unit}}
                )
                self.assertEqual(len(result.records), 1)
                obs = result.records[0]
                self.assertEqual(obs.kind, MetricKind.WEIGHT)
                self.assertEqual(obs.value.unit, "kg")
                self.assertAlmostEqual(obs.value.value, expected, places=2)

    def test_weight_without_unit_uses_the_legacy_magnitude_guess(self) -> None:
        # The legacy reader divides values above 300 by 1000 when no unit is given.
        cases: list[tuple[float, float]] = [(72100, 72.1), (72.4, 72.4), (300, 300)]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                result = _map({"weight": {"calendarDate": DAY, "weight": raw}})
                self.assertEqual(_rows(result), [("weight", expected, DAY, "-")])
                self.assertEqual(_issues(result), [])

    def test_whitespace_weight_unit_uses_the_magnitude_guess(self) -> None:
        result = _map(
            {"weight": {"calendarDate": DAY, "weight": 72100, "unitKey": "  "}}
        )

        self.assertEqual(_rows(result), [("weight", 72.1, DAY, "-")])

    def test_nested_weight_without_a_value_is_silent(self) -> None:
        result = _map({"weight": {"calendarDate": DAY, "weight": {"unitKey": "kg"}}})

        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, ())

    def test_unreadable_timestamps_leave_observed_at_empty(self) -> None:
        for timestamp in (True, 1e300, "soon, later today"):
            with self.subTest(timestamp=timestamp):
                result = _map(
                    {
                        "weight": {
                            "calendarDate": DAY,
                            "weight": 72,
                            "unitKey": "kg",
                            "timestampGMT": timestamp,
                        }
                    }
                )
                self.assertEqual(len(result.records), 1)
                self.assertIsNone(result.records[0].observed_at)

    def test_body_fat_records_do_not_share_weight_record_ids(self) -> None:
        result = _map(
            {
                "weight": [
                    {
                        "calendarDate": DAY,
                        "minWeight": {
                            "calendarDate": DAY,
                            "bodyFat": 20,
                            "unitKey": "%",
                        },
                    },
                    {"calendarDate": DAY, "weight": 70, "unitKey": "kg"},
                ]
            }
        )

        ids = sorted(obs.provenance.source_record_id or "" for obs in result.records)
        self.assertEqual(ids, ["body_fat:2026-10-10:1", "weight:2026-10-10:1"])

    def test_weight_is_read_from_weigh_in_section_aliases(self) -> None:
        for section in ("weigh_ins", "weighIns"):
            with self.subTest(section=section):
                result = _map(
                    {section: [{"calendarDate": DAY, "weight": 71.5, "unitKey": "kg"}]}
                )
                self.assertEqual(_rows(result), [("weight", 71.5, DAY, "-")])

    def test_weight_records_carry_timestamp_and_index_record_id(self) -> None:
        result = _map(
            {
                "weight": [
                    {
                        "calendarDate": DAY,
                        "weight": 72.1,
                        "unitKey": "kg",
                        "timestampGMT": "2026-10-10T06:30:00Z",
                    },
                    {"calendarDate": DAY, "weight": 71.9, "unitKey": "kg"},
                ]
            }
        )

        first, second = result.records
        self.assertEqual(first.observed_at, datetime(2026, 10, 10, 6, 30, tzinfo=UTC))
        self.assertIsNone(second.observed_at)
        self.assertEqual(first.provenance.source_record_id, f"weight:{DAY}:0")
        self.assertEqual(second.provenance.source_record_id, f"weight:{DAY}:1")

    def test_weight_unit_alias_precedence(self) -> None:
        cases: list[dict[str, object]] = [
            {"unitKey": "gram", "unit": "lb", "weight": 72100},
            {"unit": "kg", "weight": 72.4},
            {"weightUnit": "kg", "weight": 72.4},
        ]
        expected = [72.1, 72.4, 72.4]
        for fields, value in zip(cases, expected, strict=True):
            with self.subTest(fields=fields):
                result = _map({"weight": {"calendarDate": DAY, **fields}})
                self.assertAlmostEqual(result.records[0].value.value, value, places=6)

    def test_body_fat_accepts_every_alias_without_weight(self) -> None:
        for alias in (
            "bodyFat",
            "body_fat",
            "bodyFatPercent",
            "bodyFatPercentage",
            "fatPercent",
        ):
            with self.subTest(alias=alias):
                result = _map({"weight": {"calendarDate": DAY, alias: 18.5}})
                self.assertEqual(_rows(result), [("body_fat", 18.5, DAY, "-")])
                self.assertEqual(
                    result.records[0].provenance.source_kind,
                    SourceKind.DEVICE_MEASURED,
                )

    def test_weight_daily_weight_summaries_nested_without_unit_maps_grams(self) -> None:
        result = _map(
            {
                "weight": {
                    "dailyWeightSummaries": [
                        {
                            "summaryDate": "2026-09-07",
                            "latestWeight": {
                                "weight": 72800,
                            },
                        }
                    ]
                }
            }
        )
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].kind, MetricKind.WEIGHT)
        self.assertEqual(result.records[0].value.value, 72.8)
        self.assertEqual(result.records[0].observed_on, date(2026, 9, 7))
        self.assertEqual(
            result.records[0].provenance.source_record_id, "weight:2026-09-07:0"
        )

    def test_sleep_with_nested_daily_sleep_dto_maps_duration_and_score(self) -> None:
        result = _map(
            {
                "sleep": {
                    "dailySleepDTO": {
                        "calendarDate": DAY,
                        "sleepTimeSeconds": 28800,
                        "sleepScore": 85,
                    }
                }
            }
        )
        self.assertEqual(
            _rows(result),
            [
                ("sleep_duration", 28800.0, DAY, "-"),
                ("sleep_score", 85.0, DAY, "-"),
            ],
        )

    def test_sleep_daily_dto_overall_score_maps_without_flat_fields(self) -> None:
        result = _map(
            {
                "sleep": {
                    "dailySleepDTO": {
                        "calendarDate": DAY,
                        "sleepTimeSeconds": 28800,
                        "sleepScores": {"overall": {"value": 85}},
                    }
                }
            }
        )
        self.assertEqual(
            _rows(result),
            [
                ("sleep_duration", 28800.0, DAY, "-"),
                ("sleep_score", 85.0, DAY, "-"),
            ],
        )
        self.assertEqual(result.issues, ())

    def test_nested_weight_unit_and_body_fat_are_preserved(self) -> None:
        result = _map(
            {
                "weight": {
                    "dailyWeightSummaries": [
                        {
                            "summaryDate": DAY,
                            "latestWeight": {
                                "weight": 160,
                                "unit": "lb",
                                "bodyFat": 18,
                            },
                        }
                    ]
                }
            }
        )
        self.assertEqual(len(result.records), 2)
        self.assertAlmostEqual(result.records[0].value.value, 72.5747792)
        self.assertEqual(result.records[1].kind, MetricKind.BODY_FAT)
        self.assertEqual(result.records[1].value.value, 18)

    def test_nested_unitless_weight_uses_garmin_grams_without_guessing(self) -> None:
        result = _map(
            {
                "weight": {
                    "dailyWeightSummaries": [
                        {
                            "summaryDate": DAY,
                            "latestWeight": {"weight": 72.8},
                        }
                    ]
                }
            }
        )
        self.assertEqual(result.records, ())
        self.assertEqual(result.issues[0].reason, IssueReason.OUT_OF_RANGE)


class TimeAndZoneTests(unittest.TestCase):
    def test_running_threshold_sync_day_follows_athlete_zone(self) -> None:
        # 23:30 UTC on 28 March is 00:30 on 29 March in Berlin, the day the
        # clocks change. The sync day must follow the athlete's zone, not UTC.
        retrieved = datetime(2026, 3, 28, 23, 30, tzinfo=UTC)
        sections: dict[str, object] = {
            "running_threshold": {"speed_and_heart_rate": {"speed": 3.6}}
        }

        berlin = _map(sections, retrieved_at=retrieved)
        utc = _map(sections, retrieved_at=retrieved, zone=UTC)

        self.assertEqual({o.observed_on for o in berlin.records}, {date(2026, 3, 29)})
        self.assertEqual({o.observed_on for o in utc.records}, {date(2026, 3, 28)})

    def test_running_threshold_uses_calendar_date_when_present(self) -> None:
        result = _map(
            {
                "running_threshold": {
                    "calendarDate": "2026-10-07",
                    "speed_and_heart_rate": {"speed": 3.6},
                }
            }
        )

        self.assertEqual(_rows(result), [("threshold_pace", 3.6, "2026-10-07", "run")])

    def test_naive_retrieved_at_is_rejected(self) -> None:
        naive = datetime(2026, 10, 11, 6, 0)  # noqa: DTZ001
        with self.assertRaises(ValueError):
            _map({}, retrieved_at=naive)


class ProvenanceTests(unittest.TestCase):
    def test_source_kinds_and_record_ids_are_set_per_metric(self) -> None:
        result = _map(
            {
                "sleep": {
                    "calendarDate": DAY,
                    "sleepTimeSeconds": 25200,
                    "sleepScore": 78,
                },
                "resting_hr": {"calendarDate": DAY, "restingHeartRate": 49},
                "max_metrics": {
                    "calendarDate": DAY,
                    "cycling": {"vo2MaxPreciseValue": 59.0},
                },
                "running_threshold": {"speed_and_heart_rate": {"speed": 3.6}},
            }
        )

        cases: list[tuple[MetricKind, Sport | None, SourceKind, str]] = [
            (
                MetricKind.SLEEP_DURATION,
                None,
                SourceKind.DEVICE_MEASURED,
                f"sleep:{DAY}",
            ),
            (
                MetricKind.SLEEP_SCORE,
                None,
                SourceKind.PROVIDER_REPORTED,
                f"sleep:{DAY}",
            ),
            (
                MetricKind.RESTING_HR,
                None,
                SourceKind.DEVICE_MEASURED,
                f"resting_hr:{DAY}",
            ),
            (
                MetricKind.VO2MAX,
                Sport.RIDE,
                SourceKind.PROVIDER_REPORTED,
                f"max_metrics:{DAY}:cycling",
            ),
            (
                MetricKind.THRESHOLD_PACE,
                Sport.RUN,
                SourceKind.PROVIDER_REPORTED,
                "running_threshold:2026-10-11:speed_and_heart_rate",
            ),
        ]
        for kind, sport, source_kind, record_id in cases:
            with self.subTest(kind=kind.value):
                obs = _find(result, kind, sport)
                self.assertEqual(obs.provenance.source_kind, source_kind)
                self.assertEqual(obs.provenance.source_record_id, record_id)
                self.assertEqual(obs.provenance.provider, ProviderId.GARMIN)
                self.assertEqual(obs.provenance.recorded_by, RecordingOrigin.GARMIN)
                self.assertEqual(obs.provenance.retrieved_at, RETRIEVED_AT)
                self.assertEqual(obs.provenance.label, GARMIN_LABEL)
                self.assertIsNone(obs.observed_at)

    def test_observations_for_one_record_share_a_record_id(self) -> None:
        result = _map({"sleep": {"calendarDate": DAY, "sleepTimeSeconds": 25200}})
        self.assertEqual(result.records[0].provenance.source_record_id, f"sleep:{DAY}")

    def test_list_payloads_include_index_in_source_record_id(self) -> None:
        result = _map(
            {
                "sleep": [
                    {"calendarDate": DAY, "sleepTimeSeconds": 25200},
                    {"calendarDate": DAY, "sleepTimeSeconds": 27900},
                ]
            }
        )
        self.assertEqual(len(result.records), 2)
        self.assertEqual(
            result.records[0].provenance.source_record_id, f"sleep:{DAY}:0"
        )
        self.assertEqual(
            result.records[1].provenance.source_record_id, f"sleep:{DAY}:1"
        )


class ContractTests(unittest.TestCase):
    def test_mapper_version_is_pinned(self) -> None:
        self.assertEqual(MAPPER_VERSION, 2)

    def test_non_mapping_sections_yield_one_issue(self) -> None:
        for sections in (["sleep"], "sleep", None, 5):
            with self.subTest(sections=sections):
                result = _map(sections)
                self.assertEqual(result.records, ())
                self.assertEqual(
                    _issues(result),
                    [(None, "sections", IssueReason.INVALID_TYPE)],
                )

    def test_empty_and_null_payloads_are_silent(self) -> None:
        result = _map(
            {
                "sleep": None,
                "weight": None,
                "body_battery": None,
                "readiness": None,
                "running_threshold": None,
            }
        )

        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, ())

    def test_unmapped_and_unknown_sections_are_ignored_silently(self) -> None:
        result = _map(
            {
                "activities": [{"activityId": 1}],
                "gear": {"id": 2},
                "daily_stats": {"calendarDate": DAY, "totalSteps": 8421},
                "training_status": {"acuteTrainingLoadDTO": {"acuteTrainingLoad": 480}},
                "heart_rate_zones": [{"sport": "DEFAULT", "maxHeartRateUsed": 190}],
                "race_predictions": {"5k": {"raceTime": 1320}},
                "endurance_score": [{"calendarDate": DAY, "overallScore": 6850}],
                "running_tolerance": [{"calendarDate": DAY, "toleranceScore": 72}],
                "unknown_provider_key": {"calendarDate": DAY, "value": 1},
            }
        )

        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, ())

    def test_sparse_snapshot_yields_empty_result(self) -> None:
        result = _map({})

        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, ())

    def test_power_without_lactate_threshold_power_is_silent(self) -> None:
        result = _map(
            {
                "running_threshold": {
                    "calendarDate": DAY,
                    "speed_and_heart_rate": {"speed": 3.6},
                    "power": {"functionalThresholdPower": None, "other": 1},
                }
            }
        )

        self.assertEqual(_rows(result), [("threshold_pace", 3.6, DAY, "run")])
        self.assertEqual(_issues(result), [])

    def test_power_block_as_text_is_reported(self) -> None:
        result = _map(
            {
                "running_threshold": {
                    "calendarDate": DAY,
                    "power": "x",
                }
            }
        )

        self.assertEqual(
            _issues(result),
            [("running_threshold[0]", "power", IssueReason.INVALID_TYPE)],
        )

    def test_issues_never_echo_raw_values(self) -> None:
        result = _map(
            {
                "sleep": {
                    "calendarDate": DAY,
                    "sleepTimeSeconds": "RAW-VALUE-7731",
                }
            }
        )

        self.assertEqual(
            _issues(result),
            [("sleep[0]", "sleepTimeSeconds", IssueReason.INVALID_NUMBER)],
        )
        self.assertNotIn("RAW-VALUE-7731", repr(result))

    def test_garbage_inputs_become_issues(self) -> None:
        for label, sections, expected_issues, count in GARBAGE_CASES:
            with self.subTest(label):
                result = _map(sections)
                self.assertEqual(_issues(result), expected_issues)
                self.assertEqual(len(result.records), count)


if __name__ == "__main__":
    unittest.main()
