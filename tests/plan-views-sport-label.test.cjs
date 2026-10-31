const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function loadPublicScript(name) {
  return fs.readFileSync(path.join(__dirname, "../public", name), "utf8").split("\r\n").join("\n");
}

const context = vm.createContext({});
vm.runInContext(loadPublicScript("performance-view.js"), context);
vm.runInContext(`${loadPublicScript("plan-views.js")};globalThis.calendarSportType = calendarSportType;`, context);
const { calendarSportType, activitySportLabel } = context;
const label = (item) => activitySportLabel(calendarSportType(item));

test("completed activities are labelled from the canonical sport and environment", () => {
  assert.equal(label({ sport: "ride", environment: "outdoor" }), "Radfahren");
  assert.equal(label({ sport: "ride", environment: "indoor" }), "Rad indoor");
  assert.equal(label({ sport: "ride", environment: "virtual" }), "Rad indoor");
  assert.equal(label({ sport: "run", environment: "outdoor" }), "Laufen");
  assert.equal(label({ sport: "swim" }), "Schwimmen");
  assert.equal(label({ sport: "strength" }), "Kraft");
  assert.equal(label({ sport: "walk" }), "Andere");
});

test("planned units keep their stored type", () => {
  assert.equal(label({ type: "VirtualRide" }), "Rad indoor");
  assert.equal(label({ type: "Run", sport: "run" }), "Laufen");
});
