"""Synthetic workout export regressions; all provider calls are mocked."""

from datetime import date, datetime, timedelta
import unittest
from copy import deepcopy
from unittest.mock import patch

from test_server import server, parsed_workout_fixture


class WorkoutTextTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(server, "local_now", return_value=datetime.now()))

    def workout(self, description, minutes=61, **extra):
        return {
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Ride", "name": "Synthetic workout",
            "description": description, "duration_minutes": minutes,
            "target": "AUTO", **extra,
        }

    def assert_invalid(self, workout, reason):
        with self.assertRaises(server.AppError) as raised:
            server.validate_workout_description(workout)
        self.assertEqual(raised.exception.reason, reason)

    def test_screenshot_prose_is_rejected_before_any_provider_write(self):
        workout = self.workout(
            "15 min Einrollen bei 50–70 % FTP. 2x15 min bei 88–92 % FTP "
            "(261–273 W), dazwischen 6 min bei 50–60 % FTP. 10 min Ausrollen.", 65,
        )
        self.assert_invalid(workout, "missing_workout_steps")
        client = server.IntervalsClient()
        with patch.object(client, "get_or_create_workout_folder") as folder, \
                patch.object(client, "post") as post, patch.object(client, "put") as put:
            for operation in (
                lambda: client.create_library_workouts([self.workout("- 61m 60%"), workout]),
                lambda: client.update_library_workout("synthetic", workout),
                lambda: client.plan_library_workout("synthetic", workout, workout["date"]),
                lambda: server.workout_event_payload("synthetic", workout),
            ):
                with self.assertRaises(server.AppError):
                    operation()
            folder.assert_not_called()
            post.assert_not_called()
            put.assert_not_called()

    def test_sweetspot_counts_recovery_only_between_efforts(self):
        description = "- 15m 50-70%\n- 15m 88-92%\n- 6m 50-60%\n- 15m 88-92%\n- 10m 50-60%"
        self.assert_invalid(self.workout(description, 65), "workout_duration_mismatch")
        payload = server.workout_event_payload("synthetic", self.workout(description))
        self.assertEqual(payload["moving_time"], 3660)
        self.assertEqual(payload["description"], description)

    def test_reported_inline_repeat_and_competing_watts_are_rejected(self):
        reported = (
            "Warmup\n\n- 15m 50-70% (150-210w) FTP progressiv\n"
            "- 3m 80% (240w) FTP\n- 3m locker bei 50-60% (150-180w) FTP\n\n"
            "Main Set\n\n- 3x 8m 88-92% (264-276w) FTP (262-273W) 85-95rpm\n"
            "- 4m 50-60% (150-180w) FTP zwischen den Intervallen\n\n"
            "Cooldown\n\n- 10m 50-60% (150-180w) FTP\n\n"
            "Wenn die Beine noch schwer sind: nur 2 Intervalle fahren und den Rest locker ausrollen."
        )
        self.assert_invalid(self.workout(reported, 63), "ambiguous_workout_step")
        for text in ("- 15m 50-70% (150-210w) FTP progressiv", "- 8m 88-92% (264-276w) FTP (262-273W) 85-95rpm"):
            with self.subTest(text=text):
                self.assert_invalid(self.workout(text, 15), "ambiguous_workout_target")

    def test_corrected_three_by_eight_has_three_efforts_two_recoveries_and_ramp(self):
        description = (
            "Warmup\n- 15m ramp 50-70%\n- 3m 80%\n- 3m 50-60%\n\n"
            "Main Set\n- 8m 88-92% 85-95rpm\n- 4m 50-60%\n"
            "- 8m 88-92% 85-95rpm\n- 4m 50-60%\n- 8m 88-92% 85-95rpm\n\n"
            "Cooldown\n- 10m 50-60%"
        )
        workout = self.workout(description, 63)
        self.assertEqual(server.workout_event_payload("synthetic", workout)["moving_time"], 3780)
        rows = [(900, 50, 70), (180, 80, 80), (180, 50, 60),
                (480, 88, 92), (240, 50, 60), (480, 88, 92), (240, 50, 60), (480, 88, 92), (600, 50, 60)]
        steps = [{"duration": seconds, "power": {"units": "%ftp", **({"value": low} if low == high else {"start": low, "end": high})}} for seconds, low, high in rows]
        steps[0]["ramp"] = True
        reply = {"type": "Ride", "moving_time": 3780, "icu_training_load": 55, "workout_doc": {"duration": 3780, "steps": steps}}
        server.validate_intervals_workout_result(workout, reply)
        # The reported 43-minute graph has lost two efforts and one recovery.
        broken_steps = [step for index, step in enumerate(steps) if index not in {5, 6, 7}]
        with self.assertRaises(server.AppError):
            server.validate_intervals_workout_result(workout, {**reply, "moving_time": 2580, "workout_doc": {"duration": 2580, "steps": broken_steps}})

    def test_repeats_count_every_rest_and_end_at_blank_line(self):
        workout = self.workout("Warmup\n- 15m 60%\n\nMain set 2x\n- 15m 90%\n- 6m 55%\n\nCooldown\n- 10m 55%", 67)
        self.assertEqual(server.validate_workout_description(workout), 4020)
        self.assert_invalid({**workout, "duration_minutes": 61}, "workout_duration_mismatch")

    def test_missing_or_localized_targets_do_not_silently_lose_load(self):
        for text in ("- 30m locker", "- 30m Zone 2", "- 30m 50–70 % FTP", "- 30m 90rpm"):
            with self.subTest(text=text):
                self.assert_invalid(self.workout(text, 30), "missing_workout_target")
        self.assert_invalid(self.workout("- 30m", 30), "invalid_workout_step")

    def test_time_parser_accepts_only_decimal_digits(self):
        self.assert_invalid(self.workout("- ²m 60%", 2), "invalid_workout_step")

    def test_partially_structured_workout_cannot_hide_missing_time(self):
        self.assert_invalid(self.workout("Lange Ausfahrt fuer 225 Minuten.\n\n- 30m 65%", 225), "workout_duration_mismatch")

    def test_composite_and_second_durations_export_exact_seconds(self):
        workout = self.workout("- 1h2m30s Z2\n- 30s Z1\n- 5' Z1\n- 20\" Z1", 68)
        self.assertEqual(server.workout_event_payload("synthetic", workout)["moving_time"], 4100)

    def test_distance_steps_preserve_provider_time_estimation(self):
        workout = self.workout("- 1km Z1 HR\n- 4km Z2 HR\n- 1km Z1 HR", 40, sport="Run", target="HR")
        self.assertIsNone(server.validate_workout_description(workout))
        self.assertEqual(server.workout_event_payload("synthetic", workout)["moving_time"], 2400)

    def test_mixed_distance_steps_preserve_the_known_timed_subtotal(self):
        for description in ("- 10h Z1 HR\n- 1km Z1 HR", "Main 3x\n- 11m Z1 HR\n- 1km Z1 HR"):
            self.assert_invalid(self.workout(description, 30, sport="Run"), "workout_duration_mismatch")
        workout = self.workout("- 10m Z1 HR\n- 1km Z1 HR", 30, sport="Run")
        self.assertIsNone(server.validate_workout_description(workout))
        self.assertEqual(server.workout_event_payload("synthetic", workout)["moving_time"], 1800)

    def test_supported_power_hr_and_pace_targets(self):
        for target, suffix in (
            ("POWER", "88-92%"), ("POWER", "200-240w"), ("POWER", "ramp 50%-75%"),
            ("HR", "Z1-Z2 HR"), ("HR", "70-80% HR"), ("HR", "90% LTHR"),
            ("HR", "120-140bpm"), ("PACE", "Z2 Pace"), ("PACE", "80% Pace"),
            ("PACE", "5:00-5:30/km Pace"), ("PACE", "2:00/100m-2:30/100m Pace"),
        ):
            with self.subTest(suffix=suffix):
                self.assertEqual(server.validate_workout_description(self.workout(f"- 30m {suffix}", 30, target=target)), 1800)

    def test_incompatible_workout_target_is_rejected(self):
        self.assert_invalid(self.workout("- 30m Z2", 30, target="HR"), "workout_target_mismatch")
        self.assert_invalid(self.workout("- 30m Z2 HR", 30, target="POWER"), "workout_target_mismatch")

    def test_repeat_without_steps_or_separator_is_rejected(self):
        for description in ("2x", "2x\n\n- 30m 60%", "- 10m 60%\n2x\n- 10m 60%", "2x\n3x\n- 30m 60%"):
            with self.subTest(description=description):
                self.assert_invalid(self.workout(description, 30), "invalid_workout_repeat")

    def test_strength_remains_free_text(self):
        self.assertIsNone(server.validate_workout_description(self.workout("Oberkoerperkraft: 3x8 Wiederholungen", 35, sport="WeightTraining")))

    def test_non_endurance_sports_preserve_prose_through_normalization_and_readback(self):
        for sport in server.INTERVALS_WORKOUT_TYPES - server.INTERVALS_ENDURANCE_WORKOUT_TYPES:
            with self.subTest(sport=sport):
                workout = self.workout("Technik und Beweglichkeit nach Bedarf", 30, sport=sport)
                normalized = server.normalize_workout(workout)
                self.assertEqual(normalized["description"], workout["description"])
                payload = server.workout_event_payload("synthetic", normalized)
                self.assertEqual(payload["type"], sport)
                self.assertEqual(payload["moving_time"], 1800)
                server.validate_intervals_workout_result(normalized, {"type": sport, "moving_time": 1800})
                with self.assertRaises(server.AppError):
                    server.validate_intervals_workout_result(normalized, {"type": "Run"})

    def test_all_endurance_families_still_require_executable_steps(self):
        for sport in server.INTERVALS_ENDURANCE_WORKOUT_TYPES:
            with self.subTest(sport=sport):
                self.assert_invalid(self.workout("Locker trainieren", 30, sport=sport), "missing_workout_steps")

    def test_run_cannot_be_confirmed_as_weight_training(self):
        workout = self.workout("- 30m Z1 HR", 30, sport="Run")
        with self.assertRaises(server.AppError) as raised:
            server.validate_intervals_workout_result(workout, parsed_workout_fixture(sport="WeightTraining", kind="hr", units="hr_zone", value=1))
        self.assertEqual(raised.exception.reason, "intervals_workout_sport_mismatch")

    def test_library_exports_preserve_target_and_local_duration(self):
        workout = self.workout("- 30m Z2 HR", 30, target="HR", moving_time=3600)
        client = server.IntervalsClient()
        with patch.object(client, "get_or_create_workout_folder", return_value=1), \
                patch.object(client, "post", return_value={"id": "synthetic"}) as post, \
                patch.object(client, "put", return_value={"id": "synthetic"}) as put:
            client.create_library_workouts([workout])
            self.assertEqual(post.call_args.args[1]["target"], "HR")
            client.update_library_workout("synthetic", workout)
            self.assertEqual(put.call_args.args[1]["target"], "HR")
            post.return_value = [{"id": "synthetic-event", **parsed_workout_fixture(kind="hr", units="hr_zone", value=2)}]
            client.plan_library_workout("synthetic", workout, workout["date"])
            self.assertEqual(post.call_args.args[1][0]["moving_time"], 1800)

    def test_provider_readback_must_confirm_every_step_target_and_calculated_load(self):
        workout = self.workout("- 30m 85%", 30)
        valid = parsed_workout_fixture()
        server.validate_intervals_workout_result(workout, valid)
        invalid = [
            {"id": "synthetic", "type": "Ride"}, {**valid, "workout_doc": {}},
            {**valid, "icu_training_load": None}, {**valid, "icu_training_load": 0},
            {**valid, "moving_time": 2000},
        ]
        for field, value in (("duration", 900), ("power", {"units": "%ftp", "value": 65}),
                             ("power", {"units": "power_zone", "value": 85}),
                             ("power", None), ("ramp", True)):
            reply = deepcopy(valid)
            reply["workout_doc"]["steps"][0][field] = value
            invalid.append(reply)
        for reply in invalid:
            with self.subTest(reply=reply), self.assertRaises(server.AppError) as raised:
                server.validate_intervals_workout_result(workout, reply)
            self.assertEqual(raised.exception.reason, "intervals_workout_verification_failed")

    def test_provider_repeat_reply_is_compared_in_execution_order(self):
        workout = self.workout("2x\n- 15m 88-92%\n- 6m 50-60%", 42)
        steps = [
            {"duration": 900, "power": {"units": "%ftp", "start": 88, "end": 92}},
            {"duration": 360, "power": {"units": "%ftp", "start": 50, "end": 60}},
        ]
        reply = {"type": "Ride", "moving_time": 2520, "icu_training_load": 35,
                 "workout_doc": {"duration": 2520, "steps": [{"reps": 2, "steps": steps}]}}
        server.validate_intervals_workout_result(workout, reply)
        reply["workout_doc"]["steps"][0]["steps"] = list(reversed(steps))
        with self.assertRaises(server.AppError):
            server.validate_intervals_workout_result(workout, reply)


if __name__ == "__main__":
    unittest.main()
