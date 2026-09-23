import copy
import unittest
from datetime import date

from backend.performance.freshness import (
    garmin_metric_freshness,
    garmin_source_freshness,
    measurement_age,
)


class MeasurementAgeTests(unittest.TestCase):
    def test_today_earlier_and_future(self):
        current = date(2026, 9, 20)
        self.assertEqual(
            measurement_age("2026-09-20T07:00:00", current),
            {"measurement_status": "today", "measurement_age_days": 0},
        )
        self.assertEqual(
            measurement_age("2026-09-18", current),
            {"measurement_status": "earlier", "measurement_age_days": 2},
        )
        self.assertEqual(
            measurement_age("2026-09-21", current),
            {"measurement_status": "future", "measurement_age_days": -1},
        )

    def test_invalid_and_none_are_unknown(self):
        current = date(2026, 9, 20)
        expected = {"measurement_status": "unknown", "measurement_age_days": None}
        self.assertEqual(measurement_age(None, current), expected)
        self.assertEqual(measurement_age("malformed", current), expected)

    def test_current_date_is_required(self):
        with self.assertRaises(TypeError):
            measurement_age("2026-09-20")
        with self.assertRaises(TypeError):
            garmin_source_freshness({})
        with self.assertRaises(TypeError):
            garmin_metric_freshness({}, "weight", {"value": 0})


class GarminSourceFreshnessTests(unittest.TestCase):
    def test_only_dict_sources_are_projected(self):
        snapshot = {
            "source_freshness": {
                "sleep": {"freshness": "current", "observed_at": "2026-09-20"},
                "invalid": None,
                "other": "not-a-dict",
            }
        }
        self.assertEqual(
            garmin_source_freshness(snapshot, date(2026, 9, 20)),
            {
                "sleep": {
                    "freshness": "current",
                    "observed_at": "2026-09-20",
                    "measurement_status": "today",
                    "measurement_age_days": 0,
                }
            },
        )


class GarminMetricFreshnessTests(unittest.TestCase):
    def test_observed_at_key_present_with_none_wins_over_source(self):
        snapshot = {
            "source_freshness": {
                "weight": {
                    "freshness": "current",
                    "observed_at": "2026-09-18",
                    "fetched_at": "2026-09-20T08:00:00+00:00",
                }
            }
        }
        result = garmin_metric_freshness(
            snapshot,
            "weight",
            {"value": 70, "observed_at": None},
            date(2026, 9, 20),
        )
        self.assertIsNone(result["observed_at"])
        self.assertEqual(result["measurement_status"], "unknown")
        self.assertEqual(result["fetched_at"], "2026-09-20T08:00:00+00:00")

    def test_current_stale_partial_unknown_and_notes(self):
        current = garmin_metric_freshness(
            {"source_freshness": {"sleep": {"freshness": "current"}}},
            "sleep",
            {"value": 8},
            date(2026, 9, 20),
        )
        stale = garmin_metric_freshness(
            {
                "source_freshness": {
                    "weight": {"freshness": "stale", "observed_at": "2026-09-18"}
                }
            },
            "weight",
            {"value": 70, "note": "Vorhanden"},
            date(2026, 9, 20),
        )
        partial = garmin_metric_freshness(
            {"source_freshness": {"hrv": {"freshness": "partial"}}},
            "hrv",
            {"value": 45},
            date(2026, 9, 20),
        )
        unknown = garmin_metric_freshness(
            {}, "missing", {"value": None}, date(2026, 9, 20)
        )
        self.assertEqual(current["freshness"], "current")
        self.assertEqual(stale["freshness"], "stale")
        self.assertEqual(
            stale["note"],
            "Vorhanden; Messung ist 2 Tage alt; das Abrufdatum ist keine neue Messung.; "
            "Letzter guter Wert; Quelle nicht aktualisiert",
        )
        self.assertEqual(partial["note"], "Quelle nur teilweise aktualisiert")
        self.assertEqual(unknown["freshness"], "unknown")
        self.assertNotIn("note", unknown)

    def test_zero_value_counts_and_inputs_are_not_mutated(self):
        snapshot = {
            "source_freshness": {
                "weight": {"freshness": "stale", "observed_at": "2026-09-19"}
            }
        }
        value = {"value": 0}
        before = copy.deepcopy((snapshot, value))
        result = garmin_metric_freshness(snapshot, "weight", value, date(2026, 9, 20))
        self.assertIn("Letzter guter Wert", result["note"])
        self.assertEqual((snapshot, value), before)


if __name__ == "__main__":
    unittest.main()
