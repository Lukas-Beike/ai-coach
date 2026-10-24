const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { test } = require("node:test");
const source = fs.readFileSync("public/plan-views.js", "utf8");
const context = vm.createContext({ AppFormat: require("../public/format.js") });
vm.runInContext(source, context);

test("competition distances retain unknown, zero and free-form values", () => {
  for (const value of [null, undefined, "", "  ", -1]) assert.equal(context.competitionDistance(value), "Distanz unbekannt");
  assert.equal(context.competitionDistance(0), "0 km");
  assert.equal(context.competitionDistance(42195), "42,2 km");
  assert.equal(context.competitionDistance("Sprintdistanz"), "Sprintdistanz");
});

test("invalid event dates stay undated rather than rolling into another month", () => {
  for (const event_date of [null, "", "2026-02-30", "not-a-date"]) assert.equal(context.competitionDate({ event_date }, "2026-10-24"), false);
  assert.equal(context.competitionDate({ event_date: "2026-10-24" }, "2026-10-24"), true);
});
