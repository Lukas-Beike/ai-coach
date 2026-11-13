const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

function loadHelpers() {
  // Marker stripping is covered elsewhere; these tests only exercise the time handling.
  return extractFunctions("plan-views.js", ["plannedAppointmentLabel", "calendarStartTime", "plannedUnitStartTime"], { stripCalendarMarkers: (text) => String(text || "") });
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

test("a date-only value keeps its day, a moment takes the local day and an invalid value has none", () => {
  const { localDateKey } = extractFunctions("views.js", ["localDateKey"]);
  assert.equal(localDateKey("2026-10-12"), "2026-10-12");
  assert.equal(localDateKey(new Date(2026, 9, 12, 23, 30)), "2026-10-12");
  assert.equal(localDateKey("2026-10-12T23:30:00"), "2026-10-12");
  assert.equal(localDateKey("not a date"), "");
});

test("a personal event covers its days, without the end day at midnight", () => {
  const addDateKey = (key, days) => {
    const date = new Date(`${key}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
  };
  const { plannedEventDays, plannedEventTime } = extractFunctions("plan-views.js", ["plannedEventDays", "plannedEventTime"], { addDateKey });
  const days = (start, end) => [...plannedEventDays({ start_local: start, end_local: end })];
  assert.deepEqual(days("2026-10-12T19:00:00", "2026-10-12T21:00:00"), ["2026-10-12"]);
  assert.deepEqual(days("2026-10-12T00:00:00", "2026-10-14T00:00:00"), ["2026-10-12", "2026-10-13"]);
  assert.deepEqual(days("2026-10-12T22:00:00", "2026-10-13T01:00:00"), ["2026-10-12", "2026-10-13"]);
  assert.deepEqual(days("2026-10-12T00:00:00", "2026-10-12T00:00:00"), ["2026-10-12"]);
  assert.deepEqual(days("not a date", ""), []);
  assert.equal(plannedEventTime({ start_local: "2026-10-12T19:00:00", end_local: "2026-10-12T21:00:00" }), "19:00–21:00");
  assert.equal(plannedEventTime({ all_day: 1, start_local: "2026-10-12T00:00:00" }), "ganztägig");
});
