const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function loadPublicScript(name) {
  return fs.readFileSync(path.join(__dirname, "../public", name), "utf8").split("\r\n").join("\n");
}

const context = vm.createContext({});
vm.runInContext(loadPublicScript("performance-view.js"), context);
vm.runInContext(`${loadPublicScript("plan-views.js")};globalThis.calendarSportType = calendarSportType;globalThis.calendarDisplayName = calendarDisplayName;`, context);
const { calendarSportType, activitySportLabel, calendarDisplayName } = context;
const label = (item) => activitySportLabel(calendarSportType(item));

test("completed activities are labelled from the canonical sport and environment", () => {
  assert.equal(label({ sport: "ride", environment: "outdoor" }), "Radfahren");
  assert.equal(label({ sport: "ride", environment: "indoor" }), "Rad indoor");
  assert.equal(label({ sport: "ride", environment: "virtual" }), "Rad indoor");
  assert.equal(label({ sport: "run", environment: "outdoor" }), "Laufen");
  assert.equal(label({ sport: "swim" }), "Schwimmen");
  assert.equal(label({ sport: "strength" }), "Kraft");
  assert.equal(label({ sport: "walk" }), "Andere");
});

test("planned units keep their stored type", () => {
  assert.equal(label({ type: "VirtualRide" }), "Rad indoor");
  assert.equal(label({ type: "Run", sport: "run" }), "Laufen");
});

test("session summaries are labelled without an Intervals type", () => {
  assert.equal(activitySportLabel({ sport: "ride", environment: "virtual" }), "Rad indoor");
  assert.equal(activitySportLabel({ sport: "ride", environment: "outdoor" }), "Radfahren");
  assert.equal(activitySportLabel({ sport: "run" }), "Laufen");
  assert.equal(activitySportLabel({ sport: "yoga" }), "Andere");
});

test("activity names show without a leading place, names that only look like one stay intact", () => {
  for (const [stored, shown] of [
    ["Emsdetten - 3 x 10 Min Schwelle", "3 x 10 Min Schwelle"],
    ["Münster – Grundlagenausfahrt", "Grundlagenausfahrt"],
    ["Bad Oeynhausen — Lockerer Lauf", "Lockerer Lauf"],
    ["Castrop-Rauxel - Radfahren", "Radfahren"],
    ["St. Moritz - Langlauf", "Langlauf"],
    ["Emsdetten - Kontrollierter Schwellenlauf – 3 x 9 Minuten", "Kontrollierter Schwellenlauf – 3 x 9 Minuten"],
    // No spaced dash, a training word, a digit or a lower-case word: no place prefix.
    ["Emsdetten Laufen", "Emsdetten Laufen"],
    ["Emsdetten-Lauf", "Emsdetten-Lauf"],
    ["Lockerer Lauf – 40 Minuten", "Lockerer Lauf – 40 Minuten"],
    ["Intervalle - 5 x 1 km", "Intervalle - 5 x 1 km"],
    ["Zwift - Watopia", "Zwift - Watopia"],
    ["5 km - Tempo", "5 km - Tempo"],
    ["Z2 - Grundlage", "Z2 - Grundlage"],
    ["morgens - locker", "morgens - locker"],
    ["Emsdetten -", "Emsdetten -"],
    ["", ""],
  ]) assert.equal(calendarDisplayName(stored), shown, stored);
});
