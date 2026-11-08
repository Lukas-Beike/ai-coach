const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const read = (name) => fs.readFileSync(path.join(__dirname, "../public", name), "utf8").replace(/\r\n/g, "\n");

function loadStrip() {
  const context = vm.createContext({ document: { querySelector: () => null } });
  vm.runInContext(`${read("status-strip.js")}\nthis.api = { statusStripItems, statusStandLabel, statusSources };`, context);
  return context.api;
}

function loadThresholdItem() {
  const source = read("settings.js");
  const slice = (marker) => {
    const start = source.indexOf(marker);
    assert.notEqual(start, -1, marker);
    return source.slice(start, source.indexOf("\n}\n", start) + 3);
  };
  const context = vm.createContext({});
  vm.runInContext(`${slice("function zoneWarningLine(")}${slice("function thresholdStatusItem(")}\nthis.thresholdStatusItem = thresholdStatusItem;`, context);
  return context.thresholdStatusItem;
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
  assert.equal(many.detail, "2 Werte sind veraltet oder fehlen.");
});
