"""Open-checkbox parsing for scripts/issue_status.py."""

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/issue_status.py"
SPEC = importlib.util.spec_from_file_location("issue_status", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
issue_status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(issue_status)

BODY = """## Required changes
- [x] Add the CI check
- [ ] Add the hook
  * [ ] nested follow-up
- [ ]missing space is not a box
Text with [ ] inside a sentence.
"""


class IssueStatusTests(unittest.TestCase):
    def test_lists_only_open_checkboxes(self):
        self.assertEqual(
            issue_status.open_checkboxes(BODY), ["Add the hook", "nested follow-up"]
        )

    def test_empty_body_has_no_checkboxes(self):
        self.assertEqual(issue_status.open_checkboxes(None), [])

    def test_usage_error_without_number(self):
        self.assertEqual(issue_status.main(["issue_status.py"]), 2)


if __name__ == "__main__":
    unittest.main()
