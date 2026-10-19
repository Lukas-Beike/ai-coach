"""Run the standard-library test suite, optionally split into stable shards.

Shards keep every TestCase class whole, so class-level fixtures such as
ServerTestCase.setUpClass run once per class. Classes are assigned largest-first
to the currently least-loaded shard, so shard sizes stay balanced.

``--suite container`` runs only the container-sensitive modules named in
CONTAINER_SUITE_PATTERNS. The default ``--suite all`` runs everything.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def assign_classes(tests, total: int) -> dict[str, int]:
    """Map each TestCase class to a 0-based shard index, deterministically."""
    sizes: dict[str, int] = {}
    for test in tests:
        key = class_key(test)
        sizes[key] = sizes.get(key, 0) + 1
    loads = [0] * total
    assignment: dict[str, int] = {}
    for key, size in sorted(sizes.items(), key=lambda item: (-item[1], item[0])):
        shard_index = min(range(total), key=lambda index: (loads[index], index))
        assignment[key] = shard_index
        loads[shard_index] += size
    return assignment


def select_shard(tests, shard: int, total: int):
    tests = list(tests)
    assignment = assign_classes(tests, total)
    return [test for test in tests if assignment[class_key(test)] == shard - 1]


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
    args = parser.parse_args()
    if args.total < 1 or not 1 <= args.shard <= args.total:
        parser.error(
            "--shard must be between 1 and --total, and --total must be positive"
        )
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
    result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(selected))
    elapsed = time.perf_counter() - started
    print(
        f"Discovery: {len(tests)} tests; shard {args.shard}/{args.total}: "
        f"{result.testsRun} run, {len(result.skipped)} skipped in {elapsed:.2f}s"
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
