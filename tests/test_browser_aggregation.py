"""The CI gate must reject incomplete, duplicate, or mismatched browser evidence."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "browser_aggregate",
    Path(__file__).resolve().parents[1]
    / ".github/scripts/aggregate_browser_results.py",
)
assert SPEC is not None and SPEC.loader is not None
aggregate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(aggregate)


class BrowserAggregationTests(unittest.TestCase):
    def manifests(self):
        identities = [
            {"id": str(i), "project": "desktop", "file": f"e2e/spec-{i}.spec.js"}
            for i in (1, 2)
        ]
        return [
            {
                "version": 1,
                "status": "passed",
                "exit_code": 0,
                "source": {"revision": "a" * 40},
                "inputs": {"e2e/browser_durations.json": "b" * 64},
                "selection": {
                    "project": "desktop",
                    "shard": i,
                    "total": 2,
                    "specs": [],
                    "expected_identities": identities,
                },
                "children": [
                    {
                        "project": "desktop",
                        "file": identities[i - 1]["file"],
                        "identities": [copy.deepcopy(identities[i - 1])],
                        "status": "passed",
                        "exit_code": 0,
                    }
                ],
            }
            for i in (1, 2)
        ]

    def verify(self, manifests, expected=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, manifest in enumerate(manifests):
                directory = root / str(index)
                directory.mkdir()
                (directory / "manifest.json").write_text(
                    json.dumps(manifest), encoding="utf-8"
                )
            return aggregate.verify(root, expected or {"desktop": 2})

    def test_exact_complete_union_passes(self):
        self.assertEqual(self.verify(self.manifests()), {"desktop": 2})

    def test_trial_ten_shard_matrix_requires_every_project_and_shard(self):
        expected = dict.fromkeys(
            ("desktop", "mobile", "mobile-small", "tablet", "tablet-landscape"), 2
        )
        manifests = []
        for project in expected:
            for manifest in copy.deepcopy(self.manifests()):
                manifest["selection"]["project"] = project
                for item in manifest["selection"]["expected_identities"]:
                    item["project"] = project
                for child in manifest["children"]:
                    child["project"] = project
                    for item in child["identities"]:
                        item["project"] = project
                manifests.append(manifest)
        self.assertEqual(self.verify(manifests, expected), expected)
        for index in range(len(manifests)):
            with self.subTest(missing=index), self.assertRaises(ValueError):
                self.verify(manifests[:index] + manifests[index + 1 :], expected)
            failed = copy.deepcopy(manifests)
            failed[index]["status"] = "incomplete"
            with self.subTest(incomplete=index), self.assertRaises(ValueError):
                self.verify(failed, expected)

    def test_missing_duplicate_and_extra_shards_fail(self):
        manifests = self.manifests()
        for broken in (
            manifests[:1],
            [manifests[0], manifests[0]],
            [*manifests, manifests[0]],
        ):
            with self.subTest(count=len(broken)), self.assertRaises(ValueError):
                self.verify(broken)

    def test_failed_interrupted_and_pending_results_cannot_pass(self):
        for status in ("failed", "interrupted", "incomplete", "listed"):
            manifests = self.manifests()
            manifests[1]["status"] = status
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.verify(manifests)
        manifests = self.manifests()
        manifests[1]["children"][0]["status"] = "pending"
        with self.assertRaises(ValueError):
            self.verify(manifests)

    def test_changed_source_or_frozen_weights_fail(self):
        for owner, field in (
            ("source", "revision"),
            ("inputs", "e2e/browser_durations.json"),
        ):
            manifests = self.manifests()
            manifests[1][owner][field] = "c" * len(manifests[1][owner][field])
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(manifests)

    def test_focused_or_wrong_matrix_cannot_claim_complete_validation(self):
        for changes in (
            {"specs": ["e2e/one.spec.js"]},
            {"total": 3},
            {"project": "unknown"},
        ):
            manifests = self.manifests()
            manifests[1]["selection"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.verify(manifests)

    def test_changed_or_omitted_identity_fails(self):
        manifests = self.manifests()
        manifests[1]["children"][0]["identities"][0]["id"] = "absent"
        with self.assertRaises(ValueError):
            self.verify(manifests)
        manifests = self.manifests()
        manifests[1]["children"] = []
        with self.assertRaises(ValueError):
            self.verify(manifests)

    def test_split_file_and_disagreeing_expected_selections_fail(self):
        manifests = self.manifests()
        manifests[1]["children"][0]["file"] = manifests[0]["children"][0]["file"]
        with self.assertRaises(ValueError):
            self.verify(manifests)
        manifests = copy.deepcopy(self.manifests())
        manifests[1]["selection"]["expected_identities"] = manifests[1]["selection"][
            "expected_identities"
        ][:1]
        with self.assertRaises(ValueError):
            self.verify(manifests)
