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
const options = { configured: { intervals: true, garmin: true, wahoo: true } };

test("a future unit lists every configured provider it needs", () => {
  assert.deepEqual([...context.targets(unit, "2026-11-10", "2026-11-07", options)], ["garmin", "intervals", "wahoo"]);
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

const labelStart = source.indexOf("function plannedPushTargetLabel");
const labelEnd = source.indexOf("// Providers this planned unit", labelStart);
const labels = vm.createContext({ focusSport: (entry) => String(entry?.sport || "").toLowerCase() || null });
vm.runInContext(source.slice(labelStart, labelEnd) + ";globalThis.label = plannedPushTargetLabel; globalThis.blocked = plannedGarminBlockedText;", labels);
const ids = { intervals: "intervals", garmin: "garmin" };

test("the toast names what each target received", () => {
  assert.equal(labels.label("garmin", { sport: "strength" }, ids), "Garmin: strukturiert");
  // Strength reaches Intervals.icu only as a calendar note, never the watch.
  assert.equal(labels.label("intervals", { sport: "strength" }, ids), "Intervals.icu: Notiz");
  assert.equal(labels.label("intervals", { sport: "run" }, ids), "Intervals.icu");
});

test("a strength unit says why it was not sent to Garmin", () => {
  assert.equal(labels.blocked({ push_blocked: { garmin: "no_structure" } }), "Keine Kraftstruktur – nicht an Garmin gesendet");
  assert.equal(labels.blocked({ push_blocked: { garmin: "unmapped" } }), "Übung ohne Garmin-Zuordnung – nicht an Garmin gesendet");
  assert.equal(labels.blocked({ push_blocked: {} }), "");
  assert.equal(labels.blocked({}), "");
});

const pushStart = source.indexOf("async function runPlanPush");
const pushEnd = source.indexOf("// What one successful push delivered", pushStart);
const sent = [];
const pushContext = vm.createContext({
  api: async (url, options) => { sent.push(JSON.parse(options.body)); return { id: "job-1" }; },
  waitForSyncJob: async (id) => ({ id, status: "completed" }),
});
vm.runInContext(source.slice(pushStart, pushEnd) + ";globalThis.run = runPlanPush; globalThis.leftover = leftoverEntry;", pushContext);

test("a push job carries its entries; a leftover is removed by the entry its provider understands", async () => {
  const hash = "a".repeat(64);
  await pushContext.run("garmin", [{ library_workout_id: "u1", expected_payload_hash: hash }]);
  assert.deepEqual(sent[0], { provider: "garmin", type: "plan_push", payload: { entries: [{ library_workout_id: "u1", expected_payload_hash: hash }] } });
  assert.deepEqual({ ...pushContext.leftover("garmin", { id: "old-1", hash }, ids) }, { library_workout_id: "old-1", remove: true });
  assert.deepEqual({ ...pushContext.leftover("intervals", { id: "old-3", hash }, ids) }, { library_workout_id: "old-3", expected_payload_hash: hash });
});
