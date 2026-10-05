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

test("immediate remote writes report the completed operation in their receipt", () => {
  const receiptStart = source.indexOf("function coachActionReceipt(");
  const receiptEnd = source.indexOf("\nasync function executeCoachActionProposal", receiptStart);
  const context = vm.createContext({});
  vm.runInContext(source.slice(receiptStart, receiptEnd) + ";globalThis.readReceipt = coachActionReceipt;", context);

  const duplicate = context.readReceipt(
    { action_type: "delete_duplicate_intervals_activity" },
    { ok: true, status: "deleted" },
  );
  const adaptive = context.readReceipt(
    { action_type: "remote_coach_write" },
    { ok: true, status: "completed" },
  );
  const queued = context.readReceipt(
    { action_type: "remote_coach_write" },
    { ok: true, status: "queued", sync_job_id: "sync-1" },
  );

  assert.match(duplicate.details[0], /Intervals\.icu gelöscht/);
  assert.match(adaptive.details[0], /direkt ausgeführt/);
  assert.equal(queued.details.join("|"), "Syncjob sync-1 eingereiht");
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

test("an approved nutrition product write has product receipt and destination", () => {
  const start = source.indexOf("function coachActionReceipt(");
  const end = source.indexOf("\nasync function executeCoachActionProposal", start);
  const context = vm.createContext({});
  vm.runInContext(source.slice(start, end), context);
  const receipt = context.coachActionReceipt(
    { action_type: "local_coach_write", object_ids: { operation: "save_nutrition_product" } },
    { status: "applied" },
  );
  assert.equal(receipt.title, "Produkt gespeichert");
  assert.equal(receipt.message, "Das Produkt wurde lokal gespeichert.");
  assert.equal(receipt.nutritionProductWrite, true);
  assert.equal(receipt.localWrite, true);
});

test("approved nutrition product write refreshes and opens the product catalog", async () => {
  const start = source.indexOf("function coachActionReceipt(");
  const end = source.indexOf("\nfunction createPendingMessage", start);
  const routes = [];
  const loads = [];
  let request = 0;
  const context = vm.createContext({
    state: { coachActionProposals: [{ id: "proposal-1" }] },
    api: async () => (++request === 1
      ? { action_token: "token", proposed_action: { payload_hash: "hash" } }
      : { ok: true, status: "applied" }),
    renderCoachActionReview() {},
    addCoachReceipt() {},
    toast() {},
    load: async (...args) => { loads.push(args); },
    applyNavigationRoute: async (...args) => { routes.push(args); },
  });
  vm.runInContext(source.slice(start, end), context);
  await context.executeCoachActionProposal(
    { id: "proposal-1", action_type: "local_coach_write", object_ids: { operation: "save_nutrition_product" }, status: "ready" },
    { disabled: false },
  );
  assert.equal(JSON.stringify(loads), JSON.stringify([["/api/bootstrap?local=1", ["plan", "library", "profile", "feedback"]]]));
  assert.equal(JSON.stringify(routes), JSON.stringify([["nutrition/products", { historyMode: "push" }]]));
});

test("approval preview renders every bound remote-write value as text", () => {
  const start = source.indexOf("function coachActionDiff(");
  const end = source.indexOf("\nfunction coachActionButtons", start);
  const context = vm.createContext({
    document: { createElement: () => ({ textContent: "", children: [], append(node) { this.children.push(node); } }) },
  });
  vm.runInContext(source.slice(start, end), context);
  const list = context.coachActionDiff({ diff: [{
    name: "Nutrition", date: "2026-09-24", id: "race-1", kcal: "450 kcal", entries: "2",
    carbs: "60 g", protein: "20 g", fat: "10 g", keep: "ride-1", delete: "ride-2",
  }] });
  assert.match(list.children[0].textContent, /ID: race-1/);
  assert.match(list.children[0].textContent, /450 kcal.*2 Einträge.*60 g.*ride-1.*ride-2/);
});
