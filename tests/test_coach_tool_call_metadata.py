"""Direct contracts for the pure structured Coach tool-call projection."""

from __future__ import annotations

import json
import unittest
from typing import ClassVar

from backend.coach.proposals import coach_action_hash
from backend.coach.service import (
    coach_repair_key,
    dialogue_effect_key,
    dialogue_plan_effect_key,
    dialogue_request_binding_key,
    dialogue_scope_repair_key,
)
from backend.coach.tool_call_metadata import structured_tool_call_metadata
from backend.errors import AppError


class StructuredToolCallMetadataTests(unittest.TestCase):
    tools: ClassVar[list[dict[str, str]]] = [{"name": "update_profile"}]

    def item(self, *, call_id: str = "call-1", arguments: str = '{"timezone":"UTC"}') -> dict[str, str]:
        return {"name": "update_profile", "call_id": call_id, "arguments": arguments}

    def assert_app_error(self, expected_status: int, expected_reason: str, call, *args) -> None:
        with self.assertRaises(AppError) as raised:
            call(*args)
        self.assertEqual(raised.exception.status, expected_status)
        self.assertEqual(raised.exception.reason, expected_reason)

    def test_projects_fresh_arguments_and_stable_keys(self) -> None:
        item = self.item(arguments=json.dumps({
            "timezone": "UTC",
            "_request": {"scope": ["profile", "activities"], "period": "next_week"},
        }))
        projected = structured_tool_call_metadata(item, self.tools, [])
        repeated = structured_tool_call_metadata(item, self.tools, [])
        arguments = json.loads(item["arguments"])
        repair_key = coach_repair_key("update_profile", arguments)

        self.assertIsNot(projected["arguments"], arguments)
        self.assertEqual(projected["name"], "update_profile")
        self.assertEqual(projected["call_id"], "call-1")
        self.assertEqual(projected["action"], {"operation": "update_profile", "authorization_scope": []})
        self.assertEqual(projected["effect_key"], dialogue_effect_key("update_profile", arguments))
        self.assertEqual(projected["repair_key"], repair_key)
        self.assertEqual(projected["scope_repair_key"], dialogue_scope_repair_key("update_profile", arguments))
        self.assertEqual(projected["request_binding_key"], dialogue_request_binding_key(arguments))
        self.assertEqual(projected["plan_effect_key"], dialogue_plan_effect_key("update_profile", arguments))
        self.assertEqual(projected["step_key"], coach_action_hash({
            "name": "update_profile",
            "scope": ["activities", "profile"],
            "period": "next_week",
            "repair_key": repair_key,
        }))
        self.assertEqual(
            {key: value for key, value in projected.items() if key != "call_id"},
            {key: value for key, value in repeated.items() if key != "call_id"},
        )

    def test_rejects_empty_and_oversized_call_ids(self) -> None:
        for call_id in ("", "x" * 201):
            with self.subTest(call_id_length=len(call_id)):
                self.assert_app_error(
                    400,
                    "invalid_tool_call",
                    structured_tool_call_metadata,
                    self.item(call_id=call_id),
                    self.tools,
                    [],
                )

    def test_accepts_maximum_call_id_length(self) -> None:
        projected = structured_tool_call_metadata(self.item(call_id="x" * 200), self.tools, [])
        self.assertEqual(len(projected["call_id"]), 200)

    def test_command_limit_allows_only_existing_replay_id(self) -> None:
        receipts = [{"call_id": f"old-{index}"} for index in range(40)]
        self.assert_app_error(
            400,
            "command_limit",
            structured_tool_call_metadata,
            self.item(),
            self.tools,
            receipts,
        )
        replay = self.item(call_id="old-0")
        self.assertEqual(
            structured_tool_call_metadata(replay, self.tools, receipts)["call_id"],
            "old-0",
        )

    def test_rejects_tool_outside_allowlist(self) -> None:
        self.assert_app_error(
            403,
            "tool_scope_denied",
            structured_tool_call_metadata,
            {**self.item(), "name": "delete_account"},
            self.tools,
            [],
        )

    def test_preserves_json_and_object_argument_errors(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            structured_tool_call_metadata(self.item(arguments="{"), self.tools, [])
        with self.assertRaisesRegex(ValueError, "arguments_object"):
            structured_tool_call_metadata(self.item(arguments="[]"), self.tools, [])


if __name__ == "__main__":
    unittest.main()
