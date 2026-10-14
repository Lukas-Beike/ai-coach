const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function readPublic(name) {
  return fs.readFileSync(path.join(__dirname, "../public", name), "utf8");
}

function slice(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  assert.ok(start >= 0, `missing ${startMarker}`);
  const end = endMarker ? source.indexOf(endMarker, start + startMarker.length) : source.length;
  assert.ok(end > start, `missing ${endMarker}`);
  return source.slice(start, end);
}

// Objects created inside a vm context have their own prototypes; compare plain copies.
function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

class FormDataStub {
  constructor(form) {
    this.entries_ = form.entries_.map(([key, value]) => [key, value]);
  }

  [Symbol.iterator]() {
    return this.entries_[Symbol.iterator]();
  }

  getAll(name) {
    return this.entries_.filter(([key]) => key === name).map(([, value]) => value);
  }
}

function submitEvent(formEntries) {
  const button = { textContent: "Speichern", disabled: false, setAttribute() {}, removeAttribute() {} };
  const form = { entries_: formEntries };
  return { event: { preventDefault() {}, currentTarget: form, submitter: button }, button };
}

const settingsSource = readPublic("settings.js");
const performanceSource = readPublic("performance-view.js");
const coachSource = readPublic("coach.js");
const syncStatusSource = readPublic("sync-status.js");
const notificationsSource = readPublic("notifications.js");

function profileContext({ server, baseline, stateProfile }) {
  const calls = [];
  const toasts = [];
  const state = { sessionGeneration: 1, data: { profile: stateProfile }, profileBaseline: baseline, profileDirty: false };
  const context = vm.createContext({
    state,
    FormData: FormDataStub,
    api: async (path, options = {}) => {
      const method = options.method || "GET";
      const body = options.body ? JSON.parse(options.body) : null;
      calls.push({ path, method, body });
      if (path === "/api/profile" && method === "GET") return { profile: { ...server }, competitions: [] };
      return { ...body };
    },
    toast: (message, isError) => toasts.push({ message, isError: Boolean(isError) }),
    setDirtyIndicator() {},
    invalidateContextPreview() {},
    load: async () => {},
  });
  vm.runInContext(
    slice(settingsSource, "// Profile values as the form presents", "\nasync function saveCheckin")
      + slice(performanceSource, "async function saveInlineMetric", "\nfunction performanceSection"),
    context,
  );
  return { context, state, calls, toasts };
}

test("profile save keeps the server's current values for fields the athlete did not edit", async () => {
  const { context, calls, toasts } = profileContext({
    server: { name: "Anna", sports: "Cycling", typical_weekly_volume: "10 h", coaching_style: "Unterstützend", weight: "60" },
    baseline: { name: "Anna", sports: "Cycling", typical_weekly_volume: "8 h", coaching_style: "Unterstützend" },
    stateProfile: { name: "Anna", sports: "Cycling", typical_weekly_volume: "8 h", coaching_style: "Unterstützend", weight: "55" },
  });
  const { event } = submitEvent([
    ["name", "Anna M."],
    ["sports", "Cycling"],
    ["typical_weekly_volume", "8 h"],
    ["coaching_style", "Unterstützend"],
  ]);
  await context.saveProfile(event);
  const put = calls.find((call) => call.method === "PUT");
  assert.ok(put, "expected a PUT to /api/profile");
  const body = plain(put.body);
  assert.equal(body.name, "Anna M.");
  assert.equal(body.typical_weekly_volume, "10 h");
  assert.equal(body.weight, "60");
  assert.equal(toasts.at(-1).isError, false);
});

test("profile save refuses to write before the rendered baseline is known", async () => {
  const { context, calls, toasts } = profileContext({
    server: { name: "Anna", weight: "60" },
    baseline: null,
    stateProfile: {},
  });
  const { event } = submitEvent([["name", "Anna M."]]);
  await context.saveProfile(event);
  assert.equal(calls.filter((call) => call.method === "PUT").length, 0);
  assert.equal(toasts.at(-1).isError, true);
});

test("inline metric save changes only its key on the server's current profile", async () => {
  const { context, calls } = profileContext({
    server: { name: "Anna", typical_weekly_volume: "10 h", weight: "60" },
    baseline: { name: "Anna" },
    stateProfile: { name: "Anna", typical_weekly_volume: "8 h", weight: "55" },
  });
  await context.saveInlineMetric("weight", " 62 ", { disabled: false });
  const put = calls.find((call) => call.method === "PUT");
  assert.ok(put);
  const body = plain(put.body);
  assert.equal(body.weight, "62");
  assert.equal(body.typical_weekly_volume, "10 h");
});

function coachContext(apiImpl) {
  const state = { coachActionUnknownIds: new Set(), coachActionProposals: [], coachReceipts: [], route: "plan" };
  const receipts = [];
  const toasts = [];
  const apiCalls = [];
  let renders = 0;
  const context = vm.createContext({
    state,
    api: async (path, options = {}) => {
      apiCalls.push(path);
      return apiImpl(path, options);
    },
    addCoachReceipt: (receipt) => receipts.push(receipt),
    renderCoachActionReview: () => { renders += 1; },
    toast: (message, isError) => toasts.push({ message, isError: Boolean(isError) }),
    AppRouter: { navigate: async () => {} },
    load: async () => {},
  });
  vm.runInContext(slice(coachSource, "function isHttpClientRejection", "\nfunction createPendingMessage"), context);
  return { context, state, receipts, toasts, apiCalls, renders: () => renders };
}

function confirmThen(executeError) {
  return async (path) => {
    if (path === "/api/coach/actions/confirm") return { action_token: "tok", proposed_action: { payload_hash: "hash" } };
    throw executeError;
  };
}

test("a lost execute response keeps the action locked and is not reported as a failed confirmation", async () => {
  const { context, state, receipts, apiCalls } = coachContext(confirmThen(new Error("Der Server antwortet nicht innerhalb von 55 Sekunden.")));
  const proposal = { id: "p1", status: "ready", action_type: "local_coach_write" };
  state.coachActionProposals = [proposal];
  const button = { disabled: false };
  await context.executeCoachActionProposal(proposal, button);
  assert.equal(state.coachActionUnknownIds.has("p1"), true);
  assert.equal(button.disabled, true);
  assert.equal(receipts.at(-1).title, "Ausführung unklar");
  assert.equal(receipts.some((receipt) => receipt.title === "Aktion nicht bestätigt"), false);

  await context.executeCoachActionProposal(proposal, { disabled: false });
  assert.equal(apiCalls.filter((path) => path === "/api/coach/actions/execute").length, 1, "a locked proposal must not be executed again");
});

test("a server error after execute was sent also counts as an unknown outcome", async () => {
  const error = Object.assign(new Error("Interner Fehler."), { status: 500 });
  const { context, state } = coachContext(confirmThen(error));
  const proposal = { id: "p2", status: "ready", action_type: "local_coach_write" };
  await context.executeCoachActionProposal(proposal, { disabled: false });
  assert.equal(state.coachActionUnknownIds.has("p2"), true);
});

test("a 409 rejection after execute was sent is a known failure and unlocks the proposal", async () => {
  const error = Object.assign(new Error("Diese Freigabe wurde bereits verwendet."), { status: 409, reason: "proposal_used" });
  const { context, state, receipts } = coachContext(confirmThen(error));
  const proposal = { id: "p3", status: "ready", action_type: "local_coach_write" };
  const button = { disabled: false };
  await context.executeCoachActionProposal(proposal, button);
  assert.equal(state.coachActionUnknownIds.has("p3"), false);
  assert.equal(button.disabled, false);
  assert.equal(proposal.status, "used");
  assert.equal(receipts.at(-1).title, "Aktion nicht bestätigt");
});

test("reconcile reports a proposal the server already consumed and keeps it locked", async () => {
  const { context, state, receipts } = coachContext(async (path) => {
    if (path === "/api/chat/history?limit=1") return { proposed_actions: [{ id: "p1", status: "used" }] };
    throw new Error("unexpected call");
  });
  state.coachActionUnknownIds.add("p1");
  await context.reconcileCoachActionProposal("p1");
  assert.equal(state.coachActionUnknownIds.has("p1"), false);
  assert.deepEqual(plain(state.coachActionProposals), [{ id: "p1", status: "used" }]);
  assert.equal(receipts.at(-1).title, "Ausführung prüfen");
});

test("reconcile re-enables a proposal the server still reports as confirmable", async () => {
  const { context, state, receipts } = coachContext(async () => ({ proposed_actions: [{ id: "p1", status: "ready" }] }));
  state.coachActionUnknownIds.add("p1");
  await context.reconcileCoachActionProposal("p1");
  assert.equal(state.coachActionUnknownIds.has("p1"), false);
  assert.equal(receipts.at(-1).title, "Nicht ausgeführt");
});

test("a failed reconcile keeps the unknown-outcome lock", async () => {
  const { context, state, toasts } = coachContext(async () => {
    throw new Error("Keine Verbindung zum Coach-Server.");
  });
  state.coachActionUnknownIds.add("p1");
  await context.reconcileCoachActionProposal("p1");
  assert.equal(state.coachActionUnknownIds.has("p1"), true);
  assert.equal(toasts.at(-1).isError, true);
});

test("resetting the coach chat waits while queued messages have not been sent", async () => {
  const source = slice(coachSource, "async function resetCoachChat", "\nconst MAX_QUEUED_ATTACHMENT_BYTES");
  const state = { chatQueue: [{ id: 1 }] };
  const toasts = [];
  const apiCalls = [];
  let confirmations = 0;
  const context = vm.createContext({
    state,
    $: () => ({ disabled: false, textContent: "" }),
    requestConfirmation: async () => { confirmations += 1; return true; },
    api: async (path) => { apiCalls.push(path); return {}; },
    toast: (message, isError) => toasts.push({ message, isError: Boolean(isError) }),
  });
  vm.runInContext(source, context);
  await context.resetCoachChat();
  assert.equal(confirmations, 0);
  assert.equal(apiCalls.length, 0);
  assert.equal(state.chatQueue.length, 1);
  assert.equal(toasts.at(-1).isError, true);
});

test("an in-flight sync poll does not take the poll lease", async () => {
  const source = slice(syncStatusSource, "function syncPollLeaseAvailable", "\nfunction setupSyncStatusMonitoring");
  let leaseWrites = 0;
  const context = vm.createContext({
    state: { data: {}, syncPoll: { controller: {}, leaseToken: "tab", timer: null } },
    document: { visibilityState: "visible" },
    navigator: { onLine: true },
    localStorage: { getItem: () => null, setItem: () => { leaseWrites += 1; }, removeItem() {} },
    SYNC_POLL_LEASE_KEY: "lease",
    SYNC_POLL_LEASE_MS: 1000,
    SYNC_POLL_RETRY_MS: 1000,
    SYNC_POLL_IDLE_MS: 1000,
    SYNC_POLL_ACTIVE_MS: 1000,
    api: async () => { throw new Error("no request expected"); },
    providerIds: () => ({}),
  });
  vm.runInContext(source, context);
  await context.pollSyncStatus();
  assert.equal(leaseWrites, 0);
});

test("notification bodies omit competition names and provider error text", async () => {
  const source = slice(notificationsSource, "const NOTIFICATION_MAX_ATTEMPTS", "\nfunction registerServiceWorker");
  const shown = [];
  const context = vm.createContext({
    state: { notificationKeys: new Set() },
    notificationPermission: () => "granted",
    navigator: {
      serviceWorker: {
        ready: Promise.resolve({ showNotification: async (title, options) => { shown.push({ title, options }); } }),
      },
    },
  });
  vm.runInContext(source, context);
  context.notifyState({
    planning: { season: { next_event: { id: 7, name: "Geheimer Stadtlauf", days_until: 0, event_date: "2026-10-14" } } },
    sync: { last_error: "Token tok_123 abgelehnt" },
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(shown.length, 2);
  assert.equal(shown[0].options.body, "Der Wettkampf ist heute.");
  const bodies = shown.map((item) => item.options.body).join(" | ");
  assert.doesNotMatch(bodies, /Geheimer|Stadtlauf|tok_123|Token/);
  assert.equal(context.competitionCountdownText(3), "Der Wettkampf ist in 3 Tagen.");
});
