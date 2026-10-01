const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const { test } = require("node:test");

test("all contracts run on desktop and only responsive contracts repeat on smaller viewports", () => {
  const root = path.resolve(__dirname, "..");
  const report = JSON.parse(execFileSync(process.execPath, [
    require.resolve("@playwright/test/cli"), "test", "--list", "--reporter=json",
  ], { cwd: root, encoding: "utf8" }));
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
