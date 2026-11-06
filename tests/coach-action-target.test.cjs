const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/coach.js"), "utf8");
const start = source.indexOf("function coachActionDescription");
const end = source.indexOf("\nfunction coachActionStatus", start);

function describe(proposal) {
  const context = vm.createContext({ providerIds: () => ({ garmin: "garmin", intervals: "intervals" }) });
  vm.runInContext(source.slice(start, end) + ";globalThis.describe = coachActionDescription;", context);
  return context.describe(proposal);
}

test("a remote approval card names the provider it writes to", () => {
  assert.match(describe({ action_type: "remote_coach_write", target_system: "garmin" }), /an deine Garmin-Uhr gesendet/);
  assert.match(describe({ action_type: "remote_coach_write", target_system: "intervals" }), /an Intervals\.icu gesendet/);
});
