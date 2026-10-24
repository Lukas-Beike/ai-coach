"""Keep the method evidence cards in docs/performance-methods/ complete.

The cards are read as text. The check covers structure only: required fields,
tagged numeric rules and known evidence IDs. Content is reviewed by people.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARDS_DIR = ROOT / "docs" / "performance-methods"
CARD_NAMES = (
    "m1-session-rpe-load.md",
    "m2-hrv-resting-hr.md",
    "m3-sleep-duration-timing.md",
    "m4-critical-power-speed.md",
)
FRONT_FIELDS = (
    "Card",
    "Card version",
    "Method ID",
    "Status",
    "Classification",
    "Literature checked",
    "Review",
)
SECTIONS = (
    "Target construct",
    "Formula and units",
    "Sources",
    "Population and reference measurement",
    "Protocol and data window",
    "Measurement error and uncertainty",
    "Bias and transferability",
    "Deviations from the studied procedure",
    "Minimum data and stop rules",
    "Numeric rules",
    "Allowed statements",
    "Forbidden statements",
    "Open points",
)
CLASSIFICATIONS = {
    "descriptive statistic",
    "model estimate",
    "separately validated decision aid",
}
TAGS = {"source", "product assumption"}
FRONT_FIELD = re.compile(r"^- \*\*([^*]+):\*\* (.+)$", re.MULTILINE)
SECTION = re.compile(r"^## (.+)$", re.MULTILINE)
EVIDENCE_ID = re.compile(r"\b(R\d{1,2}|L\d)\b")
REGISTER_ROW = re.compile(r"^\| (R\d{1,2}|L\d) \|", re.MULTILINE)
REVIEW = re.compile(r"blocked|released \d{4}-\d{2}-\d{2} \([^)]+\)")
VERSION = re.compile(r"[1-9]\d*")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def register_ids(readme: str) -> set[str]:
    return set(REGISTER_ROW.findall(readme))


def section_bodies(card: str) -> dict[str, str]:
    matches = list(SECTION.finditer(card))
    return {
        match.group(1).strip(): card[
            match.end() : matches[index + 1].start()
            if index + 1 < len(matches)
            else len(card)
        ]
        for index, match in enumerate(matches)
    }


def numeric_rules(body: str) -> list[list[str]]:
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in body.splitlines()
        if line.strip().startswith("|")
    ]
    if len(rows) < 3 or rows[0][:4] != ["Rule", "Value", "Tag", "Rationale"]:
        return []
    return rows[2:]


def card_problems(card: str, known_ids: set[str]) -> list[str]:
    problems = []
    front = dict(FRONT_FIELD.findall(card.split("\n## ", 1)[0]))
    problems += [f"missing field {name}" for name in FRONT_FIELDS if name not in front]
    if front.get("Classification") not in CLASSIFICATIONS:
        problems.append("invalid classification")
    if not VERSION.fullmatch(front.get("Card version", "")):
        problems.append("invalid card version")
    if not REVIEW.fullmatch(front.get("Review", "")):
        problems.append("invalid review state")
    if not DATE.match(front.get("Literature checked", "")):
        problems.append("invalid literature check date")
    bodies = section_bodies(card)
    problems += [
        f"missing section {name}"
        for name in SECTIONS
        if not bodies.get(name, "").strip()
    ]
    rules = numeric_rules(bodies.get("Numeric rules", ""))
    if not rules:
        problems.append("numeric rules table missing or malformed")
    for row in rules:
        if len(row) < 4 or not row[0] or not row[1]:
            problems.append(f"incomplete numeric rule {row[0]}")
        elif row[2] not in TAGS or not row[3]:
            problems.append(f"untagged numeric rule {row[0]}")
        elif row[2] == "source" and not EVIDENCE_ID.search(row[3]):
            problems.append(f"source rule without evidence ID {row[0]}")
    problems += [
        f"unknown evidence ID {evidence}"
        for evidence in sorted(set(EVIDENCE_ID.findall(card)) - known_ids)
    ]
    return problems


class PerformanceMethodCardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.known_ids = register_ids((CARDS_DIR / "README.md").read_text("utf-8"))

    def test_register_lists_sources_and_lead(self) -> None:
        self.assertEqual(
            self.known_ids, {f"R{number}" for number in range(1, 18)} | {"L1"}
        )

    def test_every_card_is_complete(self) -> None:
        for name in CARD_NAMES:
            with self.subTest(card=name):
                card = (CARDS_DIR / name).read_text("utf-8")
                self.assertEqual(card_problems(card, self.known_ids), [])

    def test_check_rejects_broken_card(self) -> None:
        card = (CARDS_DIR / CARD_NAMES[0]).read_text("utf-8")
        broken = (
            card.replace("- **Review:**", "- **Reviewed:**", 1)
            .replace("| source |", "| guess |", 1)
            .replace("## Open points", "## Notes", 1)
            + "\nSee R99.\n"
        )
        problems = card_problems(broken, self.known_ids)
        self.assertIn("missing field Review", problems)
        self.assertIn("missing section Open points", problems)
        self.assertIn("unknown evidence ID R99", problems)
        self.assertTrue(any(item.startswith("untagged") for item in problems))

    def test_check_validates_front_values_and_rule_cells(self) -> None:
        card = (CARDS_DIR / CARD_NAMES[0]).read_text("utf-8")

        def with_review(review: str) -> str:
            return re.sub(
                r"(?m)^- \*\*Review:\*\* .+$", f"- **Review:** {review}", card
            )

        for review in ("blocked", "released 2026-10-24 (athlete)"):
            with self.subTest(review=review):
                self.assertEqual(card_problems(with_review(review), self.known_ids), [])
        for review in ("blocked junk", "released 2026-10-24 (athlete)x"):
            with self.subTest(review=review):
                self.assertIn(
                    "invalid review state",
                    card_problems(with_review(review), self.known_ids),
                )
        broken = card.replace("- **Card version:** 1", "- **Card version:** x", 1)
        self.assertIn("invalid card version", card_problems(broken, self.known_ids))
        broken = card.replace("| Rating scale range | 0 to 10 |", "|  |  |", 1)
        problems = card_problems(broken, self.known_ids)
        self.assertTrue(any(item.startswith("incomplete") for item in problems))


if __name__ == "__main__":
    unittest.main()
