import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from canonical_recovery_support import mapped_personal_recovery, mapped_recovery_inputs

from backend.athlete.profile import normalize_profile
from backend.canonical.records import UNKNOWN_CONTEXT, MeasurementContext
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.errors import AppError
from backend.performance.personal_recovery import personal_recovery


class PersonalRecoveryTests(unittest.TestCase):
    today = date(2026, 10, 2)

    def rows(self, nights):
        return [
            {
                "id": (self.today - timedelta(days=i)).isoformat(),
                "sleepSecs": 7 * 3600,
                "restingHR": 50,
                "hrv": 40,
            }
            for i in range(nights + 1)
        ]

    def test_coverage_and_excluding_current_value_from_baseline(self):
        for nights, status in (
            (13, "insufficient_data"),
            (14, "provisional"),
            (28, "ok"),
        ):
            rows = self.rows(nights)
            rows[0]["restingHR"] = 100
            result = mapped_personal_recovery(rows, {}, {}, self.today)
            pulse = next(
                row for row in result["baselines"] if row["metric"] == "resting_hr"
            )
            self.assertEqual(status, pulse["status"])
            if nights >= 14:
                self.assertEqual(50, pulse["median"])
                self.assertEqual("above", pulse["position"])
            hrv = next(row for row in result["baselines"] if row["metric"] == "hrv")
            self.assertEqual(("RMSSD", status), (hrv["measurement"], hrv["status"]))
            self.assertEqual(
                {"sleep": "duration", "resting_hr": "resting", "hrv": "RMSSD"},
                {row["metric"]: row["measurement"] for row in result["baselines"]},
            )

    def test_future_stale_and_separate_hrv_methods_are_not_classified(self):
        rows = self.rows(30)
        for row in rows:
            row["hrvSDNN"] = 30
        rows.append(
            {
                "id": "2026-10-03",
                "restingHR": 200,
                "sleepSecs": 100,
                "hrv": 200,
                "hrvSDNN": 200,
            }
        )
        result = mapped_personal_recovery(rows, {}, {}, self.today)
        self.assertEqual(
            {"RMSSD", "SDNN"},
            {
                row["measurement"]
                for row in result["baselines"]
                if row["metric"] == "hrv"
            },
        )
        self.assertFalse(
            any(
                point["date"] > "2026-10-02"
                for row in result["baselines"]
                for point in row["history"]
            )
        )
        stale = mapped_personal_recovery(self.rows(30)[3:], {}, {}, self.today)
        self.assertTrue(
            all(row["status"] == "insufficient_data" for row in stale["baselines"])
        )

    def garmin_hrv(self, contexts, *, old=55, new=55, nights=31):
        """Return Garmin HRV over 30 earlier nights, re-measured from ``contexts``.

        ``contexts`` maps days before today to the context of that night and of
        every newer night; older nights keep the mapped overnight context.
        """
        garmin = {
            "hrv": [
                {
                    "calendarDate": (self.today - timedelta(days=day)).isoformat(),
                    "lastNightAvg": old if day > min(contexts, default=-1) else new,
                }
                for day in range(nights)
            ]
        }
        inputs = mapped_recovery_inputs(garmin, [])
        observations = []
        for observation in inputs.of(MetricKind.HRV_RMSSD):
            age = (self.today - observation.observed_on).days
            starts = [day for day in contexts if age <= day]
            if starts:
                provenance = replace(
                    observation.provenance, context=contexts[min(starts)]
                )
                observation = replace(observation, provenance=provenance)
            observations.append(observation)
        inputs = replace(
            inputs,
            observations={
                **inputs.observations,
                MetricKind.HRV_RMSSD: tuple(observations),
            },
        )
        (baseline,) = [
            row
            for row in personal_recovery({}, self.today, canonical=inputs)["baselines"]
            if row["source_provider"] == ProviderId.GARMIN.value
            and row["metric"] == "hrv"
        ]
        return baseline

    def test_device_change_restarts_the_comparison(self):
        device = MeasurementContext(device_model="Forerunner 965", window="overnight")
        fresh = self.garmin_hrv({4: device})
        self.assertEqual(
            ("insufficient_data", 4, "2026-09-28", "known"),
            (
                fresh["status"],
                fresh["nights"],
                fresh["context_changed_on"],
                fresh["continuity"],
            ),
        )
        self.assertEqual(
            "Messkontext geändert; mindestens 14 passende Nächte seitdem erforderlich.",
            fresh["reason"],
        )
        self.assertEqual(
            {"device_model": "Forerunner 965", "window": "overnight"},
            fresh["measurement_context"],
        )
        self.assertNotIn("position", fresh)
        self.assertEqual(31, len(fresh["history"]))

        settled = self.garmin_hrv({20: device}, old=90, new=40)
        self.assertEqual(
            ("provisional", 20, 40, "within"),
            (
                settled["status"],
                settled["nights"],
                settled["median"],
                settled["position"],
            ),
        )

    def test_unknown_metadata_is_its_own_context_with_unknown_continuity(self):
        unchanged = self.garmin_hrv({})
        self.assertEqual(
            ("ok", None, "unknown", {"window": "overnight"}),
            (
                unchanged["status"],
                unchanged["context_changed_on"],
                unchanged["continuity"],
                unchanged["measurement_context"],
            ),
        )
        lost = self.garmin_hrv({2: UNKNOWN_CONTEXT})
        self.assertEqual(
            ("2026-09-30", 2, {}),
            (lost["context_changed_on"], lost["nights"], lost["measurement_context"]),
        )
        intervals = mapped_personal_recovery(self.rows(30), {}, {}, self.today)
        for row in intervals["baselines"]:
            self.assertEqual("ok", row["status"])
            if row["metric"] == "sleep":
                self.assertNotIn("continuity", row)
            else:
                self.assertEqual(
                    ("unknown", None), (row["continuity"], row["context_changed_on"])
                )

    def test_a_change_before_the_window_is_not_reported(self):
        device = MeasurementContext(device_model="Forerunner 965", window="overnight")
        old = self.garmin_hrv({50: device}, nights=60)
        self.assertEqual(
            (None, 42, "ok"), (old["context_changed_on"], old["nights"], old["status"])
        )

    def test_legacy_hrv_method_field_is_ignored(self):
        rows = self.rows(14)
        for row in rows:
            row["hrv_method"] = "SDNN"
        result = mapped_personal_recovery(rows, {}, {}, self.today)
        self.assertEqual(
            ["RMSSD"],
            [
                row["measurement"]
                for row in result["baselines"]
                if row["metric"] == "hrv"
            ],
        )

    def test_deficit_uses_known_nights_and_never_offsets_with_long_sleep(self):
        rows = self.rows(5)
        rows[0]["sleepSecs"] = 10 * 3600
        result = mapped_personal_recovery(
            rows, {}, {"sleep_target_hours": "8"}, self.today
        )
        deficit = result["sleep_deficits"][0]
        self.assertEqual(
            (5, 6, "partial"),
            (deficit["deficit_hours"], deficit["known_nights"], deficit["status"]),
        )
        self.assertEqual(
            [], mapped_personal_recovery(rows, {}, {}, self.today)["sleep_deficits"]
        )

    def test_note_states_the_limits_of_the_comparison(self):
        result = mapped_personal_recovery(self.rows(30), {}, {}, self.today)
        note = result["note"]
        for sentence in (
            "mit deinen eigenen früheren Werten",
            "etwa die Hälfte der Werte",
            "Keine Diagnose, keine Trainingsfreigabe und keine Trainingsänderung",
            "summiert nur bekannte Nächte",
            "fehlende Nächte und nicht erfasste Nickerchen begrenzen diese Aussage",
            "Schätzung des jeweiligen Geräts, kein gemessener Schlafbedarf",
            "kein Sleep Regularity Index",
        ):
            self.assertIn(sentence, note)
        self.assertEqual("personal-quartiles-v1", result["method"])
        self.assertEqual("sleep-timing-variability-v2", result["regularity"]["method"])

    def test_profile_target_requires_valid_explicit_value(self):
        self.assertEqual(
            "8", normalize_profile({"sleep_target_hours": 8})["sleep_target_hours"]
        )
        for value in (3, 13, "nan", "no"):
            with self.subTest(value=value), self.assertRaises(AppError):
                normalize_profile({"sleep_target_hours": value})

    def test_eight_calendar_weeks_keep_a_42_day_comparison_range(self):
        rows = self.rows(60)
        for row in rows:
            if row["id"] < "2026-08-21":
                row["restingHR"] = 100
        result = mapped_personal_recovery(rows, {}, {}, self.today)
        pulse = next(
            row for row in result["baselines"] if row["metric"] == "resting_hr"
        )
        self.assertEqual("2026-08-03", pulse["history"][0]["date"])
        self.assertEqual(61, len(pulse["history"]))
        self.assertEqual(42, pulse["nights"])
        self.assertEqual(50, pulse["median"])

    def sleep_rows(
        self, count, *, start="2026-09-01T21:30:00Z", end="2026-09-02T05:30:00Z"
    ):
        from datetime import datetime

        result = []
        for index in range(count):
            day = self.today - timedelta(days=count - index)
            start_dt = datetime.fromisoformat(start) + timedelta(days=index)
            end_dt = datetime.fromisoformat(end) + timedelta(days=index)
            result.append(
                {
                    "calendarDate": day.isoformat(),
                    "sleepStartTimestampGMT": int(
                        start_dt.replace(tzinfo=UTC).timestamp() * 1000
                    ),
                    "sleepEndTimestampGMT": int(
                        end_dt.replace(tzinfo=UTC).timestamp() * 1000
                    ),
                }
            )
        current_start = datetime.combine(
            self.today - timedelta(days=1), datetime.min.time(), tzinfo=UTC
        ).replace(hour=21, minute=30)
        current_end = datetime.combine(
            self.today, datetime.min.time(), tzinfo=UTC
        ).replace(hour=5, minute=30)
        result.append(
            {
                "calendarDate": self.today.isoformat(),
                "sleepStartTimestampGMT": int(current_start.timestamp() * 1000),
                "sleepEndTimestampGMT": int(current_end.timestamp() * 1000),
            }
        )
        return result

    def test_sleep_timing_variability_coverage_thresholds_and_display_contract(self):
        for nights, expected in (
            (13, "insufficient_data"),
            (14, "provisional"),
            (27, "provisional"),
            (28, "ok"),
        ):
            with self.subTest(nights=nights):
                result = mapped_personal_recovery(
                    [],
                    {"sleep": self.sleep_rows(nights)},
                    {"timezone": "UTC"},
                    self.today,
                )["regularity"]
                item = result["series"][0]
                self.assertEqual(expected, item["status"])
                self.assertEqual(nights, item["coverage"]["baseline_nights"])
                self.assertEqual(14, len(item["points_14"]))
                self.assertEqual(84, len(item["points_84"]))
                self.assertEqual("Garmin Connect", item["source"])
                self.assertTrue(item["method"].startswith("sleepStartTimestampGMT/"))

    def test_sleep_timing_variability_circular_midnight_median_and_sources(self):
        # 15 rows; the moved second row shares a wake date, leaving 14 earlier.
        rows = self.sleep_rows(
            15, start="2026-09-01T21:50:00Z", end="2026-09-02T05:50:00Z"
        )
        rows[1]["sleepStartTimestampGMT"] = int(
            datetime(2026, 9, 1, 22, 10, tzinfo=UTC).timestamp() * 1000
        )
        rows[1]["sleepEndTimestampGMT"] = int(
            datetime(2026, 9, 2, 6, 10, tzinfo=UTC).timestamp() * 1000
        )
        result = mapped_personal_recovery(
            [], {"sleep": rows}, {"timezone": "UTC"}, self.today
        )["regularity"]
        self.assertEqual(
            0, result["series"][0]["baseline"]["onset_deviation_median_minutes"]
        )
        self.assertEqual(
            {"Garmin Connect"}, {item["source"] for item in result["series"]}
        )

    def test_sleep_intervals_reject_future_missing_and_reversed_and_keep_dst_duration(
        self,
    ):
        malformed = [
            {
                "calendarDate": "2026-10-01",
                "sleepStartTimestampGMT": "2026-10-01T22:00:00Z",
            },
            {
                "calendarDate": "2026-10-01",
                "sleepStartTimestampGMT": "2026-10-02T05:00:00Z",
                "sleepEndTimestampGMT": "2026-10-02T04:00:00Z",
            },
            {
                "calendarDate": "2026-10-03",
                "sleepStartTimestampGMT": "2026-10-02T22:00:00Z",
                "sleepEndTimestampGMT": "2026-10-03T06:00:00Z",
            },
        ]
        sleep = [
            {
                "sleepStartTimestampGMT": "2026-09-28T21:00:00Z",
                "sleepEndTimestampGMT": "2026-09-29T04:00:00Z",
            },
            *malformed,
        ]
        item = mapped_personal_recovery(
            [], {"sleep": sleep}, {"timezone": "Europe/Berlin"}, self.today
        )["regularity"]["series"][0]
        observed = next(
            point for point in item["points"] if point["date"] == "2026-09-29"
        )
        self.assertEqual(7, observed["duration_hours"])
        self.assertEqual("2026-09-28T23:00:00+02:00", observed["onset_at"])
        self.assertEqual(1, len(item["points"]))


if __name__ == "__main__":
    unittest.main()
