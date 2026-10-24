const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/analysis.js"), "utf8").replace(/\r\n/g, "\n");
const start = source.indexOf("function parseSeasonLoadFactor(");
const end = source.indexOf("\n}\n", start) + 2;

function loadParser() {
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({});
  vm.runInContext(`${source.slice(start, end)};globalThis.parseSeasonLoadFactor = parseSeasonLoadFactor;`, context);
  return context.parseSeasonLoadFactor;
}

test("German and decimal load factors are parsed inside the scenario range", () => {
  const parse = loadParser();
  assert.equal(parse("0,8"), 0.8);
  assert.equal(parse("1.25"), 1.25);
  assert.equal(parse("1,5"), 1.5);
});

test("out-of-range, empty and malformed load factors are rejected", () => {
  const parse = loadParser();
  assert.equal(parse("0,4"), null);
  assert.equal(parse("1,6"), null);
  assert.equal(parse("abc"), null);
  assert.equal(parse(""), null);
});

test("season distances show 0 km only for a real zero and unbekannt for invalid values", () => {
  const distanceStart = source.indexOf("function seasonDistance(");
  const distanceEnd = source.indexOf("\n}\n", distanceStart) + 2;
  const context = vm.createContext({ AppFormat: require("../public/format.js") });
  vm.runInContext(`${source.slice(distanceStart, distanceEnd)};globalThis.seasonDistance = seasonDistance;`, context);
  const seasonDistance = context.seasonDistance;
  assert.equal(seasonDistance(0), "0 km");
  assert.equal(seasonDistance(-1000), "unbekannt", "a negative confirmed distance is not shown as zero");
  assert.equal(seasonDistance("abc"), "unbekannt");
  assert.equal(seasonDistance(null), "unbekannt");
  assert.equal(seasonDistance(42195), "42,2 km");
});
