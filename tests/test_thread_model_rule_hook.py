"""The T3 thread launch hook enforces the configured model/effort rule."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "scripts/hooks/thread_model_rule.py"
RULE = HOOK.with_name("thread-model-rule.json")


def run_hook(payload, rule=None):
    with tempfile.TemporaryDirectory() as temp:
        hook = Path(temp) / HOOK.name
        hook.write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
        if rule is not None:
            hook.with_name(RULE.name).write_text(rule, encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(hook)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )


def launch(model=None, effort=None):
    selection = {}
    if model is not None:
        selection["model"] = model
    if effort is not None:
        selection["options"] = {"effort": effort}
    tool_input = (
        {"title": "t", "modelSelection": selection} if selection else {"title": "t"}
    )
    return {"tool_name": "mcp__t3-code__t3_thread_launch", "tool_input": tool_input}


OPUS_LOW = json.dumps({"allowed": {"opus": "low"}})


class ThreadModelRuleHookTests(unittest.TestCase):
    def test_repository_rule_is_opus_low(self):
        self.assertEqual(
            json.loads(RULE.read_text(encoding="utf-8")), {"allowed": {"opus": "low"}}
        )

    def test_matching_launch_is_allowed(self):
        for payload in (launch("claude-opus-5-5", "low"), launch(), launch("opus")):
            with self.subTest(payload=payload):
                self.assertEqual(run_hook(payload, OPUS_LOW).returncode, 0)

    def test_wrong_model_or_effort_is_rejected_with_the_rule(self):
        for payload in (
            launch("claude-sonnet-5-5", "low"),
            launch("claude-opus-5-5", "medium"),
            launch(effort="max"),
            launch(effort="high"),
        ):
            with self.subTest(payload=payload):
                result = run_hook(payload, OPUS_LOW)
                self.assertEqual(result.returncode, 2)
                self.assertIn("opus up to effort low", result.stderr)

    def test_create_threads_targets_are_checked(self):
        payload = {
            "tool_name": "mcp__t3-code__create_threads",
            "tool_input": {
                "threads": [
                    {"target": {"model": "claude-opus-5-5", "options": []}},
                    {
                        "target": {
                            "model": "claude-opus-5-5",
                            "options": [{"id": "effort", "value": "high"}],
                        }
                    },
                ]
            },
        }
        self.assertEqual(run_hook(payload, OPUS_LOW).returncode, 2)

    def test_missing_or_invalid_rule_fails_closed(self):
        for rule in (None, "{}", '{"allowed": {"opus": "huge"}}', "not json"):
            with self.subTest(rule=rule):
                result = run_hook(launch("claude-opus-5-5", "low"), rule)
                self.assertEqual(result.returncode, 2)
                self.assertIn("missing or invalid", result.stderr)

    def test_editing_the_rule_changes_the_result(self):
        payload = launch("claude-sonnet-5-5", "high")
        self.assertEqual(run_hook(payload, OPUS_LOW).returncode, 2)
        rule = json.dumps({"allowed": {"sonnet": "high"}})
        self.assertEqual(run_hook(payload, rule).returncode, 0)

    def test_effort_without_a_model_must_fit_the_strictest_limit(self):
        rule = json.dumps({"allowed": {"opus": "low", "sonnet": "high"}})
        self.assertEqual(run_hook(launch(effort="high"), rule).returncode, 2)
        self.assertEqual(run_hook(launch(effort="low"), rule).returncode, 0)
        self.assertEqual(
            run_hook(launch("claude-sonnet-5-5", "high"), rule).returncode, 0
        )

    def test_effort_above_high_stays_blocked_whatever_the_rule(self):
        rule = json.dumps({"allowed": {"opus": "max"}})
        result = run_hook(launch("claude-opus-5-5", "xhigh"), rule)
        self.assertEqual(result.returncode, 2)
        self.assertIn("above the high cap", result.stderr)


if __name__ == "__main__":
    unittest.main()
