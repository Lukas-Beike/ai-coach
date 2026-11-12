const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, fakeDocument } = require("./frontend-harness.cjs");

const RECEIPT_TOOLS = ["HIDDEN_CHAT_RECEIPT_TOOLS", "COACH_RECEIPT_LABELS", "SYNC_JOB_RECEIPT_LABELS", "receiptIsVisible", "syncJobReceipt", "commandReceiptTitle", "commandReceiptMessage", "commandReceiptStatus", "commandReceipt", "addStructuredCoachReceipts"];
const EXECUTE_ACTIONS = ["coachActionReceipt", "isHttpClientRejection", "reconcileCoachActionProposal", "executeCoachActionProposal", "showCoachReceiptArea", "lockUnknownCoachActionOutcome", "rejectCoachActionProposal"];

function render(commands) {
  const cards = [];
  const context = extractFunctions("coach.js", RECEIPT_TOOLS, {
    state: {}, toast() {},
  });
  context.toastCoachReceipts = (receipts) => cards.push(...receipts);
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
    // Read-only tools change nothing and announce nothing.
    { tool: "read_coach_context", result: { ok: true } },
  ]);
  assert.deepEqual(cards, []);
});

test("immediate remote writes report the completed operation in their receipt", () => {
  const context = extractFunctions("coach.js", ["coachActionReceipt"]);

  const adaptive = context.coachActionReceipt(
    { action_type: "remote_coach_write" },
    { ok: true, status: "completed" },
  );
  const queued = context.coachActionReceipt(
    { action_type: "remote_coach_write" },
    { ok: true, status: "queued", sync_job_id: "sync-1" },
  );

  assert.match(adaptive.details[0], /direkt ausgeführt/);
  assert.equal(queued.details.join("|"), "Syncjob sync-1 eingereiht");
});

test("an approved remote write is identified as remote in its action receipt", () => {
  const context = extractFunctions("coach.js", ["coachActionReceipt"]);
  const receipt = context.coachActionReceipt(
    { action_type: "remote_coach_write" },
    { status: "queued", sync_job_id: "sync-1" },
  );
  assert.equal(receipt.remoteWrite, true);
  assert.equal(receipt.title, "Remote-Änderung eingereiht");
  assert.match(receipt.message, /Ergebnis steht noch aus/);
});

test("a completed remote write receipt uses completion wording", () => {
  const context = extractFunctions("coach.js", ["coachActionReceipt"]);
  const receipt = context.coachActionReceipt(
    { action_type: "remote_coach_write" },
    { status: "deleted" },
  );
  assert.equal(receipt.title, "Remote-Änderung ausgeführt");
});

test("an approved nutrition product write has product receipt and destination", () => {
  const context = extractFunctions("coach.js", ["coachActionReceipt"]);
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
  const routes = [];
  const loads = [];
  let request = 0;
  const context = extractFunctions("coach.js", EXECUTE_ACTIONS, {
    state: { coachActionProposals: [{ id: "proposal-1" }] },
    api: async () => (++request === 1
      ? { action_token: "token", proposed_action: { payload_hash: "hash" } }
      : { ok: true, status: "applied" }),
    renderCoachActionReview() {},
    addCoachReceipt() {},
    toast() {},
    load: async (...args) => { loads.push(args); },
    AppRouter: { navigate: async (...args) => { routes.push(args); } },
  });
  await context.executeCoachActionProposal(
    { id: "proposal-1", action_type: "local_coach_write", object_ids: { operation: "save_nutrition_product" }, status: "ready" },
    { disabled: false },
  );
  assert.equal(JSON.stringify(loads), JSON.stringify([["/api/bootstrap?local=1", ["plan", "library", "profile", "feedback"]]]));
  assert.equal(JSON.stringify(routes), JSON.stringify([["nutrition/products", { historyMode: "push" }]]));
});

test("action destination precedes a slow refresh and preserves newer navigation", async () => {
  for (const navigateDuringExecution of [false, true]) {
    const routes = [];
    let releaseRefresh;
    let refreshStarted;
    const refreshing = new Promise(resolve => { refreshStarted = resolve; });
    const context = extractFunctions("coach.js", EXECUTE_ACTIONS, {
      state: { route: "coach", coachActionProposals: [{ id: "proposal-1" }] },
      api: async (url) => {
        if (url.endsWith("/confirm")) return { action_token: "token", proposed_action: { payload_hash: "hash" } };
        if (navigateDuringExecution) context.state.route = "analysis/running";
        return { ok: true, status: "applied" };
      },
      renderCoachActionReview() {}, addCoachReceipt() {}, toast() {},
      load: () => { refreshStarted(); return new Promise(resolve => { releaseRefresh = resolve; }); },
      AppRouter: { navigate: async (route) => { routes.push(route); context.state.route = route; } },
    });
    const action = context.executeCoachActionProposal(
      { id: "proposal-1", action_type: "local_coach_write", status: "ready" },
      { disabled: false },
    );
    await refreshing;
    assert.deepEqual(routes, navigateDuringExecution ? [] : ["nutrition/diary"]);
    context.state.route = "coach";
    releaseRefresh();
    await action;
    assert.equal(context.state.route, "coach");
  }
});

test("approval preview renders every bound remote-write value as text", () => {
  const context = extractFunctions("coach.js", ["coachActionDiff"], { document: fakeDocument() });
  const list = context.coachActionDiff({ diff: [{
    name: "Nutrition", date: "2026-09-24", id: "race-1", kcal: "450 kcal", entries: "2",
    carbs: "60 g", protein: "20 g", fat: "10 g", keep: "ride-1", delete: "ride-2",
  }] });
  assert.match(list.children[0].textContent, /ID: race-1/);
  assert.match(list.children[0].textContent, /450 kcal.*2 Einträge.*60 g.*ride-1.*ride-2/);
});

test("a Coach action announces itself in one toast with its failures first", () => {
  const toasts = [];
  const { toastCoachReceipts } = extractFunctions("coach.js", ["toastCoachReceipts"], { toast: (text, isError) => toasts.push([text, isError]) });
  toastCoachReceipts([
    { title: "Profil aktualisiert", status: "success", message: "FTP 250 W" },
    { title: "Plan", status: "error", message: "Konflikt am Montag" },
    { title: "Profil aktualisiert", status: "success" },
  ]);
  toastCoachReceipts([{ title: "Nur Titel", status: "error", message: "Nur Titel" }]);
  toastCoachReceipts([]);
  assert.deepEqual(toasts, [["Plan: Konflikt am Montag · Profil aktualisiert", true], ["Nur Titel", true]]);
});
