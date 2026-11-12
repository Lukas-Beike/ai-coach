const assert = require("node:assert/strict");
const vm = require("node:vm");
const { test } = require("node:test");
const { extractFunctions, loadPublicScript } = require("./frontend-harness.cjs");

// Runs public/service-worker.js with recorded cache and lifecycle calls.
function worker() {
  const handlers = {};
  const calls = [];
  const context = loadPublicScript("service-worker.js", {
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
  const nodes = { "#messageInput": { value: "" }, "#backupRestoreButton": { disabled: false }, "#calendarDisplaySaveButton": { disabled: false }, "dialog[open]": null };
  const credentialFields = [{ value: "" }, { value: "" }];
  const dirtyForms = [];
  const globalListeners = {};
  const providerCredentialBusy = new Set();
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
    activeElement: null,
    querySelector: (selector) => nodes[selector] ?? null,
    querySelectorAll: (selector) => (selector.includes("#cred-form-openai input") ? credentialFields : selector.startsWith("form[data-dirty]") ? dirtyForms.filter((form) => form.dataset.dirty) : selector === "form[data-saving]" ? dirtyForms.filter((form) => form.dataset.saving) : []),
    addEventListener: (type, handler) => { documentListeners[type] = handler; },
  };
  const reloads = [];
  const context = vm.createContext({
    state,
    document,
    providerCredentialBusy,
    addEventListener: (type, handler) => { globalListeners[type] = handler; },
    setTimeout: (handler) => handler(),
    requestAnimationFrame: (handler) => handler(),
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
  extractFunctions("shared.js", ["$", "hasUnsavedChanges"], context);
  extractFunctions("coach.js", ["chatStatusJobActive", "pendingChatTurn", "voiceIsRecording"], context);
  extractFunctions("notifications.js", ["registerServiceWorker", "serviceWorkerReplaced", "serviceWorkerReloaded", "pointerHeld", "trackUnsavedForms", "editedFormPending", "UPDATE_RELOAD_INPUT_FIELDS", "pageInputPending", "updateReloadIsSafe", "reloadForUpdateWhenSafe"], context);
  context.registerServiceWorker();
  return {
    context,
    state,
    nodes,
    document,
    credentialFields,
    providerCredentialBusy,
    documentListeners,
    globalListeners,
    dirtyForms,
    leaveField: () => { document.activeElement = null; documentListeners.focusout(); },
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
  "a typed credential": ({ credentialFields }) => { credentialFields[1].value = "123456"; return () => { credentialFields[1].value = ""; }; },
  "a credential save": ({ providerCredentialBusy }) => { providerCredentialBusy.add("garmin-login"); return () => { providerCredentialBusy.clear(); }; },
  "a calendar settings save": ({ nodes }) => { nodes["#calendarDisplaySaveButton"].disabled = true; return () => { nodes["#calendarDisplaySaveButton"].disabled = false; }; },
  "an edited form": ({ dirtyForms }) => { dirtyForms.push({ dataset: { dirty: "1" }, closest: () => null }); return () => { dirtyForms.length = 0; }; },
  "an open nutrition extraction": ({ nodes }) => { nodes["#nutritionExtraction"] = { hidden: false, childElementCount: 2 }; return () => { nodes["#nutritionExtraction"] = { hidden: true, childElementCount: 2 }; }; },
  "a focused settings field": ({ document }) => {
    document.activeElement = { matches: () => true, closest: () => null };
    return () => { document.activeElement = null; };
  },
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

test("a focused empty chat input does not hold the update reload", () => {
  const view = page();
  view.document.activeElement = { matches: () => true, closest: (selector) => (selector === "#chatForm" ? {} : null) };
  view.replaceWorker();
  assert.equal(view.reloads.length, 1);
});

test("leaving a settings field runs a held update reload", () => {
  const view = page();
  blockers["a focused settings field"](view);
  view.replaceWorker();
  assert.equal(view.reloads.length, 0);
  view.leaveField();
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
  const { updateChatControls } = extractFunctions("coach.js", ["updateChatControls"]);
  assert.match(updateChatControls.toString(), /\n {2}reloadForUpdateWhenSafe\(\);\n\}$/);
});

test("typing into a form marks it unsaved until a save is confirmed or the form is reset", () => {
  const { documentListeners, globalListeners, dirtyForms } = page();
  const form = { dataset: {} };
  const field = { closest: (selector) => (selector.startsWith("form") ? form : null) };
  dirtyForms.push(form);
  documentListeners.input({ isTrusted: true, target: field });
  assert.equal(form.dataset.dirty, "1");
  documentListeners.submit({ target: form });
  // A rejected save sends no confirmation: the input stays protected.
  assert.equal(form.dataset.dirty, "1");
  globalListeners["pacecraft:saved"]();
  assert.equal(form.dataset.dirty, undefined);
  documentListeners.input({ isTrusted: true, target: field });
  documentListeners.reset({ target: form });
  assert.equal(form.dataset.dirty, undefined);
  documentListeners.input({ isTrusted: false, target: field });
  assert.equal(form.dataset.dirty, undefined);
});

test("a failed save keeps the update reload held until a later save succeeds", () => {
  const view = page();
  const form = { dataset: { dirty: "1" }, closest: () => null };
  view.dirtyForms.push(form);
  view.replaceWorker();
  view.documentListeners.submit({ target: form });
  view.context.reloadForUpdateWhenSafe();
  assert.equal(view.reloads.length, 0);
  view.documentListeners.submit({ target: form });
  view.globalListeners["pacecraft:saved"]();
  view.context.reloadForUpdateWhenSafe();
  assert.equal(view.reloads.length, 1);
});

test("an edited form in a closed dialog does not hold the update reload", () => {
  const view = page();
  view.dirtyForms.push({ dataset: { dirty: "1" }, closest: (selector) => (selector === "dialog:not([open])" ? {} : null) });
  view.replaceWorker();
  assert.equal(view.reloads.length, 1);
});

test("leaving a field during a pointer press waits for the click", () => {
  const view = page();
  view.state.chatDraftDirty = true;
  view.replaceWorker();
  view.documentListeners.pointerdown();
  view.state.chatDraftDirty = false;
  view.documentListeners.focusout();
  assert.equal(view.reloads.length, 0);
  view.documentListeners.pointerup();
  assert.equal(view.reloads.length, 1);
});

// Drives the worker's fetch handler with a recorded cache and a scripted network.
function fetching(networkStatus, { shell = true, cached = [] } = {}) {
  const handlers = {};
  const stored = new Map([...(shell ? [["/", { shell: true, status: 200 }]] : []), ...cached]);
  const puts = [];
  const network = [];
  const context = loadPublicScript("service-worker.js", {
    URL,
    setTimeout,
    clearTimeout,
    TypeError,
    addEventListener: (type, handler) => { handlers[type] = handler; },
    fetch: async (request) => {
      network.push(request.url);
      if (networkStatus === "offline") throw new TypeError("offline");
      const response = { status: networkStatus, ok: networkStatus < 400, clone: () => ({ copy: true }) };
      return response;
    },
    caches: {
      open: async () => ({
        match: async (key) => stored.get(typeof key === "string" ? key : key.url) ?? null,
        put: async (key) => { puts.push(typeof key === "string" ? key : key.url); },
      }),
    },
  });
  return async (url, mode = "navigate", method = "GET") => {
    let answer;
    const waits = [];
    handlers.fetch({ request: { url: `http://localhost${url}`, method, mode }, respondWith: (promise) => { answer = promise; }, waitUntil: (promise) => waits.push(promise) });
    const response = await answer?.catch((error) => error);
    await Promise.all(waits);
    return { response, puts, network, answered: Boolean(answer) };
  };
}

test("a server error on a navigation shows the cached app shell", async () => {
  const { response } = await fetching(502)("/");
  assert.equal(response.shell, true);
});

test("a server error without a cached shell is still shown", async () => {
  const { response } = await fetching(502, { shell: false })("/");
  assert.equal(response.status, 502);
});

test("navigations are cached under the app shell key only", async () => {
  for (const path of ["/", "/does-not-exist", "/?wahoo=connected"]) {
    const { puts } = await fetching(200)(path);
    assert.deepEqual(puts, ["/"], path);
  }
});

test("only precached files are stored for other requests", async () => {
  assert.deepEqual((await fetching(200)("/app.js", "no-cors")).puts, ["http://localhost/app.js"]);
  assert.deepEqual((await fetching(200)("/unknown.json", "no-cors")).puts, []);
});

test("API calls and writes pass through the worker untouched", async () => {
  for (const [url, method] of [["/api/bootstrap", "GET"], ["/api/chat", "POST"], ["/app.js?v=abc", "POST"]]) {
    const { answered, puts, network } = await fetching(200)(url, "no-cors", method);
    assert.deepEqual([answered, puts, network], [false, [], []], `${method} ${url}`);
  }
});

test("a versioned asset is served from the cache without the network and fetched once when missing", async () => {
  const hit = { cachedAsset: true, status: 200 };
  const cached = await fetching(200, { cached: [["http://localhost/app.js?v=abc", hit]] })("/app.js?v=abc", "no-cors");
  assert.equal(cached.response, hit);
  assert.deepEqual(cached.network, []);
  const missing = await fetching(200)("/app.js?v=abc", "no-cors");
  assert.deepEqual([missing.network, missing.puts], [["http://localhost/app.js?v=abc"], ["http://localhost/app.js?v=abc"]]);
  const failed = await fetching(404)("/app.js?v=abc", "no-cors");
  assert.deepEqual(failed.puts, []);
});
