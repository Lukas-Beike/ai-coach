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
  const shell = { classList: { contains: () => false, add() {}, remove() {} }, hidden: false };
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
  };
  const context = vm.createContext({
    state,
    document: { currentScript: { src: asset } },
    sessionStorage: {
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
  return { context, state, calls, renders, respond, storage };
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

test("the state snapshot is saved only after a full load and only for the same assets", () => {
  const first = loader();
  first.state.data = { messages: [{ id: 1 }] };
  first.context.saveStateSnapshot();
  assert.equal(first.storage.size, 0);
  first.state.initialStateLoaded = true;
  first.context.saveStateSnapshot();
  assert.deepEqual(plain(loader({ storage: first.storage }).context.readStateSnapshot()), { messages: [{ id: 1 }] });
  assert.equal(loader({ storage: first.storage, asset: "/state-loader.js?v=2" }).context.readStateSnapshot(), null);
  first.context.clearStateSnapshot();
  assert.equal(first.context.readStateSnapshot(), null);
});
