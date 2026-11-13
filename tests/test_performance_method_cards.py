"""Keep the method evidence cards in docs/performance-methods/ complete.

The cards are read as text. The check covers structure only: required fields,
tagged numeric rules and known evidence IDs. Content is reviewed by people.

Each card ends with a generated "Code constants" section listing the constants
of the modules its Status line names, read from the code; regenerate it with
`python tests/test_performance_method_cards.py --write`. A card's Method ID
version must equal the METHOD_VERSION of its implementing module.
"""

import ast
import hashlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARDS_DIR = ROOT / "docs" / "performance-methods"
CARD_NAMES = (
    "m1-session-rpe-load.md",
    "m2-hrv-resting-hr.md",
    "m3-sleep-duration-timing.md",
    "m4-critical-power-speed.md",
    "m5-smoothed-session-load.md",
    "m6-local-tss-load.md",
    "m7-local-fitness-fatigue.md",
    "m8-local-session-metrics.md",
    "m9-lt1-output-own-sessions.md",
    "m10-dfa-alpha1-first-threshold.md",
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
BEGIN = "<!-- BEGIN GENERATED CONSTANTS -->"
END = "<!-- END GENERATED CONSTANTS -->"
MODULE_PATH = re.compile(r"`(backend/[\w/]+\.py)(?::\w+)?`")
CONSTANT_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
METHOD_ID_VERSION = re.compile(r"[\s-]v([1-9]\d*)\b")
VALUE_LIMIT = 100


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


def front_line(card: str, field: str) -> str:
    return dict(FRONT_FIELD.findall(card.split("\n## ", 1)[0])).get(field, "")


def card_modules(card: str) -> list[str]:
    lines = front_line(card, "Status") + " " + front_line(card, "Method ID")
    return list(dict.fromkeys(MODULE_PATH.findall(lines)))


def is_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp):
        return is_literal(node.operand)
    if isinstance(node, ast.BinOp):
        return is_literal(node.left) and is_literal(node.right)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(is_literal(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is not None and is_literal(key) and is_literal(value)
            for key, value in zip(node.keys, node.values, strict=True)
        )
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and not node.keywords
    ):
        return False
    if node.func.id == "range":
        return 1 <= len(node.args) <= 3 and all(is_literal(arg) for arg in node.args)
    return (
        node.func.id in {"frozenset", "tuple"}
        and len(node.args) == 1
        and is_literal(node.args[0])
    )


def module_constants(module: str) -> list[tuple[str, ast.expr, str]]:
    """Return (name, value, comment) of the literal UPPER_CASE constants."""
    source = (ROOT / module).read_text("utf-8")
    lines = source.splitlines()
    found = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if not (
            isinstance(target, ast.Name)
            and CONSTANT_NAME.fullmatch(target.id)
            and is_literal(value)
        ):
            continue
        comment: list[str] = []
        index = node.lineno - 2
        while index >= 0 and lines[index].lstrip().startswith("#"):
            comment.insert(0, lines[index].lstrip().lstrip("#").strip())
            index -= 1
        found.append((target.id, value, " ".join(comment)))
    return found


def table_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("`", "")


def constant_rows(modules: list[str]) -> list[str]:
    rows = []
    for module in modules:
        for name, value, comment in module_constants(module):
            text = ast.unparse(value)
            if len(text) > VALUE_LIMIT:
                # A short digest of the whole value, so a change past the cut fails too.
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
                text = f"{text[: VALUE_LIMIT - 3]}... (sha256 {digest})"
            rows.append(
                f"| `{name}` | `{table_cell(text)}` | `{module}` | "
                f"{table_cell(comment)} |"
            )
    return rows


TABLE_HEADER = "| Constant | Value | Module | Code comment |\n| --- | --- | --- | --- |"
# Every module of the derived-metric packages, so no constant depends on a hand-kept list.
REFERENCE = CARDS_DIR / "code-constants.md"
REFERENCE_PACKAGES = ("backend/performance", "backend/activities")


def generated_section(card: str) -> str:
    rows = constant_rows(card_modules(card))
    return "\n".join([BEGIN, "## Code constants", "", TABLE_HEADER, *rows, END])


def reference_page() -> str:
    """The literal constants of every derived-metric module, one table per package."""
    packages = " and ".join(f"`{package}`" for package in REFERENCE_PACKAGES)
    lines = [
        "# Code constants of the derived metrics",
        "",
        "Generated by `python tests/test_performance_method_cards.py --write` from the",
        f"literal UPPER_CASE constants of every module in {packages}, with the code",
        "comment above each. The method cards explain the methods; this page states",
        "every named number the code fixes. A test fails when it is out of date.",
    ]
    for package in REFERENCE_PACKAGES:
        modules = sorted(
            f"{package}/{path.name}" for path in (ROOT / package).glob("*.py")
        )
        lines += ["", f"## `{package}`", "", TABLE_HEADER, *constant_rows(modules)]
    return "\n".join(lines) + "\n"


def with_generated_section(card: str) -> str:
    section = generated_section(card)
    start = card.find(BEGIN)
    if start < 0:
        return card.rstrip("\n") + "\n\n" + section + "\n"
    end = card.index(END, start) + len(END)
    return card[:start] + section + card[end:]


def code_method_versions(modules: list[str]) -> dict[str, object]:
    return {
        module: value.value
        for module in modules
        for name, value, _ in module_constants(module)
        if name == "METHOD_VERSION" and isinstance(value, ast.Constant)
    }


def method_name_problems(card: str) -> list[str]:
    """Versioned method names (``*METHOD`` strings such as ``x-v2``) must appear in the Method ID."""
    method_id = front_line(card, "Method ID")
    return [
        f"{module} {name} {value.value!r} not in Method ID"
        for module in card_modules(card)
        for name, value, _ in module_constants(module)
        if name.endswith("METHOD")
        and isinstance(value, ast.Constant)
        and isinstance(value.value, str)
        and re.search(r"-v\d+$", value.value)
        and value.value not in method_id
    ]


def version_problems(card: str) -> list[str]:
    method_id = front_line(card, "Method ID")
    problems = method_name_problems(card)
    versions = code_method_versions(card_modules(card))
    named = {module: v for module, v in versions.items() if module in method_id}
    if len(versions) > 1 and len(named) == 1:
        versions = named
    if not versions:
        return problems
    if len(versions) > 1:
        return [*problems, f"ambiguous METHOD_VERSION in {sorted(versions)}"]
    ((module, code_version),) = versions.items()
    found = METHOD_ID_VERSION.search(method_id)
    if found is None or int(found.group(1)) != code_version:
        problems.append(
            f"{module} METHOD_VERSION {code_version}, Method ID {method_id!r}"
        )
    return problems


class PerformanceMethodCardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.known_ids = register_ids((CARDS_DIR / "README.md").read_text("utf-8"))

    def test_register_lists_sources_and_lead(self) -> None:
        self.assertEqual(
            self.known_ids, {f"R{number}" for number in range(1, 63)} | {"L1"}
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
        broken = re.sub(
            r"(?m)^- \*\*Card version:\*\* \d+$", "- **Card version:** x", card, count=1
        )
        self.assertIn("invalid card version", card_problems(broken, self.known_ids))
        broken = card.replace("| Rating scale range | 0 to 10 |", "|  |  |", 1)
        problems = card_problems(broken, self.known_ids)
        self.assertTrue(any(item.startswith("incomplete") for item in problems))

    def test_generated_constants_are_current(self) -> None:
        for name in CARD_NAMES:
            card = (CARDS_DIR / name).read_text("utf-8")
            if not card_modules(card):
                continue
            with self.subTest(card=name):
                self.assertEqual(
                    with_generated_section(card),
                    card,
                    "run python tests/test_performance_method_cards.py --write",
                )

    def test_constant_reference_is_current(self) -> None:
        self.assertEqual(
            REFERENCE.read_text("utf-8"),
            reference_page(),
            "run python tests/test_performance_method_cards.py --write",
        )

    def test_method_version_matches_code(self) -> None:
        for name in CARD_NAMES:
            with self.subTest(card=name):
                card = (CARDS_DIR / name).read_text("utf-8")
                self.assertEqual(version_problems(card), [])
        card = (CARDS_DIR / "m6-local-tss-load.md").read_text("utf-8")
        self.assertEqual(
            code_method_versions(card_modules(card)),
            {"backend/performance/local_tss.py": 7},
        )
        self.assertTrue(
            version_problems(card.replace("local-tss-load v7", "local-tss-load v8"))
        )


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        REFERENCE.write_text(reference_page(), "utf-8", newline="\n")
        for card_name in CARD_NAMES:
            card_path = CARDS_DIR / card_name
            card_text = card_path.read_text("utf-8")
            if card_modules(card_text):
                card_path.write_text(
                    with_generated_section(card_text), "utf-8", newline="\n"
                )
    else:
        unittest.main()
