const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/weekly-plan.js"), "utf8");
const context = vm.createContext({});
vm.runInContext(`${source}\nglobalThis.api = { weeklyPlan, weeklyEffective, weeklyParse, weeklySerialize };`, context);
const { weeklyPlan, weeklyEffective, weeklyParse, weeklySerialize } = context.api;

test("the editor keeps no built-in hours of its own", () => {
  assert.doesNotMatch(source, /15:30-24:00|14:00-24:00/);
});

test("offline the editor shows no inherited hours", () => {
  weeklyPlan.fallback = {};
  weeklyPlan.model = weeklyParse("");
  assert.deepEqual(JSON.parse(JSON.stringify(weeklyEffective("mon"))), { windows: [], source: "fallback" });
});

test("the editor reads the server fallback and does not store it as a default", () => {
  weeklyPlan.fallback = { mon: ["00:00-06:00", "15:30-24:00"] };
  weeklyPlan.model = weeklyParse("");
  assert.deepEqual(JSON.parse(JSON.stringify(weeklyEffective("mon"))), { windows: ["00:00-06:00", "15:30-24:00"], source: "fallback" });
  weeklyPlan.model.default.mon = [{ start: "00:00", end: "06:00" }, { start: "15:30", end: "00:00" }];
  assert.equal(weeklySerialize(weeklyPlan.model), "");
});
