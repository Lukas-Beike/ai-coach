from __future__ import annotations

import unittest
from typing import Any

from backend.providers.garmin import (
    ACTIVITY_DETAIL_MAX_CHART_POINTS,
    collect_garmin_activity_detail,
)

ID = "123456789"
SECRET = "SECRET-TOKEN-5150"


class FakeClient:
    """Records every SDK call; each part returns a stable synthetic payload."""

    def __init__(self, failing: set[str] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.failing = failing or set()

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((name, args, kwargs))
        if name in self.failing:
            raise RuntimeError(f"upstream {SECRET} rejected")
        return {"source": name}

    def get_activity_details(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("get_activity_details", *args, **kwargs)

    def get_activity_splits(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("get_activity_splits", *args, **kwargs)

    def get_activity_hr_in_timezones(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("get_activity_hr_in_timezones", *args, **kwargs)

    def get_activity_power_in_timezones(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("get_activity_power_in_timezones", *args, **kwargs)


def _redact(text: str) -> str:
    return text.replace(SECRET, "[redacted]")


class RecordingExternalCall:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(self, provider: str, capability: str, fetch: Any, details: Any) -> Any:
        self.calls.append((provider, capability, details))
        return fetch()


class GarminActivityDetailCollectTests(unittest.TestCase):
    def _collect(self, client: FakeClient, **kwargs: Any) -> dict[str, Any]:
        external = kwargs.pop("external_call", RecordingExternalCall())
        return collect_garmin_activity_detail(
            client,
            ID,
            external_call=external,
            redact=_redact,
            **kwargs,
        )

    def test_all_parts_are_collected_without_errors(self):
        client = FakeClient()

        payload = self._collect(client)

        self.assertEqual(payload["activity_id"], ID)
        self.assertNotIn("errors", payload)
        self.assertEqual(payload["details"], {"source": "get_activity_details"})
        self.assertEqual(payload["splits"], {"source": "get_activity_splits"})
        self.assertEqual(
            payload["hr_zones"], {"source": "get_activity_hr_in_timezones"}
        )
        self.assertEqual(
            payload["power_zones"], {"source": "get_activity_power_in_timezones"}
        )
        self.assertEqual(
            [name for name, _args, _kwargs in client.calls],
            [
                "get_activity_details",
                "get_activity_splits",
                "get_activity_hr_in_timezones",
                "get_activity_power_in_timezones",
            ],
        )

    def test_details_call_requests_bounded_chart_points(self):
        client = FakeClient()

        self._collect(client)

        name, args, kwargs = client.calls[0]
        self.assertEqual(name, "get_activity_details")
        self.assertEqual(args, (ID,))
        self.assertEqual(kwargs, {"maxchart": ACTIVITY_DETAIL_MAX_CHART_POINTS})
        self.assertEqual(ACTIVITY_DETAIL_MAX_CHART_POINTS, 2000)

    def test_every_part_routes_through_external_call_with_capability_key(self):
        client = FakeClient()
        external = RecordingExternalCall()

        self._collect(client, external_call=external)

        self.assertEqual(
            external.calls,
            [
                ("garmin", "activity_details", {"activity_id": ID}),
                ("garmin", "activity_splits", {"activity_id": ID}),
                ("garmin", "activity_hr_zones", {"activity_id": ID}),
                ("garmin", "activity_power_zones", {"activity_id": ID}),
            ],
        )

    def test_one_failing_part_keeps_others_and_records_redacted_error(self):
        client = FakeClient(failing={"get_activity_splits"})
        warnings: list[tuple[str, str]] = []

        payload = self._collect(
            client,
            warn=lambda source, message, exc: warnings.append((source, message)),
        )

        self.assertNotIn("splits", payload)
        self.assertEqual(payload["details"], {"source": "get_activity_details"})
        self.assertEqual(
            payload["hr_zones"], {"source": "get_activity_hr_in_timezones"}
        )
        self.assertEqual(
            payload["power_zones"], {"source": "get_activity_power_in_timezones"}
        )
        self.assertEqual(
            payload["errors"],
            [
                {
                    "source": "activity_splits",
                    "message": "upstream [redacted] rejected",
                }
            ],
        )
        self.assertEqual(
            warnings, [("activity_splits", "upstream [redacted] rejected")]
        )
        self.assertNotIn(SECRET, repr(payload))

    def test_failure_callbacks_receive_capability_names(self):
        client = FakeClient(failing={"get_activity_details"})
        successes: list[str] = []
        failures: list[tuple[str, type[BaseException]]] = []

        self._collect(
            client,
            capability_success=successes.append,
            capability_failure=lambda capability, exc: failures.append(
                (capability, type(exc))
            ),
        )

        self.assertEqual(
            successes,
            ["activity_splits", "activity_hr_zones", "activity_power_zones"],
        )
        self.assertEqual(failures, [("activity_details", RuntimeError)])

    def test_paused_capability_skips_its_call(self):
        client = FakeClient()
        external = RecordingExternalCall()

        payload = self._collect(
            client,
            external_call=external,
            capability_allowed=lambda capability: capability != "activity_hr_zones",
        )

        self.assertNotIn("hr_zones", payload)
        self.assertNotIn("errors", payload)
        self.assertEqual(payload["skipped"], ["activity_hr_zones"])
        self.assertNotIn("get_activity_hr_in_timezones", [c[0] for c in client.calls])
        self.assertNotIn(
            "activity_hr_zones", [capability for _p, capability, _d in external.calls]
        )
        self.assertEqual(len(client.calls), 3)

    def test_all_parts_paused_returns_only_the_skipped_parts(self):
        client = FakeClient()

        payload = self._collect(client, capability_allowed=lambda _capability: False)

        self.assertEqual(
            payload,
            {
                "activity_id": ID,
                "skipped": [
                    "activity_details",
                    "activity_splits",
                    "activity_hr_zones",
                    "activity_power_zones",
                ],
            },
        )
        self.assertEqual(client.calls, [])

    def test_every_part_failing_keeps_all_errors_in_order(self):
        client = FakeClient(
            failing={
                "get_activity_details",
                "get_activity_splits",
                "get_activity_hr_in_timezones",
                "get_activity_power_in_timezones",
            }
        )

        payload = self._collect(client)

        self.assertEqual(
            [error["source"] for error in payload["errors"]],
            [
                "activity_details",
                "activity_splits",
                "activity_hr_zones",
                "activity_power_zones",
            ],
        )
        for key in ("details", "splits", "hr_zones", "power_zones"):
            self.assertNotIn(key, payload)
        self.assertNotIn(SECRET, repr(payload))


if __name__ == "__main__":
    unittest.main()
