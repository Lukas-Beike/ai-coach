"""Ratchet provider-specific coupling outside the provider adapters.

The scanner reads backend/**/*.py, server.py and public/*.js and counts three
kinds of findings, each keyed by (rule, repository-relative posix path, token):

- ``icu_identifier``: any ``icu_*`` name in the raw text, including comments.
- ``garmin_wire_key``: a quoted string equal to a Garmin-only wire key.
- ``provider_literal``: a quoted string equal to "intervals" or "garmin"
  (case-insensitive).

Python literals come from the AST, so f-strings and implicit concatenation are
seen while comments are ignored. JavaScript literals come from a small lexer
that consumes comments before strings, so comment text cannot hide later
literals.

The committed baseline may only shrink. New or increased entries mean the code
must move behind a provider adapter or the canonical model. Removed or decreased
entries are recorded with ``python tests/provider_coupling.py --snapshot``, which
refuses to record growth and is reviewed like any other diff.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    from .architecture_registry import BACKEND_ROOT
except ImportError:
    from architecture_registry import BACKEND_ROOT

# Natively this is the repository root. In the container CI run the tests are
# mounted at /review/tests while the image keeps backend/, server.py and public/
# under /app. The registry then falls back to Path.cwd() for BACKEND_ROOT, which
# is /app because publish-container.yml runs with --workdir /app. Both layouts
# yield identical repository-relative paths.
SOURCE_ROOT = BACKEND_ROOT.parent
BASELINE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "provider_coupling_baseline.json"
)
REGENERATE_COMMAND = "python tests/provider_coupling.py --snapshot"
BASELINE_DESCRIPTION = (
    "Ratchet baseline for provider-specific coupling outside backend/providers/ "
    "and backend/canonical/. Entries may only shrink: move new coupling behind a "
    "provider adapter or canonical model, and regenerate this file after removing "
    "coupling."
)

RULE_ICU_IDENTIFIER = "icu_identifier"
RULE_GARMIN_WIRE_KEY = "garmin_wire_key"
RULE_PROVIDER_LITERAL = "provider_literal"

ICU_IDENTIFIER_PATTERN = re.compile(r"\bicu_[A-Za-z0-9_]+")
# Alternatives are tried left to right, so a comment opener is consumed before
# any quote inside it, and a quote is consumed before any comment marker inside it.
JAVASCRIPT_TOKEN_PATTERN = re.compile(
    r"//[^\n]*"
    r"|/\*.*?\*/"
    r"|\"(?:\\.|[^\"\\\n])*\""
    r"|'(?:\\.|[^'\\\n])*'"
    r"|`(?:\\.|[^`\\])*`",
    re.DOTALL,
)

# Garmin Connect camelCase field names taken from backend/providers/garmin.py,
# backend/providers/garmin_morning.py and garmin-fixture.example.json. The
# Intervals.icu adapters do not use any of them. Generic words and JSON-schema
# keywords are deliberately excluded so the rule only matches Garmin-specific
# wire keys when they appear as quoted strings.
GARMIN_WIRE_KEYS = frozenset(
    {
        "calendarDate",
        "customMakeModel",
        "functionalThresholdPower",
        "gearMakeName",
        "gearModelName",
        "gearName",
        "gearUUID",
        "hrvLastNight",
        "hrvSummaries",
        "hrvWeeklyAvg",
        "lastNightAvg",
        "maxHeartRateUsed",
        "restingHeartRate",
        "sleepTimeSeconds",
        "startTimeLocal",
        "summaryDate",
        "timestampGMT",
        "trainingReadinessScore",
        "vO2MaxValue",
        "vo2MaxPreciseValue",
        "weightKg",
        "weeklyAvg",
    }
)
PROVIDER_LITERALS = frozenset({"intervals", "garmin"})

# Adapters and the canonical model may name providers and use provider keys.
ADAPTER_PREFIXES = ("backend/providers/", "backend/canonical/")
# Only these files may name providers as literals outside the adapters. Add a
# provider registry here only when that file actually exists.
PROVIDER_LITERAL_ALLOWED_FILES = frozenset({"backend/db/migrations.py"})

FindingKey = tuple[str, str, str]


@dataclass(frozen=True, order=True)
class CouplingEntry:
    rule: str
    path: str
    token: str
    count: int

    @property
    def key(self) -> FindingKey:
        return (self.rule, self.path, self.token)


@dataclass(frozen=True)
class CouplingChange:
    rule: str
    path: str
    token: str
    baseline: int
    current: int

    def describe(self) -> str:
        return (
            f"{self.rule} {self.path} {self.token!r}: "
            f"baseline {self.baseline}, current {self.current}"
        )


@dataclass(frozen=True)
class CouplingComparison:
    new: tuple[CouplingChange, ...]
    increased: tuple[CouplingChange, ...]
    decreased: tuple[CouplingChange, ...]
    obsolete: tuple[CouplingChange, ...]

    @property
    def grown(self) -> tuple[CouplingChange, ...]:
        return self.new + self.increased

    @property
    def shrunk(self) -> tuple[CouplingChange, ...]:
        return self.decreased + self.obsolete


def _is_adapter_path(relative_path: str) -> bool:
    return relative_path.startswith(ADAPTER_PREFIXES)


def _python_string_literals(text: str) -> list[str]:
    tree = ast.parse(text)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _javascript_string_literals(text: str) -> list[str]:
    values: list[str] = []
    for match in JAVASCRIPT_TOKEN_PATTERN.finditer(text):
        token = match.group(0)
        if token.startswith(("//", "/*")):
            continue
        body = token[1:-1]
        values.append(body)
        if token.startswith("`") and "${" in body:
            # Interpolated expressions can contain quoted provider literals.
            values.extend(_javascript_string_literals(body))
    return values


def _string_literals(path: Path, text: str) -> list[str]:
    if path.suffix == ".py":
        return _python_string_literals(text)
    return _javascript_string_literals(text)


def _findings_for_file(
    relative_path: str, text: str, literals: Sequence[str]
) -> Counter[FindingKey]:
    findings: Counter[FindingKey] = Counter()
    if not _is_adapter_path(relative_path):
        for match in ICU_IDENTIFIER_PATTERN.finditer(text):
            findings[(RULE_ICU_IDENTIFIER, relative_path, match.group(0))] += 1
        for literal in literals:
            if literal in GARMIN_WIRE_KEYS:
                findings[(RULE_GARMIN_WIRE_KEY, relative_path, literal)] += 1
    literals_allowed = (
        _is_adapter_path(relative_path)
        or relative_path in PROVIDER_LITERAL_ALLOWED_FILES
    )
    if not literals_allowed:
        for literal in literals:
            lowered = literal.lower()
            if lowered in PROVIDER_LITERALS:
                findings[(RULE_PROVIDER_LITERAL, relative_path, lowered)] += 1
    return findings


def scanned_paths(root: Path) -> list[Path]:
    required = (root / "backend", root / "public")
    missing = [
        str(path) for path in (*required, root / "server.py") if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "provider coupling scan root is missing sources: " + ", ".join(missing)
        )
    paths = list((root / "backend").rglob("*.py"))
    paths.append(root / "server.py")
    paths.extend((root / "public").glob("*.js"))
    return sorted(path for path in paths if path.is_file())


def scan_provider_coupling(root: Path = SOURCE_ROOT) -> list[CouplingEntry]:
    findings: Counter[FindingKey] = Counter()
    for path in scanned_paths(root):
        relative_path = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        literals = _string_literals(path, text)
        findings.update(_findings_for_file(relative_path, text, literals))
    return [
        CouplingEntry(rule=rule, path=path, token=token, count=count)
        for (rule, path, token), count in sorted(findings.items())
    ]


def load_baseline(path: Path = BASELINE_PATH) -> list[CouplingEntry]:
    document = json.loads(path.read_text(encoding="utf-8"))
    entries = [
        CouplingEntry(
            rule=str(item["rule"]),
            path=str(item["path"]),
            token=str(item["token"]),
            count=int(item["count"]),
        )
        for item in document["entries"]
    ]
    if len({entry.key for entry in entries}) != len(entries):
        raise ValueError("provider coupling baseline contains duplicate entries")
    if any(entry.count < 1 for entry in entries):
        raise ValueError("provider coupling baseline counts must be positive")
    return entries


def render_baseline(entries: Sequence[CouplingEntry]) -> str:
    document = {
        "description": BASELINE_DESCRIPTION,
        "regeneration": REGENERATE_COMMAND,
        "entries": [asdict(entry) for entry in sorted(entries)],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write_baseline(
    entries: Sequence[CouplingEntry], path: Path = BASELINE_PATH
) -> None:
    # Fixed LF endings keep the snapshot byte-identical on Windows and Linux.
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_baseline(entries))


def compare_coupling(
    baseline: Sequence[CouplingEntry], current: Sequence[CouplingEntry]
) -> CouplingComparison:
    expected = {entry.key: entry.count for entry in baseline}
    observed = {entry.key: entry.count for entry in current}
    new: list[CouplingChange] = []
    increased: list[CouplingChange] = []
    decreased: list[CouplingChange] = []
    obsolete: list[CouplingChange] = []
    for key in sorted(set(expected) | set(observed)):
        before = expected.get(key, 0)
        after = observed.get(key, 0)
        change = CouplingChange(
            rule=key[0], path=key[1], token=key[2], baseline=before, current=after
        )
        if before == 0:
            new.append(change)
        elif after == 0:
            obsolete.append(change)
        elif after > before:
            increased.append(change)
        elif after < before:
            decreased.append(change)
    return CouplingComparison(
        new=tuple(new),
        increased=tuple(increased),
        decreased=tuple(decreased),
        obsolete=tuple(obsolete),
    )


def snapshot_refusals(
    baseline: Sequence[CouplingEntry] | None, current: Sequence[CouplingEntry]
) -> list[str]:
    """Return why a snapshot must not be recorded; an empty list means allowed.

    A ``None`` baseline means the committed file does not exist yet, which is only
    the bootstrap case. Growth is refused once a baseline exists.
    """
    if not current:
        return [
            "the scan found no provider sources; refusing to record an empty baseline"
        ]
    if baseline is None:
        return []
    comparison = compare_coupling(baseline, current)
    return [
        f"refusing to record growth: {change.describe()}" for change in comparison.grown
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="record removed coupling in the baseline from the current source tree",
    )
    arguments = parser.parse_args(argv)
    current = scan_provider_coupling()
    if arguments.snapshot:
        baseline = load_baseline() if BASELINE_PATH.exists() else None
        refusals = snapshot_refusals(baseline, current)
        if refusals:
            for refusal in refusals:
                print(refusal)
            return 1
        write_baseline(current)
        print(f"Wrote {len(current)} provider coupling entries to {BASELINE_PATH}.")
        return 0
    comparison = compare_coupling(load_baseline(), current)
    changes = comparison.grown + comparison.shrunk
    if not changes:
        print("Provider coupling matches the baseline.")
        return 0
    for change in comparison.new:
        print(f"new: {change.describe()}")
    for change in comparison.increased:
        print(f"increased: {change.describe()}")
    for change in comparison.decreased:
        print(f"decreased: {change.describe()}")
    for change in comparison.obsolete:
        print(f"obsolete: {change.describe()}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
