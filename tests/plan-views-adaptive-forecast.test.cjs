const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, loadPublicScript, FakeElement } = require("./frontend-harness.cjs");

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

// A replan preview only fills the Coach notice; the client has no apply path of its own, so the
// render must not call the API or touch the planned units. Applying is a separate Coach action.
function renderAdaptiveNotice(data) {
  const requests = [];
  const notice = new FakeElement("div");
  const detail = new FakeElement("small");
  notice.querySelector = () => detail;
  const state = { data };
  const views = loadPublicScript("plan-views.js").AppPlanViews.create({
    $: (selector) => (selector === "#coachAdaptivePlanningNotice" ? notice : null),
    state,
    formatTime,
    api: async (...args) => { requests.push(args); },
  });
  const before = JSON.stringify(data);
  views.renderAdaptivePlanning(data);
  return { notice, detail, requests, untouched: JSON.stringify(data) === before && state.data === data };
}

test("a replan preview shows the notice and asks for the Coach, without any write", () => {
  const planned = [{ local_id: "u1", planned_date: "2026-11-14" }];
  const { notice, detail, requests, untouched } = renderAdaptiveNotice({
    planned,
    planning: { needs_replan: true, replan_changes: 2, latest_replan: { status: "preview", changes: [{ blocking_triggers: ["weather"] }, {}], weather_forecast: { fetched_at: "t1", stale: false } } },
  });
  assert.equal(notice.hidden, false);
  assert.equal(detail.textContent, "2 zukünftige Entwürfe brauchen eine Anpassung. Wetterprognose Stand formatted:t1. Bitte den Coach um die Anpassung.");
  assert.deepEqual(requests, []);
  assert.equal(untouched, true);
});

test("without a needed replan the Coach notice stays hidden", () => {
  const { notice, detail, requests } = renderAdaptiveNotice({ planning: { needs_replan: false, latest_replan: { status: "applied", changes: [] } } });
  assert.equal(notice.hidden, true);
  assert.equal(detail.textContent, "");
  assert.deepEqual(requests, []);
});
