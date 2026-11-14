"""A mapper's code cannot change without the version that replays it (#1672).

Stored provider records are re-projected only when the version of their mapper
changes. Sub-mappers have no version of their own: they ride on the version of
the mapper that calls them. This guard pins a fingerprint of every mapping
module's code, and of every backend/providers or backend/canonical module a
replayed mapper imports (directly or through another such module, #2501),
together with the versions that replay it. Changing the code without bumping
one of those versions fails here. Widely shared canonical modules such as
vocabulary are pinned too: a change that maps nothing differently (a new enum
member) only updates the fingerprint.

The fingerprint ignores comments, docstrings and layout, so documentation edits
pass. When a code change does not alter any mapped output (a pure refactor),
update the fingerprint and say so in the PR; otherwise bump the version first.
Run this module to print the current table.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import importlib
import io
import tokenize
import unittest
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ROOT / "backend" / "providers"
CANONICAL = "canonical."

# Mapping module -> the modules whose MAPPER_VERSION replays its output.
REPLAYED_BY: Final[dict[str, tuple[str, ...]]] = {
    "fit_activity_detail_mapping": (
        "fit_activity_detail_mapping",
        "garmin_activity_detail_mapping",
    ),
    "fit_rr_mapping": (
        "fit_activity_detail_mapping",
        "garmin_activity_detail_mapping",
    ),
    "fit_sensor_mapping": (
        "fit_activity_detail_mapping",
        "garmin_activity_detail_mapping",
    ),
    "garmin_activity_detail_mapping": ("garmin_activity_detail_mapping",),
    "garmin_activity_mapping": ("garmin_activity_mapping",),
    "garmin_gear_mapping": ("garmin_health_mapping",),
    "garmin_health_mapping": ("garmin_health_mapping",),
    "garmin_status_mapping": ("garmin_health_mapping",),
    "garmin_zone_mapping": ("garmin_health_mapping",),
    "garmin_training_mapping": ("garmin_health_mapping",),
    "sleep_period_mapping": ("garmin_health_mapping",),
    # garmin_activity_mapping uses wahoo_device_type for relayed Wahoo rides.
    "wahoo_activity_mapping": ("wahoo_activity_mapping", "garmin_activity_mapping"),
    "wahoo_threshold_mapping": ("wahoo_threshold_mapping",),
}
# Mapping modules that project nothing that is stored and replayed.
NOT_REPLAYED: Final[dict[str, str]] = {
    "wahoo_plan_mapping": "outbound: builds Wahoo plan payloads for export",
}
# Module -> (replaying versions, code fingerprint).
PINNED: Final[dict[str, tuple[tuple[int, ...], str]]] = {
    "canonical.activity_detail": (
        (9, 10),
        "4bbe2f0504dbb54e038e81fe8f323245fab24f45b6f7d61d55bbdc5bd64bc5e2",
    ),
    "canonical.decimal_text": (
        (9, 10, 21, 23, 8, 2),
        "fe45d029fb3c059900543f140a5715de91421a68f6226ddfb1f9d4a093edaaa6",
    ),
    "canonical.dfa_alpha1": (
        (9, 10),
        "3057e5bd8fb86e99bd00be2b17914438dc2c7af18559d983ec1909a753439cdf",
    ),
    "canonical.domain_records": (
        (23,),
        "aa1376a854a6b040e304d690004ce1b779bf5c234071748603764f3a77f25271",
    ),
    "canonical.local_time": (
        (9, 10, 21, 23, 8, 2),
        "bb8d2cace6846fc1f0f57aa0cc04ee9561fb8603105cb65f337204eece611886",
    ),
    "canonical.mapping": (
        (9, 10, 21, 23, 8, 2),
        "ce31fc467c34d7276223455adccf24557ed633520a1c849051216c23d0549359",
    ),
    "canonical.records": (
        (9, 10, 21, 23, 8, 2),
        "ca06ef248ed891b0643a14c08469268a974fd84a313389e6faa48fbc59a9e26d",
    ),
    "canonical.sleep_bounds": (
        (23,),
        "a18b7a440cdfb7ba0d03909e5d28cc843a99fc962d73383d8f4905084022884c",
    ),
    "canonical.sports": (
        (10, 21),
        "223eb5ca42399100cccd4093e4ec74e042986f3cd34c71022651e794bba0df66",
    ),
    "canonical.validation": (
        (9, 10, 21, 23, 8, 2),
        "f1b07b7ef7b107fe73184807c1cd0c729d0371fd6c8e13951aca589786dfa9d8",
    ),
    "canonical.vocabulary": (
        (9, 10, 21, 23, 8, 2),
        "fa8db208b0b0bae1fe7e6fd238ba5b5522a22b484125e4c5136da54c57577754",
    ),
    "fit_activity_detail_mapping": (
        (9, 10),
        "f7fc2667529631b41c1146091f8e7566a0d287c73baecd5267f6fff7d09dba26",
    ),
    "fit_file": (
        (9, 10),
        "fb27149c7f770bae44b8a485dbcb3f1d2aaeff7c25cd4006c89fc825fc625b11",
    ),
    "fit_rr_mapping": (
        (9, 10),
        "4319aab924017281cffb92b24b53fa67ed8633d747b55e9f61f57b58821c6981",
    ),
    "fit_sensor_mapping": (
        (9, 10),
        "0bc6dc6a5828641940f851dc9a2c4d6362d1b53d7f0f66d412f1f0ebdcbe71f6",
    ),
    "garmin_activity_detail_mapping": (
        (10,),
        "0ab0623a3230c7528265cc524ba235d7bd48f996a8e9b7996ead4ae2c3dfb2ac",
    ),
    "garmin_activity_mapping": (
        (21,),
        "adb059dae3b2103933de835f3cec94d2abf0a2e9d76e2898d394f1b015a27f8b",
    ),
    "garmin_device_records": (
        (23,),
        "68ecba9d45e93b4ec7d4427cca42a212b43e921f264960cdb532f67b192cce66",
    ),
    "garmin_fields": (
        (23,),
        "0091aa0ad891d7b0fe6d7e2dd90d3003c19dce4dc01f5509b0ba66a268bbb9ab",
    ),
    "garmin_gear_mapping": (
        (23,),
        "b53d3b960450b21475f4f86a73c6be8ecd3d182afa0b73ed3055b535482d9028",
    ),
    "garmin_health_mapping": (
        (23,),
        "724b2bcc1dd72694b7d5c5805a985036b590a45ee93fe7bbfe2ff405d71a9544",
    ),
    "garmin_performance_fields": (
        (23,),
        "6762077b0617cbc1ead19f39a298a29458d6647c2c7d2f391b76b54f55e1eec4",
    ),
    "garmin_status_mapping": (
        (23,),
        "5da9d6874214b0b966721bd1cdd155ffdb64dcc247c79db92c11739b112a1f96",
    ),
    "garmin_training_mapping": (
        (23,),
        "39bfa63cd233c003f99a41fdd5eaac447bfc9373f3b13dda2084e7778e93aaa7",
    ),
    "garmin_weight_walk": (
        (23,),
        "8f795a850ba38fc4c15ea53623ecdca84e34a3ca7760f9c4379462b51372ed9d",
    ),
    "garmin_zone_mapping": (
        (23,),
        "b06dffd17d1c09036a5ef7c1aab7695d56f0d5d8e2e4616238afc4a5f21dfeee",
    ),
    "sleep_period_mapping": (
        (23,),
        "77efab15de0cda5414ed02c0d5005a9fe6fb1a650ec103bdb40e01cef065cf0f",
    ),
    "wahoo_activity_mapping": (
        (8, 21),
        "9b74c3dca726d23d18e782b7dd8f351572a6a24c2230187db13a5cb5ba181312",
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


def module_path(module: str) -> Path:
    """Source of a provider module, or of a ``canonical.<name>`` module."""
    if module.startswith(CANONICAL):
        return ROOT / "backend" / "canonical" / f"{module.removeprefix(CANONICAL)}.py"
    return PROVIDERS / f"{module}.py"


@functools.cache
def backend_imports(module: str) -> set[str]:
    """The backend.providers and ``canonical.<name>`` modules ``module`` imports."""
    package = ["backend", "canonical" if module.startswith(CANONICAL) else "providers"]
    dotted: list[str] = []
    for node in ast.walk(ast.parse(module_path(module).read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            # A relative import resolves from the importing module's package.
            parent = package[: len(package) + 1 - node.level] if node.level else []
            base = ".".join(parent + (node.module or "").split(".")).strip(".")
            dotted += [f"{base}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Import):
            dotted += [alias.name for alias in node.names]
    names = {
        (CANONICAL if parts[1] == "canonical" else "") + parts[2]
        for parts in (name.split(".") for name in dotted)
        if len(parts) > 2
        and parts[0] == "backend"
        and parts[1] in ("canonical", "providers")
    }
    return {name for name in names if module_path(name).is_file()}


def helper_replayed_by() -> dict[str, tuple[str, ...]]:
    """Helper module -> the versions replaying every mapper that reaches it,
    also through a sub-mapper it calls."""
    owners: dict[str, set[str]] = {}
    for mapping, replaying in REPLAYED_BY.items():
        pending, seen = [mapping], {mapping}
        while pending:
            for name in backend_imports(pending.pop()) - seen:
                seen.add(name)
                pending.append(name)
        for helper in seen:
            # Registered mappers carry their own replaying versions.
            if helper not in REPLAYED_BY:
                owners.setdefault(helper, set()).update(replaying)
    return {helper: tuple(sorted(found)) for helper, found in owners.items()}


def replayed_by() -> dict[str, tuple[str, ...]]:
    return {**REPLAYED_BY, **helper_replayed_by()}


def current_table() -> dict[str, tuple[tuple[int, ...], str]]:
    table = {}
    for module, owners in sorted(replayed_by().items()):
        versions = tuple(
            int(importlib.import_module(f"backend.providers.{owner}").MAPPER_VERSION)
            for owner in owners
        )
        source = module_path(module).read_text(encoding="utf-8")
        table[module] = (versions, fingerprint(source))
    return table


class MapperVersionGuardTests(unittest.TestCase):
    def test_every_mapping_module_is_registered(self) -> None:
        modules = {path.stem for path in PROVIDERS.glob("*_mapping.py")}
        self.assertEqual(modules, set(REPLAYED_BY) | set(NOT_REPLAYED))
        # Every mapper and every provider or canonical module it reaches,
        # also through another one, is pinned (#2484, #2501).
        self.assertEqual(set(PINNED), set(replayed_by()))
        helpers = helper_replayed_by()
        detail = ("fit_activity_detail_mapping", "garmin_activity_detail_mapping")
        for module, owners in (
            ("garmin_weight_walk", ("garmin_health_mapping",)),
            ("canonical.sleep_bounds", ("garmin_health_mapping",)),
            ("canonical.dfa_alpha1", detail),
            ("canonical.activity_detail", detail),
        ):
            with self.subTest(module=module):
                self.assertEqual(helpers[module], owners)

    def test_code_changes_come_with_a_replaying_version_bump(self) -> None:
        owners = replayed_by()
        for module, (versions, digest) in current_table().items():
            with self.subTest(module=module):
                pinned_versions, pinned_digest = PINNED[module]
                if digest != pinned_digest:
                    # Every replaying version, not just one: each projects it.
                    self.assertEqual(
                        len(versions),
                        len(pinned_versions),
                        f"{module} changed together with its replaying mappers; "
                        "bump every one of them, then update PINNED",
                    )
                    unbumped = [
                        owner
                        for owner, now, pinned in zip(
                            owners[module], versions, pinned_versions, strict=True
                        )
                        if now == pinned
                    ]
                    self.assertEqual(
                        unbumped,
                        [],
                        f"{module} changed without bumping the MAPPER_VERSION of "
                        f"{', '.join(unbumped)}; bump each so stored records "
                        "replay, then update PINNED (a change that maps nothing "
                        "differently only updates the fingerprint)",
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
