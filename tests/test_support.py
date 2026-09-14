import unittest

from support import IntervalsRequestRecorder, RecordedIntervalsClient, parsed_workout_fixture


class SupportFixtureTests(unittest.TestCase):
    def test_workout_fixture_has_the_provider_shape(self):
        workout = parsed_workout_fixture(600, sport="Run", kind="hr", units="hr_zone", value=1)
        self.assertEqual(workout["type"], "Run")
        self.assertEqual(workout["workout_doc"]["steps"][0]["hr"]["units"], "hr_zone")

    def test_recorded_intervals_client_records_safe_mutation_metadata(self):
        recorder = IntervalsRequestRecorder()
        client = RecordedIntervalsClient(recorder)
        client.create_library_workouts([{"name": "Synthetic"}])
        self.assertEqual(recorder.mutations[0]["method"], "POST")
        self.assertEqual(recorder.mutations[0]["path"], "/athlete/0/workouts")
        self.assertEqual(recorder.mutations[0]["payload_count"], 1)


if __name__ == "__main__":
    unittest.main()
