const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function loadPublicScript(name) {
  const source = fs.readFileSync(path.join(__dirname, "../public", name), "utf8");
  return source.split("\r\n").join("\n");
}

// plan-views.js keeps its helpers private, so load it into a sandbox and expose the pollen helper.
const context = vm.createContext({});
vm.runInContext(loadPublicScript("format.js"), context);
vm.runInContext(`${loadPublicScript("plan-views.js")};globalThis.plannedPollenLabel = plannedPollenLabel;`, context);
const { plannedPollenLabel } = context;

test("pollen label lists DWD hazard levels by species", () => {
  assert.equal(
    plannedPollenLabel({ source: "DWD", region: "Westfalen", levels: { Birke: "1-2", Gräser: "1" } }),
    "Pollen: Birke 1-2, Gräser 1",
  );
});

test("pollen label reports an empty DWD forecast as no load", () => {
  assert.equal(plannedPollenLabel({ source: "DWD", levels: {} }), "Pollen: keine Belastung");
});

test("pollen label falls back to CAMS concentrations and ignores malformed data", () => {
  assert.equal(plannedPollenLabel({ source: "Open-Meteo/CAMS", concentrations: { Erle: 12 } }), "Pollen: Erle 12");
  assert.equal(plannedPollenLabel(null), "");
  assert.equal(plannedPollenLabel({ source: "DWD", levels: "hoch" }), "");
});
