const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

const context = extractFunctions("plan-views.js", ["externalCalendarDetail"]);

test("the calendar status names the skipped appointments", () => {
  assert.equal(context.externalCalendarDetail({ skipped_events: 2 }), "2 Termine übersprungen");
  assert.equal(context.externalCalendarDetail({ skipped_events: 0 }), "");
  assert.equal(context.externalCalendarDetail({}), "");
});

test("an error outranks the skipped count", () => {
  assert.equal(context.externalCalendarDetail({ last_error: "x", skipped_events: 2 }), "Fehler bei letzter Aktualisierung");
});
