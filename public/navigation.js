const NAV_ROUTES = Object.freeze({
  coach: "chatPanel",
  today: "todayPanel",
  plan: "workoutsPanel",
  "plan/calendar": "workoutsPanel",
  "plan/templates": "workoutsPanel",
  "plan/goals": "workoutsPanel",
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
const NAV_ALIASES = Object.freeze({
  activities: "analysis/history",
  performance: "analysis/performance",
  planned: "plan/calendar",
  "planned/calendar": "plan/calendar",
  "planned/library": "plan/templates",
  "planned/goals": "plan/goals",
  profile: "more/profile",
  settings: "more",
  "plan/library": "plan/templates",
});
const DEFAULT_NAV_ROUTE = "coach";

function routeFromHash(hash = window.location.hash) {
  const rawRoute = String(hash || "").replace(/^#/, "").toLowerCase();
  const route = NAV_ALIASES[rawRoute] || rawRoute;
  return Object.prototype.hasOwnProperty.call(NAV_ROUTES, route) ? route : DEFAULT_NAV_ROUTE;
}

function hashContainsKnownRoute(hash = window.location.hash) {
  const rawRoute = String(hash || "").replace(/^#/, "").toLowerCase();
  const route = NAV_ALIASES[rawRoute] || rawRoute;
  return Object.prototype.hasOwnProperty.call(NAV_ROUTES, route);
}

function planSegmentFromRoute(route = state.route) {
  const segment = String(route || "").split("/")[1];
  return ["calendar", "templates", "goals"].includes(segment) ? segment : "calendar";
}

function analysisSegmentFromRoute(route = state.route) {
  const segment = String(route || "").split("/")[1];
  return ["history", "performance"].includes(segment) ? segment : "history";
}

function baseRoute(route = state.route) {
  return String(route || DEFAULT_NAV_ROUTE).split("/")[0];
}

function moreSegmentFromRoute(route = state.route) {
  const segment = String(route || "").split("/")[1];
  if (["profile", "connections", "coach", "privacy", "operations"].includes(segment)) return segment;
  return route === "profile" ? "profile" : "connections";
}
