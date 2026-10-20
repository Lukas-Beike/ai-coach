const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/state-loader.js"), "utf8");

// Loads public/state-loader.js with the real render and stubbed area renderers.
function loader(route) {
  const state = { data: null, route, sessionGeneration: 0, replaceDataOnLoad: false };
  const reloads = [];
  const context = vm.createContext({
    state,
    document: { currentScript: { src: "/state-loader.js?v=1" } },
    setTimeout,
    clearTimeout,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    AppRouter: { baseRoute: () => route.split("/")[0] },
    loadNutrition: () => reloads.push(["day", state.data?.profile?.timezone]),
    loadNutritionProducts: () => reloads.push(["products", state.data?.profile?.timezone]),
  });
  for (const name of [
    "renderAppVersion", "renderCoachOverview", "renderCoachReceipts", "renderQuickMessageTemplates", "notifyState",
    "renderStatus", "renderMessages", "renderPlanned", "renderLibrary", "renderProfile", "renderCheckins", "renderGarmin",
    "renderAdaptivePlanning", "renderExternalCalendar", "renderPerformance", "renderModel", "renderThinkingLevel",
    "renderServiceTier", "renderDiagnosticCapture", "renderSettings", "updateVoiceButton",
  ]) context[name] = () => {};
  vm.runInContext(source, context);
  return { context, reloads };
}

const data = { app: {}, messages: [], profile: { timezone: "Europe/Berlin" } };

// The diary resolves "today" in the profile's zone; before the state is in place a
// reload after local midnight would fall back to the device's zone and open the wrong day.
test("the first render reloads the open nutrition diary with the profile in place", () => {
  const { context, reloads } = loader("nutrition/diary");
  context.render(data);
  assert.deepEqual(JSON.parse(JSON.stringify(reloads)), [["day", "Europe/Berlin"]]);
});

test("the first render reloads the open product list with the profile in place", () => {
  const { context, reloads } = loader("nutrition/products");
  context.render(data);
  assert.deepEqual(JSON.parse(JSON.stringify(reloads)), [["products", "Europe/Berlin"]]);
});

test("a render without the route reload leaves the nutrition view alone", () => {
  const { context, reloads } = loader("nutrition/diary");
  context.render(data, { reloadRoute: false });
  assert.deepEqual(reloads, []);
});
