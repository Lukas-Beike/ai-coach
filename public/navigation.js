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

function routeFromHash(hash = globalThis.location.hash) {
  const rawRoute = String(hash || "").replace(/^#/, "").toLowerCase();
  return Object.hasOwn(NAV_ROUTES, rawRoute) ? rawRoute : DEFAULT_NAV_ROUTE;
}

function hashContainsKnownRoute(hash = globalThis.location.hash) {
  const rawRoute = String(hash || "").replace(/^#/, "").toLowerCase();
  return Object.hasOwn(NAV_ROUTES, rawRoute);
}

function planSegmentFromRoute(route = state.route) {
  const segment = String(route || "").split("/")[1];
  return ["overview", "library", "season"].includes(segment) ? segment : "overview";
}

function baseRoute(route = state.route) {
  return String(route || DEFAULT_NAV_ROUTE).split("/")[0];
}

function moreSegmentFromRoute(route = state.route) {
  const segment = String(route || "").split("/")[1];
  if (["profile", "equipment", "connections", "coach", "privacy", "operations", "appearance"].includes(segment)) return segment;
  return "connections";
}
