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
### Acceptance criteria
- [ ] closing summary covers this
#### Edge cases
- [ ] still a criterion
```bash
# Acceptance criteria inside a fence is no heading
```
## Parts
- [ ] Part two
```bash
# acceptance criteria smoke test
```
- [ ] Part three
"""


class IssueStatusTests(unittest.TestCase):
    def test_lists_only_open_checkboxes(self):
        self.assertEqual(
            issue_status.open_checkboxes(BODY),
            ["Add the hook", "nested follow-up", "Part two", "Part three"],
        )
        criteria = issue_status.open_boxes(BODY)[1]
        self.assertEqual(
            [m[1] for m in criteria],
            ["closing summary covers this", "still a criterion"],
        )
        # #2799: a plain "Acceptance" heading starts the criteria too
        parts, criteria = issue_status.open_boxes(
            "## Acceptance\n- [ ] a\n## B\n- [ ] b"
        )
        self.assertEqual(
            ([m[1] for m in parts], [m[1] for m in criteria]), (["b"], ["a"])
        )

    def test_only_closing_or_part_of_references_link_a_pr(self):
        bodies = {  # #2798: a mention in prose or a longer number does not link
            1: "Closes #12",
            2: "Part of #12",
            3: "fixed: #12.",
            4: "RESOLVES #12 and more",
            5: "Builds on #12 (merge hold).",
            6: "Closes #123",
            7: "Part of #1",
            8: None,
            9: "_Part of #12_",
            10: "Suffixes #12",
        }
        pulls = [{"number": n, "body": body} for n, body in bodies.items()]
        calls = []
        linked = issue_status.linked_pulls(12, lambda *a: calls.append(a) or pulls)
        self.assertEqual([pull["number"] for pull in linked], [1, 2, 3, 4, 9])
        # the default 30 results could hide an older linked PR
        self.assertIn("1000", calls[0])

    def test_empty_body_has_no_checkboxes(self):
        self.assertEqual(issue_status.open_checkboxes(None), [])

    def test_usage_error_without_number(self):
        self.assertEqual(issue_status.main(["issue_status.py"]), 2)


if __name__ == "__main__":
    unittest.main()
