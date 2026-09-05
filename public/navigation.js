const NAV_ROUTES = Object.freeze({
  coach: "chatPanel",
  today: "todayPanel",
  plan: "workoutsPanel",
  "plan/overview": "workoutsPanel",
  "plan/library": "workoutsPanel",
  analysis: "dataPanel",
  "analysis/history": "dataPanel",
  "analysis/performance": "dataPanel",
  more: "settingsPanel",
  "more/connections": "settingsPanel",
  "more/coach": "settingsPanel",
  "more/privacy": "settingsPanel",
  "more/operations": "settingsPanel",
  "more/profile": "profilePanel",
});
const NAV_LINK_ROUTES = Object.freeze({
  coach: "coach",
  today: "today",
  plan: "plan",
  analysis: "analysis",
  more: "more",
});
const DEFAULT_NAV_ROUTE = "coach";

function routeFromHash(hash = window.location.hash) {
  const rawRoute = String(hash || "").replace(/^#/, "").toLowerCase();
  return Object.prototype.hasOwnProperty.call(NAV_ROUTES, rawRoute) ? rawRoute : DEFAULT_NAV_ROUTE;
}

function hashContainsKnownRoute(hash = window.location.hash) {
  const rawRoute = String(hash || "").replace(/^#/, "").toLowerCase();
  return Object.prototype.hasOwnProperty.call(NAV_ROUTES, rawRoute);
}

function analysisSegmentFromRoute(route = state.route) {
  const segment = String(route || "").split("/")[1];
  return ["history", "performance"].includes(segment) ? segment : "performance";
}

function planSegmentFromRoute(route = state.route) {
  const segment = String(route || "").split("/")[1];
  return ["overview", "library"].includes(segment) ? segment : "overview";
}

function baseRoute(route = state.route) {
  return String(route || DEFAULT_NAV_ROUTE).split("/")[0];
}

function moreSegmentFromRoute(route = state.route) {
  const segment = String(route || "").split("/")[1];
  if (["profile", "connections", "coach", "privacy", "operations"].includes(segment)) return segment;
  return "connections";
}
