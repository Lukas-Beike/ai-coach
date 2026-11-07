const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function loadPublicScript(name) {
  return fs.readFileSync(path.join(__dirname, "../public", name), "utf8").split("\r\n").join("\n");
}

function element() {
  return {
    children: [],
    attributes: {},
    style: {},
    className: "",
    textContent: "",
    title: "",
    append(...items) {
      this.children.push(...items);
    },
    setAttribute(name, value) {
      this.attributes[name] = value;
    },
  };
}

const context = vm.createContext({ AppFormat: require("../public/format.js"), document: { createElement: () => element() } });
vm.runInContext(loadPublicScript("performance-view.js"), context);
vm.runInContext(`${loadPublicScript("plan-views.js")};globalThis.appendPlannedExecution = appendPlannedExecution;`, context);
const { appendPlannedExecution } = context;

test("a strength unit compared by sets shows its execution chip", () => {
  const card = element();
  appendPlannedExecution(card, { compliance: { basis: "strength_sets", percentage: 75 } }, "completed");
  const chip = card.children[0];
  assert.ok(chip, "chip rendered");
  assert.match(chip.textContent, /75 %/);
  assert.equal(chip.title, "Ausführung gegenüber Plan (Sätze)");
  assert.match(chip.className, /is-deviation/);
});

test("an unknown basis still shows no chip", () => {
  const card = element();
  appendPlannedExecution(card, { compliance: { basis: "unavailable", percentage: 100 } }, "completed");
  assert.equal(card.children.length, 0);
});
