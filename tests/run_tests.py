"""Run the standard-library test suite, optionally split into stable shards."""

from __future__ import annotations

import argparse
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


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


def select_shard(tests, shard: int, total: int):
    return [test for index, test in enumerate(tests) if index % total == shard - 1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=int, default=1, help="1-based shard number")
    parser.add_argument("--total", type=int, default=1, help="number of total shards")
    args = parser.parse_args()
    if args.total < 1 or not 1 <= args.shard <= args.total:
        parser.error(
            "--shard must be between 1 and --total, and --total must be positive"
        )
    return args


def main() -> int:
    args = parse_args()
    tests = discover_tests()
    selected = select_shard(tests, args.shard, args.total)
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
