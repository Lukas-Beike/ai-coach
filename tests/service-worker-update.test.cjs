const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const read = (name) => fs.readFileSync(path.join(__dirname, "../public", name), "utf8").replace(/\r\n/g, "\n");
const workerSource = read("service-worker.js");
const notificationsSource = read("notifications.js");
const sharedSource = read("shared.js");
const coachSource = read("coach.js");

function slice(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = endMarker ? source.indexOf(endMarker, start) : source.length;
  assert.ok(start >= 0 && end > start, startMarker);
  return source.slice(start, end);
}

// Runs public/service-worker.js with recorded cache and lifecycle calls.
function worker() {
  const handlers = {};
  const calls = [];
  const context = vm.createContext({
    URL,
    addEventListener: (type, handler) => { handlers[type] = handler; },
    skipWaiting: async () => { calls.push(["skipWaiting"]); },
    clients: { claim: async () => { calls.push(["claim"]); } },
    caches: {
      open: async (name) => ({ addAll: async () => { calls.push(["addAll", name]); } }),
      keys: async () => ["intervals-coach-old", cacheName],
      delete: async (key) => { calls.push(["delete", key]); return true; },
    },
  });
  vm.runInContext(workerSource, context);
  const cacheName = vm.runInContext("CACHE", context);
  const run = async (type) => {
    const waits = [];
    handlers[type]({ waitUntil: (promise) => waits.push(promise) });
    await Promise.all(waits);
  };
  return { calls, run, cacheName };
}

test("a new service worker takes over once its assets are cached", async () => {
  const { calls, run, cacheName } = worker();
  await run("install");
  assert.deepEqual(calls, [["addAll", cacheName], ["skipWaiting"]]);
});

test("an activated service worker removes old caches and controls open pages", async () => {
  const { calls, run } = worker();
  await run("activate");
  assert.deepEqual(calls, [["delete", "intervals-coach-old"], ["claim"]]);
});

// Runs the service worker registration of public/notifications.js with the real
// unsaved-change and Coach job checks against a stubbed page.
function page({ controlled = true } = {}) {
  const workerListeners = {};
  const documentListeners = {};
  const nodes = { "#messageInput": { value: "" }, "#backupRestoreButton": { disabled: false }, "dialog[open]": null };
  const pendingTurn = new Map();
  const state = {
    profileDirty: false,
    chatDraftDirty: false,
    chatQueue: [],
    rejectedMessages: [],
    chatAttachments: [],
    chatAttachmentsLoading: false,
    busy: false,
    chatRequest: null,
    chatServerOperationId: null,
    chatStream: null,
    voiceRecorder: null,
    voiceTranscribing: false,
    loadPromise: null,
  };
  const document = {
    visibilityState: "visible",
    querySelector: (selector) => nodes[selector] ?? null,
    addEventListener: (type, handler) => { documentListeners[type] = handler; },
  };
  const reloads = [];
  const context = vm.createContext({
    state,
    document,
    sessionStorage: { getItem: (key) => pendingTurn.get(key) ?? null },
    location: { reload: () => reloads.push(1) },
    navigator: {
      serviceWorker: {
        controller: controlled ? {} : null,
        addEventListener: (type, handler) => { workerListeners[type] = handler; },
        register: async () => ({}),
      },
    },
  });
  vm.runInContext([
    slice(sharedSource, "const $ =", "\n"),
    slice(sharedSource, "function hasUnsavedChanges", "\n}\n") + "\n}\n",
    slice(coachSource, "function chatStatusJobActive", "\nfunction chatStatusPollWanted"),
    slice(coachSource, "function pendingChatTurn", "\nasync function pollPendingChatReceipt"),
    slice(coachSource, "function voiceIsRecording", "\nfunction formatVoiceDuration"),
    slice(notificationsSource, "function registerServiceWorker"),
  ].join("\n"), context);
  context.registerServiceWorker();
  return {
    context,
    state,
    nodes,
    pendingTurn,
    reloads,
    replaceWorker: () => workerListeners.controllerchange(),
    hide: () => { document.visibilityState = "hidden"; documentListeners.visibilitychange(); },
  };
}

test("a replaced service worker reloads an idle page once", () => {
  const { reloads, replaceWorker } = page();
  replaceWorker();
  assert.equal(reloads.length, 1);
});

test("two worker changes reload the page only once", () => {
  const { context, reloads, replaceWorker } = page();
  replaceWorker();
  replaceWorker();
  context.reloadForUpdateWhenSafe();
  assert.equal(reloads.length, 1);
});

test("the first service worker install does not reload the page", () => {
  const { context, reloads, replaceWorker, hide } = page({ controlled: false });
  replaceWorker();
  context.reloadForUpdateWhenSafe();
  hide();
  assert.equal(reloads.length, 0);
});

test("a page without a replaced worker never reloads on a check", () => {
  const { context, reloads, hide } = page();
  context.reloadForUpdateWhenSafe();
  hide();
  assert.equal(reloads.length, 0);
});

// Each state holds the reload until it ends, then the next check reloads once.
const blockers = {
  "typed text": ({ nodes }) => { nodes["#messageInput"].value = "Entwurf"; return () => { nodes["#messageInput"].value = ""; }; },
  "a staged attachment": ({ state }) => { state.chatAttachments = [{ name: "route.gpx" }]; return () => { state.chatAttachments = []; }; },
  "an attachment being read": ({ state }) => { state.chatAttachmentsLoading = true; return () => { state.chatAttachmentsLoading = false; }; },
  "a running Coach turn": ({ state, pendingTurn }) => {
    state.busy = true;
    state.chatRequest = { phase: "streaming", clientTurnId: "turn-1" };
    pendingTurn.set("coachPendingTurn", "turn-1");
    return () => { state.busy = false; state.chatRequest = null; pendingTurn.clear(); };
  },
  "a recovering Coach turn": ({ state }) => { state.chatRequest = { phase: "recovering", clientTurnId: "turn-1" }; return () => { state.chatRequest = null; }; },
  "a queued message": ({ state }) => { state.chatQueue = [{ id: 1, message: "Danach" }]; return () => { state.chatQueue = []; }; },
  "a rejected message": ({ state }) => { state.rejectedMessages = [{ content: "Abgelehnt" }]; return () => { state.rejectedMessages = []; }; },
  "an unsaved profile": ({ state }) => { state.profileDirty = true; return () => { state.profileDirty = false; }; },
  "a voice recording": ({ state }) => { state.voiceRecorder = { state: "recording" }; return () => { state.voiceRecorder = null; }; },
  "a state load": ({ state }) => { state.loadPromise = Promise.resolve(); return () => { state.loadPromise = null; }; },
  "a backup restore": ({ nodes }) => { nodes["#backupRestoreButton"].disabled = true; return () => { nodes["#backupRestoreButton"].disabled = false; }; },
  "an open dialog": ({ nodes }) => { nodes["dialog[open]"] = {}; return () => { nodes["dialog[open]"] = null; }; },
};

for (const [name, block] of Object.entries(blockers)) {
  test(`${name} holds the update reload until it ends`, () => {
    const view = page();
    const clear = block(view);
    view.replaceWorker();
    view.context.reloadForUpdateWhenSafe();
    assert.equal(view.reloads.length, 0);
    clear();
    view.context.reloadForUpdateWhenSafe();
    view.context.reloadForUpdateWhenSafe();
    assert.equal(view.reloads.length, 1);
  });
}

test("a hidden page runs a held update reload once nothing is in progress", () => {
  const view = page();
  const clear = blockers["a backup restore"](view);
  view.replaceWorker();
  assert.equal(view.reloads.length, 0);
  clear();
  view.hide();
  assert.equal(view.reloads.length, 1);
});

test("a hidden page keeps a draft instead of reloading", () => {
  const view = page();
  blockers["typed text"](view);
  view.replaceWorker();
  view.hide();
  assert.equal(view.reloads.length, 0);
  assert.equal(view.nodes["#messageInput"].value, "Entwurf");
});

// The chat states end with a control update; the state loads are checked in state-loader-startup.test.cjs.
test("every chat control update checks a held update reload", () => {
  const updateChatControls = slice(coachSource, "function updateChatControls", "\n}\n");
  assert.match(updateChatControls, /\n {2}reloadForUpdateWhenSafe\(\);$/);
});
