import json
import unittest
from copy import deepcopy

from backend.errors import AppError
from backend.planning import competitions


class PlanningCompetitionTests(unittest.TestCase):
    def test_normalize_preserves_existing_contract(self) -> None:
        result = competitions.normalize_competition(
            {
                "id": "9dca66eb-f8a1-45c9-8481-fb584a08297c",
                "name": "  Autumn Race  ",
                "event_date": "2026-10-04",
                "start_date_local": "2026-10-03T09:12:37+02:00",
                "sport": "Running",
                "priority": "a",
                "distance": "42.195 km",
                "target": {"pace": "4:30/km"},
                "notes": "Course notes",
                "moving_time": "10800",
            }
        )

        self.assertEqual(result["name"], "Autumn Race")
        self.assertEqual(result["event_date"], "2026-10-04")
        self.assertEqual(result["start_date_local"], "2026-10-04T09:12:00")
        self.assertEqual(result["category"], "RACE_A")
        self.assertEqual(result["priority"], "A")
        self.assertEqual(result["distance"], "42195")
        self.assertEqual(json.loads(result["target"]), {"pace": "4:30/km"})
        self.assertEqual(result["description"], "Course notes")
        self.assertEqual(result["moving_time"], 10800)

    def test_validation_rejects_missing_identity_and_invalid_bounds(self) -> None:
        cases = (
            ({}, "Jeder Wettkampf benötigt einen Namen."),
            (
                {"name": "Race", "event_date": "invalid"},
                "Der Startzeitpunkt des Wettkampfs muss ein gültiges Datum sein.",
            ),
            (
                {"name": "Race", "event_date": "2026-10-04", "priority": "Z"},
                "Die Kategorie für „Race“ muss RACE_A, RACE_B oder RACE_C sein.",
            ),
            (
                {
                    "name": "Race",
                    "event_date": "2026-10-04",
                    "moving_time": 604801,
                },
                "Die Wettkampfdauer muss zwischen 0 und 604800 Sekunden liegen.",
            ),
        )
        for payload, message in cases:
            with self.subTest(message=message), self.assertRaises(AppError) as error:
                competitions.normalize_competition(payload)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(error.exception.message, message)

    def test_sport_aliases_and_intervals_fallbacks(self) -> None:
        expected = {
            "cycling": "Ride",
            "rad": "Ride",
            "rad outdoor": "Ride",
            "radfahren": "Ride",
            "ride": "Ride",
            "virtualride": "VirtualRide",
            "virtual ride": "VirtualRide",
            "rad indoor": "VirtualRide",
            "indoor cycling": "VirtualRide",
            "virtual cycling": "VirtualRide",
            "running": "Run",
            "lauf": "Run",
            "laufen": "Run",
            "run": "Run",
            "strength": "WeightTraining",
            "kraft": "WeightTraining",
            "krafttraining": "WeightTraining",
            "weighttraining": "WeightTraining",
        }
        self.assertEqual(competitions.COMPETITION_SPORTS, expected)
        for alias, intervals_type in expected.items():
            with self.subTest(alias=alias):
                self.assertEqual(
                    competitions.supported_competition_sport(alias), intervals_type
                )
        self.assertEqual(
            competitions.supported_competition_sport(" VIRTUAL_RIDE "), "VirtualRide"
        )
        self.assertIsNone(competitions.supported_competition_sport("swimming"))
        self.assertIsNone(competitions.supported_competition_sport(None))
        self.assertEqual(competitions.intervals_competition_sport(None), "Ride")
        self.assertEqual(competitions.intervals_competition_sport(""), "Ride")
        self.assertEqual(
            competitions.intervals_competition_sport("  hiking  "), "hiking"
        )
        self.assertEqual(competitions.intervals_competition_sport("x" * 90), "x" * 80)

    def test_external_id_and_optional_payload_preserve_types_and_input(self) -> None:
        source = {
            "moving_time": "3600",
            "distance": "42.5",
            "target": {"pace": "4:30/km"},
            "intervals_event_id": "00123",
        }
        original = deepcopy(source)

        self.assertEqual(
            competitions.COMPETITION_EXTERNAL_PREFIX,
            "intervals-coach-competition-",
        )
        self.assertEqual(
            competitions.competition_external_id("abc"),
            "intervals-coach-competition-abc",
        )
        self.assertEqual(
            competitions.competition_event_optional_payload(source),
            {
                "moving_time": 3600,
                "distance": 42.5,
                "target": '{"pace":"4:30/km"}',
                "id": 123,
            },
        )
        self.assertEqual(source, original)
        self.assertEqual(
            competitions.competition_event_optional_payload(
                {"distance": "trail", "intervals_event_id": "remote-7"}
            ),
            {"id": "remote-7"},
        )
        self.assertEqual(
            competitions.competition_event_optional_payload(
                {"intervals_event_id": "-7"}
            ),
            {"id": "-7"},
        )
        self.assertEqual(competitions.competition_event_optional_payload({}), {})
        with self.assertRaises(ValueError):
            competitions.competition_event_optional_payload({"moving_time": "bad"})

    def test_event_payload_fallbacks_limits_and_input_immutability(self) -> None:
        source = {
            "id": "race-id",
            "event_date": "2026-10-04",
            "category": "race_c",
            "priority": "A",
            "sport": "Running",
            "name": "N" * 210,
            "description": "D" * 12010,
            "moving_time": 0,
            "distance": "10,5",
            "target": ["finish"],
        }
        original = deepcopy(source)
        payload = competitions.competition_event_payload(source)

        self.assertEqual(payload["category"], "RACE_C")
        self.assertEqual(payload["start_date_local"], "2026-10-04T00:00:00")
        self.assertEqual(payload["type"], "Run")
        self.assertEqual(payload["name"], "N" * 200)
        self.assertEqual(payload["description"], "D" * 12000)
        self.assertEqual(payload["external_id"], "intervals-coach-competition-race-id")
        self.assertEqual(payload["distance"], 10.5)
        self.assertEqual(payload["target"], '["finish"]')
        self.assertEqual(payload["moving_time"], 0)
        self.assertEqual(source, original)
        fallback = competitions.competition_event_payload(
            {
                "id": "x",
                "event_date": "2026-10-04",
                "category": "unknown",
                "priority": "a",
            }
        )
        self.assertEqual(fallback["category"], "RACE_B")
        self.assertEqual(fallback["type"], "Ride")
        self.assertEqual(fallback["name"], "Zielwettkampf")
        self.assertEqual(fallback["description"], "")
        self.assertEqual(fallback["external_id"], "intervals-coach-competition-x")
        with self.assertRaises(KeyError):
            competitions.competition_event_payload({"id": "x"})

    def test_remote_date_uses_first_present_field_and_rejects_invalid_values(
        self,
    ) -> None:
        self.assertEqual(
            competitions.remote_competition_date(
                {
                    "start_date_local": "2026-10-04T09:00:00+02:00",
                    "date": "2026-10-05",
                }
            ),
            "2026-10-04",
        )
        self.assertEqual(
            competitions.remote_competition_date(
                {"start_date_local": "", "date": "2026-10-05T00:00:00Z"}
            ),
            "2026-10-05",
        )
        self.assertIsNone(
            competitions.remote_competition_date(
                {"start_date_local": "invalid", "date": "2026-10-05"}
            )
        )
        self.assertIsNone(competitions.remote_competition_date({"date": "2026-02-30"}))
        self.assertIsNone(competitions.remote_competition_date({}))
        self.assertIsNone(competitions.remote_competition_date(None))

    def test_remote_moving_time_and_distance_normalization(self) -> None:
        self.assertIsNone(competitions.remote_competition_moving_time(None))
        self.assertIsNone(competitions.remote_competition_moving_time(""))
        self.assertEqual(competitions.remote_competition_moving_time("1.9"), 1)
        self.assertEqual(competitions.remote_competition_moving_time(0), 0)
        self.assertEqual(
            competitions.remote_competition_moving_time(7 * 24 * 60 * 60),
            7 * 24 * 60 * 60,
        )
        self.assertIsNone(competitions.remote_competition_moving_time("invalid"))
        self.assertIsNone(competitions.remote_competition_moving_time(-1))
        self.assertIsNone(competitions.remote_competition_moving_time(604801))
        self.assertEqual(competitions.remote_competition_distance(42195), "42195")
        self.assertEqual(competitions.remote_competition_distance(42.5), "42.5")
        self.assertEqual(competitions.remote_competition_distance("42.5 km"), "42500")
        self.assertEqual(competitions.remote_competition_distance("trail"), "trail")
        self.assertEqual(competitions.remote_competition_distance(None), "")

    def test_remote_data_validation_fallbacks_limits_and_input_immutability(
        self,
    ) -> None:
        source = {
            "id": 123,
            "name": "  R" + "x" * 205 + "  ",
            "start_date_local": "2026-10-04T08:45:00+02:00",
            "type": "Virtual_Ride",
            "category": "unusual_C",
            "distance": "trail",
            "moving_time": "bad",
            "target": {"p": "z" * 1100},
            "description": "D" * 12050,
        }
        original = deepcopy(source)
        result = competitions.remote_competition_data(source)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["intervals_event_id"], "123")
        self.assertEqual(result["name"], ("R" + "x" * 199))
        self.assertEqual(result["event_date"], "2026-10-04")
        self.assertEqual(result["start_date_local"], "2026-10-04T08:45:00")
        self.assertEqual(result["sport"], "VirtualRide")
        self.assertEqual(result["priority"], "C")
        self.assertEqual(result["category"], "RACE_C")
        self.assertEqual(result["distance"], "trail")
        self.assertEqual(result["moving_time"], None)
        self.assertEqual(len(result["target"]), 1000)
        self.assertEqual(len(result["description"]), 12000)
        self.assertEqual(len(result["notes"]), 2000)
        self.assertEqual(source, original)
        self.assertIsNone(competitions.remote_competition_data({"name": "Race"}))
        self.assertIsNone(
            competitions.remote_competition_data(
                {"date": "2026-10-04", "name": "Race", "type": "Swimming"}
            )
        )
        fallback = competitions.remote_competition_data(
            {"date": "2026-10-04", "name": " Race ", "intervals_event_id": " 7 "}
        )
        self.assertIsNotNone(fallback)
        assert fallback is not None
        self.assertEqual(fallback["start_date_local"], "2026-10-04T00:00:00")
        self.assertEqual(fallback["sport"], "Ride")
        self.assertEqual(fallback["category"], "RACE_B")
        self.assertEqual(fallback["intervals_event_id"], "7")

    def test_conflict_payload_has_explicit_timestamp_and_preserves_input(self) -> None:
        remote = {
            "date": "2026-10-04",
            "name": "Sommerlauf",
            "sport": "Running",
            "external_id": " ext " + "x" * 210,
        }
        original = deepcopy(remote)
        with self.assertRaises(TypeError):
            competitions.competition_conflict_payload(remote, "changed")
        with self.assertRaises(TypeError):
            competitions.competition_conflict_payload(
                remote, "changed", "2026-10-04T12:00:00Z"
            )
        payload = json.loads(
            competitions.competition_conflict_payload(
                remote, "remote_changed", detected_at="2026-10-04T12:00:00Z"
            )
        )
        self.assertEqual(payload["type"], "remote_changed")
        self.assertEqual(payload["detected_at"], "2026-10-04T12:00:00Z")
        self.assertEqual(payload["remote"]["name"], "Sommerlauf")
        self.assertEqual(payload["remote"]["external_id"], ("ext " + "x" * 196))
        self.assertEqual(remote, original)

    def test_remote_event_filtering_uses_supported_sport_and_linked_ids(self) -> None:
        linked_ids = {"linked-1"}
        self.assertTrue(
            competitions.is_remote_competition_event(
                {"type": "Ride", "category": "RACE_SPECIAL"}, linked_ids
            )
        )
        self.assertTrue(
            competitions.is_remote_competition_event(
                {
                    "type": "Running",
                    "external_id": competitions.competition_external_id("x"),
                },
                linked_ids,
            )
        )
        self.assertTrue(
            competitions.is_remote_competition_event(
                {"type": "Run", "id": "linked-1"}, linked_ids
            )
        )
        self.assertFalse(competitions.is_remote_competition_event({}, linked_ids))
        self.assertFalse(
            competitions.is_remote_competition_event(
                {"type": "Swimming", "category": "RACE_A", "id": "linked-1"},
                linked_ids,
            )
        )
        self.assertFalse(
            competitions.is_remote_competition_event({"type": "Ride"}, linked_ids)
        )

    def test_sync_key_is_conservative_and_does_not_mutate(self) -> None:
        source = {"name": "  Fall   Race ", "event_date": "2026-10-04", "sport": "rad"}
        original = deepcopy(source)
        self.assertEqual(
            competitions.competition_sync_key(source),
            ("fall race", "2026-10-04", "Ride"),
        )
        self.assertEqual(source, original)
        self.assertEqual(
            competitions.competition_sync_key(
                {"name": "Race", "date": "2026-10-05", "type": "Running"}
            ),
            ("race", "2026-10-05", "Run"),
        )
        self.assertIsNone(
            competitions.competition_sync_key({"event_date": "2026-10-04"})
        )
        self.assertIsNone(
            competitions.competition_sync_key(
                {"name": "Race", "event_date": "2026-10-04", "sport": "Swimming"}
            )
        )


if __name__ == "__main__":
    unittest.main()
