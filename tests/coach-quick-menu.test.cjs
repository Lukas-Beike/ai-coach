const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const root = path.join(__dirname, "..", "public");
const source = fs.readFileSync(path.join(root, "coach.js"), "utf8");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const start = source.indexOf("function quickMenuTarget(");
const end = source.indexOf("\nfunction setupQuickActionMenu(", start);
assert.ok(start >= 0 && end > start);
const context = vm.createContext({});
vm.runInContext(`${source.slice(start, end)};globalThis.quickMenuTarget = quickMenuTarget;`, context);
const target = context.quickMenuTarget;

test("arrow keys wrap and Home/End jump", () => {
  const items = [0, 1, 2];
  assert.equal(target(items, 2, "ArrowDown"), 0);
  assert.equal(target(items, 0, "ArrowUp"), 2);
  assert.equal(target(items, 0, "ArrowRight"), 1);
  assert.equal(target(items, 1, "ArrowLeft"), 0);
  assert.equal(target(items, 1, "Home"), 0);
  assert.equal(target(items, 1, "End"), 2);
});

test("menu items carry a request kind and a German message with the period", () => {
  const items = [...html.slice(html.indexOf('id="quickAnalysisMenu"')).matchAll(/<button type="button" role="menuitem"[^>]*data-request-kind="(\w+)" data-message="([^"]+)"/g)];
  const kinds = items.map((item) => item[1]);
  assert.deepEqual(
    kinds.slice(0, 9),
    ["session_analysis", "progress_review", "progress_review", "progress_review", "progress_review", "plan_week", "plan_block", "plan_block", "plan_block"],
  );
  for (const weeks of [2, 4, 8, 12]) assert.ok(items.some((item) => item[1] === "progress_review" && item[2].includes(`${weeks} Wochen`)));
  for (const weeks of [2, 3, 4]) assert.ok(items.some((item) => item[1] === "plan_block" && item[2].includes(`${weeks} Wochen`)));
});

test("morning check-in keeps its request kind outside the menu", () => {
  assert.match(html, /id="quickMorningCheckinButton"[^>]*data-request-kind="morning_checkin"/);
});
