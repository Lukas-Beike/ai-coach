const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/plan-views.js"), "utf8");
const start = source.indexOf("function externalCalendarDetail");
const end = source.indexOf("function stripCalendarMarkers", start);
const context = vm.createContext({});
vm.runInContext(source.slice(start, end) + ";globalThis.detail = externalCalendarDetail;", context);

test("the calendar status names the skipped appointments", () => {
  assert.equal(context.detail({ skipped_events: 2 }), "2 Termine übersprungen");
  assert.equal(context.detail({ skipped_events: 0 }), "");
  assert.equal(context.detail({}), "");
});

test("an error outranks the skipped count", () => {
  assert.equal(context.detail({ last_error: "x", skipped_events: 2 }), "Fehler bei letzter Aktualisierung");
});
