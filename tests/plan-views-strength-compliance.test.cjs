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
vm.runInContext(`${loadPublicScript("plan-views.js")};globalThis.appendPlannedEntryStatus = appendPlannedEntryStatus;`, context);
const { appendPlannedEntryStatus } = context;
const completed = (compliance) => ({ compliance: { ...compliance, actual_activity: { id: "a1" } } });

test("a strength unit compared by sets shows its share of the plan in the status", () => {
  const line = element();
  appendPlannedEntryStatus(line, completed({ basis: "strength_sets", percentage: 75 }), "completed", null, "2026-11-10", "2026-11-11", true);
  assert.equal(line.children[0].textContent, "✓ Absolviert · 75 %");
});

test("an unknown basis shows the status without a share", () => {
  const line = element();
  appendPlannedEntryStatus(line, completed({ basis: "unavailable", percentage: 100 }), "completed", null, "2026-11-10", "2026-11-11", true);
  assert.equal(line.children[0].textContent, "✓ Absolviert");
});
