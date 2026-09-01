const NAV_ROUTES = Object.freeze({
  coach: "chatPanel",
  today: "todayPanel",
  activities: "activitiesPanel",
  planned: "workoutsPanel",
  "planned/calendar": "workoutsPanel",
  "planned/library": "workoutsPanel",
  "planned/goals": "workoutsPanel",
  performance: "dataPanel",
  more: "settingsPanel",
  "more/connections": "settingsPanel",
  "more/coach": "settingsPanel",
  "more/privacy": "settingsPanel",
  "more/operations": "settingsPanel",
  "more/profile": "profilePanel",
  profile: "profilePanel",
  settings: "settingsPanel",
});
const NAV_LINK_ROUTES = Object.freeze({
  coach: "coach",
  today: "today",
  activities: "activities",
  planned: "planned",
  performance: "performance",
  more: "more",
  profile: "more",
  settings: "more",
});
const DEFAULT_NAV_ROUTE = "coach";

function routeFromHash(hash = window.location.hash) {
  const route = String(hash || "").replace(/^#/, "").toLowerCase();
  return Object.prototype.hasOwnProperty.call(NAV_ROUTES, route) ? route : DEFAULT_NAV_ROUTE;
}

function hashContainsKnownRoute(hash = window.location.hash) {
  const route = String(hash || "").replace(/^#/, "").toLowerCase();
  return Object.prototype.hasOwnProperty.call(NAV_ROUTES, route);
}

function planSegmentFromRoute(route = state.route) {
  const segment = String(route || "").split("/")[1];
  return ["calendar", "library", "goals"].includes(segment) ? segment : "calendar";
}

function baseRoute(route = state.route) {
  return String(route || DEFAULT_NAV_ROUTE).split("/")[0];
}

function moreSegmentFromRoute(route = state.route) {
  const segment = String(route || "").split("/")[1];
  if (["profile", "connections", "coach", "privacy", "operations"].includes(segment)) return segment;
  return route === "profile" ? "profile" : "connections";
}
