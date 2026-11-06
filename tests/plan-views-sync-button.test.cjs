const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/plan-views.js"), "utf8");
const start = source.indexOf("function plannedPushTargets");
const end = source.indexOf("const CALENDAR_MARKERS", start);
const context = vm.createContext({});
vm.runInContext(source.slice(start, end) + ";globalThis.targets = plannedPushTargets;", context);

const unit = { local_id: "u1", payload_hash: "a".repeat(64), push_pending: { intervals: true, garmin: true, wahoo: true } };
const options = { configured: { intervals: true, garmin: true, wahoo: true }, intervals: "intervals" };

test("a future unit lists every configured provider it needs, Intervals.icu last", () => {
  assert.deepEqual([...context.targets(unit, "2026-11-10", "2026-11-07", options)], ["garmin", "wahoo", "intervals"]);
  assert.deepEqual([...context.targets({ ...unit, push_pending: { intervals: false, garmin: true } }, "2026-11-07", "2026-11-07", options)], ["garmin"]);
  const garminOff = { ...options, configured: { intervals: true, garmin: false } };
  assert.deepEqual([...context.targets(unit, "2026-11-10", "2026-11-07", garminOff)], ["intervals"]);
});

test("past, completed, synced or unhashed units show no button", () => {
  for (const [entry, day] of [
    [unit, "2026-11-06"],
    [{ ...unit, is_completed_activity: true }, "2026-11-10"],
    [{ ...unit, push_pending: { intervals: false } }, "2026-11-10"],
    [{ ...unit, payload_hash: "" }, "2026-11-10"],
    [{ ...unit, push_pending: undefined }, "2026-11-10"],
  ]) assert.deepEqual([...context.targets(entry, day, "2026-11-07", options)], []);
  // A planned unit already matched to a recorded activity is done.
  assert.deepEqual([...context.targets(unit, "2026-11-07", "2026-11-07", { ...options, completed: true })], []);
  // Without configuration nothing is offered.
  assert.deepEqual([...context.targets(unit, "2026-11-10", "2026-11-07")], []);
});
