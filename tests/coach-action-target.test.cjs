const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

function describe(proposal) {
  const context = extractFunctions("coach.js", ["coachActionDescription"], { providerIds: () => ({ garmin: "garmin", intervals: "intervals" }) });
  return context.coachActionDescription(proposal);
}

test("a remote approval card names the provider it writes to", () => {
  assert.match(describe({ action_type: "remote_coach_write", target_system: "garmin" }), /an deine Garmin-Uhr gesendet/);
  assert.match(describe({ action_type: "remote_coach_write", target_system: "intervals" }), /an Intervals\.icu gesendet/);
});
