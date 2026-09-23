import unittest
from datetime import date, datetime, timedelta, timezone

from backend.providers.garmin_morning import fetch_morning_body_battery


class FakeClient:
    def __init__(self):
        self.calls = []
        self.login_result = (False, None)
        self.sleep = {"sleep": "payload"}
        self.records = [{"value": 75}]

    def login(self, tokenstore):
        self.calls.append(("login", tokenstore))
        return self.login_result

    def get_sleep_data(self, value):
        self.calls.append(("sleep", value))
        return self.sleep

    def get_body_battery(self, start, end):
        self.calls.append(("body_battery", start, end))
        return self.records


class GarminMorningBodyBatteryTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.external_calls = []

    def external_call(self, provider, operation, callback, details):
        self.external_calls.append((provider, operation, details))
        return callback()

    def fetch(self, sleep_start, **overrides):
        arguments = {
            "tokenstore": "synthetic-tokens",
            "email_configured": True,
            "tokenstore_exists": False,
            "profile_timezone": "Europe/Berlin",
            "fallback_zone": timezone.utc,
            "external_call": self.external_call,
            "sleep_bounds": lambda _payload: (sleep_start, None),
        }
        arguments.update(overrides)
        return fetch_morning_body_battery(self.client, date(2026, 9, 4), **arguments)

    def test_mfa_short_circuits_sleep_and_body_battery(self):
        self.client.login_result = (True, "mfa")

        self.assertEqual(self.fetch(None), ({}, []))
        self.assertEqual(self.client.calls, [("login", "synthetic-tokens")])
        self.assertEqual(
            self.external_calls[0],
            (
                "garmin",
                "login",
                {"email_configured": True, "tokenstore_exists": False},
            ),
        )

    def test_sleep_local_date_bounds_the_body_battery_request(self):
        sleep_start = datetime(2026, 9, 3, 23, 30, tzinfo=timezone.utc)

        sleep, records = self.fetch(sleep_start)

        self.assertIs(sleep, self.client.sleep)
        self.assertEqual(records, self.client.records)
        self.assertEqual(
            self.client.calls,
            [
                ("login", "synthetic-tokens"),
                ("sleep", "2026-09-04"),
                ("body_battery", "2026-09-04", "2026-09-04"),
            ],
        )
        self.assertEqual(
            self.external_calls[-1][2],
            {
                "window_start": "2026-09-04",
                "window_end": "2026-09-04",
                "purpose": "morning_recovery",
            },
        )

    def test_missing_sleep_or_non_list_records_are_bounded(self):
        self.assertEqual(self.fetch(None), (self.client.sleep, []))
        self.assertNotIn("body_battery", [call[0] for call in self.client.calls])

        self.client.calls.clear()
        self.client.records = {"unexpected": True}
        sleep_start = datetime(2026, 9, 4, 1, 0, tzinfo=timezone.utc)
        sleep, records = self.fetch(
            sleep_start,
            profile_timezone="invalid/timezone",
            fallback_zone=timezone(timedelta(hours=-2)),
        )
        self.assertIs(sleep, self.client.sleep)
        self.assertEqual(records, [])
        self.assertEqual(
            self.client.calls[-1],
            ("body_battery", "2026-09-03", "2026-09-04"),
        )


if __name__ == "__main__":
    unittest.main()
