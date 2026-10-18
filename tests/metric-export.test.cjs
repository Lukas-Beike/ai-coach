const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/performance-view.js"), "utf8");
const start = source.indexOf("function metricExportActions()");
const end = source.indexOf("\n}", start) + 2;

function render(status) {
  const context = vm.createContext({
    state: { data: { garmin: { metric_export_status: status } } },
    reportNode: (tag, text, className) => ({ tag, text, className, children: [], append(node) { this.children.push(node); } }),
  });
  vm.runInContext(source.slice(start, end), context);
  return context.metricExportActions();
}

test("current metrics explain automatic transfer without manual controls or writes", () => {
  const node = render(null);
  assert.equal(node.tag, "div");
  assert.equal(node.children.length, 1);
  assert.equal(node.children[0].tag, "p");
  assert.match(node.children[0].text, /automatisch an Intervals\.icu/);
  assert.match(node.children[0].text, /Herzfrequenzzonen bleiben/);
  assert.match(node.children[0].text, /pausieren/);
});

test("the last sync receipt is rendered as text", () => {
  const status = "Intervals.icu: 2 Messwerte gesendet, 1 Konflikte, 0 fehlgeschlagen.";
  const node = render(status);
  assert.equal(node.children.length, 2);
  assert.equal(node.children[1].tag, "p");
  assert.equal(node.children[1].text, status);
});
