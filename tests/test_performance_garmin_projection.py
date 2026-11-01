import unittest
from datetime import date

from performance_day_support import garmin_metrics_from_payload

from backend.performance.freshness import GarminSyncStatus
from backend.performance.garmin_projection import (
    garmin_training_load_projection as project_training_load,
)
from backend.providers.garmin_morning import latest_garmin_record


def garmin_training_load_projection(snapshot, current_date):
    """Project the canonical values the production mapper makes of the snapshot."""
    return project_training_load(
        GarminSyncStatus.from_state(snapshot),
        current_date,
        garmin_metrics_from_payload(snapshot),
    )


class GarminProjectionTests(unittest.TestCase):
    def test_latest_record_prefers_dated_records_and_latest_date(self):
        value = {
            "records": [
                {"id": "9999", "score": 1},
                {"calendarDate": "2026-08-28", "score": 28},
                {"summaryDate": "2026-08-30", "score": 30},
                {"date": "2026-08-29", "score": 29},
            ],
            "untrusted": {"id": "newer-id", "score": 99},
        }
        result = latest_garmin_record(value)
        self.assertEqual(result, {"summaryDate": "2026-08-30", "score": 30})

    def test_latest_record_list_limit_visit_limit_and_fallback(self):
        records = [{"id": f"{index:04}"} for index in range(501)]
        self.assertEqual(latest_garmin_record(records)["id"], "0499")

        chain: dict[str, object] = {"id": f"{2005:04}"}
        for index in range(2004, -1, -1):
            chain = {"id": f"{index:04}", "next": chain}
        self.assertEqual(latest_garmin_record(chain)["id"], "1999")

        original = {"payload": {"unrelated": True}}
        self.assertIs(latest_garmin_record(original), original)
        self.assertEqual(latest_garmin_record([{"payload": True}]), {})

    def test_training_load_projection_uses_verified_fields_and_provenance(self):
        snapshot = {
            "training_load_balance": {
                "metricsTrainingLoadBalanceDTOMap": {
                    "device-a": {
                        "primaryTrainingDevice": True,
                        "calendarDate": "2026-10-06",
                        "monthlyLoadAerobicLow": 75,
                        "monthlyLoadAerobicLowTargetMin": 50,
                        "monthlyLoadAerobicLowTargetMax": 100,
                        "monthlyLoadAerobicHigh": 40,
                        "monthlyLoadAerobicHighTargetMin": 30,
                        "monthlyLoadAerobicHighTargetMax": 60,
                        "monthlyLoadAnaerobic": 12,
                        "monthlyLoadAnaerobicTargetMin": 5,
                        "monthlyLoadAnaerobicTargetMax": 20,
                        "trainingBalanceFeedbackPhrase": "free form text",
                    }
                }
            },
            "daily_training_status": {
                "latestTrainingStatusData": {
                    "device-a": {
                        "primaryTrainingDevice": True,
                        "calendarDate": "2026-10-06",
                        "acuteTrainingLoadDTO": {
                            "dailyTrainingLoadAcute": 110,
                            "dailyTrainingLoadChronic": 95,
                            "dailyAcuteChronicWorkloadRatio": 1.15,
                        },
                        "trainingStatusFeedbackPhrase": "free form text",
                    }
                }
            },
            "source_freshness": {
                "training_load_balance": {
                    "freshness": "current",
                    "observed_at": "2026-10-06",
                    "fetched_at": "2026-10-06T08:00:00Z",
                },
                "daily_training_status": {
                    "freshness": "partial",
                    "observed_at": "2026-10-06",
                    "fetched_at": "2026-10-06T08:00:00Z",
                },
            },
        }
        result = garmin_training_load_projection(snapshot, date(2026, 10, 6))
        self.assertEqual(result["four_week_balance"]["monthlyLoadAerobicLow"], 75)
        self.assertEqual(result["four_week_balance"]["freshness"], "current")
        self.assertNotIn("trainingBalanceFeedbackPhrase", str(result))
        self.assertEqual(result["daily_status"]["acute_load"], 110)
        self.assertEqual(result["daily_status"]["chronic_load"], 95)
        self.assertEqual(result["daily_status"]["acute_chronic_ratio"], 1.15)
        self.assertEqual(result["daily_status"]["freshness"], "partial")

    def test_ambiguous_device_load_balance_stays_unknown(self):
        result = garmin_training_load_projection(
            {
                "training_load_balance": {
                    "metricsTrainingLoadBalanceDTOMap": {
                        "device-a": {
                            "calendarDate": "2026-10-06",
                            "monthlyLoadAerobicLow": 20,
                        },
                        "device-b": {
                            "calendarDate": "2026-10-06",
                            "monthlyLoadAerobicLow": 30,
                        },
                    }
                }
            },
            date(2026, 10, 6),
        )
        self.assertNotIn("four_week_balance", result)

    def test_multiple_primary_devices_and_unverified_shapes_stay_unknown(self):
        result = garmin_training_load_projection(
            {
                "training_load_balance": {
                    "metricsTrainingLoadBalanceDTOMap": {
                        "device-a": {
                            "primaryTrainingDevice": True,
                            "calendarDate": "2026-10-06",
                            "monthlyLoadAerobicLow": 20,
                        },
                        "device-b": {
                            "primaryTrainingDevice": True,
                            "calendarDate": "2026-10-06",
                            "monthlyLoadAerobicLow": 20,
                        },
                    }
                },
                "daily_training_status": {"load": 123},
            },
            date(2026, 10, 6),
        )
        self.assertNotIn("four_week_balance", result)
        self.assertNotIn("daily_status", result)

    def test_old_observation_and_malformed_primary_date_hide_load_values(self):
        result = garmin_training_load_projection(
            {
                "training_load_balance": {
                    "metricsTrainingLoadBalanceDTOMap": {
                        "device-a": {
                            "primaryTrainingDevice": True,
                            "calendarDate": "not-a-date",
                            "monthlyLoadAerobicLow": 20,
                        }
                    }
                },
                "daily_training_status": {
                    "latestTrainingStatusData": {
                        "device-a": {
                            "primaryTrainingDevice": True,
                            "calendarDate": "2026-10-05",
                            "acuteTrainingLoadDTO": {
                                "dailyTrainingLoadAcute": 100,
                                "dailyTrainingLoadChronic": 90,
                            },
                        }
                    }
                },
                "source_freshness": {
                    "training_load_balance": {
                        "freshness": "current",
                        "observed_at": "2026-10-06",
                    },
                    "daily_training_status": {
                        "freshness": "current",
                        "observed_at": "2026-10-05",
                    },
                },
            },
            date(2026, 10, 6),
        )
        self.assertNotIn("four_week_balance", result)
        self.assertIsNone(result["daily_status"]["acute_load"])
        self.assertIsNone(result["daily_status"]["chronic_load"])

    def test_selected_primary_date_controls_daily_load_freshness(self):
        for primary_day, secondary_day in (
            ("2026-10-05", "2026-10-06"),
            ("2026-10-07", "2026-10-06"),
        ):
            with self.subTest(primary_day=primary_day):
                result = garmin_training_load_projection(
                    {
                        "daily_training_status": {
                            "latestTrainingStatusData": {
                                "device-a": {
                                    "primaryTrainingDevice": True,
                                    "calendarDate": primary_day,
                                    "acuteTrainingLoadDTO": {
                                        "dailyTrainingLoadAcute": 100,
                                        "dailyTrainingLoadChronic": 90,
                                    },
                                },
                                "device-b": {
                                    "primaryTrainingDevice": False,
                                    "calendarDate": secondary_day,
                                    "acuteTrainingLoadDTO": {
                                        "dailyTrainingLoadAcute": 80,
                                        "dailyTrainingLoadChronic": 85,
                                    },
                                },
                            }
                        },
                        "source_freshness": {
                            "daily_training_status": {
                                "freshness": "current",
                                "observed_at": "2026-10-06",
                            }
                        },
                    },
                    date(2026, 10, 6),
                )
                self.assertIsNone(result["daily_status"]["acute_load"])
                self.assertIsNone(result["daily_status"]["chronic_load"])


if __name__ == "__main__":
    unittest.main()
