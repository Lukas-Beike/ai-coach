"""Run the standard-library test suite, optionally split into stable shards.

Shards keep every TestCase class whole, so class-level fixtures such as
ServerTestCase.setUpClass run once per class. Classes are assigned heaviest-first
to the currently least-loaded shard. A class weighs its recorded wall time from
DURATIONS_FILE; a class without a recording weighs its test count times the
median recorded seconds per test, so new or renamed classes still balance.
Refresh the recording with ``--record-durations tests/test_durations.json`` on a
full run, for example inside the image used by run_sqlcipher_tests.ps1.

``--suite container`` runs only the container-sensitive modules named in
CONTAINER_SUITE_PATTERNS. The default ``--suite all`` runs everything.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import statistics
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DURATIONS_FILE = Path(__file__).resolve().parent / "test_durations.json"

# Module-name patterns for the container-sensitive subset: image dependencies,
# SQLCipher, the read-only non-root runtime, configuration, startup, security
# limits, privacy/redaction, and authentication sessions. Every pattern must
# match at least one test module; test_ci_contracts.py enforces this.
CONTAINER_SUITE_PATTERNS = (
    "test_container_delivery",
    "test_db_*",
    "test_database_*",
    "test_server_database*",
    "test_server_runtime*",
    "test_runtime_*",
    "test_security_resource_limits",
    "test_config*",
    "test_diagnostic_logs*",
    "test_privacy_*",
    "test_http_privacy_*",
    "test_garmin_login*",
    "test_session_auth_*",
    "test_http_auth_post*",
    "test_startup_sync_scheduler*",
)
SUITES = ("all", "container")


def iter_tests(suite: unittest.TestSuite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from iter_tests(test)
        else:
            yield test


def discover_tests(directory: Path | None = None):
    loader = unittest.TestLoader()
    loaded = loader.discover(
        str(directory or Path(__file__).resolve().parent), pattern="test_*.py"
    )
    if loader.errors:
        raise RuntimeError(
            "Test discovery failed:\n" + "\n".join(map(str, loader.errors))
        )
    return sorted(iter_tests(loaded), key=lambda test: test.id())


def module_name(test) -> str:
    return type(test).__module__


def class_key(test) -> str:
    cls = type(test)
    return f"{cls.__module__}.{cls.__qualname__}"


def load_durations(path: Path = DURATIONS_FILE) -> dict[str, float]:
    """Return recorded seconds per TestCase class, or nothing without a recording."""
    if not path.exists():
        return {}
    return {
        str(key): float(seconds)
        for key, seconds in json.loads(path.read_text(encoding="utf-8")).items()
    }


def class_weights(tests, durations: dict[str, float]) -> dict[str, float]:
    """Weigh each class by recorded seconds, else by its estimated test time."""
    sizes: dict[str, int] = {}
    for test in tests:
        key = class_key(test)
        sizes[key] = sizes.get(key, 0) + 1
    recorded = [durations[key] / size for key, size in sizes.items() if key in durations]
    per_test = statistics.median(recorded) if recorded else 1.0
    return {key: durations.get(key, size * per_test) for key, size in sizes.items()}


def assign_classes(
    tests, total: int, durations: dict[str, float] | None = None
) -> dict[str, int]:
    """Map each TestCase class to a 0-based shard index, deterministically."""
    weights = class_weights(tests, load_durations() if durations is None else durations)
    loads = [0.0] * total
    assignment: dict[str, int] = {}
    for key, weight in sorted(weights.items(), key=lambda item: (-item[1], item[0])):
        shard_index = min(range(total), key=lambda index: (loads[index], index))
        assignment[key] = shard_index
        loads[shard_index] += weight
    return assignment


def select_shard(tests, shard: int, total: int, durations: dict[str, float] | None = None):
    tests = list(tests)
    assignment = assign_classes(tests, total, durations)
    return [test for test in tests if assignment[class_key(test)] == shard - 1]


class ClassTimingResult(unittest.TextTestResult):
    """Attribute the wall time since the previous finished test to each test's
    class, so setUpClass counts towards the class that needs it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_seconds: dict[str, float] = {}
        self._mark = time.perf_counter()

    def stopTest(self, test):
        super().stopTest(test)
        now = time.perf_counter()
        key = class_key(test)
        self.class_seconds[key] = self.class_seconds.get(key, 0.0) + now - self._mark
        self._mark = now


def select_suite(tests, suite: str):
    tests = list(tests)
    if suite == "all":
        return tests
    if suite == "container":
        return [
            test
            for test in tests
            if any(
                fnmatch.fnmatchcase(module_name(test), pattern)
                for pattern in CONTAINER_SUITE_PATTERNS
            )
        ]
    raise ValueError(f"unknown suite: {suite}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=int, default=1, help="1-based shard number")
    parser.add_argument("--total", type=int, default=1, help="number of total shards")
    parser.add_argument(
        "--suite",
        choices=SUITES,
        default="all",
        help="'container' runs only the container-sensitive test modules",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list selected test IDs without executing them",
    )
    parser.add_argument(
        "--record-durations",
        type=Path,
        metavar="PATH",
        help="write per-class wall time as JSON; requires a full unsharded run",
    )
    args = parser.parse_args()
    if args.total < 1 or not 1 <= args.shard <= args.total:
        parser.error(
            "--shard must be between 1 and --total, and --total must be positive"
        )
    if args.record_durations and (args.total != 1 or args.suite != "all"):
        parser.error("--record-durations needs the full suite in a single shard")
    return args


def main() -> int:
    args = parse_args()
    tests = select_suite(discover_tests(), args.suite)
    selected = select_shard(tests, args.shard, args.total)
    if args.list:
        print("\n".join(test.id() for test in selected))
        return 0
    if not selected:
        raise SystemExit(f"shard {args.shard}/{args.total} contains no tests")

    started = time.perf_counter()
    runner = unittest.TextTestRunner(verbosity=1, resultclass=ClassTimingResult)
    result = runner.run(unittest.TestSuite(selected))
    elapsed = time.perf_counter() - started
    print(
        f"Discovery: {len(tests)} tests; shard {args.shard}/{args.total}: "
        f"{result.testsRun} run, {len(result.skipped)} skipped in {elapsed:.2f}s"
    )
    if args.record_durations:
        assert isinstance(result, ClassTimingResult)
        recorded = {
            key: round(seconds, 3)
            for key, seconds in sorted(result.class_seconds.items())
        }
        args.record_durations.write_text(
            json.dumps(recorded, indent=1) + "\n", encoding="utf-8"
        )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
