"""Garmin training sections and status codes in the canonical model.

Synthetic Garmin sections only; no account, network or real data is used.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from backend.canonical.vocabulary import CategoricalDomain, MetricKind, Sport
from backend.providers import canonical_plans
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.providers.garmin_status_mapping import map_garmin_status_codes

ZONE = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)
DAY = "2026-10-10"


def rows(sections: object) -> list[tuple[str, float, str, str]]:
    return sorted(
        (
            o.kind.value,
            o.value.value,
            o.observed_on.isoformat(),
            "-" if o.sport is None else o.sport.value,
        )
        for o in map_garmin_health(
            sections, zone=ZONE, retrieved_at=RETRIEVED_AT
        ).records
    )


def device(day: str = DAY, primary: bool | None = True, **acute: float) -> dict:
    record: dict = {"calendarDate": day, "acuteTrainingLoadDTO": acute}
    if primary is not None:
        record["primaryTrainingDevice"] = primary
    return record


def daily(*devices: dict) -> dict:
    return {
        "mostRecentTrainingStatus": {
            "latestTrainingStatusData": {f"dev-{i}": d for i, d in enumerate(devices)}
        }
    }


class DailyTrainingStatusTests(unittest.TestCase):
    def test_primary_device_values_are_mapped(self) -> None:
        self.assertEqual(
            rows(
                {
                    "daily_training_status": daily(
                        device(
                            dailyTrainingLoadAcute=480,
                            dailyTrainingLoadChronic=0,
                            dailyAcuteChronicWorkloadRatio=1.17,
                        ),
                        device(primary=False, dailyTrainingLoadAcute=900),
                    )
                }
            ),
            [
                ("acute_chronic_ratio", 1.17, DAY, "-"),
                ("acute_load", 480.0, DAY, "-"),
                ("chronic_load", 0.0, DAY, "-"),
            ],
        )

    def test_disagreeing_devices_without_a_primary_map_nothing(self) -> None:
        self.assertEqual(
            rows(
                {
                    "daily_training_status": daily(
                        device(primary=None, dailyTrainingLoadAcute=480),
                        device(primary=None, dailyTrainingLoadAcute=500),
                    )
                }
            ),
            [],
        )

    def test_unresolved_devices_are_reported_as_a_coverage_gap(self) -> None:
        result = map_garmin_health(
            {
                "daily_training_status": daily(
                    device(primary=None, dailyTrainingLoadAcute=480),
                    device(primary=None, dailyTrainingLoadAcute=500),
                )
            },
            zone=ZONE,
            retrieved_at=RETRIEVED_AT,
        )
        self.assertEqual(
            [(i.record_ref, i.field, i.reason.value) for i in result.issues],
            [(None, "daily_training_status", "unknown_value")],
        )

    def test_agreeing_latest_devices_map_once(self) -> None:
        self.assertEqual(
            rows(
                {
                    "daily_training_status": daily(
                        device(primary=None, dailyTrainingLoadAcute=480),
                        device(primary=None, dailyTrainingLoadAcute=480),
                        device("2026-10-01", None, dailyTrainingLoadAcute=10),
                    )
                }
            ),
            [("acute_load", 480.0, DAY, "-")],
        )


class LoadBalanceTests(unittest.TestCase):
    def test_balance_and_targets_are_separate_kinds(self) -> None:
        balance = {
            "metricsTrainingLoadBalanceDTOMap": {
                "dev": {
                    "calendarDate": DAY,
                    "primaryTrainingDevice": True,
                    "monthlyLoadAnaerobic": 30,
                    "monthlyLoadAnaerobicTargetMin": 0,
                    "trainingBalanceFeedbackPhrase": "free text is ignored",
                }
            }
        }
        self.assertEqual(
            rows({"training_load_balance": balance}),
            [
                ("load_balance_anaerobic", 30.0, DAY, "-"),
                ("load_balance_anaerobic_target_min", 0.0, DAY, "-"),
            ],
        )


class HistoryTests(unittest.TestCase):
    def test_acute_load_history_and_ambiguous_rows(self) -> None:
        self.assertEqual(
            rows(
                {
                    "training_status": [
                        {"calendarDate": "2026-10-08", "acuteTrainingLoad": 300},
                        {
                            "calendarDate": "2026-10-09",
                            "acuteTrainingLoadDTO": {"acuteTrainingLoad": 310},
                        },
                        {
                            "calendarDate": DAY,
                            "acuteTrainingLoad": 1,
                            "nested": {"dailyTrainingLoadAcute": 2},
                        },
                        {"acuteTrainingLoad": 400},
                    ],
                    "weekly_training_status": {
                        "weeklyTrainingStatusDTOList": [
                            {"date": "2026-10-03", "dailyTrainingLoadAcute": 250}
                        ]
                    },
                }
            ),
            [
                ("acute_load", 250.0, "2026-10-03", "-"),
                ("acute_load", 300.0, "2026-10-08", "-"),
                ("acute_load", 310.0, "2026-10-09", "-"),
            ],
        )

    def test_tolerance_readiness_history_and_endurance_groups(self) -> None:
        self.assertEqual(
            rows(
                {
                    "running_tolerance": [
                        {"calendarDate": DAY, "toleranceScore": 72},
                        {
                            "calendarDate": DAY,
                            "date": "2026-10-11",
                            "toleranceScore": 1,
                        },
                    ],
                    "training_readiness_history": [
                        {"calendarDate": "2026-10-09", "score": 64, "level": "MODERATE"}
                    ],
                    "endurance_score": {
                        "overallScore": 6850,
                        "calendarDate": DAY,
                        "groupMap": {
                            "2026-09-28": {"groupAverage": 6800, "groupMax": 6900},
                            "invalid": {"groupAverage": 7200},
                        },
                    },
                }
            ),
            [
                ("endurance_score", 6850.0, DAY, "-"),
                ("endurance_score_group_average", 6800.0, "2026-09-28", "-"),
                ("endurance_score_group_max", 6900.0, "2026-09-28", "-"),
                ("readiness", 64.0, "2026-10-09", "-"),
                ("running_tolerance", 72.0, DAY, Sport.RUN.value),
            ],
        )


class StatusCodeTests(unittest.TestCase):
    def codes(self, section: str, element: object) -> list[tuple[str, str, str]]:
        return [
            (o.domain.value, o.code, o.observed_on.isoformat())
            for o in map_garmin_status_codes(
                section,
                element,
                source_record_id=f"{section}/{DAY}",
                retrieved_at=RETRIEVED_AT,
            )
        ]

    def test_hrv_status_and_readiness_levels(self) -> None:
        self.assertEqual(
            self.codes("hrv", {"calendarDate": DAY, "hrvStatus": "BALANCED"}),
            [(CategoricalDomain.HRV_STATUS.value, "BALANCED", DAY)],
        )
        self.assertEqual(
            self.codes("readiness", {"calendarDate": DAY, "level": "HIGH"}),
            [(CategoricalDomain.READINESS_LEVEL.value, "HIGH", DAY)],
        )
        self.assertEqual(
            self.codes(
                "training_readiness_history",
                {"data": [{"calendarDate": "2026-10-09", "level": "LOW"}]},
            ),
            [(CategoricalDomain.READINESS_LEVEL.value, "LOW", "2026-10-09")],
        )

    def test_training_status_text_code_of_the_primary_device(self) -> None:
        element = daily(
            {**device(), "trainingStatus": "PRODUCTIVE"},
            {**device(primary=False), "trainingStatus": "PEAKING"},
        )
        self.assertEqual(
            self.codes("daily_training_status", element),
            [(CategoricalDomain.TRAINING_STATUS.value, "PRODUCTIVE", DAY)],
        )

    def test_numeric_free_text_and_undated_codes_are_not_mapped(self) -> None:
        for section, element in (
            ("daily_training_status", daily({**device(), "trainingStatus": 4})),
            ("hrv", {"calendarDate": DAY, "hrvStatus": "free form text"}),
            ("hrv", {"hrvStatus": "BALANCED"}),
            ("readiness", {"calendarDate": DAY, "level": None}),
            ("sleep", {"calendarDate": DAY, "level": "HIGH"}),
        ):
            with self.subTest(section=section, element=element):
                self.assertEqual(self.codes(section, element), [])


class PlanTests(unittest.TestCase):
    def test_status_codes_travel_as_batches_and_reproject_without_refetch(
        self,
    ) -> None:
        plan = canonical_plans.garmin_ingest_plan(
            {
                "synced_at": "2026-10-11T06:00:00+00:00",
                "hrv": [
                    {"calendarDate": DAY, "hrvStatus": "BALANCED", "lastNightAvg": 61}
                ],
            },
            zone=ZONE,
        )
        (raw,) = plan.raw_records
        (batch,) = plan.domain_batches
        self.assertEqual(batch.source_record_id, raw.source_record_id)
        self.assertEqual([o.code for o in batch.categorical], ["BALANCED"])
        reprojected = canonical_plans.reprojection_plan(
            {
                "provider": "garmin",
                "record_kind": raw.record_kind,
                "source_record_id": raw.source_record_id,
                "payload": json.dumps(raw.payload),
                "fetched_at": (raw.retrieved_at or RETRIEVED_AT).isoformat(),
            },
            zone=ZONE,
        )
        assert reprojected is not None
        self.assertEqual(reprojected.domain_batches, (batch,))
        self.assertIn(
            MetricKind.HRV_RMSSD,
            [item.observation.kind for item in reprojected.observations],
        )


if __name__ == "__main__":
    unittest.main()
