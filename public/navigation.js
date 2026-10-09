const NAV_ROUTES = Object.freeze({
  coach: "chatPanel",
  plan: "workoutsPanel",
  "plan/overview": "workoutsPanel",
  "plan/library": "workoutsPanel",
  "plan/season": "workoutsPanel",
  nutrition: "nutritionPanel",
  "nutrition/diary": "nutritionPanel",
  "nutrition/meals": "nutritionPanel",
  "nutrition/products": "nutritionPanel",
  analysis: "dataPanel",
  "analysis/performance": "dataPanel",
  "analysis/load": "dataPanel",
  "analysis/body": "dataPanel",
  "analysis/recovery": "dataPanel",
  more: "settingsPanel",
  "more/connections": "settingsPanel",
  "more/coach": "settingsPanel",
  "more/privacy": "settingsPanel",
  "more/operations": "settingsPanel",
  "more/appearance": "settingsPanel",
  "more/profile": "profilePanel",
  "more/equipment": "settingsPanel",
});
const NAV_LINK_ROUTES = Object.freeze({
  coach: "coach",
  plan: "plan",
  nutrition: "nutrition",
  analysis: "analysis",
  more: "more",
});
const DEFAULT_NAV_ROUTE = "coach";
const PLAN_SEGMENTS = Object.freeze(["overview", "library", "season"]);
const MORE_SEGMENTS = Object.freeze(["profile", "equipment", "connections", "coach", "privacy", "operations", "appearance"]);

globalThis.AppNavigation = Object.freeze({
  routes: NAV_ROUTES,
  linkRoutes: NAV_LINK_ROUTES,
  defaultRoute: DEFAULT_NAV_ROUTE,
  planSegments: PLAN_SEGMENTS,
  moreSegments: MORE_SEGMENTS,
});

globalThis.AppRouter = (() => {
  const { routes, linkRoutes, defaultRoute, planSegments, moreSegments } = AppNavigation;
  let handlers = {};
  let configured = false;
  let hashchangeRegistered = false;

  function routeFromHash(hash = globalThis.location.hash) {
    const rawRoute = String(hash || "").replace(/^#/, "").toLowerCase();
    return Object.hasOwn(routes, rawRoute) ? rawRoute : defaultRoute;
  }

  function hashContainsKnownRoute(hash = globalThis.location.hash) {
    const rawRoute = String(hash || "").replace(/^#/, "").toLowerCase();
    return Object.hasOwn(routes, rawRoute);
  }

  function planSegmentFromRoute(route = AppState.state.route) {
    const segment = String(route || "").split("/")[1];
    return planSegments.includes(segment) ? segment : planSegments[0];
  }

  function baseRoute(route = AppState.state.route) {
    return String(route || defaultRoute).split("/")[0];
  }

  function moreSegmentFromRoute(route = AppState.state.route) {
    const segment = String(route || "").split("/")[1];
    return moreSegments.includes(segment) ? segment : moreSegments[2];
  }

  function activatePanel(panelRoute, navigationRoute) {
    document.querySelectorAll(".nav-item, .panel").forEach((node) => node.classList.remove("active"));
    const navigation = document.querySelector(`.nav-item[data-route="${navigationRoute}"]`);
    const panel = document.querySelector(`#${routes[panelRoute]}`);
    if (!navigation || !panel) return null;
    document.querySelectorAll(".nav-item").forEach((item) => item.removeAttribute("aria-current"));
    document.querySelectorAll(`.nav-item[data-route="${navigationRoute}"]`).forEach((item) => {
      item.classList.add("active");
      item.setAttribute("aria-current", "page");
    });
    panel.classList.add("active");
    return panel;
  }

  function updateHistory(panelRoute, historyMode) {
    const targetHash = `#${panelRoute}`;
    if (globalThis.location.hash === targetHash) return;
    if (historyMode === "push") globalThis.history.pushState({ route: panelRoute }, "", targetHash);
    else if (historyMode === "replace") globalThis.history.replaceState({ route: panelRoute }, "", targetHash);
  }

  async function navigate(route, { historyMode = "none", focus = true } = {}) {
    if (!configured) throw new Error("AppRouter is not configured");
    const state = AppState.state;
    const panelRoute = routes[route] ? route : defaultRoute;
    const mainRoute = baseRoute(panelRoute);
    const shouldFocusPlannedToday = mainRoute === "plan" && planSegmentFromRoute(panelRoute) === "overview";
    const navigationRoute = linkRoutes[mainRoute] || mainRoute;
    const currentPanel = document.querySelector(".nav-item.active")?.dataset.panel || "chatPanel";
    if (currentPanel !== routes[panelRoute] && handlers.hasUnsavedChanges({ includeChatDraft: false })) {
      if (!(await handlers.confirmDiscardChanges())) return false;
      handlers.discardUnsavedChanges();
    }
    const returningToChat = currentPanel !== "chatPanel" && mainRoute === "coach";
    if (state.data && !state.chatInitialScrollPending && historyMode === "push" && currentPanel === "chatPanel" && mainRoute !== "coach") {
      state.chatScrollY = globalThis.scrollY;
    }
    if (currentPanel === "chatPanel" && mainRoute !== "coach" && (state.chatRequest || state.chatServerOperationId)) state.chatResponseScrollPending = true;
    const panel = activatePanel(panelRoute, navigationRoute);
    if (!panel) return false;
    state.plannedTodayFocusPending = shouldFocusPlannedToday;
    AppState.setRoute(panelRoute);
    handlers.renderActiveRoute(mainRoute, panelRoute);
    updateHistory(panelRoute, historyMode);
    if (state.data) handlers.renderStatus(state.data);
    handlers.restoreRouteScroll(mainRoute, returningToChat, shouldFocusPlannedToday);
    handlers.ensureRouteData(panelRoute);
    if (focus && !document.querySelector("#appShell")?.hidden) {
      panel.setAttribute("tabindex", "-1");
      panel.focus({ preventScroll: true });
    }
    return true;
  }

  async function syncFromHash() {
    const route = routeFromHash();
    const applied = await navigate(route, {
      historyMode: !hashContainsKnownRoute() ? "replace" : "none",
    });
    if (!applied && AppState.state.route) globalThis.history.replaceState({ route: AppState.state.route }, "", `#${AppState.state.route}`);
  }

  function configure(nextHandlers) {
    const requiredHandlers = [
      "hasUnsavedChanges",
      "confirmDiscardChanges",
      "discardUnsavedChanges",
      "renderActiveRoute",
      "renderStatus",
      "restoreRouteScroll",
      "ensureRouteData",
    ];
    if (!nextHandlers || requiredHandlers.some((name) => typeof nextHandlers[name] !== "function")) {
      throw new Error("AppRouter.configure requires all navigation handlers");
    }
    handlers = nextHandlers;
    configured = true;
    if (!hashchangeRegistered) {
      globalThis.addEventListener("hashchange", syncFromHash);
      hashchangeRegistered = true;
    }
  }

  return Object.freeze({
    configure,
    navigate,
    syncFromHash,
    routeFromHash,
    hashContainsKnownRoute,
    planSegmentFromRoute,
    baseRoute,
    moreSegmentFromRoute,
  });
})();
