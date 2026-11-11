const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, loadPublicScript } = require("./frontend-harness.cjs");

function loadStrip() {
  return loadPublicScript("status-strip.js", { document: { querySelector: () => null } });
}

function loadThresholdItem() {
  return extractFunctions("settings.js", ["zoneWarningLine", "thresholdStatusItem"]).thresholdStatusItem;
}

const item = (level, title) => ({ level, title });
// The strip runs in its own realm, so compare plain arrays.
const keys = (entries) => Array.from(entries, (entry) => entry.key);

test("the strip ranks notices by the athlete's order and shows only one as text", () => {
  const { statusStripItems } = loadStrip();
  const sources = new Map([
    ["thresholds", item("warning", "Schwellenwerte")],
    ["coach_error", item("critical", "Coach")],
    ["offline", item("warning", "Offline")],
    ["maintenance", item("critical", "Wartung")],
    ["openai", item("critical", "OpenAI")],
    ["provider", item("critical", "Anbindung")],
  ]);
  assert.deepEqual(keys(statusStripItems(sources)), ["maintenance", "offline", "openai", "coach_error", "provider", "thresholds"]);
});

test("the slim Intervals.icu line only shows when nothing more important does", () => {
  const { statusStripItems } = loadStrip();
  const sources = new Map([["intervals_key", item("info", "Intervals.icu-API-Schlüssel fehlt")]]);
  assert.deepEqual(keys(statusStripItems(sources)), ["intervals_key"]);
  sources.set("thresholds", item("warning", "Schwellenwerte"));
  assert.deepEqual(keys(statusStripItems(sources)), ["thresholds"]);
});

test("the loading notice stands alone", () => {
  const { statusStripItems } = loadStrip();
  const sources = new Map([["loading", item("working", "Lädt")], ["offline", item("warning", "Offline")]]);
  assert.deepEqual(keys(statusStripItems(sources)), ["loading"]);
});

test("unknown sources never reach the strip", () => {
  const { statusStripItems } = loadStrip();
  assert.equal(statusStripItems(new Map([["unknown", item("critical", "?")]])).length, 0);
});

test("the age of shown data reads as a short German label", () => {
  const { statusStandLabel } = loadStrip();
  const now = Date.UTC(2026, 10, 8, 12, 0, 0);
  const minutes = (count) => now - count * 60_000;
  assert.equal(statusStandLabel(null, now), "");
  assert.equal(statusStandLabel(minutes(0), now), "Stand gerade eben");
  assert.equal(statusStandLabel(minutes(12), now), "Stand vor 12 min");
  assert.equal(statusStandLabel(minutes(125), now), "Stand vor 2 h");
  assert.equal(statusStandLabel(minutes(60 * 24 * 3), now), "Stand vor 3 Tagen");
});

test("a stale threshold becomes one warning line that points to the profile", () => {
  const thresholdStatusItem = loadThresholdItem();
  assert.equal(thresholdStatusItem(null), null);
  assert.equal(thresholdStatusItem({ items: [] }), null);
  const one = thresholdStatusItem({ items: [{ label: "FTP Rad", value_text: "250 W", source_label: "Lokal", age_days: 70 }] });
  assert.equal(one.level, "warning");
  assert.match(one.detail, /FTP Rad 250 W · Lokal · 70 Tage alt/);
  assert.equal(one.action.href, "#more/profile");
  const many = thresholdStatusItem({ items: [{ label: "FTP Rad", value_text: "250 W", source_label: "Lokal" }, { label: "LTHR", value_text: "170 bpm", source_label: "Lokal" }] });
  assert.equal(many.detail, "2 Werte sind veraltet.");
});

test("an active maintenance mode becomes a critical notice and ends with it", () => {
  const updates = [];
  const { renderSyncStatus } = extractFunctions("sync-status.js", ["renderSyncStatus", "renderMaintenanceStatus"], {
    state: { data: null },
    updateStatusSources: (change) => updates.push(change.maintenance),
  });
  renderSyncStatus({ maintenance: { active: true } });
  renderSyncStatus({ maintenance: { active: false } });
  renderSyncStatus({});
  assert.equal(updates[0].level, "critical");
  assert.equal(updates[0].title, "Wartungsmodus aktiv");
  assert.match(updates[0].detail, /Änderungen sind vorübergehend pausiert/);
  assert.deepEqual(updates.slice(1), [null, null]);
});
