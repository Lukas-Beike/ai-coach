"""Ratchet provider-specific coupling outside the provider adapters.

The scanner reads backend/**/*.py, server.py and public/*.js and counts three
kinds of findings, each keyed by (rule, repository-relative posix path, token):

- ``icu_identifier``: any ``icu_*`` name in the raw text, including comments.
- ``garmin_wire_key``: a quoted string equal to a Garmin-only wire key.
- ``provider_literal``: a quoted string equal to "intervals", "garmin" or
  "wahoo" (case-insensitive).

Python literals come from the AST, so f-strings and implicit concatenation are
seen while comments are ignored. JavaScript literals come from a small lexer
that consumes comments before strings, so comment text cannot hide later
literals.

Three owner-read rules, ``snapshot_key``, ``source_label`` and
``field_module_import``, are checked apart
from the baseline against ``OWNER_READ_ALLOWLIST``: raw snapshot reads and provider
display-name literals belong to the sync/provider owners, not to consumers.

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
from collections.abc import Mapping, Sequence
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
PROVIDER_LITERALS = frozenset({"intervals", "garmin", "wahoo"})

# Adapters and the canonical model may name providers and use provider keys.
ADAPTER_PREFIXES = ("backend/providers/", "backend/canonical/")
# Only these files may name providers as literals outside the adapters. The sync
# provider registry (backend/sync/provider_registry.py) is literal-free and must
# never be listed here; its provider data lives in backend/providers/descriptors.py.
PROVIDER_LITERAL_ALLOWED_FILES = frozenset({"backend/db/migrations.py"})

RULE_SNAPSHOT_KEY = "snapshot_key"
RULE_SOURCE_LABEL = "source_label"
RULE_FIELD_MODULE_IMPORT = "field_module_import"

# Owner-read rules. Unlike the ratchet rules above they are checked against an
# explicit per-file allowlist and never enter the baseline, which stays empty.
#
# ``snapshot_key`` flags, in backend/**/*.py and server.py, a quoted raw snapshot
# key-value key and any reference to ``latest_snapshot`` (the Intervals.icu raw
# snapshot reader), including an aliased import and a quoted name such as a
# ``getattr`` argument. A key embedded in a larger string, such as SQL against the
# kv table, counts too; docstrings do not. Consumers read canonical observations
# instead.
SNAPSHOT_KEY_LITERALS = frozenset({"garmin_snapshot", "intervals_snapshot"})
SNAPSHOT_KEY_PATTERN = re.compile(r"\b(garmin_snapshot|intervals_snapshot)\b")
SNAPSHOT_READ_NAME = "latest_snapshot"
# ``source_label`` flags a quoted string that is exactly a provider display name.
# Exact matches are data/source labels; prose such as "Mit Garmin Connect
# verbinden" or "Garmin Connect Radaktivitäten" never matches. The rule covers
# only consumers that emit or compare source labels. Labels belong in
# backend/providers/source_labels.py; connection, settings and sync copy in
# backend/sync/, backend/providers/ and the other public/*.js files names the
# provider for a user action and stays out of scope.
SOURCE_LABEL_LITERALS = frozenset({"Garmin Connect", "Intervals.icu"})
SOURCE_LABEL_SCOPES = (
    "backend/athlete/",
    "backend/coach/",
    "backend/http_api/",
    "backend/nutrition/",
    "backend/performance/",
    "backend/planning/",
    "public/analysis.js",
    "public/performance-view.js",
)

# ``field_module_import`` flags, in backend/**/*.py outside the adapters and
# backend/sync/, an import of a provider field-name module (``FIELD_NAME_MODULES``).
# A consumer that names provider fields through those constants is still
# provider-shaped (#1413); it reads the canonical model or a neutral shape instead.
FIELD_NAME_MODULES = frozenset(
    {
        "garmin_fields",
        "garmin_gear_fields",
        "garmin_performance_fields",
        "intervals_activity_fields",
        "intervals_performance_fields",
    }
)
FIELD_MODULE_IMPORT_ALLOWED_PREFIXES = (*ADAPTER_PREFIXES, "backend/sync/")

_SYNC_WRITER = "writer: persists or ingests the raw provider snapshot"
_BACKUP = "export: backup/privacy export serializes the stored raw snapshot"
_SYNC_STATUS = "sync-status: reads synced_at/freshness, not metric values"
_AWAITING_PERFORMANCE_KINDS = (
    "awaiting-kind: legacy builders still take the snapshot; needs metric kinds for "
    "performance and FTP history, power curve, training status and load balance, "
    "training effect/load focus and the overall endurance score"
)
_LEGACY_LABEL = (
    "legacy-label: view still emits or compares the label itself; move it to "
    "backend/providers/source_labels.py"
)

_ACTIVITY_ROWS = (
    "activity-rows: reads Intervals-shaped activity rows or the Coach activity "
    "allowlist; moves to the neutral activity summary (#1510)"
)
_LEGACY_FALLBACK = (
    "legacy-fallback: Garmin view, snapshot athlete or legacy wellness fallback "
    "removed when the canonical record wins (#1415)"
)
_DEAD_LEGACY = (
    "dead-legacy: no production caller; deleted with the read selector (#1416)"
)
_PLANNING_RECORDS = (
    "planning-records: local planned units and library entries still store the "
    "provider training-load and intensity keys (start and duration moved in #1507)"
)
# repository-relative path -> (reason, field-name modules it may still import).
# A new module in an allowlisted file fails the guard as well.
_FIELD_MODULE_OWNERS: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "backend/activities/calendar_projection.py": (
        _ACTIVITY_ROWS,
        ("intervals_performance_fields",),
    ),
    "backend/activities/detail_projection.py": (
        _ACTIVITY_ROWS,
        ("intervals_performance_fields",),
    ),
    "backend/activities/detail_store.py": (
        _DEAD_LEGACY,
        ("intervals_performance_fields",),
    ),
    "backend/activities/duplicates.py": (_ACTIVITY_ROWS, ("garmin_gear_fields",)),
    "backend/athlete/equipment.py": (_LEGACY_FALLBACK, ("garmin_gear_fields",)),
    "backend/coach/context.py": (_ACTIVITY_ROWS, ("intervals_performance_fields",)),
    "backend/nutrition/sync_status.py": (_LEGACY_FALLBACK, ("garmin_fields",)),
    "backend/performance/activity_validation.py": (
        _ACTIVITY_ROWS,
        (
            "garmin_performance_fields",
            "intervals_performance_fields",
        ),
    ),
    "backend/performance/canonical_sections.py": (
        _ACTIVITY_ROWS,
        ("intervals_activity_fields",),
    ),
    "backend/performance/current_metrics.py": (
        _LEGACY_FALLBACK,
        ("intervals_performance_fields",),
    ),
    "backend/performance/eftp.py": (
        _ACTIVITY_ROWS,
        (
            "garmin_fields",
            "intervals_performance_fields",
        ),
    ),
    "backend/performance/garmin_metric_history.py": (
        _LEGACY_FALLBACK,
        ("garmin_performance_fields",),
    ),
    "backend/performance/garmin_metrics.py": (
        _LEGACY_FALLBACK,
        (
            "garmin_fields",
            "garmin_performance_fields",
        ),
    ),
    "backend/performance/garmin_observations.py": (
        _LEGACY_FALLBACK,
        ("garmin_performance_fields",),
    ),
    "backend/performance/garmin_projection.py": (
        _LEGACY_FALLBACK,
        (
            "garmin_fields",
            "garmin_performance_fields",
        ),
    ),
    "backend/performance/garmin_weight.py": (
        _LEGACY_FALLBACK,
        (
            "garmin_fields",
            "garmin_performance_fields",
        ),
    ),
    "backend/performance/load.py": (_ACTIVITY_ROWS, ("intervals_performance_fields",)),
    "backend/performance/planning_recovery.py": (
        _DEAD_LEGACY,
        (
            "garmin_fields",
            "garmin_performance_fields",
        ),
    ),
    "backend/performance/recovery.py": (
        _LEGACY_FALLBACK,
        (
            "garmin_fields",
            "garmin_performance_fields",
        ),
    ),
    "backend/performance/report_service.py": (
        _ACTIVITY_ROWS,
        ("intervals_activity_fields",),
    ),
    "backend/performance/session_analysis.py": (
        _ACTIVITY_ROWS,
        ("intervals_performance_fields",),
    ),
    "backend/performance/tag_impact.py": (
        _ACTIVITY_ROWS,
        ("intervals_performance_fields",),
    ),
    "backend/performance/training_focus.py": (
        _ACTIVITY_ROWS,
        ("garmin_performance_fields",),
    ),
    "backend/performance/training_report.py": (
        _ACTIVITY_ROWS,
        (
            "intervals_activity_fields",
            "intervals_performance_fields",
        ),
    ),
    "backend/performance/wellness.py": (
        _LEGACY_FALLBACK,
        ("garmin_performance_fields",),
    ),
    "backend/planning/context.py": (
        _PLANNING_RECORDS,
        (
            "intervals_activity_fields",
            "intervals_performance_fields",
        ),
    ),
    "backend/planning/library.py": (
        _PLANNING_RECORDS,
        ("intervals_performance_fields",),
    ),
    "backend/planning/season_preparation.py": (
        _ACTIVITY_ROWS,
        ("intervals_performance_fields",),
    ),
    "backend/planning/target_snapshot.py": (
        _PLANNING_RECORDS,
        ("intervals_performance_fields",),
    ),
}
FIELD_MODULE_IMPORTS_ALLOWED = frozenset(
    (file_path, module)
    for file_path, (_reason, allowed) in _FIELD_MODULE_OWNERS.items()
    for module in allowed
)

# (rule, repository-relative path) -> reason. Only the files the rules actually
# fire on are listed; a stale entry fails the guard. Remove an awaiting-kind entry
# once its consumer reads canonical observations.
OWNER_READ_ALLOWLIST: Mapping[tuple[str, str], str] = {
    (RULE_SNAPSHOT_KEY, "backend/canonical/garmin_payload.py"): _SYNC_WRITER,
    (RULE_SNAPSHOT_KEY, "backend/sync/garmin.py"): _SYNC_WRITER,
    (RULE_SNAPSHOT_KEY, "backend/sync/snapshot_reader.py"): _SYNC_WRITER,
    (RULE_SNAPSHOT_KEY, "backend/sync/snapshot_storage.py"): _SYNC_WRITER,
    (RULE_SNAPSHOT_KEY, "backend/sync/state.py"): _SYNC_WRITER,
    (RULE_SNAPSHOT_KEY, "backend/sync/canonical_projection_assembly.py"): _SYNC_WRITER,
    (RULE_SNAPSHOT_KEY, "backend/backup/export.py"): _BACKUP,
    (RULE_SNAPSHOT_KEY, "backend/privacy.py"): _BACKUP,
    (RULE_SNAPSHOT_KEY, "backend/activities/read_service.py"): _SYNC_STATUS,
    (RULE_SOURCE_LABEL, "backend/athlete/equipment.py"): _LEGACY_LABEL,
    (RULE_SNAPSHOT_KEY, "backend/diagnostics/report.py"): _SYNC_STATUS,
    (RULE_SNAPSHOT_KEY, "backend/coach/context.py"): _AWAITING_PERFORMANCE_KINDS,
    (RULE_SNAPSHOT_KEY, "backend/http_api/assembly.py"): _AWAITING_PERFORMANCE_KINDS,
    (
        RULE_SNAPSHOT_KEY,
        "backend/http_api/athlete_assembly.py",
    ): _AWAITING_PERFORMANCE_KINDS,
    (
        RULE_SNAPSHOT_KEY,
        "backend/http_api/bootstrap_state.py",
    ): _AWAITING_PERFORMANCE_KINDS,
    (
        RULE_SNAPSHOT_KEY,
        "backend/http_api/public_performance.py",
    ): _AWAITING_PERFORMANCE_KINDS,
    (RULE_SNAPSHOT_KEY, "backend/http_api/public_plan.py"): _AWAITING_PERFORMANCE_KINDS,
    (
        RULE_SNAPSHOT_KEY,
        "backend/http_api/state_prelude.py",
    ): _AWAITING_PERFORMANCE_KINDS,
    **{
        (RULE_SOURCE_LABEL, path): _LEGACY_LABEL
        for path in (
            "backend/performance/body.py",
            "backend/performance/chart_history.py",
            "backend/performance/garmin_metric_history.py",
            "backend/performance/garmin_projection.py",
            "backend/performance/morning_battery.py",
            "backend/performance/personal_recovery.py",
            "backend/performance/planning_recovery.py",
            "backend/performance/report_service.py",
            "backend/performance/session_analysis.py",
            "backend/performance/training_focus.py",
            "backend/performance/training_report.py",
        )
    },
    **{
        (RULE_FIELD_MODULE_IMPORT, path): reason
        for path, (reason, _modules) in _FIELD_MODULE_OWNERS.items()
    },
}

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


def _import_base(node: ast.ImportFrom, relative_path: str) -> str:
    """Return the absolute module an ``ImportFrom`` names, resolving relative ones."""
    if not node.level:
        return node.module or ""
    package = relative_path.split("/")[:-1]
    if node.level > 1:
        package = package[: len(package) - (node.level - 1)]
    return ".".join([*package, *([node.module] if node.module else [])])


def _field_module_imports(text: str, relative_path: str = "") -> list[str]:
    """Return the provider field-name modules a Python source imports.

    Absolute and relative imports count, including a field-name module imported
    as a name of its package (``from backend.providers import garmin_fields``).
    """
    modules: list[str] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = _import_base(node, relative_path)
            names = [base, *(f"{base}.{alias.name}" for alias in node.names)]
        else:
            continue
        found = {
            name.rsplit(".", 1)[-1]
            for name in names
            if name.startswith("backend.providers.")
            and name.rsplit(".", 1)[-1] in FIELD_NAME_MODULES
        }
        modules.extend(sorted(found))
    return modules


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


def _snapshot_key_tokens(text: str) -> list[str]:
    tree = ast.parse(text)
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    tokens: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            tokens.extend(SNAPSHOT_KEY_PATTERN.findall(node.value))
        if (
            (isinstance(node, ast.Attribute) and node.attr == SNAPSHOT_READ_NAME)
            or (isinstance(node, ast.Name) and node.id == SNAPSHOT_READ_NAME)
            or (isinstance(node, ast.alias) and node.name == SNAPSHOT_READ_NAME)
            or (isinstance(node, ast.Constant) and node.value == SNAPSHOT_READ_NAME)
        ):
            tokens.append(SNAPSHOT_READ_NAME)
    return tokens


def scan_owner_reads(root: Path = SOURCE_ROOT) -> list[CouplingEntry]:
    """Count raw snapshot reads, source-label literals and field-module imports."""
    findings: Counter[FindingKey] = Counter()
    for path in scanned_paths(root):
        relative_path = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            for token in _snapshot_key_tokens(text):
                findings[(RULE_SNAPSHOT_KEY, relative_path, token)] += 1
            if not relative_path.startswith(FIELD_MODULE_IMPORT_ALLOWED_PREFIXES):
                for module in _field_module_imports(text, relative_path):
                    findings[(RULE_FIELD_MODULE_IMPORT, relative_path, module)] += 1
        if relative_path.startswith(SOURCE_LABEL_SCOPES):
            for literal in _string_literals(path, text):
                if literal in SOURCE_LABEL_LITERALS:
                    findings[(RULE_SOURCE_LABEL, relative_path, literal)] += 1
    return [
        CouplingEntry(rule=rule, path=path, token=token, count=count)
        for (rule, path, token), count in sorted(findings.items())
    ]


def unallowed_owner_reads(
    entries: Sequence[CouplingEntry],
    allowlist: Mapping[tuple[str, str], str] = OWNER_READ_ALLOWLIST,
    field_imports: frozenset[tuple[str, str]] = FIELD_MODULE_IMPORTS_ALLOWED,
) -> list[CouplingEntry]:
    """Findings outside the allowlist; field-module imports also match the module."""
    return [
        entry
        for entry in entries
        if (entry.rule, entry.path) not in allowlist
        or (
            entry.rule == RULE_FIELD_MODULE_IMPORT
            and (entry.path, entry.token) not in field_imports
        )
    ]


def stale_owner_allowlist(
    entries: Sequence[CouplingEntry],
    allowlist: Mapping[tuple[str, str], str] = OWNER_READ_ALLOWLIST,
    field_imports: frozenset[tuple[str, str]] = FIELD_MODULE_IMPORTS_ALLOWED,
) -> list[tuple[str, str]]:
    """Allowlist entries whose file, or field-name module, no longer triggers."""
    observed = {(entry.rule, entry.path) for entry in entries}
    imported = {
        (entry.path, entry.token)
        for entry in entries
        if entry.rule == RULE_FIELD_MODULE_IMPORT
    }
    stale_modules = [
        (RULE_FIELD_MODULE_IMPORT, f"{file_path}: {module}")
        for file_path, module in sorted(field_imports - imported)
        if (RULE_FIELD_MODULE_IMPORT, file_path) in allowlist
    ]
    return sorted(set(allowlist) - observed) + stale_modules


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
    baseline: Sequence[CouplingEntry] | None,
    current: Sequence[CouplingEntry],
    *,
    sources_scanned: bool = False,
) -> list[str]:
    """Return why a snapshot must not be recorded; an empty list means allowed.

    A ``None`` baseline means the committed file does not exist yet, which is only
    the bootstrap case. Growth is refused once a baseline exists. An empty scan is
    recorded only when an existing baseline confirms that source files were
    scanned and every remaining entry was removed.
    """
    if not current and (baseline is None or not sources_scanned):
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
        refusals = snapshot_refusals(
            baseline, current, sources_scanned=bool(scanned_paths(SOURCE_ROOT))
        )
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
