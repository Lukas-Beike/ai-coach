"""Guard the recorded canonical consumer parity ledger."""

from __future__ import annotations

import json
import unittest
from typing import Any

try:
    from .canonical_consumer_parity import (
        FIELD_NAMES,
        compare_ledger,
        compute_ledger,
        ledger_refusals,
        load_ledger,
        render_ledger,
    )
except ImportError:
    from canonical_consumer_parity import (
        FIELD_NAMES,
        compare_ledger,
        compute_ledger,
        ledger_refusals,
        load_ledger,
        render_ledger,
    )


def _row(
    field: str,
    *,
    case: str = "complete",
    point: str = "current",
    legacy: object = 1.0,
    canonical: object = 2.0,
) -> dict[str, Any]:
    return {
        "case": case,
        "field": field,
        "point": point,
        "legacy": legacy,
        "canonical": canonical,
    }


def _ledger(rows: list[dict[str, Any]], *, compared: int = 1) -> dict[str, Any]:
    return {
        "fields": {
            name: {"compared": compared, "rows": 0, "switchable": True}
            for name in FIELD_NAMES
        },
        "rows": rows,
    }


class CanonicalConsumerParityLedgerTests(unittest.TestCase):
    def test_recorded_ledger_matches_computed(self) -> None:
        recorded = load_ledger()
        computed = json.loads(render_ledger(compute_ledger()))
        self.assertEqual(compare_ledger(recorded, computed), [])

    def test_switchable_fields_have_no_rows(self) -> None:
        ledger = compute_ledger()
        for name, summary in ledger["fields"].items():
            with self.subTest(field=name):
                field_rows = [row for row in ledger["rows"] if row["field"] == name]
                self.assertEqual(summary["rows"], len(field_rows))
                self.assertEqual(summary["switchable"], not field_rows)
                self.assertGreater(summary["compared"], 0)
                if summary["switchable"]:
                    self.assertGreater(summary["matched"], 0)

    def test_compare_reports_changed_row(self) -> None:
        recorded = _ledger([_row("weight_kg", canonical=2.0)])
        computed = _ledger([_row("weight_kg", canonical=3.0)])
        messages = compare_ledger(recorded, computed)
        self.assertEqual(len(messages), 1)
        self.assertTrue(messages[0].startswith("changed:"))

    def test_bootstrap_allows_first_recording(self) -> None:
        self.assertEqual(ledger_refusals(None, _ledger([_row("weight_kg")])), [])

    def test_refuses_new_rows(self) -> None:
        baseline = _ledger([_row("weight_kg")])
        current = _ledger([_row("weight_kg"), _row("ctl")])
        self.assertEqual(len(ledger_refusals(baseline, current)), 1)

    def test_refuses_changed_rows(self) -> None:
        baseline = _ledger([_row("weight_kg", canonical=2.0)])
        current = _ledger([_row("weight_kg", canonical=3.0)])
        self.assertEqual(len(ledger_refusals(baseline, current)), 1)

    def test_allows_removed_rows(self) -> None:
        baseline = _ledger([_row("weight_kg"), _row("ctl")])
        current = _ledger([_row("weight_kg")])
        self.assertEqual(ledger_refusals(baseline, current), [])

    def test_refuses_empty_comparison(self) -> None:
        self.assertNotEqual(ledger_refusals(None, _ledger([], compared=0)), [])


if __name__ == "__main__":
    unittest.main()
