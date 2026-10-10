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
