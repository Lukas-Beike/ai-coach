"""Golden run of the targeted Garmin refreshes (#2079).

Nutrition and Analyse refreshes, their failure paths and the daytime store run
against mocked Garmin reads and a temporary database. The digest pins every
stored row (raw records, canonical rows, freshness markers, sync state) and
every result, apart from generated ids and wall-clock row stamps, so merging the refresh services cannot change what they store or
return.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import unittest
from datetime import date, timedelta, timezone
from typing import Any
from unittest.mock import Mock

from support import temp_database

from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.sync.garmin import GarminPayloadService
from backend.sync.garmin_service import (
    GarminSyncCoordination,
    GarminTargetedRefreshService,
)
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.state import SyncStateRepository

ZONE = timezone(timedelta(hours=1))
NOW = "2026-09-24T12:00:00+00:00"
TODAY = date(2026, 9, 24)
GOLDEN_DIGEST = "2eb9093e512cde3185e2188b3174710659a071153debd76dfa419dbef64901fd"


def _day(offset: int) -> str:
    return (TODAY - timedelta(days=offset)).isoformat()


NUTRITION_READS: dict[str, tuple[list[dict[str, Any]], bool]] = {
    "daily_stats": (
        [
            {
                "calendarDate": _day(0),
                "totalKilocalories": 2400,
                "activeKilocalories": 600,
            },
            {
                "calendarDate": _day(1),
                "totalKilocalories": 2250,
                "activeKilocalories": 450,
            },
        ],
        True,
    ),
    "weight": (
        [
            {
                "weighIns": [
                    {"samplePk": 11, "calendarDate": _day(0), "weight": 70400},
                    {
                        "samplePk": 12,
                        "calendarDate": _day(2),
                        "weight": 70900,
                        "bodyFat": 14.2,
                    },
                ]
            }
        ],
        True,
    ),
}

ANALYSIS_READS: dict[str, tuple[dict[str, Any], dict[str, bool]]] = {
    "sessions": (
        {
            "activities": [
                {
                    "activityId": 7001,
                    "activityName": "Synthetic ride",
                    "activityType": {"typeKey": "cycling"},
                    "startTimeLocal": f"{_day(1)} 17:00:00",
                    "duration": 3600.0,
                }
            ]
        },
        {"activities": True},
    ),
    "load": (
        {
            "training_load_balance": {"metricsTrainingLoadBalanceDTOMap": {}},
            "daily_training_status": None,
        },
        {"training_load_balance": True, "daily_training_status": False},
    ),
    "recovery": (
        {
            "sleep": [
                {
                    "calendarDate": _day(0),
                    "dailySleepDTO": {
                        "calendarDate": _day(0),
                        "sleepTimeSeconds": 27000,
                    },
                }
            ],
            "hrv": [{"calendarDate": _day(0), "hrvSummary": {"lastNightAvg": 61}}],
            "resting_hr": [{"calendarDate": _day(0), "restingHeartRate": 47}],
        },
        {"sleep": True, "hrv": True, "resting_hr": False},
    ),
}


class GarminTargetedRefreshGoldenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = temp_database(
            self, "golden.sqlite3", row_factory=sqlite3.Row, schema=True
        )
        key_values = KeyValueRepository(lambda: NOW)
        self.payload = GarminPayloadService(
            self.database,
            key_values,
            SyncStateRepository(self.database, key_values, lambda: NOW),
            lambda: TODAY,
        )
        self.writer = GarminSnapshotWriter(key_values, lambda: ZONE)
        with self.database.unit_of_work() as db:
            self.writer.write(
                db,
                {
                    "synced_at": "2026-09-20T06:00:00+00:00",
                    "daily_stats": [
                        {"calendarDate": _day(1), "totalKilocalories": 2100},
                        {"calendarDate": _day(9), "totalKilocalories": 1990},
                    ],
                    "weight": [
                        {
                            "weight": [
                                {
                                    "samplePk": 9,
                                    "calendarDate": _day(2),
                                    "weight": 71000,
                                }
                            ]
                        }
                    ],
                    "daily_training_status": {"old": "kept"},
                    "source_freshness": {"sleep": {"freshness": "current"}},
                },
            )
        self.reader = Mock()
        self.reader.fetch_nutrition_data.side_effect = lambda source, _start, _end: (
            NUTRITION_READS[source]
        )
        self.reader.fetch_analysis_data.side_effect = lambda area, _start, _end: (
            ANALYSIS_READS[area]
        )
        self.coordination = GarminSyncCoordination(threading.Lock())
        self.configured = True

    def service(self) -> GarminTargetedRefreshService:
        return GarminTargetedRefreshService(
            self.reader,
            self.database,
            self.writer,
            self.payload,
            self.coordination,
            lambda: NOW,
            lambda: self.configured,
        )

    def run_golden_sequence(self) -> list[Any]:
        service = self.service()
        start = TODAY - timedelta(days=6)
        results: list[Any] = [
            service.refresh_nutrition("daily_stats", start, TODAY),
            service.refresh_nutrition("weight", start, TODAY),
            service.refresh_analysis("sessions", start, TODAY),
            service.refresh_analysis("load", start, TODAY),
            service.refresh_analysis("recovery", start, TODAY),
            service.store_daytime(
                TODAY,
                {"daily_stats": [{"calendarDate": _day(0), "totalKilocalories": 2500}]},
            ),
            service.store_daytime(
                TODAY,
                {"daily_stats": [{"calendarDate": _day(0), "totalKilocalories": 2500}]},
            ),
        ]
        self.reader.fetch_nutrition_data.side_effect = lambda *_a: ([], True)
        results.append(service.refresh_nutrition("weight", start, TODAY))
        self.reader.fetch_nutrition_data.side_effect = RuntimeError("provider down")
        self.reader.fetch_analysis_data.side_effect = RuntimeError("provider down")
        results.append(service.refresh_nutrition("daily_stats", start, TODAY))
        results.append(service.refresh_analysis("load", start, TODAY))
        for reason in ("not_supported", "library_unavailable", "not_configured"):
            error = AppError(503, "unavailable", reason=reason)
            self.reader.fetch_nutrition_data.side_effect = error
            self.reader.fetch_analysis_data.side_effect = error
            results.append(service.refresh_nutrition("weight", start, TODAY))
            results.append(service.refresh_analysis("recovery", start, TODAY))
        for call in (
            lambda: service.refresh_nutrition("sleep", start, TODAY),
            lambda: service.refresh_nutrition("weight", TODAY, start),
            lambda: service.refresh_analysis("nutrition", start, TODAY),
            lambda: service.refresh_analysis("load", TODAY - timedelta(days=90), TODAY),
        ):
            results.append(self.app_error(call))
        self.reader.fetch_nutrition_data.side_effect = AppError(
            500, "x", reason="other"
        )
        self.reader.fetch_analysis_data.side_effect = AppError(500, "x", reason="other")
        results.append(
            self.app_error(lambda: service.refresh_nutrition("weight", start, TODAY))
        )
        results.append(
            self.app_error(lambda: service.refresh_analysis("load", start, TODAY))
        )
        self.assertTrue(self.coordination.acquire())
        try:
            results.append(
                self.app_error(
                    lambda: service.refresh_nutrition("weight", start, TODAY)
                )
            )
            results.append(
                self.app_error(lambda: service.refresh_analysis("load", start, TODAY))
            )
            results.append(service.store_daytime(TODAY, {"daily_stats": [{"x": 1}]}))
        finally:
            self.coordination.release()
        self.configured = False
        results.append(service.refresh_nutrition("weight", start, TODAY))
        results.append(service.refresh_analysis("load", start, TODAY))
        return results

    @staticmethod
    def app_error(call: Any) -> dict[str, Any]:
        try:
            call()
        except AppError as error:
            return {
                "status": error.status,
                "message": str(error),
                "reason": error.reason,
            }
        raise AssertionError("expected AppError")

    def stored_rows(self) -> dict[str, list[list[Any]]]:
        with self.database.unit_of_work() as db:
            tables = [
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            return {
                table: sorted(
                    [
                        [
                            value.hex() if isinstance(value, bytes) else value
                            for value in tuple(row)
                        ]
                        for row in db.execute(f'SELECT * FROM "{table}"')
                    ],
                    key=lambda row: json.dumps(row, default=str),
                )
                for table in tables
            }

    def test_refreshes_store_and_return_the_golden_state(self) -> None:
        results = self.run_golden_sequence()
        stored = {name: rows for name, rows in self.stored_rows().items() if rows}
        dump = json.dumps(
            {"results": results, "stored": stored}, sort_keys=True, default=str
        )
        # Generated session ids and wall-clock row stamps vary between runs.
        dump = re.sub(r"act_[0-9a-f]{32}", "act_ID", dump)
        dump = re.sub(r"\d{4}-\d\d-\d\dT[\d:]+\.\d+\+00:00", "WALL_CLOCK", dump)

        self.assertIn("nutrition_refresh", dump)
        self.assertIn("source_freshness", dump)
        self.assertIn("7001", dump)
        self.assertEqual(
            hashlib.sha256(dump.encode()).hexdigest(), GOLDEN_DIGEST, dump[:4000]
        )


if __name__ == "__main__":
    unittest.main()
