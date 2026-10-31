"""Garmin history charts show the same points from canonical values.

The snapshot charts keep every numeric field of a record; the analysis view shows
one value per point (``providerMetricValue`` in public/analysis.js, or the point
value for readiness and the weekly status). The canonical charts carry the shown
fields only, so the comparison is on the shown date and value. Synthetic Garmin
sections only; no account, network or real data is used.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.vocabulary import MetricKind
from backend.performance import chart_history
from backend.performance.garmin_canonical import read_garmin_state
from backend.providers.garmin_health_mapping import map_garmin_health

TODAY = date(2026, 10, 12)
START = TODAY - timedelta(days=89)
ZONE = ZoneInfo("Europe/Berlin")
# public/analysis.js providerMetricValue.
SHOWN_FIELDS = {
    "endurance_score": ("overallScore", "enduranceScore", "score", "groupAverage"),
    "running_tolerance": ("toleranceScore", "runningTolerance", "tolerance"),
}


class MappedReader:
    def __init__(self, sections: dict[str, Any]) -> None:
        self.records = map_garmin_health(
            sections, zone=ZONE, retrieved_at=datetime(2026, 10, 12, 6, tzinfo=UTC)
        ).records

    def observations(self, db: Any, kind: MetricKind, **_: Any) -> tuple:
        return tuple(record for record in self.records if record.kind is kind)


def shown(metrics: dict[str, Any]) -> dict[str, list[tuple[str, Any]]]:
    result: dict[str, list[tuple[str, Any]]] = {}
    for key, item in metrics.items():
        points = []
        for point in item["points"]:
            if key in SHOWN_FIELDS:
                value = next(
                    (
                        point["values"][field]
                        for field in SHOWN_FIELDS[key]
                        if isinstance(point["values"].get(field), int | float)
                    ),
                    None,
                )
            else:
                value = point.get("value")
            if value is not None:
                points.append((point["date"], value))
        result[key] = points
    return result


def day(offset: int) -> str:
    return (TODAY - timedelta(days=offset)).isoformat()


GARMIN = {
    "synced_at": "2026-10-12T06:00:00Z",
    "endurance_score": {
        "groupMap": {
            day(14): {"groupAverage": 6800, "groupMax": 6900},
            day(7): {"groupAverage": 6850},
        },
    },
    "running_tolerance": [
        {"calendarDate": day(3), "toleranceScore": 72},
        {"calendarDate": day(1), "toleranceScore": 0},
    ],
    "training_readiness_history": [
        {"calendarDate": day(2), "score": 64, "level": "MODERATE"},
        {"calendarDate": day(1), "score": 70},
    ],
    "weekly_training_status": {
        "weeklyTrainingStatusDTOList": [
            {"date": day(7), "dailyTrainingLoadAcute": 410},
            {"date": day(0), "dailyTrainingLoadAcute": 455},
        ]
    },
    "training_status": [
        {"calendarDate": day(4), "acuteTrainingLoadDTO": {"acuteTrainingLoad": 380}},
        {
            "calendarDate": day(5),
            "acuteTrainingLoad": 1,
            "other": {"dailyTrainingLoadAcute": 2},
        },
    ],
}


class ChartParityTests(unittest.TestCase):
    def canonical(self) -> Any:
        return read_garmin_state(MappedReader(GARMIN), None).metrics

    def test_provider_charts_show_the_same_points(self) -> None:
        sections = {
            key: value for key, value in GARMIN.items() if key != "training_status"
        }
        canonical = chart_history._provider_metrics(
            {"synced_at": GARMIN["synced_at"]},
            START,
            TODAY,
            read_garmin_state(MappedReader(sections), None).metrics,
        )
        self.assertEqual(
            shown(canonical),
            {
                "endurance_score": [(day(14), 6800), (day(7), 6850)],
                "running_tolerance": [(day(3), 72), (day(1), 0)],
                "training_readiness_history": [(day(2), 64), (day(1), 70)],
                "weekly_training_status": [(day(7), 410), (day(0), 455)],
            },
        )
        self.assertEqual(
            shown(canonical)["running_tolerance"], [(day(3), 72), (day(1), 0)]
        )
        for item in canonical.values():
            self.assertEqual(item["fetched_at"], GARMIN["synced_at"])

    def test_a_cached_chart_keeps_its_status_and_takes_the_sync_time(self) -> None:
        cached = {
            "running_tolerance": {
                "status": "stale",
                "fetched_at": "2026-10-05T06:00:00Z",
                "points": [],
            }
        }
        sections = {"synced_at": GARMIN["synced_at"], "provider_metrics": cached}
        canonical = chart_history._provider_metrics(
            sections, START, TODAY, self.canonical()
        )
        item = canonical["running_tolerance"]
        self.assertEqual(item["status"], "stale")
        self.assertEqual(item["fetched_at"], GARMIN["synced_at"])
        self.assertEqual(
            shown(canonical)["running_tolerance"], [(day(3), 72), (day(1), 0)]
        )

    def test_acute_load_is_one_quantity_across_garmin_sections(self) -> None:
        # The training-status history adds its day to the weekly acute-load chart
        # (one ACUTE_LOAD row per day, athlete decision 2026-10-25).
        canonical = chart_history._provider_metrics(
            {"synced_at": GARMIN["synced_at"]}, START, TODAY, self.canonical()
        )
        self.assertEqual(
            shown(canonical)["weekly_training_status"],
            [(day(7), 410), (day(4), 380), (day(0), 455)],
        )

    def test_acute_load_history_skips_ambiguous_days(self) -> None:
        dates = [(START + timedelta(days=i)).isoformat() for i in range(90)]
        only_status = read_garmin_state(
            MappedReader({"training_status": GARMIN["training_status"]}), None
        ).metrics
        load = chart_history._load_history(dates, only_status)
        self.assertIn({"date": day(4), "value": 380}, load)
        self.assertIn({"date": day(5), "value": None}, load)
        self.assertEqual(sum(point["value"] is not None for point in load), 1)


if __name__ == "__main__":
    unittest.main()
