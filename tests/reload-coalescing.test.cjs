const assert = require("node:assert/strict");
const vm = require("node:vm");
const { test } = require("node:test");
const { extractFunctions, loadPublicScript } = require("./frontend-harness.cjs");

// Only the status polling of coach.js: the rest needs the whole chat interface.
const STATUS_POLL = ["scheduleChatStatusPoll", "chatStatusJobActive", "chatStatusPollWanted", "stopChatStatusPoll", "loadChatHistoryFresh", "refreshChatProposalsInBackground", "resumeQueuedChat", "chatPollStateIsCurrent", "pendingChatTurn", "pollPendingChatReceipt", "showRunningChatStatus", "finishRecoveredChatStatus", "CHAT_STATUS_SAFETY_POLL_MS", "rescheduleChatStatusPoll", "settleChatStatusPoll", "pollChatStatus", "loadInitialState"];
// The cadence constants of the sync status poll.
const SYNC_POLL_CONSTANTS = ["SYNC_POLL_ACTIVE_MS", "SYNC_POLL_IDLE_MS", "SYNC_POLL_RETRY_MS"];

const BOOTSTRAP = "/api/bootstrap?local=1";
const tick = () => new Promise((resolve) => setImmediate(resolve));

// A manual clock: timers only fire when advance() moves it.
function fakeClock() {
  let now = 0;
  let sequence = 0;
  const timers = new Map();
  const add = (fn, ms, repeat) => {
    const id = ++sequence;
    timers.set(id, { fn, at: now + ms, repeat: repeat ? ms : null });
    return id;
  };
  return {
    get now() { return now; },
    setTimeout: (fn, ms = 0) => add(fn, ms, false),
    setInterval: (fn, ms) => add(fn, ms, true),
    clear: (id) => { timers.delete(id); },
    pending: () => timers.size,
    async advance(ms) {
      const target = now + ms;
      for (;;) {
        const due = [...timers.entries()].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        const [id, timer] = due;
        now = Math.max(now, timer.at);
        if (timer.repeat) timer.at += timer.repeat;
        else timers.delete(id);
        timer.fn();
        await tick();
      }
      now = target;
    },
  };
}

function frontend({ eventSource = false } = {}) {
  const clock = fakeClock();
  const calls = [];
  const pending = [];
  const auto = new Map();
  const sources = [];
  const bootstrap = { state_versions: {} };
  const shell = { classList: { contains: () => false, add() {}, remove() {} } };
  const statusElements = {};
  const statusUpdates = [];
  const bodies = {
    [BOOTSTRAP]: () => ({ ...bootstrap }),
    "/api/plan?local=1": () => ({}),
    "/api/performance": () => ({ performance: {} }),
    "/api/library?limit=100": () => ({ workouts: [] }),
    "/api/chat/history?limit=100": () => ({}),
    "/api/profile": () => ({ profile: {}, competitions: [] }),
    "/api/feedback": () => ({}),
  };
  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.listeners = {};
      this.closed = false;
      sources.push(this);
    }
    addEventListener(name, listener) { this.listeners[name] = listener; }
    close() { this.closed = true; }
  }
  const context = loadPublicScript(["state.js", "state-loader.js", "sync-status.js"], {
    crypto: { randomUUID: () => "test" },
    document: { scripts: [], currentScript: { src: "" }, visibilityState: "visible" },
    navigator: { onLine: true },
    performance: { now: () => clock.now },
    Date: { now: () => clock.now, parse: Date.parse },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    AppApi: { messageForReason: () => "" },
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clear,
    setInterval: clock.setInterval,
    clearInterval: clock.clear,
    $: (selector) => (selector === "#appShell" ? shell : statusElements[selector] || null),
    currentPlanLoadAreas: () => ["chat"],
    applyChatResult() {},
    renderCompetitionReadStatus() {},
    finishAppShellLoading() {},
    renderPerformance() {},
    renderSettings() {},
    renderQuickMessageTemplates() {},
    updateStatusSources(changes) { statusUpdates.push(changes); },
    updateChatControls() {},
    AppRouter: { routeFromHash: () => "coach", planSegmentFromRoute: () => "overview", baseRoute: () => "coach" },
    AppState: { setPlanSegment() {} },
    retryBootstrapAuth() {},
    scrollChatToLatest() {},
    reloadForUpdateWhenSafe() {},
    renderMessages() {},
    rememberChatTurn() {},
    api(requestPath) {
      calls.push(requestPath);
      if (auto.has(requestPath)) return Promise.resolve(auto.get(requestPath));
      return new Promise((resolve, reject) => pending.push({ path: requestPath, resolve, reject }));
    },
    ...(eventSource ? { EventSource: FakeEventSource } : {}),
  });
  extractFunctions("shared.js", SYNC_POLL_CONSTANTS, context);
  extractFunctions("coach.js", STATUS_POLL, context);
  extractFunctions("connection-status.js", ["connectionsShown"], context);
  const state = vm.runInContext("state", context);
  context.render = (data) => { state.data = data; };
  state.data = { provider_ids: { garmin: "garmin" }, state_versions: {}, messages: [] };
  // Answers the requests in flight once, so a follow-up load stays observable.
  const respondOnce = async () => {
    await tick();
    pending.splice(0).forEach((request) => request.resolve(bodies[request.path]?.() ?? {}));
    await tick();
  };
  const settle = async () => {
    for (let round = 0; round < 10; round += 1) {
      await respondOnce();
      if (!pending.length) break;
    }
  };
  const count = (requestPath) => calls.filter((call) => call === requestPath).length;
  return { context, state, clock, calls, pending, auto, sources, bootstrap, statusElements, statusUpdates, respondOnce, settle, count };
}

const event = (type, payload = {}, lastEventId = "") => ({ type, data: JSON.stringify(payload), lastEventId });

test("sync status refreshes Yazio only while the connections panel is shown", () => {
  const app = frontend();
  const panel = { open: true };
  app.context.connectionsShown = () => panel.open;
  let checks = 0;
  app.context.loadYazioStatus = async () => { checks += 1; };
  app.context.handleSyncStatus({ running: false });
  assert.equal(checks, 1);
  panel.open = false;
  app.context.handleSyncStatus({ running: false });
  assert.equal(checks, 1);
});

test("reloads requested during a load run as one follow-up", async () => {
  const app = frontend();
  const first = app.context.requestBackgroundLoad(BOOTSTRAP, ["plan"]);
  await tick();
  assert.equal(app.count(BOOTSTRAP), 1);
  for (let index = 0; index < 5; index += 1) app.context.requestBackgroundLoad(BOOTSTRAP, ["plan", "performance"]);
  await tick();
  assert.equal(app.count(BOOTSTRAP), 1);
  await app.respondOnce();
  await app.respondOnce();
  assert.equal(app.count(BOOTSTRAP), 2);
  await app.settle();
  await first;
  assert.equal(app.count(BOOTSTRAP), 2);
  assert.equal(app.count("/api/plan?local=1"), 2);
  assert.equal(app.count("/api/performance"), 1);
});

test("a server version that is already requested is not requested again", async () => {
  const app = frontend();
  app.state.data.state_versions = { plan: 1 };
  app.bootstrap.state_versions = { plan: 2 };
  const status = () => ({ running: false, state_versions: { plan: 2 } });
  app.context.handleSyncStatus(status());
  await tick();
  for (let index = 0; index < 4; index += 1) app.context.handleSyncStatus(status());
  await tick();
  assert.equal(app.count(BOOTSTRAP), 1);
  assert.equal(app.state.data.state_versions.plan, 1, "a requested version is only recorded by its load");
  await app.settle();
  assert.equal(app.state.data.state_versions.plan, 2);
  assert.deepEqual(JSON.parse(JSON.stringify(app.state.requestedStateVersions)), {});
  app.context.handleSyncStatus(status());
  await app.settle();
  assert.equal(app.count(BOOTSTRAP), 1);
});

test("a live load records the version it was started for, not one that arrived while it ran", async () => {
  const app = frontend();
  const CHAT = "/api/chat/history?limit=100";
  app.state.busy = true;
  app.state.data.state_versions = { chat: 1 };
  app.context.handleSyncStatus({ running: false, state_versions: { chat: 2 } });
  await tick();
  assert.equal(app.count(CHAT), 1);
  app.context.handleSyncStatus({ running: false, state_versions: { chat: 3 } });
  await tick();
  app.pending.shift().resolve({});
  await tick();
  await tick();
  assert.equal(app.state.data.state_versions.chat, 2, "the first read only covers version 2");
  assert.equal(app.count(CHAT), 2);
  // The follow-up for version 3 fails, so version 3 stays unread.
  app.pending.shift().reject(new Error("timeout"));
  await app.state.loadPromise?.catch(() => {});
  await tick();
  assert.equal(app.state.data.state_versions.chat, 2);
  assert.equal(app.statusUpdates.at(-1).load_failure.detail, "chat: timeout");
  // A failed first load must not leave the loading notice in front of the error.
  assert.equal(app.statusUpdates.at(-1).loading, null);
  app.context.handleSyncStatus({ running: false, state_versions: { chat: 3 } });
  await tick();
  assert.equal(app.count(CHAT), 3, "the next poll retries the unread version");
  await app.settle();
  assert.equal(app.state.data.state_versions.chat, 3);
});

test("state events replayed before the first ready do not reload the loaded app", async () => {
  const app = frontend();
  app.context.handleStateEvent(event("reset", {}, "1"));
  app.context.handleStateEvent(event("coach", { status: "changed" }, "2"));
  app.context.handleStateEvent(event("planning", {}, "3"));
  await app.clock.advance(1_000);
  assert.equal(app.calls.length, 0);
  app.context.handleStateEvent(event("ready", { latest_event_id: 3 }));
  assert.equal(app.state.stateEventLastId, 3);
  assert.equal(app.state.stateEventBaselined, true);
  app.context.handleStateEvent(event("planning", {}, "4"));
  app.context.handleStateEvent(event("sync", { status: "completed" }, "5"));
  app.context.handleStateEvent(event("planning", {}, "6"));
  await app.clock.advance(400);
  await app.settle();
  assert.equal(app.count(BOOTSTRAP), 1);
  assert.equal(app.count("/api/plan?local=1"), 1);
  assert.equal(app.count("/api/library?limit=100"), 1);
});

test("a reconnect after the app was loaded replays the events it missed", async () => {
  const app = frontend({ eventSource: true });
  app.context.connectStateEvents();
  app.sources[0].listeners.ready(event("ready", { latest_event_id: 7 }));
  app.sources[0].onerror();
  assert.equal(app.sources[0].closed, true);
  await app.clock.advance(1_000);
  assert.equal(app.sources.length, 2);
  assert.match(app.sources[1].url, /since=7$/);
  app.sources[1].listeners.planning(event("planning", {}, "8"));
  await app.clock.advance(400);
  await app.settle();
  assert.equal(app.count(BOOTSTRAP), 1);
});

test("the status is not polled every 1.5 seconds while the event stream is healthy", async () => {
  const app = frontend({ eventSource: true });
  app.auto.set("/api/chat/status", { status: "running", operation_id: "op-1" });
  app.state.busy = true;
  app.context.connectStateEvents();
  app.sources[0].listeners.ready(event("ready", { latest_event_id: 1 }));
  assert.equal(app.context.stateEventStreamHealthy(), true);
  app.context.scheduleChatStatusPoll(0);
  await app.clock.advance(0);
  assert.equal(app.count("/api/chat/status"), 1);
  await app.clock.advance(14_000);
  assert.equal(app.count("/api/chat/status"), 1);
  app.sources[0].listeners.heartbeat(event("heartbeat"));
  await app.clock.advance(1_100);
  assert.equal(app.count("/api/chat/status"), 2, "a slow safety check remains");
  // A Coach event from the stream checks the status at once.
  app.sources[0].listeners.coach(event("coach", { role: "assistant", message_id: 3 }, "2"));
  await app.clock.advance(0);
  assert.equal(app.count("/api/chat/status"), 3);
});

test("the status is polled every 1.5 seconds without a healthy event stream", async () => {
  const unsupported = frontend();
  unsupported.auto.set("/api/chat/status", { status: "running", operation_id: "op-1" });
  unsupported.state.busy = true;
  assert.equal(unsupported.context.stateEventStreamHealthy(), false);
  unsupported.context.scheduleChatStatusPoll(0);
  await unsupported.clock.advance(0);
  await unsupported.clock.advance(3_000);
  assert.equal(unsupported.count("/api/chat/status"), 3);

  const stale = frontend({ eventSource: true });
  stale.auto.set("/api/chat/status", { status: "running", operation_id: "op-1" });
  stale.state.busy = true;
  stale.context.connectStateEvents();
  stale.sources[0].listeners.ready(event("ready", { latest_event_id: 1 }));
  await stale.clock.advance(50_000);
  assert.equal(stale.context.stateEventStreamHealthy(), false, "no heartbeat for three intervals");
  stale.context.scheduleChatStatusPoll(0);
  await stale.clock.advance(0);
  await stale.clock.advance(1_500);
  assert.equal(stale.count("/api/chat/status"), 2);

  const errored = frontend({ eventSource: true });
  errored.auto.set("/api/chat/status", { status: "running", operation_id: "op-1" });
  errored.state.busy = true;
  errored.context.connectStateEvents();
  errored.sources[0].listeners.ready(event("ready", { latest_event_id: 1 }));
  errored.context.scheduleChatStatusPoll(0);
  await errored.clock.advance(0);
  assert.equal(errored.count("/api/chat/status"), 1);
  errored.sources[0].onerror();
  assert.equal(errored.context.stateEventStreamHealthy(), false);
  await errored.clock.advance(0);
  assert.equal(errored.count("/api/chat/status"), 2, "the fallback starts when the stream fails");
  await errored.clock.advance(1_500);
  assert.equal(errored.count("/api/chat/status"), 3);
});

test("background reloads wait while the Coach works and run once after 60 seconds", async () => {
  const app = frontend();
  app.state.busy = true;
  app.context.requestBackgroundLoad(BOOTSTRAP, ["plan"]);
  app.context.requestBackgroundLoad(BOOTSTRAP, ["performance", "library"]);
  app.context.requestBackgroundLoad(BOOTSTRAP, ["plan"]);
  await app.clock.advance(59_000);
  assert.equal(app.calls.length, 0);
  await app.clock.advance(1_000);
  await app.settle();
  assert.equal(app.count(BOOTSTRAP), 1);
  assert.equal(app.count("/api/plan?local=1"), 1);
  assert.equal(app.count("/api/performance"), 1);
  assert.equal(app.count("/api/library?limit=100"), 1);
  assert.equal(app.state.deferredLoad, null);
  await app.clock.advance(120_000);
  assert.equal(app.count(BOOTSTRAP), 1, "the deferral timers are gone");
});

test("background reloads run once as soon as the Coach turn ends", async () => {
  const app = frontend();
  app.state.busy = true;
  app.context.requestBackgroundLoad(BOOTSTRAP, ["plan"]);
  await app.clock.advance(10_000);
  assert.equal(app.calls.length, 0);
  app.state.busy = false;
  await app.clock.advance(1_000);
  await app.settle();
  assert.equal(app.count(BOOTSTRAP), 1);
  await app.clock.advance(120_000);
  assert.equal(app.count(BOOTSTRAP), 1);
});

test("athlete actions and the live transcript do not wait for a busy Coach", async () => {
  const action = frontend();
  action.state.busy = true;
  const loading = action.context.load(BOOTSTRAP, ["plan"]);
  await tick();
  assert.equal(action.count(BOOTSTRAP), 1);
  await action.settle();
  await loading;

  const live = frontend();
  live.state.busy = true;
  live.context.requestBackgroundLoad(BOOTSTRAP, ["chat", "profile"]);
  await live.settle();
  assert.equal(live.count("/api/chat/history?limit=100"), 1);
  assert.equal(live.count("/api/profile"), 1);
  assert.equal(live.count(BOOTSTRAP), 0, "only the live areas are read");
  assert.equal(live.state.deferredLoad, null);
});

test("leaving the session drops the waiting background reloads", async () => {
  const app = frontend();
  app.state.busy = true;
  app.context.requestBackgroundLoad(BOOTSTRAP, ["plan"]);
  assert.notEqual(app.state.deferredLoad, null);
  app.context.cancelDeferredLoads();
  assert.equal(app.state.deferredLoad, null);
  assert.equal(app.clock.pending(), 0);
  await app.clock.advance(120_000);
  assert.equal(app.calls.length, 0);
});

test("a Coach event during a status check checks again as soon as that check ends", async () => {
  const app = frontend({ eventSource: true });
  app.state.busy = true;
  app.context.connectStateEvents();
  app.sources[0].listeners.ready(event("ready", { latest_event_id: 1 }));
  app.context.scheduleChatStatusPoll(0);
  await app.clock.advance(0);
  assert.equal(app.count("/api/chat/status"), 1);
  // The answer is committed while the first check is still waiting for its "running" reply.
  app.sources[0].listeners.coach(event("coach", { role: "assistant", message_id: 3 }, "2"));
  await app.clock.advance(400);
  assert.equal(app.count("/api/chat/status"), 1, "only one check runs at a time");
  app.auto.set("/api/chat/status", { status: "running", operation_id: "op-1" });
  await app.respondOnce();
  await app.clock.advance(0);
  assert.equal(app.count("/api/chat/status"), 2, "the event is not left to the slow safety check");
});

test("a live transcript load during a Coach turn records the version it was requested for", async () => {
  const app = frontend();
  app.state.busy = true;
  app.state.data.state_versions = { chat: 1 };
  const status = () => ({ running: false, state_versions: { chat: 2 } });
  app.context.handleSyncStatus(status());
  await app.settle();
  assert.equal(app.count("/api/chat/history?limit=100"), 1);
  assert.equal(app.state.data.state_versions.chat, 2);
  for (let index = 0; index < 3; index += 1) {
    app.context.handleSyncStatus(status());
    await app.settle();
  }
  assert.equal(app.count("/api/chat/history?limit=100"), 1, "the same chat version is read once");
});

test("a status check that still reads a finished turn as running looks again shortly", async () => {
  const app = frontend({ eventSource: true });
  Object.assign(app.context, { loadChatHistoryFresh: async () => {}, resumeQueuedChat() {}, scrollChatToResponseStart() {} });
  app.auto.set("/api/chat/status", { status: "running", operation_id: "op-1" });
  app.context.connectStateEvents();
  app.sources[0].listeners.ready(event("ready", { latest_event_id: 1 }));
  // Another device's turn ends; its stream has not closed yet, so the server still reports it.
  app.sources[0].listeners.coach(event("coach", { role: "assistant", message_id: 3 }, "2"));
  await app.clock.advance(0);
  assert.equal(app.count("/api/chat/status"), 1);
  assert.equal(app.state.busy, true);
  app.auto.set("/api/chat/status", { status: "idle" });
  await app.clock.advance(1_500);
  assert.equal(app.count("/api/chat/status"), 2, "the stale running state is not kept for the slow interval");
  await app.clock.advance(60_000);
  assert.equal(app.count("/api/chat/status"), 2, "an idle chat stops checking");
});

test("a started turn keeps the slow check while the event stream is healthy", async () => {
  const app = frontend({ eventSource: true });
  app.auto.set("/api/chat/status", { status: "running", operation_id: "op-1" });
  app.context.connectStateEvents();
  app.sources[0].listeners.ready(event("ready", { latest_event_id: 1 }));
  app.sources[0].listeners.coach(event("coach", { role: "user", message_id: 2 }, "2"));
  await app.clock.advance(0);
  await app.clock.advance(14_000);
  assert.equal(app.count("/api/chat/status"), 1);
});

test("a silently stalled event stream switches to the fast check once it counts as stale", async () => {
  const app = frontend({ eventSource: true });
  app.auto.set("/api/chat/status", { status: "running", operation_id: "op-1" });
  app.state.busy = true;
  app.context.connectStateEvents();
  app.sources[0].listeners.ready(event("ready", { latest_event_id: 1 }));
  await app.clock.advance(10_000);
  app.context.scheduleChatStatusPoll(0);
  await app.clock.advance(0);
  // No heartbeat and no error: checks at 25 s, 40 s and the stale point at 45 s.
  await app.clock.advance(35_000);
  assert.equal(app.count("/api/chat/status"), 4);
  assert.equal(app.context.stateEventStreamHealthy(), false);
  await app.clock.advance(1_500);
  assert.equal(app.count("/api/chat/status"), 5, "the fast check starts at the stale point");
});

const AREAS_OF_RESET = ["chat", "plan", "library", "performance", "feedback", "profile"];
const AREA_READS = {
  chat: "/api/chat/history?limit=100",
  plan: "/api/plan?local=1",
  library: "/api/library?limit=100",
  performance: "/api/performance",
  feedback: "/api/feedback",
  profile: "/api/profile",
};

test("a changed server version reloads the areas that show it", () => {
  const app = frontend();
  const areasOf = (versions) => [...app.context.changedSyncAreas(versions)].sort();
  assert.deepEqual(areasOf({ garmin: 1 }), ["performance", "plan"]);
  assert.deepEqual(areasOf({ checkins: 1 }), ["feedback", "plan"]);
  assert.deepEqual(areasOf({ activity_feedback: 1 }), ["feedback", "performance", "plan"]);
  assert.deepEqual(areasOf({ activities: 1 }), ["performance", "plan", "profile"]);
  assert.deepEqual(areasOf({ library: 1 }), ["library", "plan"]);
  // A zone save on another device moves the performance version (#2479).
  assert.deepEqual(areasOf({ performance: 1 }), ["performance", "plan"]);
  assert.deepEqual(areasOf({ chat: 1, profile: 1 }), ["chat", "performance", "profile"]);
  // A version the page already shows reloads nothing.
  app.state.data.state_versions = { checkins: 1 };
  assert.deepEqual(areasOf({ checkins: 1 }), []);
});

test("a reset event after the first ready reloads every area and the start data", async () => {
  const app = frontend();
  app.context.handleStateEvent(event("ready", { latest_event_id: 1 }));
  app.context.handleStateEvent(event("reset", {}, "2"));
  await app.clock.advance(400);
  await app.settle();
  assert.equal(app.count(BOOTSTRAP), 1);
  for (const area of AREAS_OF_RESET) assert.equal(app.count(AREA_READS[area]), 1, area);
});

test("the sync status is read every 1.5 seconds while a sync runs and slowly when idle", async () => {
  const app = frontend();
  app.context.AbortController = AbortController;
  const STATUS = "/api/sync/status";
  app.auto.set(STATUS, { running: true, state_versions: {} });
  app.context.setupSyncStatusMonitoring();
  await app.clock.advance(0);
  assert.equal(app.count(STATUS), 1);
  await app.clock.advance(1_500);
  assert.equal(app.count(STATUS), 2);
  await app.clock.advance(3_000);
  assert.equal(app.count(STATUS), 4);
  app.auto.set(STATUS, { running: false, state_versions: {} });
  await app.clock.advance(1_500);
  assert.equal(app.count(STATUS), 5);
  await app.clock.advance(59_000);
  assert.equal(app.count(STATUS), 5, "an idle app waits a minute");
  await app.clock.advance(1_000);
  assert.equal(app.count(STATUS), 6);
});

test("the start reads the local bootstrap with every area, then refreshes the weather", async () => {
  const app = frontend();
  app.auto.set("/api/profile", { profile: { weather_location: "Berlin" }, competitions: [] });
  let loadedWhenWeatherWasRead = null;
  const read = app.context.api;
  app.context.api = (requestPath, options) => {
    if (requestPath.startsWith("/api/weather")) loadedWhenWeatherWasRead = app.state.initialStateLoaded;
    return read(requestPath, options);
  };
  app.state.initialStateLoaded = true;
  const starting = app.context.loadInitialState();
  assert.equal(app.state.initialStateLoaded, false, "the start is not loaded while it reads");
  await app.settle();
  await starting;
  assert.equal(app.count(BOOTSTRAP), 1);
  for (const area of AREAS_OF_RESET) assert.equal(app.count(AREA_READS[area]), 1, area);
  assert.equal(app.state.initialStateLoaded, true);
  assert.equal(loadedWhenWeatherWasRead, true, "the weather refresh follows the loaded start");
});

test("a session that ended while the start was reading leaves the start unloaded", async () => {
  const app = frontend();
  app.auto.set("/api/profile", { profile: { weather_location: "Berlin" }, competitions: [] });
  const starting = app.context.loadInitialState();
  await app.clock.advance(0);
  app.state.sessionGeneration += 1;
  await app.settle();
  await starting;
  assert.equal(app.state.initialStateLoaded, false);
  assert.equal(app.calls.some((call) => call.startsWith("/api/weather")), false);
});
