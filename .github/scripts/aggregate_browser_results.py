"""Fail closed unless every declared browser shard supplies complete evidence."""

import argparse
import json
import re
from pathlib import Path


def identity(item):
    return item["project"], item["id"]


def validate_shard(manifest, expected, required, seen):
    selection = manifest["selection"]
    project, shard, total = (
        selection["project"],
        selection["shard"],
        selection["total"],
    )
    key = project, shard
    if (
        type(shard) is not int
        or type(total) is not int
        or key not in required
        or key in seen
        or total != expected[project]
        or selection["specs"]
    ):
        raise ValueError("Unexpected, duplicate, or focused browser shard")
    seen.add(key)
    if (
        manifest["version"] != 1
        or manifest["status"] != "passed"
        or manifest["exit_code"] != 0
    ):
        raise ValueError("Browser shard failed or did not finish")
    return project, key


def validate_source(manifest, previous):
    revision = manifest["source"]["revision"]
    timing = manifest["inputs"]["e2e/browser_durations.json"]
    if not re.fullmatch(r"[a-f0-9]{40}", revision) or not re.fullmatch(
        r"[a-f0-9]{64}", timing
    ):
        raise ValueError("Missing source or frozen duration identity")
    current = revision, timing
    if previous is not None and previous != current:
        raise ValueError("Browser shards used different source or timing inputs")
    return current


def validate_expected(selection, project, selections):
    promised_keys = [identity(item) for item in selection["expected_identities"]]
    if (
        not promised_keys
        or len(promised_keys) != len(set(promised_keys))
        or any(item[0] != project for item in promised_keys)
    ):
        raise ValueError("Invalid complete project selection")
    promised = set(promised_keys)
    if project in selections and selections[project] != promised:
        raise ValueError("Shards disagree on complete project selection")
    selections[project] = promised


def collect_children(manifest, project, key, files, actual):
    children = manifest["children"]
    if not children:
        raise ValueError("Empty browser shard")
    for child in children:
        if (
            child["status"] != "passed"
            or child["exit_code"] != 0
            or child["project"] != project
        ):
            raise ValueError("A browser child failed or did not finish")
        file_key = project, child["file"]
        if file_key in files:
            raise ValueError("Browser file assigned more than once")
        files[file_key] = key
        child_ids = child["identities"]
        if not child_ids or any(
            item["project"] != project or item["file"] != child["file"]
            for item in child_ids
        ):
            raise ValueError("Invalid browser child identities")
        actual.setdefault(project, []).extend(identity(item) for item in child_ids)


def verify(directory, expected):
    manifests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in directory.rglob("manifest.json")
    ]
    required = {
        (project, shard)
        for project, total in expected.items()
        for shard in range(1, total + 1)
    }
    if len(manifests) != len(required):
        raise ValueError("Missing or extra browser shard manifests")
    seen, source = set(), None
    selections, actual, files = {}, {}, {}
    for manifest in manifests:
        project, key = validate_shard(manifest, expected, required, seen)
        source = validate_source(manifest, source)
        validate_expected(manifest["selection"], project, selections)
        collect_children(manifest, project, key, files, actual)
    if seen != required:
        raise ValueError("Missing browser shard")
    for project, promised in selections.items():
        observed = actual.get(project, [])
        if len(observed) != len(set(observed)) or set(observed) != promised:
            raise ValueError("Browser selection was duplicated or incomplete")
    return {project: len(items) for project, items in sorted(selections.items())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument(
        "--expected", required=True, action="append", metavar="PROJECT:SHARDS"
    )
    args = parser.parse_args()
    try:
        expected = {}
        for item in args.expected:
            project, total = item.split(":")
            if project in expected or int(total) < 1:
                raise ValueError("Invalid expected matrix")
            expected[project] = int(total)
        print(json.dumps(verify(args.results, expected), sort_keys=True))
    except OSError, ValueError, KeyError, TypeError:
        parser.exit(
            1, "Browser evidence is missing, failed, inconsistent, or incomplete.\n"
        )


if __name__ == "__main__":
    main()
