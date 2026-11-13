"""The Claude adapter, its streaming client and the per-family model resolution.

Every response is a synthetic event sequence in the documented Messages API
shapes (tests/fixtures/claude_messages.json); nothing reaches a real account.
"""

import base64
import io
import json
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

from backend.errors import AppError
from backend.providers.claude_messages_adapter import (
    FALLBACK_BETA,
    claude_family,
    model_turn,
    request_payload,
)
from backend.providers.claude_models import (
    ClaudeModelResolver,
    newest_by_family,
)
from backend.providers.claude_requests import (
    ClaudeMessagesClient,
    ClaudeTransportConfig,
)
from backend.providers.model_seam import ModelRequest, ModelStep

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "claude_messages.json").read_text(
        encoding="utf-8"
    )
)
SYNTHETIC_KEY = "sk-ant-synthetic-key"


def sse_body(events):
    lines = []
    for event in events:
        lines.append(f"event: {event['type']}\n")
        lines.append(f"data: {json.dumps(event)}\n\n")
    return "".join(lines).encode("utf-8")


class FakeResponse(io.BytesIO):
    status = 200
    headers = None


class FakeOpener:
    """Answers each request with the next canned body or raises its error."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)

    def payload(self, index=-1):
        return json.loads(self.requests[index].data.decode("utf-8"))


class FakeProviderState:
    def __init__(self):
        self.usage = []
        self.usage_models = []

        self.status = []

    def record_usage(self, provider, response, operation, model=""):
        self.usage.append((provider, response, operation))
        self.usage_models.append(model)

    def record_success(self, provider):
        self.status.append((provider, "ok", None))

    def record_status(self, provider, *, state, reason, message, **kwargs):
        self.status.append((provider, state, reason))


class FakeLogger:
    def __init__(self):
        self.calls = []

    def info(self, *args, **kwargs):
        self.calls.append(("info", args, kwargs))

    def warning(self, *args, **kwargs):
        self.calls.append(("warning", args, kwargs))


def http_error(status, error_type, message="Synthetic provider text"):
    body = json.dumps(
        {"type": "error", "error": {"type": error_type, "message": message}}
    ).encode("utf-8")
    return HTTPError(
        "https://api.anthropic.com/v1/messages",
        status,
        "error",
        {"retry-after": "7"},
        io.BytesIO(body),
    )


def make_client(*answers, api_key=SYNTHETIC_KEY, max_bytes=1_000_000):
    opener = FakeOpener(*answers)
    state = FakeProviderState()
    logger = FakeLogger()
    client = ClaudeMessagesClient(
        ClaudeTransportConfig(
            api_key=api_key,
            base_url="https://claude.example.test",
            default_base_url="https://api.anthropic.com",
            timeout_seconds=30,
            max_response_bytes=max_bytes,
            app_version="0.0.0",
        ),
        provider_state=state,
        logger=logger,
        opener=opener,
    )
    return client, opener, state, logger


class ClaudeRequestPayloadTests(unittest.TestCase):
    def test_coach_turn_maps_tools_effort_caching_and_fallbacks(self):
        payload = request_payload(
            ModelRequest(
                model="claude-opus-5-5",
                instructions="Stable rules\n\nContext",
                input='{"current_message":"Hallo"}',
                tools=[
                    {
                        "type": "function",
                        "name": "read_plan",
                        "description": "Read the plan.",
                        "parameters": {"type": "object", "properties": {}},
                        "strict": True,
                    }
                ],
                reasoning_effort="medium",
                max_output_tokens=8000,
            ),
            stream=True,
        )
        self.assertEqual(
            payload,
            {
                "model": "claude-opus-5-5",
                "max_tokens": 8000,
                "system": [
                    {
                        "type": "text",
                        "text": "Stable rules\n\nContext",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": '{"current_message":"Hallo"}'}
                        ],
                    }
                ],
                "cache_control": {"type": "ephemeral"},
                "tools": [
                    {
                        "name": "read_plan",
                        "description": "Read the plan.",
                        "input_schema": {"type": "object", "properties": {}},
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
                "output_config": {"effort": "medium"},
                "fallbacks": "default",
                "stream": True,
            },
        )

    def test_family_rules_for_fallbacks_effort_and_minimum_tokens(self):
        cases = (
            ("claude-opus-5-5", True),
            ("claude-sonnet-5-5", True),
            ("claude-haiku-5-5", False),
        )
        for model, fallbacks in cases:
            with self.subTest(model=model):
                payload = request_payload(
                    ModelRequest(
                        model=model, reasoning_effort="minimal", max_output_tokens=1024
                    )
                )
                self.assertEqual("fallbacks" in payload, fallbacks)
                self.assertEqual(payload["output_config"], {"effort": "low"})
                # Thinking counts toward max_tokens; a short answer needs room.
                self.assertEqual(payload["max_tokens"], 4096)
                self.assertNotIn("thinking", payload)
                self.assertNotIn("temperature", payload)
        self.assertEqual(claude_family("claude-sonnet-5"), "sonnet")
        self.assertIsNone(claude_family("gpt-6-luna"))

    def test_tool_rounds_replay_assistant_content_and_send_results(self):
        thinking = {"type": "thinking", "thinking": "", "signature": "sig-1"}
        call = {"type": "tool_use", "id": "toolu_1", "name": "read_plan", "input": {}}
        payload = request_payload(
            ModelRequest(
                model="claude-sonnet-5-5",
                input="Frage",
                steps=[
                    ModelStep(
                        opaque_state=[thinking, call],
                        tool_results=[{"call_id": "toolu_1", "output": '{"ok":true}'}],
                    )
                ],
            )
        )
        self.assertEqual(
            payload["messages"][1:],
            [
                {"role": "assistant", "content": [thinking, call]},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": '{"ok":true}',
                        }
                    ],
                },
            ],
        )

    def test_images_and_attachments_become_image_and_document_blocks(self):
        measurement = base64.b64encode(b'{"distance_m": 1000}').decode()
        payload = request_payload(
            ModelRequest(
                model="claude-opus-5-5",
                input="Was steht darauf?",
                images=[{"mime": "image/jpeg", "data": "aW1n"}],
                attachments=[
                    {
                        "evidence": {"untrusted_attachment_name": "ride"},
                        "kind": "file",
                        "filename": "ride.json",
                        "mime": "application/json",
                        "data": measurement,
                    }
                ],
                json_output=True,
            )
        )
        content = payload["messages"][0]["content"]
        self.assertEqual(
            content[0],
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": "aW1n",
                },
            },
        )
        self.assertEqual(content[1], {"type": "text", "text": "Was steht darauf?"})
        self.assertEqual(content[3]["type"], "document")
        self.assertEqual(content[3]["source"]["data"], '{"distance_m": 1000}')
        # Claude has no JSON object mode: the instruction asks for one.
        self.assertIn("exactly one JSON object", payload["system"][0]["text"])
        self.assertNotIn("output_config", payload)

    def test_schema_answer_uses_output_format_unless_the_web_is_searched(self):
        schema = {"name": "values", "schema": {"type": "object", "properties": {}}}
        plain = request_payload(
            ModelRequest(model="claude-opus-5-5", output_schema=schema)
        )
        self.assertEqual(
            plain["output_config"]["format"],
            {"type": "json_schema", "schema": schema["schema"]},
        )
        for model, tool_type in (
            ("claude-opus-5-5", "web_search_20260209"),
            ("claude-haiku-5-5", "web_search_20250305"),
        ):
            with self.subTest(model=model):
                searched = request_payload(
                    ModelRequest(
                        model=model,
                        instructions="Find values.",
                        output_schema=schema,
                        web_search=True,
                        reasoning_effort="low",
                    )
                )
                # Search citations and a schema-bound answer are exclusive (400).
                self.assertEqual(searched["output_config"], {"effort": "low"})
                self.assertEqual(
                    searched["tools"], [{"type": tool_type, "name": "web_search"}]
                )
                self.assertIn('"properties": {}', searched["system"][0]["text"])
                self.assertNotIn("tool_choice", searched)


class ClaudeModelTurnTests(unittest.TestCase):
    def test_a_message_that_is_not_a_message_is_invalid(self):
        for value in (None, {"type": "error"}, []):
            with self.subTest(value=value), self.assertRaises(AppError) as raised:
                model_turn(value)
            self.assertEqual(raised.exception.reason, "invalid_response")

    def test_stop_reasons_map_to_the_seam(self):
        for wire, neutral in (
            ("end_turn", "completed"),
            ("tool_use", "completed"),
            ("max_tokens", "max_tokens"),
            ("model_context_window_exceeded", "max_tokens"),
            ("pause_turn", "incomplete"),
            ("refusal", "refused"),
        ):
            with self.subTest(wire=wire):
                turn = model_turn(
                    {"type": "message", "content": [], "stop_reason": wire}
                )
                self.assertEqual(turn.stop_reason, neutral)


class ClaudeStreamClientTests(unittest.TestCase):
    def test_tool_round_streams_text_and_returns_calls_and_replayable_state(self):
        client, opener, state, _ = make_client(sse_body(FIXTURES["tool_round"]))
        deltas = []
        turn = client.stream(
            ModelRequest(model="claude-opus-5-5", input="Plan?"), deltas.append
        )
        self.assertEqual(deltas, ["Ich schaue ", "nach."])
        self.assertEqual(
            turn.tool_calls,
            [
                {
                    "call_id": "toolu_synthetic1",
                    "name": "read_plan",
                    "arguments": '{"week": "2026-W46"}',
                }
            ],
        )
        self.assertEqual(
            [block["type"] for block in turn.opaque_state],
            ["thinking", "text", "tool_use"],
        )
        self.assertEqual(turn.opaque_state[0]["signature"], "sig-synthetic-1")
        self.assertEqual(turn.stop_reason, "completed")
        self.assertEqual(
            turn.usage,
            {
                "input_tokens": 4200,
                "output_tokens": 85,
                "total_tokens": 4285,
                "input_tokens_details": {"cached_tokens": 0},
            },
        )
        request = opener.requests[0]
        self.assertEqual(request.full_url, "https://claude.example.test/v1/messages")
        self.assertEqual(request.get_header("X-api-key"), SYNTHETIC_KEY)
        self.assertEqual(request.get_header("Anthropic-version"), "2026-10-21")
        self.assertEqual(request.get_header("Anthropic-beta"), FALLBACK_BETA)
        self.assertTrue(opener.payload()["stream"])
        self.assertEqual(
            state.usage,
            [("anthropic", {"usage": turn.usage}, "messages_stream")],
        )

    def test_web_search_reports_final_json_and_the_pages_read_and_cited(self):
        client, opener, _, _ = make_client(sse_body(FIXTURES["web_search"]))
        turn = client.complete(
            ModelRequest(
                model="claude-sonnet-5-5",
                output_schema={"name": "values", "schema": {"type": "object"}},
                web_search=True,
            )
        )
        self.assertEqual(
            json.loads(turn.final_text), {"products": [{"ref": 1, "values": []}]}
        )
        self.assertEqual(
            turn.sources,
            [
                "https://shop.example.test/riegel",
                "https://hersteller.example.test/riegel",
                "https://hersteller.example.test/riegel",
            ],
        )
        self.assertEqual(opener.requests[0].get_header("Anthropic-beta"), FALLBACK_BETA)

    def test_paused_search_is_resumed_with_its_content(self):
        client, opener, state, _ = make_client(
            sse_body(FIXTURES["paused_search"]), sse_body(FIXTURES["web_search"])
        )
        turn = client.complete(
            ModelRequest(
                model="claude-sonnet-5-5",
                input="Suche",
                web_search=True,
                json_output=True,
            )
        )
        self.assertEqual(turn.stop_reason, "completed")
        resumed = opener.payload(1)["messages"]
        self.assertEqual(resumed[-1]["role"], "assistant")
        self.assertEqual(resumed[-1]["content"][0]["type"], "server_tool_use")
        self.assertEqual(len(state.usage), 2)
        # The turn keeps what came before the pause: replay needs the call.
        self.assertEqual(
            [block["type"] for block in turn.opaque_state][:2],
            ["server_tool_use", "text"],
        )
        self.assertEqual(json.loads(turn.final_text)["products"][0]["ref"], 1)

    def test_a_search_pauses_at_most_three_times_more(self):
        paused = sse_body(FIXTURES["paused_search"])
        client, opener, _, _ = make_client(paused, paused, paused, paused)
        turn = client.complete(
            ModelRequest(model="claude-sonnet-5-5", input="Suche", web_search=True)
        )
        self.assertEqual(len(opener.requests), 4)
        self.assertEqual(turn.stop_reason, "incomplete")

    def test_malformed_events_are_invalid_responses(self):
        for events in (
            [
                {
                    "type": "content_block_delta",
                    "index": 3,
                    "delta": {"type": "text_delta", "text": "x"},
                }
            ],
            [{"type": "content_block_start"}],
            [{"type": "message_delta", "delta": {}}],
        ):
            with self.subTest(events=events):
                client, _, state, _ = make_client(sse_body(events))
                with self.assertRaises(AppError) as raised:
                    client.complete(ModelRequest(model="claude-opus-5-5"))
                self.assertEqual(raised.exception.reason, "invalid_response")
                self.assertEqual(state.usage[0][2], "messages_stream_failed")
        client, _, _, _ = make_client(b"data: \xff\xfe\n\n")
        with self.assertRaises(AppError) as raised:
            client.complete(ModelRequest(model="claude-opus-5-5"))
        self.assertEqual(raised.exception.reason, "invalid_response")

    def test_status_follows_success_and_failure(self):
        client, _, state, _ = make_client(sse_body(FIXTURES["tool_round"]))
        client.complete(ModelRequest(model="claude-opus-5-5"))
        self.assertEqual(state.status, [("anthropic", "ok", None)])
        client, _, state, _ = make_client(http_error(401, "authentication_error"))
        with self.assertRaises(AppError):
            client.complete(ModelRequest(model="claude-opus-5-5"))
        self.assertEqual(
            state.status, [("anthropic", "error", "authentication_or_permission")]
        )
        client, _, state, _ = make_client(TimeoutError())
        with self.assertRaises(AppError):
            client.complete(ModelRequest(model="claude-opus-5-5"))
        self.assertEqual(state.status, [("anthropic", "error", "provider_timeout")])
        client, _, state, _ = make_client(OSError("synthetic network failure"))
        with self.assertRaises(AppError):
            client.complete(ModelRequest(model="claude-opus-5-5"))
        self.assertEqual(state.status, [("anthropic", "error", "provider_unavailable")])

    def test_refusal_after_the_fallback_chain_ends_with_a_safe_error(self):
        client, _, state, logger = make_client(sse_body(FIXTURES["refusal"]))
        with self.assertRaises(AppError) as raised:
            client.stream(ModelRequest(model="claude-opus-5-5"), lambda _text: None)
        self.assertEqual(raised.exception.reason, "refused")
        self.assertEqual(
            raised.exception.message, "Claude hat diese Anfrage abgelehnt."
        )
        self.assertNotIn("Synthetic explanation", raised.exception.message)
        # The refused message was billed and names the model that answered;
        # the turn counts it under the family setting its receipt names (#2638).
        self.assertEqual(state.usage[0][2], "messages_stream")
        self.assertEqual(state.usage_models, ["claude-opus"])
        capture = Mock()
        client, _, _, _ = make_client(sse_body(FIXTURES["refusal"]))
        client.diagnostic_capture = capture
        with self.assertRaises(AppError):
            client.complete(ModelRequest(model="claude-opus-5-5", input="private"))
        kind, details = capture.capture.call_args.args
        self.assertEqual(kind, "anthropic_stream")
        self.assertEqual(details["served_model"], "claude-opus-5")
        self.assertNotIn("private", json.dumps(details))
        self.assertNotIn("Dazu", json.dumps(details))
        self.assertEqual(
            logger.calls[-1][2]["extra"]["context"]["served_model"], "claude-opus-5"
        )

    def test_error_event_and_http_errors_are_classified_without_provider_text(self):
        client, _, state, _ = make_client(sse_body(FIXTURES["overloaded"]))
        with self.assertRaises(AppError) as raised:
            client.complete(ModelRequest(model="claude-haiku-5-5"))
        self.assertEqual(raised.exception.reason, "provider_unavailable")
        self.assertEqual(state.usage[0][2], "messages_stream_failed")
        for status, error_type, reason in (
            (400, "invalid_request_error", "request_failed"),
            (401, "authentication_error", "authentication_or_permission"),
            (404, "not_found_error", "not_found"),
            (429, "rate_limit_error", "rate_limit_exceeded"),
            (529, "overloaded_error", "provider_unavailable"),
            (402, "billing_error", "insufficient_quota"),
        ):
            with self.subTest(status=status):
                client, _, _, logger = make_client(http_error(status, error_type))
                with self.assertRaises(AppError) as raised:
                    client.complete(ModelRequest(model="claude-opus-5-5"))
                error = raised.exception
                self.assertEqual(error.reason, reason)
                self.assertEqual(error.upstream_status, status)
                self.assertNotIn("Synthetic provider text", error.message)
                self.assertNotIn("Synthetic provider text", json.dumps(logger.calls))
        self.assertEqual(raised.exception.retry_after_seconds, 7)

    def test_missing_key_oversized_and_truncated_streams_fail_safely(self):
        client, opener, _, _ = make_client(api_key=" ")
        with self.assertRaises(AppError) as raised:
            client.complete(ModelRequest(model="claude-opus-5-5"))
        self.assertEqual(raised.exception.reason, "anthropic_not_configured")
        self.assertEqual(opener.requests, [])
        client, _, _, _ = make_client(sse_body(FIXTURES["tool_round"]), max_bytes=200)
        with self.assertRaises(AppError) as raised:
            client.complete(ModelRequest(model="claude-opus-5-5"))
        self.assertEqual(raised.exception.reason, "response_too_large")
        client, _, _, _ = make_client(sse_body(FIXTURES["tool_round"][:-1]))
        with self.assertRaises(AppError) as raised:
            client.complete(ModelRequest(model="claude-opus-5-5"))
        self.assertEqual(raised.exception.reason, "invalid_response")

    def test_a_cancel_that_closes_the_response_is_a_cancel(self):
        cancel = threading.Event()

        class ClosedOnRead(FakeResponse):
            def readline(self, size=-1):
                cancel.set()
                return b""

        client, _, state, _ = make_client()
        client.opener = lambda request, timeout: ClosedOnRead(b"")
        with self.assertRaises(AppError) as raised:
            client.stream(
                ModelRequest(model="claude-opus-5-5"), lambda _t: None, cancel
            )
        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.assertEqual(state.usage[0][2], "messages_stream_cancelled")

    def test_cancellation_stops_the_stream_and_bills_what_it_reported(self):
        cancel = threading.Event()
        client, _, state, _ = make_client(sse_body(FIXTURES["tool_round"]))

        def cancel_on_first_text(_text):
            cancel.set()

        with self.assertRaises(AppError) as raised:
            client.stream(
                ModelRequest(model="claude-opus-5-5"), cancel_on_first_text, cancel
            )
        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.assertEqual(state.usage[0][0], "anthropic")
        self.assertEqual(state.usage[0][2], "messages_stream_cancelled")
        self.assertFalse(hasattr(cancel, "_provider_response"))

    def test_models_listing_sends_the_key_and_reads_one_page(self):
        client, opener, _, _ = make_client(json.dumps(FIXTURES["models_page"]).encode())
        page = client.list_models()
        self.assertEqual(page["data"][0]["id"], "claude-opus-5-5")
        self.assertEqual(
            opener.requests[0].full_url,
            "https://claude.example.test/v1/models?limit=100",
        )
        self.assertEqual(opener.requests[0].get_header("X-api-key"), SYNTHETIC_KEY)


class ClaudeModelResolverTests(unittest.TestCase):
    NOW = datetime(2026, 12, 2, 8, 0, tzinfo=UTC)

    def make(self, state=None, listing=None):
        store = {"state": state or {}}
        calls = []

        def list_models():
            calls.append(1)
            if isinstance(listing, Exception):
                raise listing
            return listing if listing is not None else FIXTURES["models_page"]

        resolver = ClaudeModelResolver(
            read_state=lambda: store["state"],
            write_state=lambda value: store.__setitem__("state", value),
            list_models=list_models,
            now=lambda: self.NOW,
            logger=FakeLogger(),
        )
        return resolver, store, calls

    def test_newest_model_per_family_skips_snapshots_and_other_families(self):
        self.assertEqual(
            newest_by_family(FIXTURES["models_page"]),
            {
                "opus": "claude-opus-5-6",
                "sonnet": "claude-sonnet-5-5",
                "haiku": "claude-haiku-5-5",
            },
        )
        self.assertEqual(newest_by_family({"data": "x"}), {})
        # An old-style dated snapshot is no family model.
        self.assertEqual(
            newest_by_family(
                {"data": [{"id": "claude-sonnet-4-20250514", "created_at": "2030"}]}
            ),
            {},
        )

    def test_resolution_lists_models_once_a_day_and_keeps_them_on_failure(self):
        resolver, store, calls = self.make()
        self.assertEqual(resolver.resolve("opus"), "claude-opus-5-6")
        self.assertEqual(resolver.resolve("opus"), "claude-opus-5-6")
        self.assertEqual(len(calls), 1)
        store["state"]["fetched_at"] = (self.NOW - timedelta(days=2)).isoformat()
        resolver._list_models = lambda: (_ for _ in ()).throw(
            AppError(503, "x", reason="provider_unavailable")
        )
        self.assertEqual(resolver.resolve("opus"), "claude-opus-5-6")
        failing, _, failed_calls = self.make(listing=AppError(503, "x", reason="x"))
        self.assertEqual(failing.resolve("sonnet"), "claude-sonnet-5-5")
        # A failed listing is retried an hour later, not on every request.
        self.assertEqual(failing.resolve("sonnet"), "claude-sonnet-5-5")
        self.assertEqual(len(failed_calls), 1)
        failing._now = lambda: self.NOW + timedelta(hours=1, minutes=1)
        failing.resolve("sonnet")
        self.assertEqual(len(failed_calls), 2)

    def test_a_rejected_new_model_steps_back_to_the_last_working_one(self):
        resolver, store, _ = self.make(state={"working": {"opus": "claude-opus-5-5"}})
        sent = []

        def send(model):
            sent.append(model)
            if model == "claude-opus-5-6":
                raise AppError(400, "x", reason="request_failed", upstream_status=400)
            return "answer"

        self.assertEqual(resolver.call("opus", send), "answer")
        self.assertEqual(sent, ["claude-opus-5-6", "claude-opus-5-5"])
        self.assertEqual(
            resolver.status()["opus"],
            {"model": "claude-opus-5-5", "rejected": "claude-opus-5-6"},
        )
        # Later requests go straight to the working model.
        sent.clear()
        self.assertEqual(resolver.call("opus", send), "answer")
        self.assertEqual(sent, ["claude-opus-5-5"])
        self.assertEqual(store["state"]["rejected"], {"opus": "claude-opus-5-6"})

    def test_no_step_back_without_a_different_working_model_or_on_other_errors(self):
        for state, error in (
            ({}, AppError(400, "x", upstream_status=400)),
            (
                {"working": {"opus": "claude-opus-5-6"}},
                AppError(400, "x", upstream_status=400),
            ),
            (
                {"working": {"opus": "claude-opus-5-5"}},
                AppError(429, "x", upstream_status=429),
            ),
        ):
            with self.subTest(state=state, status=error.upstream_status):
                resolver, store, _ = self.make(state=dict(state))
                sent = []

                def send(model, error=error, sent=sent):
                    sent.append(model)
                    raise error

                with self.assertRaises(AppError):
                    resolver.call("opus", send)
                self.assertEqual(sent, ["claude-opus-5-6"])
                self.assertNotIn("opus", store["state"].get("rejected", {}))

    def test_a_failing_fallback_does_not_blame_the_new_model(self):
        resolver, store, _ = self.make(state={"working": {"opus": "claude-opus-5-5"}})

        def send(model):
            raise AppError(400, "x", upstream_status=400)

        with self.assertRaises(AppError):
            resolver.call("opus", send)
        self.assertNotIn("opus", store["state"].get("rejected", {}))
        self.assertEqual(resolver.status()["opus"]["rejected"], None)

    def test_success_records_the_working_model_and_status_needs_no_listing(self):
        resolver, store, calls = self.make()
        self.assertEqual(
            resolver.call("haiku", lambda model: model), "claude-haiku-5-5"
        )
        self.assertEqual(store["state"]["working"], {"haiku": "claude-haiku-5-5"})
        calls.clear()
        fresh, _, fresh_calls = self.make()
        self.assertEqual(
            fresh.status()["opus"], {"model": "claude-opus-5-5", "rejected": None}
        )
        self.assertEqual(fresh_calls, [])


if __name__ == "__main__":
    unittest.main()
