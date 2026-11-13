const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

const PLAN_PUSH = ["runPlanPush", "leftoverEntry", "plannedWeekSyncSummary", "plannedGarminBlockedText", "plannedGarminSdkRequired", "plannedPushTargets", "PLAN_PUSH_MAX_ENTRIES", "plannedWeekSyncJobs", "runPlannedWeekSync", "plannedLeftoverWeek"];
const sent = [];
const context = extractFunctions("plan-views.js", PLAN_PUSH, {
  api: async (url, options) => { sent.push(JSON.parse(options.body)); return { id: JSON.parse(options.body).provider }; },
  // A Wahoo job fails, every other job completes.
  waitForSyncJob: async (id) => ({ id, status: id === "wahoo" ? "failed" : "completed" }),
  providerJobErrorDetail: () => "abgelehnt",
  providerIds: () => ({ intervals: "intervals", garmin: "garmin", wahoo: "wahoo" }),
  focusSport: (entry) => String(entry?.sport || "").toLowerCase() || null,
});

const plain = (value) => JSON.parse(JSON.stringify(value));
const hash = "a".repeat(64);
const ids = { intervals: "intervals", garmin: "garmin", wahoo: "wahoo" };
const unit = { local_id: "u1", payload_hash: hash, push_pending: { intervals: true, garmin: true, wahoo: true } };
const options = { configured: { intervals: true, garmin: true, wahoo: true } };

test("a future unit lists every configured provider it needs", () => {
  assert.deepEqual([...context.plannedPushTargets(unit, "2026-11-10", "2026-11-07", options)], ["garmin", "intervals", "wahoo"]);
  assert.deepEqual([...context.plannedPushTargets({ ...unit, push_pending: { intervals: false, garmin: true } }, "2026-11-07", "2026-11-07", options)], ["garmin"]);
  const garminOff = { ...options, configured: { intervals: true, garmin: false } };
  assert.deepEqual([...context.plannedPushTargets(unit, "2026-11-10", "2026-11-07", garminOff)], ["intervals"]);
});

test("past, completed, synced or unhashed units need no push", () => {
  for (const [entry, day] of [
    [unit, "2026-11-06"],
    [{ ...unit, is_completed_activity: true }, "2026-11-10"],
    [{ ...unit, push_pending: { intervals: false } }, "2026-11-10"],
    [{ ...unit, payload_hash: "" }, "2026-11-10"],
    [{ ...unit, push_pending: undefined }, "2026-11-10"],
  ]) assert.deepEqual([...context.plannedPushTargets(entry, day, "2026-11-07", options)], []);
  // A planned unit already matched to a recorded activity is done.
  assert.deepEqual([...context.plannedPushTargets(unit, "2026-11-07", "2026-11-07", { ...options, completed: true })], []);
  // Without configuration nothing is offered.
  assert.deepEqual([...context.plannedPushTargets(unit, "2026-11-10", "2026-11-07")], []);
});

test("the week's sync sends every waiting unit and removes the week's leftovers, Intervals.icu last", () => {
  const strength = { local_id: "s1", payload_hash: hash, sport: "strength", push_pending: { garmin: true, intervals: true } };
  const ride = { local_id: "r1", payload_hash: hash, sport: "ride", push_pending: { intervals: true } };
  const synced = { local_id: "d1", payload_hash: hash, push_pending: { intervals: false } };
  const past = { local_id: "p1", payload_hash: hash, push_pending: { intervals: true } };
  const units = [
    { entry: strength, dateKey: "2026-11-10" },
    { entry: ride, dateKey: "2026-11-11" },
    { entry: synced, dateKey: "2026-11-11" },
    { entry: past, dateKey: "2026-11-06" },
  ];
  const leftovers = { garmin: [{ id: "old-g" }], intervals: [{ id: "old-i", hash }], wahoo: [{ id: "old-w" }] };
  const jobs = plain(context.plannedWeekSyncJobs(units, leftovers, "2026-11-07", options.configured, ids));
  assert.deepEqual(jobs.map((job) => [job.provider, job.kind, job.entries.map((entry) => entry.library_workout_id)]), [
    ["garmin", "send", ["s1"]],
    ["garmin", "remove", ["old-g"]],
    ["wahoo", "remove", ["old-w"]],
    ["intervals", "send", ["s1", "r1"]],
    ["intervals", "remove", ["old-i"]],
  ]);
  assert.deepEqual(jobs[0].entries[0], { library_workout_id: "s1", expected_payload_hash: hash });
  assert.deepEqual(jobs[1].entries[0], { library_workout_id: "old-g", remove: true });
  assert.deepEqual(jobs[4].entries[0], { library_workout_id: "old-i", expected_payload_hash: hash });
  // A provider that is not configured gets no job; a week with nothing to do gets none at all.
  const intervalsOnly = { intervals: true };
  assert.deepEqual(plain(context.plannedWeekSyncJobs(units, leftovers, "2026-11-07", intervalsOnly, ids)).map((job) => job.provider), ["intervals", "intervals"]);
  assert.deepEqual(plain(context.plannedWeekSyncJobs([{ entry: synced, dateKey: "2026-11-11" }], {}, "2026-11-07", options.configured, ids)), []);
});

test("a large week is split into jobs of at most 28 entries", () => {
  const many = Array.from({ length: 30 }, (_, index) => ({ entry: { local_id: `u${index}`, payload_hash: hash, push_pending: { intervals: true } }, dateKey: "2026-11-10" }));
  const jobs = plain(context.plannedWeekSyncJobs(many, {}, "2026-11-07", { intervals: true }, ids));
  assert.deepEqual(jobs.map((job) => job.entries.length), [28, 2]);
});

test("each leftover belongs to its own week, an earlier or undated one to the current week", () => {
  const weekStart = (day) => ({ "2026-11-04": "2026-11-02", "2026-11-12": "2026-11-09", "2026-11-19": "2026-11-16", "2026-12-24": "2026-12-21" })[day];
  const week = (item) => context.plannedLeftoverWeek(item, "2026-11-09", "2026-12-07", weekStart);
  assert.equal(week({ date: "2026-11-12" }), "2026-11-09");
  assert.equal(week({ date: "2026-11-19" }), "2026-11-16");
  assert.equal(week({ date: "2026-11-04" }), "2026-11-09");
  assert.equal(week({ date: "" }), "2026-11-09");
  // One beyond the shown weeks stays reachable from the last shown week.
  assert.equal(week({ date: "2026-12-24" }), "2026-12-07");
});

test("the toast names what each provider received", () => {
  const done = [
    { provider: "garmin", kind: "send", entries: [{}], units: [{ sport: "strength" }] },
    { provider: "garmin", kind: "remove", entries: [{}, {}], units: [] },
    { provider: "intervals", kind: "send", entries: [{}, {}], units: [{ sport: "strength" }, { sport: "ride" }] },
  ];
  const label = (provider) => ({ garmin: "Garmin", intervals: "Intervals.icu" })[provider];
  // Strength reaches Intervals.icu only as a calendar note, never the watch.
  assert.equal(context.plannedWeekSyncSummary(done, ids, label), "Garmin: 1 strukturiert, 2 alte entfernt · Intervals.icu: 2 gesendet, davon 1 als Notiz");
});

test("a strength unit says why it was not sent to Garmin", () => {
  assert.equal(context.plannedGarminBlockedText({ push_blocked: { garmin: "no_structure" } }), "Keine Kraftstruktur – nicht an Garmin gesendet");
  assert.equal(context.plannedGarminBlockedText({ push_blocked: { garmin: "unmapped" } }), "Übung ohne Garmin-Zuordnung – nicht an Garmin gesendet");
  assert.equal(context.plannedGarminBlockedText({ push_blocked: {} }), "");
  assert.equal(context.plannedGarminBlockedText({}), "");
});

test("a Garmin unit needs the SDK login: with the Personal API key alone the notice replaces the push", () => {
  const waiting = { push_pending: { garmin: true } };
  const personalOnly = { configured: true, can_write_workouts: false };
  assert.equal(context.plannedGarminSdkRequired(waiting, personalOnly), true);
  assert.equal(context.plannedGarminSdkRequired({ push_pending: { garmin: false } }, personalOnly), false);
  assert.equal(context.plannedGarminSdkRequired({ push_pending: { intervals: true } }, personalOnly), false);
  assert.equal(context.plannedGarminSdkRequired(waiting, { configured: true, can_write_workouts: true }), false);
  assert.equal(context.plannedGarminSdkRequired(waiting, { configured: false, can_write_workouts: false }), false);
  assert.equal(context.plannedGarminSdkRequired(waiting, undefined), false);
});

test("a push job carries its entries; a leftover is removed by the entry its provider understands", async () => {
  await context.runPlanPush("garmin", [{ library_workout_id: "u1", expected_payload_hash: hash }]);
  assert.deepEqual(sent[0], { provider: "garmin", type: "plan_push", payload: { entries: [{ library_workout_id: "u1", expected_payload_hash: hash }] } });
  assert.deepEqual(plain(context.leftoverEntry("garmin", { id: "old-1", hash }, ids)), { library_workout_id: "old-1", remove: true });
  // A Wahoo plan of a deleted library entry is removed the same way.
  assert.deepEqual(plain(context.leftoverEntry("wahoo", { id: "old-2" }, ids)), { library_workout_id: "old-2", remove: true });
  assert.deepEqual(plain(context.leftoverEntry("intervals", { id: "old-3", hash }, ids)), { library_workout_id: "old-3", expected_payload_hash: hash });
});

test("a week's sync runs every job, reports failures first and keeps going after one", async () => {
  sent.length = 0;
  const label = (provider) => ({ garmin: "Garmin", intervals: "Intervals.icu", wahoo: "Wahoo" })[provider];
  const jobs = [
    { provider: "garmin", kind: "send", entries: [{ library_workout_id: "s1" }], units: [{ sport: "strength" }] },
    { provider: "wahoo", kind: "remove", entries: [{ library_workout_id: "old-w", remove: true }], units: [] },
    { provider: "intervals", kind: "send", entries: [{ library_workout_id: "r1" }], units: [{ sport: "ride" }] },
  ];
  const outcome = plain(await context.runPlannedWeekSync(jobs, ids, label));
  assert.deepEqual(sent.map((body) => body.provider), ["garmin", "wahoo", "intervals"]);
  assert.deepEqual(outcome, {
    failed: true,
    message: "Wahoo: Alte Einträge nicht entfernt: abgelehnt · Garmin: 1 strukturiert · Intervals.icu: 1 gesendet",
  });
});

test("a partial job still names what arrived, and a strength unit without a Garmin workout says why", async () => {
  const partial = extractFunctions("plan-views.js", PLAN_PUSH, {
    api: async () => ({ id: "job-2" }),
    waitForSyncJob: async (id) => ({ id, status: "partial", items: [{ item_key: "r1", status: "completed" }, { item_key: "s1", status: "failed" }] }),
    providerJobErrorDetail: () => "Seit der Vorschau geändert",
    focusSport: (entry) => String(entry?.sport || "").toLowerCase() || null,
  });
  const label = (provider) => ({ garmin: "Garmin", intervals: "Intervals.icu" })[provider];
  const units = [{ local_id: "s1", sport: "strength" }, { local_id: "r1", sport: "ride" }];
  const jobs = [{ provider: "intervals", kind: "send", entries: [{ library_workout_id: "s1" }, { library_workout_id: "r1" }], units, items: [] }];
  assert.deepEqual(plain(await partial.runPlannedWeekSync(jobs, ids, label)), {
    failed: true,
    message: "Intervals.icu: Seit der Vorschau geändert · Intervals.icu: 1 gesendet",
  });
  const blocked = [{ provider: "intervals", kind: "send", entries: [{}], units: [{ sport: "strength", push_blocked: { garmin: "no_structure" } }] }];
  assert.equal(partial.plannedWeekSyncSummary(blocked, ids, label), "Intervals.icu: 1 gesendet, davon 1 als Notiz · Keine Kraftstruktur – nicht an Garmin gesendet");
});
