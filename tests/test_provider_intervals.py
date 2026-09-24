import base64
import json
import unittest
from unittest.mock import Mock

from backend.errors import AppError
from backend.providers.intervals import IntervalsApiClient


class IntervalsApiClientTests(unittest.TestCase):
    def test_auth_base_url_and_get_query(self):
        request = Mock(return_value={"ok": True})
        params = {"include": ["a", "b"]}
        client = IntervalsApiClient(
            api_key="synthetic-key",
            request=request,
            base_url="https://intervals.test/api/v1/",
        )

        self.assertEqual(client.get("/athlete/1", params), {"ok": True})
        self.assertEqual(params, {"include": ["a", "b"]})
        request.assert_called_once_with(
            "GET",
            "https://intervals.test/api/v1/athlete/1?include=a&include=b",
            headers={
                "Authorization": "Basic " + base64.b64encode(b"API_KEY:synthetic-key").decode()
            },
            service="intervals",
        )

    def test_cancel_event_is_only_forwarded_when_set(self):
        request = Mock(side_effect=[{"ok": True}, {"ok": True}])
        client = IntervalsApiClient(api_key="key", request=request)
        cancel_event = object()

        client.get("/one")
        client.get("/two", cancel_event=cancel_event)

        self.assertNotIn("cancel_event", request.call_args_list[0].kwargs)
        self.assertIs(request.call_args_list[1].kwargs["cancel_event"], cancel_event)

    def test_all_write_verbs_preserve_payload_params_and_service(self):
        request = Mock(side_effect=["post", "put", "delete"])
        client = IntervalsApiClient(api_key="key", request=request)

        self.assertEqual(client.post("/events", {"id": 1}, {"tag": ["a", "b"]}), "post")
        self.assertEqual(client.put("/events/1", {"id": 1}, {"force": True}), "put")
        self.assertEqual(client.delete("/events/1", {"force": True}), "delete")

        self.assertEqual(request.call_args_list[0].args[:3], ("POST", "https://intervals.icu/api/v1/events?tag=a&tag=b", {"id": 1}))
        self.assertEqual(request.call_args_list[1].args[:3], ("PUT", "https://intervals.icu/api/v1/events/1?force=True", {"id": 1}))
        self.assertEqual(request.call_args_list[2].args[:2], ("DELETE", "https://intervals.icu/api/v1/events/1?force=True"))
        self.assertTrue(all(call.kwargs["service"] == "intervals" for call in request.call_args_list))

    def test_pagination_accumulates_and_state_is_independent(self):
        first = Mock(side_effect=[[{"id": 1}, {"id": 2}], [{"id": 3}], [{"id": 4}]])
        second = Mock(side_effect=[[{"id": 3}]])
        first_client = IntervalsApiClient(api_key="key", request=first)
        second_client = IntervalsApiClient(api_key="key", request=second)

        first_client.get_paged_collection("/items", {"sport": "Run"}, "items", page_size=2)
        first_client.get_paged_collection("/items", {"sport": "Run"}, "items", page_size=2)
        second_client.get_paged_collection("/items", {}, "items")

        self.assertEqual(dict(first_client.pagination["items"]), {"pages": 3, "records": 4, "complete": True})
        self.assertEqual(dict(second_client.pagination["items"]), {"pages": 1, "records": 1, "complete": True})
        pagination_copy = first_client.pagination
        self.assertEqual(json.loads(json.dumps(pagination_copy)), {
            "items": {"pages": 3, "records": 4, "complete": True},
        })
        pagination_copy["items"]["pages"] = 0
        self.assertEqual(first_client.pagination["items"]["pages"], 3)

    def test_pagination_errors_are_app_errors(self):
        for response, message in (
            ({"not": "a list"}, "Invalid items page"),
            ([{"id": 1}, "bad"], "Invalid items records"),
            ([{"id": 1}], "Repeated items page"),
        ):
            request = Mock(side_effect=[response, response])
            client = IntervalsApiClient(api_key="key", request=request)
            with self.subTest(message=message), self.assertRaisesRegex(AppError, message) as raised:
                client.get_paged_collection("/items", {}, "items", page_size=1)
            self.assertEqual(raised.exception.status, 502)

    def test_pagination_page_limit_is_bounded(self):
        request = Mock(side_effect=[[{"id": index}] for index in range(100)])
        client = IntervalsApiClient(api_key="key", request=request)
        with self.assertRaisesRegex(AppError, "Page limit exceeded for items"):
            client.get_paged_collection("/items", {}, "items", page_size=1)
        self.assertEqual(request.call_count, 100)


if __name__ == "__main__":
    unittest.main()
