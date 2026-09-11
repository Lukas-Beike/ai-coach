const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/app.js"), "utf8");
const start = source.indexOf("function addStructuredCoachReceipts(payload) {");
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
