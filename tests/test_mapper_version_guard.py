"""A mapper's code cannot change without the version that replays it (#1672).

Stored provider records are re-projected only when the version of their mapper
changes. Sub-mappers have no version of their own: they ride on the version of
the mapper that calls them. This guard pins a fingerprint of every mapping
module's code together with the versions that replay it. Changing the code
without bumping one of those versions fails here.

The fingerprint ignores comments, docstrings and layout, so documentation edits
pass. When a code change does not alter any mapped output (a pure refactor),
update the fingerprint and say so in the PR; otherwise bump the version first.
Run this module to print the current table.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import io
import tokenize
import unittest
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ROOT / "backend" / "providers"

# Mapping module -> the modules whose MAPPER_VERSION replays its output.
REPLAYED_BY: Final[dict[str, tuple[str, ...]]] = {
    "fit_activity_detail_mapping": ("fit_activity_detail_mapping",),
    "garmin_activity_detail_mapping": ("garmin_activity_detail_mapping",),
    "garmin_activity_mapping": ("garmin_activity_mapping",),
    "garmin_gear_mapping": ("garmin_health_mapping",),
    "garmin_health_mapping": ("garmin_health_mapping",),
    "garmin_status_mapping": ("garmin_health_mapping",),
    "garmin_training_mapping": ("garmin_health_mapping",),
    "intervals_activity_detail_mapping": ("intervals_activity_detail_mapping",),
    "intervals_activity_mapping": ("intervals_activity_mapping",),
    "intervals_power_curve_mapping": ("intervals_power_curve_mapping",),
    "intervals_wellness_mapping": ("intervals_wellness_mapping",),
    "intervals_zone_mapping": ("intervals_wellness_mapping",),
    "sleep_period_mapping": ("garmin_health_mapping", "intervals_wellness_mapping"),
    "wahoo_activity_mapping": ("wahoo_activity_mapping",),
    "wahoo_threshold_mapping": ("wahoo_threshold_mapping",),
}
# Mapping modules that project nothing that is stored and replayed.
NOT_REPLAYED: Final[dict[str, str]] = {
    "wahoo_plan_mapping": "outbound: builds Wahoo plan payloads for export",
}
# Module -> (replaying versions, code fingerprint).
PINNED: Final[dict[str, tuple[tuple[int, ...], str]]] = {
    "fit_activity_detail_mapping": (
        (2,),
        "43952bd67a189645af8944a284a5902c66e498d9cb4f8dfbc85285b59910235a",
    ),
    "garmin_activity_detail_mapping": (
        (2,),
        "581b457314c458d0c4fd5378e5785a6494372d83d53eb01be5d7b5d549815e9c",
    ),
    "garmin_activity_mapping": (
        (13,),
        "8f2d7fb44720f87c287a7e3edc0a4e60eecb5ac606ade7ac2a49e28c602e2950",
    ),
    "garmin_gear_mapping": (
        (17,),
        "c1065949991a138dd91ec1b96da88939bf8c847e52ef550dc32a665cce0e1b7c",
    ),
    "garmin_health_mapping": (
        (17,),
        "60043de739cfbbf163d613af7a01709d6e8341f2e5de761462d3935ba2081050",
    ),
    "garmin_status_mapping": (
        (17,),
        "6eb0749c1fee8ce3f6ccf61c5620475b7eea3eac353aab4be5e58f1d866be8f5",
    ),
    "garmin_training_mapping": (
        (17,),
        "34fd2a6d7884c0b54f9b87ccba040fb83f5cc7c481c69776edbd71c30e87be0e",
    ),
    "intervals_activity_detail_mapping": (
        (2,),
        "d1556e715a8c85384ac6da1444683f6093e8c61599a9c46c8b9d5a4eee483280",
    ),
    "intervals_activity_mapping": (
        (10,),
        "814125637b58cd0ec59d6484a2db42c46b8f05fa0c279b00e84fa7877b2b005f",
    ),
    "intervals_power_curve_mapping": (
        (1,),
        "e2496632923707d6e14984261722a6345e7f8745ef4ab0c95a29571396387d1e",
    ),
    "intervals_wellness_mapping": (
        (12,),
        "3537dd0f49deaf687a8ac32662fa83b02a7a9cf058517272cad53641b9ca9eb2",
    ),
    "intervals_zone_mapping": (
        (12,),
        "6d741d7c81757d9149da43d1f0635532ef181918a47c6da3485f396eb229ca75",
    ),
    "sleep_period_mapping": (
        (17, 12),
        "77efab15de0cda5414ed02c0d5005a9fe6fb1a650ec103bdb40e01cef065cf0f",
    ),
    "wahoo_activity_mapping": (
        (6,),
        "bbd6940b2a3598b79fbdfbdc3797f97ba154b5d3670f0f6cfe5ae5e32e011537",
    ),
    "wahoo_threshold_mapping": (
        (2,),
        "97792201907fefa34005f62fa805c7190b09177ac8b82f56d8e40e0d12823d89",
    ),
}


def fingerprint(source: str) -> str:
    """SHA-256 of the code tokens, without comments, docstrings and layout."""
    docstrings = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            )
            and ast.get_docstring(node, clean=False) is not None
        ):
            first = node.body[0]
            docstrings.add((first.lineno, first.col_offset))
    skipped = {tokenize.COMMENT, tokenize.NL, tokenize.ENCODING}
    parts = [
        # Token names, not numbers: the numbers differ between Python versions.
        f"{tokenize.tok_name[token.type]}:{token.string}"
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type not in skipped
        and not (token.type == tokenize.STRING and token.start in docstrings)
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def current_table() -> dict[str, tuple[tuple[int, ...], str]]:
    table = {}
    for module, owners in sorted(REPLAYED_BY.items()):
        versions = tuple(
            int(importlib.import_module(f"backend.providers.{owner}").MAPPER_VERSION)
            for owner in owners
        )
        source = (PROVIDERS / f"{module}.py").read_text(encoding="utf-8")
        table[module] = (versions, fingerprint(source))
    return table


class MapperVersionGuardTests(unittest.TestCase):
    def test_every_mapping_module_is_registered(self) -> None:
        modules = {path.stem for path in PROVIDERS.glob("*_mapping.py")}
        self.assertEqual(modules, set(REPLAYED_BY) | set(NOT_REPLAYED))

    def test_code_changes_come_with_a_replaying_version_bump(self) -> None:
        for module, (versions, digest) in current_table().items():
            with self.subTest(module=module):
                pinned_versions, pinned_digest = PINNED[module]
                if digest != pinned_digest:
                    self.assertNotEqual(
                        versions,
                        pinned_versions,
                        f"{module} changed without bumping the MAPPER_VERSION of "
                        f"{', '.join(REPLAYED_BY[module])}; bump it so stored "
                        "records replay, then update PINNED",
                    )
                self.assertEqual(
                    (versions, digest),
                    (pinned_versions, pinned_digest),
                    f"update PINNED[{module!r}] to the new version and fingerprint",
                )

    def test_docstring_and_comment_edits_keep_the_fingerprint(self) -> None:
        code = 'def f(x):\n    """Doc."""\n    return x + 1  # note\n'
        edited = 'def f(x):\n    """Other doc."""\n\n    return x + 1\n'
        changed = 'def f(x):\n    """Doc."""\n    return x + 2\n'
        self.assertEqual(fingerprint(code), fingerprint(edited))
        self.assertNotEqual(fingerprint(code), fingerprint(changed))


if __name__ == "__main__":
    for name, row in current_table().items():
        print(f"    {name!r}: {row!r},")
