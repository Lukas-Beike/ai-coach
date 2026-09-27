const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/app.js"), "utf8");
const start = source.indexOf("const HIDDEN_CHAT_RECEIPT_TOOLS");
const end = source.indexOf("\nasync function retryProvider", start);

function render(commands) {
  assert.ok(start >= 0 && end > start);
  const cards = [];
  const context = vm.createContext({
    state: {}, renderCoachReceipts() {}, addCoachReceipt(card) { cards.push(card); },
  });
  vm.runInContext(source.slice(start, end), context);
  context.addStructuredCoachReceipts({ command_receipts: commands });
  return cards;
}

test("a repaired planning attempt shows the successful result without a red card", () => {
  const cards = render([
    { tool: "apply_training_patch", resolved: true, result: { ok: false, reason: "request_scope" } },
    { tool: "apply_training_patch", result: { ok: true, library_entry_ids: ["ride", "run"] } },
  ]);
  assert.equal(cards.length, 1);
  assert.equal(cards[0].status, "success");
  assert.match(cards[0].details[0], /^2 lokale/);
});

test("a different unresolved failure remains visible beside the saved workout", () => {
  const cards = render([
    { tool: "apply_training_patch", resolved: false, result: { ok: false, error: "Synthetic failure" } },
    { tool: "apply_training_patch", result: { ok: true, library_entry_ids: ["run"] } },
  ]);
  assert.equal(cards.length, 2);
  assert.equal(cards[0].status, "error");
  assert.equal(cards[0].message, "Synthetic failure");
  assert.equal(cards[1].status, "success");
});

test("synchronization progress does not create chat cards", () => {
  const cards = render([
    { tool: "start_intervals_plan_sync", result: { ok: true, status: "queued", sync_job_id: "sync-1" } },
    { tool: "get_sync_job", result: { job: { id: "sync-1", status: "running" } } },
    { tool: "start_provider_refresh", result: { ok: true, status: "queued", sync_job_id: "sync-2" } },
  ]);
  assert.deepEqual(cards, []);
});

test("an approved remote write is identified as remote in its action receipt", () => {
  const start = source.indexOf("function coachActionReceipt(");
  const end = source.indexOf("\nasync function executeCoachActionProposal", start);
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({});
  vm.runInContext(source.slice(start, end), context);
  const receipt = context.coachActionReceipt(
    { action_type: "remote_coach_write" },
    { status: "queued", sync_job_id: "sync-1" },
  );
  assert.equal(receipt.remoteWrite, true);
  assert.equal(receipt.title, "Remote-Änderung eingereiht");
  assert.match(receipt.message, /Ergebnis steht noch aus/);
});

test("a completed remote write receipt uses completion wording", () => {
  const start = source.indexOf("function coachActionReceipt(");
  const end = source.indexOf("\nasync function executeCoachActionProposal", start);
  const context = vm.createContext({});
  vm.runInContext(source.slice(start, end), context);
  const receipt = context.coachActionReceipt(
    { action_type: "remote_coach_write" },
    { status: "deleted" },
  );
  assert.equal(receipt.title, "Remote-Änderung ausgeführt");
});

test("approval preview renders every bound remote-write value as text", () => {
  const start = source.indexOf("function coachActionDiff(");
  const end = source.indexOf("\nfunction coachActionButtons", start);
  const context = vm.createContext({
    document: { createElement: () => ({ textContent: "", children: [], append(node) { this.children.push(node); } }) },
  });
  vm.runInContext(source.slice(start, end), context);
  const list = context.coachActionDiff({ diff: [{
    name: "Nutrition", date: "2026-09-24", kcal: "450 kcal", entries: "2",
    carbs: "60 g", protein: "20 g", fat: "10 g", keep: "ride-1", delete: "ride-2",
  }] });
  assert.match(list.children[0].textContent, /450 kcal.*2 Einträge.*60 g.*ride-1.*ride-2/);
});
