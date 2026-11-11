const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadPublicScript } = require("./frontend-harness.cjs");

const plain = (value) => JSON.parse(JSON.stringify(value));

// A panel or nav item that records what the router does to it.
function element(dataset = {}) {
  const classes = new Set();
  const attributes = {};
  const focused = [];
  return {
    dataset, classes, attributes, focused,
    classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name) },
    setAttribute: (name, value) => { attributes[name] = value; },
    removeAttribute: (name) => { delete attributes[name]; },
    focus: (options) => focused.push(options),
  };
}

// State and navigation run in one context, with a small page of five nav items and their panels.
function router({ hash = "" } = {}) {
  const panels = new Map(["chatPanel", "workoutsPanel", "nutritionPanel", "dataPanel", "settingsPanel", "profilePanel"].map((id) => [id, element()]));
  const items = new Map([["coach", "chatPanel"], ["plan", "workoutsPanel"], ["nutrition", "nutritionPanel"], ["analysis", "dataPanel"], ["more", "settingsPanel"]]
    .map(([route, panel]) => [route, element({ route, panel })]));
  const listeners = [];
  const history = [];
  const location = { hash };
  const document = {
    querySelectorAll(selector) {
      if (selector === ".nav-item, .panel") return [...items.values(), ...panels.values()];
      if (selector === ".nav-item") return [...items.values()];
      const route = /data-route="([^"]+)"/.exec(selector)?.[1];
      return items.has(route) ? [items.get(route)] : [];
    },
    querySelector(selector) {
      const route = /data-route="([^"]+)"/.exec(selector)?.[1];
      if (route) return items.get(route) || null;
      if (selector === "#appShell") return { hidden: false };
      if (selector === ".nav-item.active") return [...items.values()].find((item) => item.classes.has("active")) || null;
      return panels.get(selector.slice(1)) || null;
    },
  };
  const context = loadPublicScript(["state.js", "navigation.js"], {
    crypto: { randomUUID: () => "00000000-0000-4000-8000-000000000000" },
    document, location,
    history: { pushState: (...args) => { history.push(["push", ...args]); location.hash = args[2]; }, replaceState: (...args) => { history.push(["replace", ...args]); location.hash = args[2]; } },
    addEventListener: (type, handler) => listeners.push([type, handler]),
    scrollY: 0,
  });
  const calls = [];
  const handlers = {
    unsaved: false, confirm: true,
    hasUnsavedChanges: () => handlers.unsaved,
    confirmDiscardChanges: async () => handlers.confirm,
    discardUnsavedChanges: () => calls.push("discard"),
    renderActiveRoute: (...args) => calls.push(["render", ...args]),
    renderStatus: () => {},
    restoreRouteScroll: () => {},
    ensureRouteData: (route) => calls.push(["data", route]),
  };
  return { context, panels, items, listeners, history, location, handlers, calls };
}

test("the app state starts with its defaults and a tab-bound token", () => {
  const { context } = router();
  const state = context.AppState.state;
  assert.ok(Object.isFrozen(context.AppState));
  assert.equal(state.chatScrollRestoring, false);
  assert.equal(state.planSegment, "overview");
  assert.equal(state.route, null);
  assert.equal(state.syncPoll.leaseToken, "tab-00000000-0000-4000-8000-000000000000");
  assert.throws(() => loadPublicScript("state.js", {}), /Secure random generator unavailable/);
});

test("the route and plan segment are set through the state owner", () => {
  const { context } = router();
  assert.equal(context.AppState.setRoute("plan/library"), "plan/library");
  assert.equal(context.AppState.setPlanSegment("season"), "season");
  assert.deepEqual([context.AppState.state.route, context.AppState.state.planSegment], ["plan/library", "season"]);
});

test("the routes name their panels and the segments the views offer", () => {
  const { context } = router();
  const { routes, planSegments, moreSegments, linkRoutes, defaultRoute } = context.AppNavigation;
  assert.ok(Object.isFrozen(context.AppNavigation));
  assert.deepEqual(plain(planSegments), ["overview", "library", "season"]);
  assert.deepEqual(plain(moreSegments), ["profile", "equipment", "connections", "coach", "operations", "appearance"]);
  assert.deepEqual(plain(Object.keys(linkRoutes)), ["coach", "plan", "nutrition", "analysis", "more"]);
  assert.equal(defaultRoute, "coach");
  assert.equal(routes.plan, "workoutsPanel");
  assert.equal(routes["plan/overview"], "workoutsPanel");
  assert.equal(routes["plan/library"], "workoutsPanel");
  assert.equal(routes.analysis, "dataPanel");
  assert.equal(routes["analysis/performance"], "dataPanel");
  assert.equal(routes["more/profile"], "profilePanel");
});

test("a hash names a known route in any case, and a removed route falls back to the Coach", () => {
  const { context } = router();
  const { routeFromHash, hashContainsKnownRoute } = context.AppRouter;
  assert.equal(routeFromHash("#Plan/Overview"), "plan/overview");
  assert.equal(routeFromHash("#analysis/performance"), "analysis/performance");
  for (const removed of ["#today", "#activities", "#planned", "#performance", "#analysis/history", "", "#unknown"]) {
    assert.equal(routeFromHash(removed), "coach", removed);
    assert.equal(hashContainsKnownRoute(removed), false, removed);
  }
  assert.equal(hashContainsKnownRoute("#more"), true);
});

test("the route parts fall back to the first plan segment and the connections section", () => {
  const { context } = router();
  const { planSegmentFromRoute, moreSegmentFromRoute, baseRoute } = context.AppRouter;
  assert.equal(planSegmentFromRoute("plan/library"), "library");
  assert.equal(planSegmentFromRoute("plan/other"), "overview");
  assert.equal(moreSegmentFromRoute("more/operations"), "operations");
  assert.equal(moreSegmentFromRoute("more"), "connections");
  assert.equal(baseRoute("analysis/performance"), "analysis");
  assert.equal(baseRoute(null), "coach");
});

test("the router needs every handler before it navigates and listens to the hash once", async () => {
  const { context, handlers, listeners } = router();
  await assert.rejects(context.AppRouter.navigate("plan"), /AppRouter is not configured/);
  assert.throws(() => context.AppRouter.configure({ ...handlers, ensureRouteData: undefined }), /requires all navigation handlers/);
  assert.throws(() => context.AppRouter.configure(null), /requires all navigation handlers/);
  assert.equal(listeners.length, 0);
  context.AppRouter.configure(handlers);
  context.AppRouter.configure(handlers);
  assert.deepEqual(listeners.map(([type]) => type), ["hashchange"]);
  assert.equal(listeners[0][1], context.AppRouter.syncFromHash);
});

test("navigating shows the panel and its nav item, records the history and focuses the panel", async () => {
  const { context, handlers, panels, items, history, calls } = router();
  context.AppRouter.configure(handlers);
  assert.equal(await context.AppRouter.navigate("plan/library", { historyMode: "push" }), true);
  assert.equal(context.AppState.state.route, "plan/library");
  assert.equal(panels.get("workoutsPanel").classes.has("active"), true);
  assert.equal(panels.get("chatPanel").classes.has("active"), false);
  assert.equal(items.get("plan").attributes["aria-current"], "page");
  assert.equal(items.get("coach").attributes["aria-current"], undefined);
  assert.deepEqual(plain(history), [["push", { route: "plan/library" }, "", "#plan/library"]]);
  assert.deepEqual(plain(calls), [["render", "plan", "plan/library"], ["data", "plan/library"]]);
  assert.equal(panels.get("workoutsPanel").attributes.tabindex, "-1");
  assert.deepEqual(plain(panels.get("workoutsPanel").focused), [{ preventScroll: true }]);
});

test("an unknown route opens the Coach, and a hash change applies the hash route", async () => {
  const { context, handlers, panels, location } = router();
  context.AppRouter.configure(handlers);
  await context.AppRouter.navigate("nowhere");
  assert.equal(context.AppState.state.route, "coach");
  assert.equal(panels.get("chatPanel").classes.has("active"), true);
  location.hash = "#analysis/performance";
  await context.AppRouter.syncFromHash();
  assert.equal(context.AppState.state.route, "analysis/performance");
  assert.equal(panels.get("dataPanel").classes.has("active"), true);
});

test("leaving a panel with unsaved changes asks first and stays when the athlete declines", async () => {
  const { context, handlers, calls } = router();
  context.AppRouter.configure(handlers);
  await context.AppRouter.navigate("coach");
  handlers.unsaved = true;
  handlers.confirm = false;
  calls.length = 0;
  assert.equal(await context.AppRouter.navigate("plan"), false);
  assert.equal(context.AppState.state.route, "coach");
  assert.deepEqual(plain(calls), []);
  handlers.confirm = true;
  assert.equal(await context.AppRouter.navigate("plan"), true);
  assert.equal(context.AppState.state.route, "plan");
  assert.equal(calls[0], "discard");
});
