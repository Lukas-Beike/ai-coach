const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadPublicScript } = require("./frontend-harness.cjs");

const context = loadPublicScript("state-loader.js", { console, document: { scripts: [] } });

test("bootstrap competitions keep the last loaded race result of the same event", () => {
  const loaded = [
    { id: "c-1", event_date: "2026-11-01", result: { duration_s: 2400 } },
    { id: "c-2", event_date: "2026-10-01", result: { duration_s: 3600 } },
  ];
  const bootstrap = [
    { id: "c-1", event_date: "2026-11-01", name: "Edited" },
    { id: "c-2", event_date: "2026-10-08" },
    { id: "c-3", event_date: "2026-09-01" },
  ];
  const merged = JSON.parse(JSON.stringify(context.withLoadedRaceResults(bootstrap, loaded)));
  assert.deepEqual(merged, [
    { id: "c-1", event_date: "2026-11-01", name: "Edited", result: { duration_s: 2400 } },
    { id: "c-2", event_date: "2026-10-08" },
    { id: "c-3", event_date: "2026-09-01" },
  ]);
  assert.equal(context.withLoadedRaceResults(bootstrap, undefined), bootstrap);
});
