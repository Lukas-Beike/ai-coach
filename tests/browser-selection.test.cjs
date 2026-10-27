const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const { test } = require("node:test");

const root = path.resolve(__dirname, "..");
const cli = require.resolve("@playwright/test/cli");
let cachedReport;
function listing(arguments = []) {
  if (arguments.length === 0 && cachedReport) return cachedReport;
  const report = JSON.parse(execFileSync(process.execPath, [
    cli, "test", ...arguments, "--list", "--reporter=json",
  ], { cwd: root, encoding: "utf8" }));
  assert.deepEqual(report.errors, []);
  if (arguments.length === 0) cachedReport = report;
  return report;
}

test("all contracts run on desktop and only responsive contracts repeat on smaller viewports", () => {
  const report = listing();
  assert.deepEqual(report.errors, []);
  const counts = new Map();
  const selected = new Map();
  function check(suite) {
    for (const spec of suite.specs || []) {
      const key = `${spec.file}:${spec.line}:${spec.title}`;
      const entry = selected.get(key) || { responsive: spec.tags.includes("responsive"), projects: [] };
      entry.projects.push(...spec.tests.map((item) => item.projectName));
      selected.set(key, entry);
    }
    for (const child of suite.suites || []) check(child);
  }
  for (const suite of report.suites) check(suite);
  for (const [key, { responsive, projects }] of selected) {
    assert.deepEqual(projects.sort(), responsive
      ? ["desktop", "mobile", "mobile-small", "tablet", "tablet-landscape"]
      : ["desktop"], key);
    counts.set(responsive, (counts.get(responsive) || 0) + 1);
  }
  assert.ok(counts.get(true) > 0, "responsive coverage must remain selected");
  assert.ok(counts.get(false) > 0, "functional contracts must not repeat");
});

test("locked runner preserves all discovered identities, whole-file shards, and exact prepared spec filters", () => {
  const report = listing();
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ai-coach-browser-selection-"));
  try {
    // One real runner discovery; reuse the cached CLI report for every partition.
    const value = JSON.parse(execFileSync(process.env.PYTHON || "python", ["-c", `
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest import mock

root = Path.cwd()
spec = importlib.util.spec_from_file_location("browser_runner", root / "scripts/run_browser_tests.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
listing = runner.parse_listing(json.load(sys.stdin))
output = io.StringIO()
with contextlib.redirect_stdout(output):
    code = runner.main(["--project", "all", "--list", "--results-dir", sys.argv[1]])
if code:
    raise SystemExit(code)
baseline = json.loads(output.getvalue())
timing = runner.read_weights(root / "e2e/browser_durations.json")
partitions = [
    {"project": project, "shard": shard,
     "children": runner.select(listing, project, [], shard, 2, timing)}
    for project in sorted({child["project"] for child in baseline["children"]})
    for shard in (1, 2)
]
args = runner.parser().parse_args(["--project", "desktop", "--browser-image", "synthetic-image"])
containers = mock.Mock(run_id="selection")
containers.create.return_value = "a" * 64
execute = runner.Execution(root, args, None, None, containers, Path(sys.argv[1]),
                           "app-image", {"id": "browser-image-id"}, "synthetic-node", "synthetic-cli")
first = next(child for child in baseline["children"] if child["project"] == "desktop")
files = sorted({first["file"], "e2e/contracts.spec.js", "e2e/css-cascade.spec.js"})
commands = []
for file in files:
    child = runner.select(listing, "desktop", [file], 1, 1, timing)[0]
    with (mock.patch.object(runner.os, "getuid", return_value=1000, create=True),
          mock.patch.object(runner.os, "getgid", return_value=1000, create=True)):
        execute.browser_command(child, 9100, Path(sys.argv[1]) / "results", Path(sys.argv[1]) / "private")
    creation = containers.create.call_args.args[1]
    commands.append({"child": child, "arguments": creation[creation.index("browser-image-id") + 3:]})
print(json.dumps({"baseline": baseline, "partitions": partitions, "commands": commands}))
`, directory], {
      cwd: root, input: JSON.stringify(report), encoding: "utf8", maxBuffer: 16 * 1024 * 1024,
    }));

    function reportIdentities(suite) {
      return [
        ...(suite.specs || []).flatMap((spec) => spec.tests.map((item) => ({
          id: spec.id, project: item.projectName, project_id: item.projectId,
          file: spec.file.startsWith("e2e/") ? spec.file : `e2e/${spec.file}`,
          line: spec.line, title: spec.title,
        }))),
        ...(suite.suites || []).flatMap(reportIdentities),
      ];
    }
    const key = (identity) => JSON.stringify([
      identity.id, identity.project, identity.project_id,
      identity.file, identity.line, identity.title,
    ]);
    const keys = (identities) => identities.map(key).sort();
    const childIdentities = (children) => children.flatMap((child) => child.identities);
    const expected = report.suites.flatMap(reportIdentities);
    assert.ok(expected.length > 0);
    const baseline = value.baseline;
    assert.equal(baseline.selection.mode, "complete");
    assert.deepEqual(keys(baseline.selection.expected_identities), keys(expected));
    assert.deepEqual(keys(childIdentities(baseline.children)), keys(expected));
    const projects = ["desktop", "mobile", "mobile-small", "tablet", "tablet-landscape"];
    assert.deepEqual([...new Set(baseline.children.map((child) => child.project))].sort(), projects);
    assert.equal(value.partitions.length, 10);
    const combined = value.partitions.flatMap((partition) => partition.children);
    assert.deepEqual(keys(childIdentities(combined)), keys(expected));
    assert.equal(new Set(keys(childIdentities(combined))).size, expected.length);
    assert.equal(new Set(combined.map((child) => `${child.project}:${child.file}`)).size, combined.length);
    for (const project of projects) {
      const partitions = value.partitions.filter((partition) => partition.project === project);
      assert.deepEqual(partitions.map((partition) => partition.shard), [1, 2]);
      assert.deepEqual(keys(childIdentities(partitions.flatMap((partition) => partition.children))),
        keys(expected.filter((identity) => identity.project === project)));
    }
    assert.ok(value.commands.some(({ child }) => child.file === "e2e/contracts.spec.js"));
    assert.ok(value.commands.some(({ child }) => child.file === "e2e/css-cascade.spec.js"));
    for (const { child, arguments: command } of value.commands) {
      assert.ok(command.includes("--workers=1"));
      assert.ok(command.includes("--trace=off"));
      const observed = listing(command.slice(1)).suites.flatMap(reportIdentities);
      assert.deepEqual(keys(observed), keys(child.identities), child.file);
      assert.ok(observed.every((identity) => identity.file === child.file && identity.project === "desktop"));
    }
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
