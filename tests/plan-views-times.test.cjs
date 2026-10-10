const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/plan-views.js"), "utf8");

function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} exists`);
  const end = source.indexOf("\n}", start);
  assert.ok(end > start, `${name} is closed`);
  return source.slice(start, end + 2);
}

function loadHelpers() {
  // Marker stripping is covered elsewhere; these tests only exercise the time handling.
  const context = vm.createContext({ stripCalendarMarkers: (text) => String(text || "") });
  vm.runInContext(
    ["plannedAppointmentLabel", "calendarStartTime", "plannedUnitStartTime"].map(functionSource).join("\n"),
    context,
  );
  return context;
}

test("external appointments keep a genuine midnight start time", () => {
  const { plannedAppointmentLabel } = loadHelpers();
  assert.equal(
    plannedAppointmentLabel({ name: "Physio", all_day: false, start_local: "2026-10-12T00:00:00" }),
    "Physio · 00:00",
  );
});

test("all-day external appointments show no clock time", () => {
  const { plannedAppointmentLabel } = loadHelpers();
  assert.equal(
    plannedAppointmentLabel({ name: "Urlaub", all_day: true, start_local: "2026-10-12T00:00:00" }),
    "Urlaub · ganztägig",
  );
});

test("date-only planned units at midnight show no start time", () => {
  const { plannedUnitStartTime } = loadHelpers();
  assert.equal(plannedUnitStartTime("2026-10-12T00:00:00"), null);
  assert.equal(plannedUnitStartTime("2026-10-12"), null);
  assert.equal(plannedUnitStartTime("2026-10-12T07:30:00"), "07:30");
});

test("completed activities keep their recorded midnight start time", () => {
  const { calendarStartTime } = loadHelpers();
  assert.equal(calendarStartTime("2026-10-12T00:00:00"), "00:00");
});
