"""Direct contracts for structured Coach tool failure projection."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from backend.coach.tool_failures import CoachStructuredToolFailureService
from backend.errors import AppError


class StructuredToolFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="coach-tool-failure-")
        self.addCleanup(self.temporary.cleanup)
        self.receipts: list[dict[str, Any]] = []
        self.logger = Mock(spec=logging.Logger)
        self.service = CoachStructuredToolFailureService(
            Path(self.temporary.name), self.logger, frozenset({"read_profile"})
        )

    def project(self, exc: BaseException, *, name: str = "read_profile") -> dict[str, Any]:
        return self.service.project(
            exc,
            name=name,
            call_id="call-1",
            effect_key="effect-1",
            step_key="step-1",
            repair_key="repair-1",
            scope_repair_key="scope-repair-1",
            request_binding_key="request-binding-1",
            plan_effect_key="plan-effect-1",
            action={"request": "safe request", "private": "must not be projected"},
            command_receipts=self.receipts,
        )

    def test_app_error_reason_and_validation_reason_are_preserved(self) -> None:
        error = AppError(400, "Safe user-facing message", reason="request_invalid")
        error.validation_reason = "request_question"

        result = self.project(error)

        self.assertEqual(
            result,
            {
                "ok": False,
                "reason": "request_invalid",
                "error": "Safe user-facing message",
                "validation_reason": "request_question",
            },
        )
        self.assertEqual(self.receipts[0]["result"], result)
        self.assertEqual(self.receipts[0]["call_id"], "call-1")
        self.assertEqual(self.receipts[0]["effect_key"], "effect-1")
        self.assertEqual(self.receipts[0]["step_key"], "step-1")
        self.assertEqual(self.receipts[0]["repair_key"], "repair-1")
        self.assertEqual(self.receipts[0]["scope_repair_key"], "scope-repair-1")
        self.assertEqual(self.receipts[0]["request_binding_key"], "request-binding-1")
        self.assertEqual(self.receipts[0]["plan_effect_key"], "plan-effect-1")
        self.assertEqual(self.receipts[0]["request"], "safe request")
        self.assertNotIn("private", self.receipts[0])
        self.logger.warning.assert_called_once()
        args, kwargs = self.logger.warning.call_args
        self.assertEqual(args, ("Coach step failed",))
        self.assertEqual(kwargs["extra"]["event"], "coach_tool_failed")
        self.assertEqual(kwargs["extra"]["context"]["tool"], "read_profile")

    def test_non_app_error_uses_generic_text_and_does_not_leak_exception(self) -> None:
        result = self.project(RuntimeError("secret exception text"))

        self.assertEqual(result["reason"], "tool_arguments_invalid")
        self.assertIn("ungültig", result["error"])
        self.assertNotIn("secret exception text", str(result))
        self.assertNotIn("secret exception text", str(self.receipts[0]["diagnostic_error"]))

    def test_empty_app_error_reason_uses_400_fallback(self) -> None:
        result = self.project(AppError(400, "Bad request", reason=""))

        self.assertEqual(result["reason"], "tool_arguments_invalid")

    def test_empty_non_400_app_error_reason_uses_tool_failed_fallback(self) -> None:
        result = self.project(AppError(503, "Unavailable", reason=""))

        self.assertEqual(result["reason"], "tool_failed")

    def test_invalid_validation_reason_is_omitted_and_unknown_name_is_redacted(self) -> None:
        error = AppError(400, "Invalid request", reason="invalid")
        error.validation_reason = "request_" + "x" * 73
        result = self.project(error, name="untrusted-tool-name")

        self.assertNotIn("validation_reason", result)
        self.assertEqual(self.logger.warning.call_args.kwargs["extra"]["context"]["tool"], "unknown")
        self.assertEqual(self.receipts[0]["tool"], "untrusted-tool-name")

    def test_receipt_is_appended_before_logger_event(self) -> None:
        self.logger.warning.side_effect = lambda *_args, **_kwargs: self.assertEqual(
            len(self.receipts), 1
        )

        self.project(AppError(409, "Conflict", reason="conflict"))

        self.logger.warning.assert_called_once()
        self.assertEqual(len(self.receipts), 1)


if __name__ == "__main__":
    unittest.main()
