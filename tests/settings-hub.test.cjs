const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const {
  CONNECTION_CHIPS,
  connectionsSummaryText,
  connectionKind,
  intervalsConnectionKind,
  yazioConnectionKind,
  garminConnectionKind,
  garminSourceLines,
} = require("../public/connection-status.js");

test("chips are words: connected, not set up, error or not checked", () => {
  assert.deepEqual(Object.values(CONNECTION_CHIPS), ["Verbunden", "Nicht eingerichtet", "Fehler", "Nicht geprüft"]);
  assert.equal(connectionKind({ configured: false, error: true }), "off");
  assert.equal(connectionKind({ configured: true, error: true }), "error");
  assert.equal(connectionKind({ configured: true }), "ok");
  assert.equal(connectionKind({ configured: true, unchecked: true }), "unchecked");
});

test("the section header counts chips instead of listing providers", () => {
  assert.equal(connectionsSummaryText({ ok: 5, error: 1, off: 1 }), "5 verbunden · 1 Fehler · 1 nicht eingerichtet");
  assert.equal(connectionsSummaryText({ ok: 7 }), "7 verbunden");
  assert.equal(connectionsSummaryText({ unchecked: 1 }), "1 nicht geprüft");
  assert.equal(connectionsSummaryText({}), "");
});

test("Intervals.icu and Yazio map their states to chips", () => {
  assert.equal(intervalsConnectionKind({ configured: false, state: "not_configured" }), "off");
  assert.equal(intervalsConnectionKind({ configured: true, state: "configured" }), "unchecked");
  assert.equal(intervalsConnectionKind({ configured: true, state: "error" }), "error");
  assert.equal(intervalsConnectionKind({ configured: true, state: "syncing" }), "ok");
  assert.equal(yazioConnectionKind("success"), "ok");
  assert.equal(yazioConnectionKind("not_configured"), "off");
  assert.equal(yazioConnectionKind("auth_failed"), "error");
  assert.equal(yazioConnectionKind("unchecked"), "unchecked");
  assert.equal(yazioConnectionKind(undefined), "unchecked");
});

test("Garmin is an error for a rejected or expired key, an expiring key stays connected", () => {
  assert.equal(garminConnectionKind({ configured: false }), "off");
  assert.equal(garminConnectionKind({ configured: true, available: false }), "off");
  assert.equal(garminConnectionKind({ configured: true }), "ok");
  assert.equal(garminConnectionKind({ configured: true, last_error: "x" }), "error");
  assert.equal(garminConnectionKind({ configured: true, personal_api: { configured: true, state: "rejected" } }), "error");
  assert.equal(garminConnectionKind({ configured: true, personal_api: { configured: true, state: "expired" } }), "error");
  assert.equal(garminConnectionKind({ configured: true, personal_api: { configured: true, state: "expiring" } }), "ok");
});

test("Garmin names the Personal API key and the SDK login in words", () => {
  assert.deepEqual(garminSourceLines({ configured: true }, true), [
    { label: "Personal API", text: "nicht eingerichtet" },
    { label: "SDK-Login", text: "aktiv" },
  ]);
  assert.deepEqual(garminSourceLines({ personal_api: { configured: true, state: "expired" }, sdk_skipped: { reason: "login_failed" } }, true), [
    { label: "Personal API", text: "abgelaufen" },
    { label: "SDK-Login", text: "erneuern" },
  ]);
  assert.deepEqual(garminSourceLines({ personal_api: { configured: true, state: "valid", expires_on: "2027-02-12" } }, false), [
    { label: "Personal API", text: "gültig bis 2027-02-12" },
    { label: "SDK-Login", text: "nicht eingerichtet" },
  ]);
});

function profileSummaries(profile) {
  const source = fs.readFileSync(path.join(__dirname, "../public/views.js"), "utf8");
  const start = source.indexOf("const PROFILE_SPORT_LABELS");
  const end = source.indexOf("\nfunction renderProfileSummary(", start);
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({});
  vm.runInContext(`${source.slice(start, end)};globalThis.summaries = profileSummaries;`, context);
  return JSON.parse(JSON.stringify(context.summaries(profile)));
}

test("each profile section summarises itself in one line", () => {
  const summaries = profileSummaries({
    name: "Ada",
    sports: "Cycling,Running",
    typical_weekly_volume: "8 h",
    goals: "Ironman 70.3 im September\nDanach Pause",
    training_model: "polarized",
    training_preferences: "Draußen",
    training_preferences_running: "Trail",
    timezone: "Europe/Berlin",
    weather_location: "Münster",
  });
  assert.deepEqual(summaries, {
    profileSummary: "Ada · Radfahren, Laufen",
    profileGoalsSummary: "8 h · Ironman 70.3 im September",
    profileTrainingSummary: "Polarisiert · 2 Präferenzen",
    profileSourcesSummary: "Europe/Berlin · Münster",
  });
});

test("an empty profile says so in every section", () => {
  const summaries = profileSummaries({});
  assert.deepEqual(Object.values(summaries), ["Noch nicht ausgefüllt", "Noch nicht ausgefüllt", "Noch nicht ausgefüllt", "Noch nicht ausgefüllt"]);
});

test("long goals are cut for the one-line summary", () => {
  const summaries = profileSummaries({ goals: "x".repeat(80) });
  assert.equal(summaries.profileGoalsSummary.length, 40);
  assert.ok(summaries.profileGoalsSummary.endsWith("…"));
});
