const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");
const {
  CONNECTION_CHIPS,
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
  const context = extractFunctions("views.js", ["PROFILE_SPORT_LABELS", "profileSportsLabel", "PROFILE_TRAINING_MODEL_LABELS", "PROFILE_SUMMARY_EMPTY", "PROFILE_SUMMARY_GOALS_LENGTH", "profileGoalsLine", "profilePreferencesLine", "profileSummaries"]);
  return JSON.parse(JSON.stringify(context.profileSummaries(profile)));
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

test("the Intervals.icu detail names the last export, also one that was no library push", () => {
  const { intervalsConnectionDetail } = extractFunctions("views.js", ["intervalsConnectionDetail"], { formatTime: (value) => `um ${value}` });
  const base = { configured: true, library_sync: { last_sync_at: null, state: {} } };
  assert.equal(intervalsConnectionDetail({ ...base, state: "connected", last_used_at: "T1" }), "Letzte Aktualisierung: um T1");
  assert.equal(intervalsConnectionDetail({ ...base, state: "configured" }), "Noch nicht getestet");
  assert.equal(intervalsConnectionDetail({ ...base, state: "error", last_error: null }), "Letzter Export fehlgeschlagen");
});

test("the Coach model list groups OpenAI and Claude and names the resolved Claude model", () => {
  const { modelOptionLabel, modelNoticeText } = extractFunctions("views.js", ["modelOptionLabel", "modelNoticeText"]);
  assert.equal(modelOptionLabel({ id: "gpt-6-luna", label: "GPT-6 Luna", provider: "openai" }), "GPT-6 Luna");
  assert.equal(modelOptionLabel({ id: "claude-opus", label: "Opus", provider: "anthropic", model: "claude-opus-5-5" }), "Opus (claude-opus-5-5)");
  assert.equal(modelOptionLabel({ id: "claude-haiku", label: "Haiku", provider: "anthropic", model: null }), "Haiku");
  const options = [
    { id: "claude-opus", label: "Opus", provider: "anthropic", model: "claude-opus-5-5", rejected: "claude-opus-5-6" },
    { id: "claude-sonnet", label: "Sonnet", provider: "anthropic", model: "claude-sonnet-5-5", rejected: null },
  ];
  assert.equal(modelNoticeText({ selected: "claude-opus", options }), "claude-opus-5-6 abgelehnt – Coach nutzt claude-opus-5-5.");
  assert.equal(modelNoticeText({ selected: "claude-sonnet", options }), "");
  assert.equal(modelNoticeText(undefined), "");
});

test("the chat needs the selected model's key; before a load it stays usable", () => {
  const { coachConfigured } = extractFunctions("coach.js", ["coachConfigured"]);
  assert.equal(coachConfigured(undefined), true);
  assert.equal(coachConfigured({ openai: true, coach: false }), false);
  assert.equal(coachConfigured({ openai: false, coach: true }), true);
  // An older server without the coach flag keeps the OpenAI rule.
  assert.equal(coachConfigured({ openai: false }), false);
});

test("the microphone needs a transcription endpoint whichever model answers", () => {
  const button = { disabled: false, classList: { toggle() {} }, setAttribute() {}, title: "", innerHTML: "" };
  const state = { data: { messages: [], configured: { openai: true, transcription: false, coach: true } }, voiceTranscribing: false };
  const { updateVoiceButton } = extractFunctions("coach.js", ["voiceIsRecording", "setVoiceButtonIcon", "updateVoiceButton"], {
    $: () => button,
    state,
    updateChatControls: () => {},
  });
  updateVoiceButton();
  assert.equal(button.disabled, true);
  state.data.configured.transcription = true;
  updateVoiceButton();
  assert.equal(button.disabled, false);
});
