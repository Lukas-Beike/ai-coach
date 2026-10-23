const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/state-loader.js"), "utf8");

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

// Loads public/state-loader.js with recorded API calls and stubbed rendering.
function loader({ asset = "/state-loader.js?v=1", storage = new Map() } = {}) {
  const calls = [];
  const responses = new Map();
  const renders = [];
  const updateChecks = [];
  const shell = { loading: false, hidden: false };
  shell.classList = { contains: () => shell.loading, add() {}, remove() {} };
  const state = {
    data: null,
    sessionGeneration: 0,
    chatGeneration: 0,
    chatContentVersion: 0,
    loadSequence: 0,
    loadPromise: null,
    pendingLoads: new Map(),
    loadingAreas: new Set(),
    loadedAreas: new Set(),
    initialStateLoaded: false,
    replaceDataOnLoad: false,
  };
  const context = vm.createContext({
    state,
    document: { currentScript: { src: asset } },
    setTimeout,
    clearTimeout,
    btoa,
    localStorage: {
      getItem: (key) => (storage.has(key) ? storage.get(key) : null),
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: (key) => storage.delete(key),
    },
    $: () => shell,
    providerIds: () => ({ garmin: "garmin" }),
    currentPlanLoadAreas: () => ["chat"],
    applyChatResult() {},
    finishAppShellLoading() {},
    reloadForUpdateWhenSafe() { updateChecks.push(state.loadPromise); },
    api(requestPath) {
      calls.push(requestPath);
      const response = responses.get(requestPath) || deferred();
      responses.set(requestPath, response);
      return response.promise;
    },
  });
  vm.runInContext(source, context);
  context.render = (data) => { state.data = data; renders.push(data); };
  const respond = (requestPath, body) => {
    const response = responses.get(requestPath) || deferred();
    responses.set(requestPath, response);
    response.resolve(body);
  };
  return { context, state, shell, calls, renders, respond, storage, updateChecks };
}

test("area reads start before the bootstrap response arrives", async () => {
  const { context, calls, respond } = loader();
  const loading = context.load("/api/bootstrap?local=1", ["performance", "feedback"]);
  await Promise.resolve();
  assert.deepEqual(plain(calls), ["/api/performance", "/api/feedback", "/api/bootstrap?local=1"]);
  respond("/api/performance", { performance: {} });
  respond("/api/feedback", { checkins: [] });
  respond("/api/bootstrap?local=1", { state_versions: { performance: 2 } });
  await loading;
});

test("a live area refresh reads only its areas and keeps the known versions", async () => {
  const { context, state, calls, respond } = loader();
  state.data = { profile: { weather_location: "Berlin" }, state_versions: { weather: 3 } };
  const loading = context.load(vm.runInContext("LIVE_AREA_REFRESH", context), ["weather"]);
  respond("/api/weather", { days: [1] });
  await loading;
  assert.deepEqual(plain(calls), ["/api/weather"]);
  assert.deepEqual(plain(state.data.weather), { days: [1] });
  assert.deepEqual(plain(state.data.state_versions), { weather: 3 });
  assert.equal(state.data.profile.weather_location, "Berlin");
});

test("an area is reported loading only while a request for it is in flight", async () => {
  const { context, respond } = loader();
  const loading = context.load("/api/bootstrap?local=1", ["plan", "library"]);
  assert.equal(context.areaLoading("plan"), true);
  assert.equal(context.areaLoading("profile"), false);
  respond("/api/plan?local=1", {});
  respond("/api/library?limit=100", { workouts: [] });
  respond("/api/bootstrap?local=1", {});
  await loading;
  assert.equal(context.areaLoading("plan"), false);
});

test("the state snapshot is saved only after a full load and marks an update across assets", () => {
  const first = loader();
  first.state.data = { messages: [{ id: 1 }] };
  first.context.saveStateSnapshot();
  assert.equal(first.storage.size, 0);
  first.state.initialStateLoaded = true;
  first.context.saveStateSnapshot();
  assert.deepEqual(plain(loader({ storage: first.storage }).context.readStateSnapshot()), { data: { messages: [{ id: 1 }] }, updated: false });
  assert.deepEqual(plain(loader({ storage: first.storage, asset: "/state-loader.js?v=2" }).context.readStateSnapshot()), { data: { messages: [{ id: 1 }] }, updated: true });
  first.context.clearStateSnapshot();
  assert.equal(first.context.readStateSnapshot(), null);
});

test("a completed load schedules one coalesced snapshot save", async () => {
  const { context, state, storage, respond } = loader();
  state.initialStateLoaded = true;
  const loading = context.load("/api/bootstrap", ["performance"]);
  respond("/api/bootstrap", { state_versions: {} });
  respond("/api/performance", { performance: { ctl: 40 } });
  await loading;
  assert.equal(storage.size, 0);
  await new Promise((done) => setTimeout(done, vm.runInContext("STATE_SNAPSHOT_SAVE_DELAY_MS", context) + 50));
  assert.deepEqual(plain(context.readStateSnapshot().data.performance), { ctl: 40 });
});

test("the view cache keeps recent reads for the same assets and is cleared with the snapshot", () => {
  const first = loader();
  first.context.rememberViewCache("/api/nutrition/week", { days: [1] }, 0);
  assert.equal(first.storage.size, 0);
  first.state.data = {};
  first.context.rememberViewCache("/api/nutrition/week", { days: [1] }, 0);
  first.context.rememberViewCache("/api/nutrition/week", { days: [2] }, 0);
  assert.deepEqual(plain(first.context.readViewCache("/api/nutrition/week")), { days: [2] });
  assert.equal(first.context.readViewCache("/api/analysis/season"), null);
  assert.equal(loader({ storage: first.storage, asset: "/state-loader.js?v=2" }).context.readViewCache("/api/nutrition/week"), null);
  const limit = vm.runInContext("VIEW_CACHE_LIMIT", first.context);
  for (let index = 0; index <= limit; index += 1) first.context.rememberViewCache(`/view/${index}`, index, 0);
  assert.equal(first.context.readViewCache("/view/0"), null);
  assert.equal(first.context.readViewCache(`/view/${limit}`), limit);
  first.context.clearStateSnapshot();
  assert.equal(first.storage.size, 0);
  // A read that started before the clear does not store its response.
  first.context.rememberViewCache("/api/nutrition/week", { days: [3] }, 0);
  assert.equal(first.context.readViewCache("/api/nutrition/week"), null);
  first.context.rememberViewCache("/api/nutrition/week", { days: [3] }, vm.runInContext("viewCacheEpoch", first.context));
  assert.deepEqual(plain(first.context.readViewCache("/api/nutrition/week")), { days: [3] });
});

test("snapshot data never overrides the startup bootstrap or claims its versions", async () => {
  const { context, state, shell, respond } = loader();
  shell.loading = true;
  const loading = context.load("/api/bootstrap?local=1", ["performance"]);
  context.render({ planned: [{ id: "stale" }], weather: { days: ["stale"] }, state_versions: { plan: 1 } });
  state.replaceDataOnLoad = true;
  respond("/api/bootstrap?local=1", { planned: [{ id: "fresh" }], state_versions: { plan: 2, performance: 5 } });
  respond("/api/performance", { performance: { ctl: 40 } });
  await loading;
  assert.deepEqual(plain(state.data.planned), [{ id: "fresh" }]);
  assert.equal(state.data.weather, undefined);
  assert.deepEqual(plain(state.data.state_versions), { plan: 2, performance: 5 });
  assert.equal(state.replaceDataOnLoad, false);
});

test("placeholder data is never saved and only a bootstrap load replaces it", async () => {
  const { context, state, storage, respond } = loader();
  state.initialStateLoaded = true;
  state.data = { planned: [{ id: "deleted" }], profile: { weather_location: "Berlin" } };
  state.replaceDataOnLoad = true;
  context.saveStateSnapshot();
  assert.equal(storage.size, 0);
  const live = context.load(vm.runInContext("LIVE_AREA_REFRESH", context), ["weather"]);
  respond("/api/weather", { days: [] });
  await live;
  assert.equal(state.replaceDataOnLoad, true);
  const full = context.load("/api/bootstrap", ["performance"]);
  respond("/api/bootstrap", { planned: [], state_versions: {} });
  respond("/api/performance", { performance: {} });
  await full;
  assert.deepEqual(plain(state.data.planned), []);
  assert.equal(state.replaceDataOnLoad, false);
  context.saveStateSnapshot();
  assert.equal(storage.size, 1);
});

test("a load that started before a privacy deletion is dropped", async () => {
  const { context, state, respond } = loader();
  state.data = { planned: [{ id: "deleted" }] };
  const loading = context.load("/api/bootstrap", ["plan"]);
  state.loadSequence += 1;
  state.replaceDataOnLoad = true;
  respond("/api/bootstrap", { state_versions: {} });
  respond("/api/plan", { planned: [{ id: "deleted" }] });
  await loading;
  assert.equal(state.replaceDataOnLoad, true);
  assert.equal(state.loadedAreas.has("plan"), false);
  assert.deepEqual(plain(state.data.planned), [{ id: "deleted" }]);
});

test("a full storage drops the view cache before the state snapshot", () => {
  // Storage that has room for the snapshot only once the view cache is gone.
  class FullStorage extends Map {
    set(key, value) {
      if (key === "coach-state-snapshot" && this.has("coach-view-cache")) throw new Error("QuotaExceededError");
      return super.set(key, value);
    }
  }
  const { context, state, storage } = loader({ storage: new FullStorage() });
  state.data = { messages: [{ id: 1 }] };
  context.rememberViewCache("/api/nutrition/week", { days: [1] }, 0);
  state.initialStateLoaded = true;
  context.saveStateSnapshot();
  assert.equal(storage.has("coach-view-cache"), false);
  assert.deepEqual(plain(context.readStateSnapshot().data), { messages: [{ id: 1 }] });
});

test("a load with failed areas stores the loaded areas and keeps the previous failed ones", async () => {
  const { context, state, respond } = loader();
  state.initialStateLoaded = true;
  state.data = { performance: { ctl: 40 }, library: [{ id: "w1" }] };
  context.saveStateSnapshot();
  // A start from the snapshot replaces all data; the bootstrap's placeholders stand in for the failed library.
  state.replaceDataOnLoad = true;
  const placeholders = { state_versions: {}, performance: {}, library: [], checkins: [], weather: {} };
  const failing = context.load("/api/bootstrap", ["performance", "library"]);
  respond("/api/bootstrap", placeholders);
  respond("/api/performance", { performance: { ctl: 41 } });
  respond("/api/library?limit=100", Promise.reject(new Error("offline")));
  await failing;
  assert.deepEqual(plain(state.data.library), []);
  context.saveStateSnapshot();
  const stored = context.readStateSnapshot().data;
  assert.deepEqual(plain([stored.performance, stored.library]), [{ ctl: 41 }, [{ id: "w1" }]]);
  const complete = context.load("/api/bootstrap?local=1", ["performance"]);
  respond("/api/bootstrap?local=1", placeholders);
  await complete;
  context.saveStateSnapshot();
  assert.equal(context.readStateSnapshot().data.performance.ctl, 41);
});

test("areas still loading keep the shown snapshot instead of the bootstrap placeholders", async () => {
  const { context, state, respond, renders } = loader();
  state.data = { performance: { ctl: 40 }, library: [{ id: "w1" }], checkins: [{ id: "c1" }] };
  state.replaceDataOnLoad = true;
  context.markStateSnapshotShown(true);
  const placeholders = { state_versions: {}, performance: {}, library: [], checkins: [] };
  const loading = context.load("/api/bootstrap", ["performance", "library", "feedback"]);
  respond("/api/bootstrap", placeholders);
  respond("/api/performance", { performance: { ctl: 41 } });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(plain([state.data.performance, state.data.library, state.data.checkins]), [{ ctl: 41 }, [{ id: "w1" }], [{ id: "c1" }]]);
  respond("/api/library?limit=100", { workouts: [{ id: "w2" }] });
  respond("/api/feedback", { checkins: [] });
  await loading;
  assert.deepEqual(plain([state.data.library, state.data.checkins]), [[{ id: "w2" }], []]);
  assert.ok(renders.length >= 2);
});

test("after a privacy deletion, loading areas show placeholders, not the deleted data", async () => {
  const { context, state, respond } = loader();
  context.markStateSnapshotShown(true);
  context.clearStateSnapshot();
  state.data = { performance: { ctl: 40 }, library: [{ id: "w1" }] };
  state.replaceDataOnLoad = true;
  const loading = context.load("/api/bootstrap", ["performance", "library"]);
  respond("/api/bootstrap", { state_versions: {}, performance: {}, library: [] });
  respond("/api/performance", { performance: { ctl: 41 } });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(plain(state.data.library), []);
  respond("/api/library?limit=100", { workouts: [] });
  await loading;
});

test("a load reloads the open route view only with its first area render", async () => {
  const { context, state, respond } = loader();
  const reloads = [];
  context.render = (data, { reloadRoute = true } = {}) => { state.data = data; reloads.push(reloadRoute); };
  const loading = context.load("/api/bootstrap", ["performance", "library", "feedback"]);
  respond("/api/bootstrap", { state_versions: {} });
  respond("/api/performance", { performance: {} });
  respond("/api/library?limit=100", { workouts: [] });
  respond("/api/feedback", { checkins: [] });
  await loading;
  assert.deepEqual(reloads, [true, false, false]);
});

test("a later load without a failed area still stores that area from the shown snapshot", async () => {
  const { context, state, respond } = loader();
  state.data = { performance: { ctl: 40 }, library: [{ id: "w1" }] };
  state.replaceDataOnLoad = true;
  context.markStateSnapshotShown(true);
  const placeholders = { state_versions: {}, performance: {}, library: [] };
  const start = context.load("/api/bootstrap", ["performance", "library"]);
  respond("/api/bootstrap", placeholders);
  respond("/api/performance", { performance: { ctl: 41 } });
  respond("/api/library?limit=100", Promise.reject(new Error("offline")));
  await start;
  const later = context.load("/api/bootstrap?local=1", ["feedback"]);
  respond("/api/bootstrap?local=1", placeholders);
  respond("/api/feedback", { checkins: [{ id: "c1" }] });
  await later;
  context.saveStateSnapshot();
  const stored = context.readStateSnapshot().data;
  assert.deepEqual(plain([stored.performance, stored.library, stored.checkins]), [{ ctl: 41 }, [{ id: "w1" }], [{ id: "c1" }]]);
});

test("loaded state renders as real data, so it may notify", async () => {
  const { context, state, respond } = loader();
  const flags = [];
  context.render = (data) => { state.data = data; flags.push(state.replaceDataOnLoad); };
  state.replaceDataOnLoad = true;
  const loading = context.load("/api/bootstrap", ["performance"]);
  respond("/api/bootstrap", { state_versions: {} });
  respond("/api/performance", { performance: {} });
  await loading;
  assert.deepEqual(flags, [false]);
});

test("shown messages are cached at once as the latest page and replace older snapshot messages", () => {
  const first = loader();
  first.state.initialStateLoaded = true;
  first.state.data = { messages: [{ id: 1, content: "alt" }], messages_generation: "g1" };
  first.context.saveStateSnapshot();
  const messages = Array.from({ length: 25 }, (_, index) => ({ id: index + 1, role: "user", content: `m${index + 1}` }));
  first.context.rememberChatCache({ messages: [...messages, { client_turn_id: "pending", role: "user" }], messages_generation: "g1", messages_next_cursor: null });
  const snapshot = loader({ storage: first.storage }).context.readStateSnapshot();
  assert.equal(snapshot.data.messages.length, vm.runInContext("CHAT_CACHE_LIMIT", first.context));
  assert.deepEqual([snapshot.data.messages[0].id, snapshot.data.messages.at(-1).id], [6, 25]);
  // The server cursor for "before message 6": base64url of the JSON id.
  assert.equal(snapshot.data.messages_next_cursor, Buffer.from("6").toString("base64url"));
  assert.equal(snapshot.data.messages_generation, "g1");
  // A complete page keeps the server cursor; placeholder data is never cached.
  first.context.rememberChatCache({ messages: messages.slice(0, 3), messages_generation: "g1", messages_next_cursor: "older" });
  first.state.replaceDataOnLoad = true;
  first.context.rememberChatCache({ messages: [{ id: 99 }], messages_generation: "g1" });
  const cached = first.context.readChatCache();
  assert.deepEqual([cached.messages.length, cached.next_cursor], [3, "older"]);
  first.context.clearStateSnapshot();
  assert.equal(first.storage.size, 0);
});

test("a full storage drops the view cache before the message cache", () => {
  class FullStorage extends Map {
    set(key, value) {
      if (key === "coach-chat-cache" && this.has("coach-view-cache")) throw new Error("QuotaExceededError");
      return super.set(key, value);
    }
  }
  const { context, state, storage } = loader({ storage: new FullStorage() });
  state.data = {};
  context.rememberViewCache("/api/nutrition/week", { days: [1] }, 0);
  context.rememberChatCache({ messages: [{ id: 1 }] });
  assert.equal(storage.has("coach-view-cache"), false);
  assert.deepEqual(plain(context.readChatCache().messages), [{ id: 1 }]);
});

const saveDelay = (context) => vm.runInContext("STATE_SNAPSHOT_SAVE_DELAY_MS", context) + 50;
const wait = (ms) => new Promise((done) => setTimeout(done, ms));

test("each area is rendered and stored as soon as it arrives, without waiting for a slower one", async () => {
  const { context, state, renders, storage, respond } = loader();
  const loading = context.load("/api/bootstrap", ["library", "performance"]);
  respond("/api/bootstrap", { state_versions: { library: 3, performance: 4 } });
  respond("/api/library?limit=100", { workouts: [{ id: "w1" }], next_cursor: null });
  await wait(saveDelay(context));
  // The delayed performance area is still open: library is shown and stored, versions only for it.
  assert.deepEqual(plain(state.data.library), [{ id: "w1" }]);
  assert.equal(state.data.performance, undefined);
  assert.deepEqual(plain(state.data.state_versions), { library: 3 });
  assert.deepEqual(plain(context.readStateSnapshot().data.library), [{ id: "w1" }]);
  assert.equal(storage.has("coach-state-snapshot"), true);
  respond("/api/performance", { performance: { ctl: 40 } });
  await loading;
  assert.equal(state.data.state_versions.performance, 4);
  assert.equal(renders.length, 2);
  await wait(saveDelay(context));
  const stored = context.readStateSnapshot().data;
  assert.deepEqual(plain([stored.library, stored.performance]), [[{ id: "w1" }], { ctl: 40 }]);
});

test("a partial startup is stored when the app is closed right after an area arrived", async () => {
  const { context, state, respond } = loader();
  const loading = context.load("/api/bootstrap", ["library", "performance"]);
  respond("/api/bootstrap", {});
  respond("/api/library?limit=100", { workouts: [{ id: "w1" }] });
  await wait(0);
  assert.equal(state.initialStateLoaded, false);
  context.saveStateSnapshot();
  assert.deepEqual(plain(context.readStateSnapshot().data.library), [{ id: "w1" }]);
  respond("/api/performance", { performance: {} });
  await loading;
});

test("a failed area keeps its previous snapshot value while the others are stored early", async () => {
  const { context, state, respond } = loader();
  state.initialStateLoaded = true;
  state.data = { performance: { ctl: 40 }, library: [{ id: "old" }] };
  context.saveStateSnapshot();
  state.replaceDataOnLoad = true;
  const loading = context.load("/api/bootstrap", ["library", "performance"]);
  // The bootstrap's placeholders must not replace the pending or failed library.
  respond("/api/bootstrap", { performance: {}, library: [] });
  respond("/api/performance", { performance: { ctl: 41 } });
  await wait(0);
  context.saveStateSnapshot();
  let stored = context.readStateSnapshot().data;
  assert.deepEqual(plain([stored.performance, stored.library]), [{ ctl: 41 }, [{ id: "old" }]]);
  respond("/api/library?limit=100", Promise.reject(new Error("offline")));
  await loading;
  context.saveStateSnapshot();
  stored = context.readStateSnapshot().data;
  assert.deepEqual(plain([stored.performance, stored.library]), [{ ctl: 41 }, [{ id: "old" }]]);
});

test("area responses of a replaced session or load are neither rendered nor stored", async () => {
  const { context, state, renders, storage, respond } = loader();
  const loading = context.load("/api/bootstrap", ["library", "performance"]);
  respond("/api/bootstrap", {});
  respond("/api/library?limit=100", { workouts: [{ id: "w1" }] });
  await wait(0);
  assert.equal(renders.length, 1);
  state.sessionGeneration += 1;
  context.clearStateSnapshot();
  respond("/api/performance", { performance: { ctl: 40 } });
  await loading;
  await wait(saveDelay(context));
  assert.equal(renders.length, 1);
  assert.equal(storage.size, 0);
});

test("a load replaced by a newer one does not render or store its late areas", async () => {
  const { context, state, renders, storage, respond } = loader();
  const loading = context.load("/api/bootstrap", ["library"]);
  respond("/api/bootstrap", {});
  await wait(0);
  state.loadSequence += 1;
  respond("/api/library?limit=100", { workouts: [{ id: "late" }] });
  await loading;
  await wait(saveDelay(context));
  assert.equal(renders.length, 0);
  assert.equal(storage.size, 0);
});

// The Coach shows device-cached messages with a sync note until the fresh load ends.
function syncingLoader() {
  const loaded = loader();
  loaded.state.chatCacheSyncing = true;
  loaded.syncCalls = [];
  loaded.context.setChatCacheSyncing = (value) => { loaded.state.chatCacheSyncing = value; loaded.syncCalls.push(value); };
  loaded.context.showStateLoadFailure = () => {};
  return loaded;
}

test("the cached-message sync note stays until the fresh chat load completes", async () => {
  const { context, state, syncCalls, respond } = syncingLoader();
  const loading = context.load("/api/bootstrap?local=1", ["chat"]);
  respond("/api/bootstrap?local=1", {});
  await Promise.resolve();
  assert.equal(state.chatCacheSyncing, true);
  respond("/api/chat/history?limit=100", { messages: [] });
  await loading;
  assert.deepEqual(syncCalls, [false]);
});

test("the sync note ends with the fresh messages, not with a slower area", async () => {
  const { context, state, syncCalls, respond } = syncingLoader();
  const loading = context.load("/api/bootstrap?local=1", ["chat", "library"]);
  respond("/api/bootstrap?local=1", {});
  respond("/api/chat/history?limit=100", { messages: [] });
  for (let tick = 0; tick < 5; tick += 1) await Promise.resolve();
  assert.equal(state.chatCacheSyncing, false);
  respond("/api/library?limit=100", { workouts: [] });
  await loading;
  assert.deepEqual(syncCalls, [false]);
});

test("a failed start load ends the cached-message sync note", async () => {
  const { context, state, syncCalls } = syncingLoader();
  context.api = () => Promise.reject(new Error("offline"));
  await context.load("/api/bootstrap?local=1", ["chat"]);
  assert.equal(state.chatCacheSyncing, false);
  assert.deepEqual(syncCalls, [false]);
});

test("a live area refresh leaves the cached-message sync note alone", async () => {
  const { context, state, syncCalls, respond } = syncingLoader();
  state.data = { profile: {}, state_versions: {} };
  const loading = context.load(vm.runInContext("LIVE_AREA_REFRESH", context), ["weather"]);
  respond("/api/weather", { days: [] });
  await loading;
  assert.equal(state.chatCacheSyncing, true);
  assert.deepEqual(syncCalls, []);
});

test("a load without the chat area leaves the cached-message sync note alone", async () => {
  const { context, state, syncCalls, respond } = syncingLoader();
  const loading = context.load("/api/bootstrap?local=1", ["library"]);
  respond("/api/bootstrap?local=1", {});
  respond("/api/library?limit=100", { workouts: [] });
  await loading;
  assert.equal(state.chatCacheSyncing, true);
  assert.deepEqual(syncCalls, []);
});

// Starts the next app version from a snapshot stored by the previous one, as the
// "Update wird verarbeitet…" start does: the snapshot is not shown and the
// bootstrap's placeholders replace all data.
async function updateStart(storedData, libraryResponse) {
  const previous = loader({ asset: "/state-loader.js?v=1" });
  previous.state.initialStateLoaded = true;
  previous.state.data = storedData;
  previous.context.saveStateSnapshot();
  const updated = loader({ storage: previous.storage, asset: "/state-loader.js?v=2" });
  assert.equal(updated.context.readStateSnapshot().updated, true);
  updated.state.replaceDataOnLoad = true;
  const loading = updated.context.load("/api/bootstrap", ["performance", "library"]);
  updated.respond("/api/bootstrap", { state_versions: {}, performance: {}, library: [], checkins: [], weather: {} });
  updated.respond("/api/performance", { performance: { ctl: 41 } });
  updated.respond("/api/library?limit=100", libraryResponse);
  await loading;
  return updated;
}

test("after an app update a failed area keeps its stored data", async () => {
  const { context } = await updateStart(
    { performance: { ctl: 40 }, library: [{ id: "w1" }], library_next_cursor: "c1" },
    Promise.reject(new Error("offline")),
  );
  context.saveStateSnapshot();
  const snapshot = context.readStateSnapshot();
  assert.equal(snapshot.updated, false);
  assert.deepEqual(plain([snapshot.data.performance, snapshot.data.library, snapshot.data.library_next_cursor]), [{ ctl: 41 }, [{ id: "w1" }], "c1"]);
});

test("after an app update a later load without the failed area keeps its stored data", async () => {
  const { context, respond } = await updateStart(
    { performance: { ctl: 40 }, library: [{ id: "w1" }] },
    Promise.reject(new Error("offline")),
  );
  context.saveStateSnapshot();
  const later = context.load("/api/bootstrap?local=1", ["feedback"]);
  respond("/api/bootstrap?local=1", { state_versions: {}, library: [] });
  respond("/api/feedback", { checkins: [{ id: "c1" }] });
  await later;
  context.saveStateSnapshot();
  const stored = context.readStateSnapshot().data;
  assert.deepEqual(plain([stored.library, stored.checkins]), [[{ id: "w1" }], [{ id: "c1" }]]);
});

test("after an app update a stored area of another shape is dropped, not replaced by a placeholder", async () => {
  const { context } = await updateStart(
    { performance: { ctl: 40 }, library: { w1: { id: "w1" } } },
    Promise.reject(new Error("offline")),
  );
  context.saveStateSnapshot();
  const stored = context.readStateSnapshot().data;
  assert.equal("library" in stored, false);
  assert.equal("library_next_cursor" in stored, false);
  assert.deepEqual(plain(stored.performance), { ctl: 41 });
});

test("a finished load chain checks a held update reload once it is no longer loading", async () => {
  const { context, respond, updateChecks } = loader();
  const loading = context.load("/api/bootstrap", ["performance"]);
  respond("/api/bootstrap", { state_versions: {} });
  respond("/api/performance", { performance: {} });
  await loading;
  assert.deepEqual(updateChecks, [null]);
});

test("after an app update a loaded area stores its fresh data", async () => {
  const { context } = await updateStart(
    { performance: { ctl: 40 }, library: [{ id: "w1" }] },
    { workouts: [{ id: "w2" }], next_cursor: null },
  );
  context.saveStateSnapshot();
  assert.deepEqual(plain(context.readStateSnapshot().data.library), [{ id: "w2" }]);
});
