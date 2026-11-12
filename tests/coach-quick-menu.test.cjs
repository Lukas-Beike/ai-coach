const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

const root = path.join(__dirname, "..", "public");
const source = fs.readFileSync(path.join(root, "coach.js"), "utf8");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const { quickMenuTarget: target, buildComposerPlusMenu } = extractFunctions("coach.js", ["quickMenuTarget", "buildComposerPlusMenu"]);

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
    kinds.slice(0, 10),
    ["session_analysis", "progress_review", "progress_review", "progress_review", "progress_review", "plan_week", "plan_block", "plan_block", "plan_block", "adjust_week"],
  );
  // Progress and block review are one review; two weeks are too short to show progress.
  for (const weeks of [4, 8, 12]) assert.ok(items.some((item) => item[1] === "progress_review" && item[2].includes(`${weeks} Wochen`)));
  assert.ok(items.some((item) => item[1] === "progress_review" && item[2].includes("letzten Test")));
  assert.ok(!kinds.includes("block_review"));
  assert.ok(!items.some((item) => item[1] === "progress_review" && item[2].includes("letzten 2 Wochen")));
  for (const weeks of [2, 3, 4]) assert.ok(items.some((item) => item[1] === "plan_block" && item[2].includes(`${weeks} Wochen`)));
});

test("morning check-in keeps its request kind outside the menu", () => {
  assert.match(html, /id="quickMorningCheckinButton"[^>]*data-request-kind="morning_checkin"/);
});

test("composer plus menu is cloned from the quick bar and still opens the file picker", () => {
  assert.match(html, /id="attachmentButton"[^>]*aria-haspopup="menu"[^>]*aria-controls="composerPlusMenu"[^>]*popovertarget="composerPlusMenu"/);
  assert.match(html, /id="composerPlusMenu"[^>]*popover="auto"[^>]*role="menu"/);
  assert.match(html, /role="menuitem" id="attachFileMenuItem">Datei anhängen</);
  const build = buildComposerPlusMenu.toString();
  assert.ok(build.includes('$("#quickMorningCheckinButton")') && build.includes('$("#quickAnalysisMenu")'));
  assert.ok(build.includes('morningItem.setAttribute("role", "menuitem")'));
  assert.ok(build.includes("menu.append(morningItem, ...[...source.children].map(copy))"));
  assert.match(source, /attachFileMenuItem"\)\.addEventListener\("click"[\s\S]*?\$\("#attachmentInput"\)\.click\(\)/);
  assert.ok(source.includes('$("#composerPlusMenu").addEventListener("click", startQuickAction)'));
});

test("the morning check-in is offered unless the Coach says it is not available", () => {
  const buttons = [{ hidden: false }, { hidden: false }];
  const { renderCoachOverview } = extractFunctions("coach.js", ["renderCoachOverview"], {
    document: { querySelectorAll: (selector) => (selector === "[data-request-kind=morning_checkin]" ? buttons : []) },
  });
  renderCoachOverview({ coach_quick_actions: { morning_checkin: false } });
  assert.deepEqual(buttons.map((button) => button.hidden), [true, true]);
  renderCoachOverview({ coach_quick_actions: { morning_checkin: true } });
  assert.deepEqual(buttons.map((button) => button.hidden), [false, false]);
  renderCoachOverview({});
  assert.deepEqual(buttons.map((button) => button.hidden), [false, false]);
});
