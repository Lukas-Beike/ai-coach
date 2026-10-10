const assert = require("node:assert/strict");
const { test } = require("node:test");

const AppFormat = require("../public/format.js");

test("format module exposes a single frozen global object", () => {
  assert.equal(globalThis.AppFormat, AppFormat);
  assert.ok(Object.isFrozen(AppFormat));
});

test("number uses de-DE separators and honours digits", () => {
  assert.equal(AppFormat.number(12.345), "12,3");
  assert.equal(AppFormat.number(12), "12");
  assert.equal(AppFormat.number("7.25", { digits: 2 }), "7,25");
  assert.equal(AppFormat.number(1234.56, { digits: 0 }), "1.235");
  assert.equal(AppFormat.number(NaN), null);
  assert.equal(AppFormat.number(Infinity), null);
  assert.equal(AppFormat.number("abc"), null);
});

test("distance formats kilometres with one decimal in de-DE", () => {
  assert.equal(AppFormat.distance(12300), "12,3 km");
  assert.equal(AppFormat.distance(42000), "42,0 km");
  assert.equal(AppFormat.distance(500), "0,5 km");
});

test("distance returns null for missing or non-positive values", () => {
  assert.equal(AppFormat.distance(null), null);
  assert.equal(AppFormat.distance(undefined), null);
  assert.equal(AppFormat.distance(""), null);
  assert.equal(AppFormat.distance(0), null);
  assert.equal(AppFormat.distance(-5), null);
  assert.equal(AppFormat.distance("abc"), null);
});

test("duration uses minutes under one hour and h:mm h from one hour", () => {
  assert.equal(AppFormat.duration(2700), "45 min");
  assert.equal(AppFormat.duration(3570), "1:00 h");
  assert.equal(AppFormat.duration(3600), "1:00 h");
  assert.equal(AppFormat.duration(3900), "1:05 h");
  assert.equal(AppFormat.duration(0), "0 min");
  assert.equal(AppFormat.duration(null), null);
  assert.equal(AppFormat.duration(undefined), null);
  assert.equal(AppFormat.duration(-60), null);
});

test("clock keeps the stopwatch style for pace and lap values", () => {
  assert.equal(AppFormat.clock(65), "1:05");
  assert.equal(AppFormat.clock(3661), "1:01:01");
  assert.equal(AppFormat.clock(299.6), "5:00");
  assert.equal(AppFormat.clock(null), null);
  assert.equal(AppFormat.clock("abc"), null);
});

test("relativeDay names neighbouring days and counts whole days", () => {
  assert.equal(AppFormat.relativeDay("2026-10-10", "2026-10-10"), "Heute");
  assert.equal(AppFormat.relativeDay("2026-10-11", "2026-10-10"), "Morgen");
  assert.equal(AppFormat.relativeDay("2026-10-09", "2026-10-10"), "Gestern");
  assert.equal(AppFormat.relativeDay("2026-10-13", "2026-10-10"), "in 3 Tagen");
  assert.equal(AppFormat.relativeDay("2026-09-30", "2026-10-10"), "vor 10 Tagen");
});

test("relativeDay counts whole days across the daylight-saving change", () => {
  assert.equal(AppFormat.relativeDay("2026-03-30", "2026-03-28"), "in 2 Tagen");
  assert.equal(AppFormat.relativeDay("2026-10-26", "2026-10-24"), "in 2 Tagen");
});

test("relativeDay returns null for invalid date keys", () => {
  assert.equal(AppFormat.relativeDay("bad", "2026-10-10"), null);
  assert.equal(AppFormat.relativeDay("2026-10-10", null), null);
  assert.equal(AppFormat.relativeDay("2026-02-30", "2026-10-10"), null);
});

test("date formats date keys in de-DE without shifting the calendar day", () => {
  assert.equal(AppFormat.date("2026-09-08"), "08.09.2026");
  assert.equal(AppFormat.date("2026-01-01", { timeZone: "America/Los_Angeles" }), "01.01.2026");
  assert.equal(AppFormat.date(null), null);
  assert.equal(AppFormat.date("not a date"), null);
});

test("date and dateTime honour a valid timezone and fall back for an invalid one", () => {
  assert.equal(AppFormat.dateTime("2026-09-08T12:00:00Z", { timeZone: "Europe/Berlin" }), "08.09.2026, 14:00");
  assert.equal(AppFormat.dateTime("2026-09-08T12:00:00Z", { timeZone: "Not/AZone" }), AppFormat.dateTime("2026-09-08T12:00:00Z"));
  assert.equal(AppFormat.date("2026-09-08T12:00:00Z", { timeZone: "Not/AZone" }), AppFormat.date("2026-09-08T12:00:00Z"));
});

test("dateTime returns null for missing or invalid values", () => {
  assert.equal(AppFormat.dateTime(null), null);
  assert.equal(AppFormat.dateTime(""), null);
  assert.equal(AppFormat.dateTime("garbage"), null);
});
