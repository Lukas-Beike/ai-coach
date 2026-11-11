const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

function loadAdaptiveForecastNote() {
  return extractFunctions("plan-views.js", ["adaptiveForecastNote"]).adaptiveForecastNote;
}

const formatTime = (value) => `formatted:${value}`;

test("adaptive notice shows the forecast age of a fresh weather preview", () => {
  const note = loadAdaptiveForecastNote();
  assert.equal(
    note({ fetched_at: "2026-10-14T08:00:00+00:00", stale: false }, formatTime),
    "Wetterprognose Stand formatted:2026-10-14T08:00:00+00:00",
  );
});

test("adaptive notice marks a stale or last-good forecast as veraltet", () => {
  const note = loadAdaptiveForecastNote();
  assert.equal(
    note({ fetched_at: "2026-10-12T06:00:00+00:00", stale: true }, formatTime),
    "Wetterprognose Stand formatted:2026-10-12T06:00:00+00:00 (veraltet)",
  );
});

test("adaptive notice stays silent when the preview has no forecast age", () => {
  const note = loadAdaptiveForecastNote();
  assert.equal(note(undefined, formatTime), "");
  assert.equal(note({ state: "not_configured", stale: false }, formatTime), "");
});
