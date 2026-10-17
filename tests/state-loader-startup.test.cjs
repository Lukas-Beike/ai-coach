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
  return { context, state, shell, calls, renders, respond, storage };
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
