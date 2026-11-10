const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/coach.js"), "utf8");
const start = source.indexOf("async function executeCoachActionProposal");
const end = source.indexOf("\nfunction createPendingMessage", start);

function harness(apiResponses) {
  const receipts = [];
  const toasts = [];
  const calls = [];
  const context = vm.createContext({
    state: { route: "plan", coachActionUnknownIds: new Set(), coachActionProposals: [] },
    api: async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      return apiResponses.shift();
    },
    addCoachReceipt(card) { receipts.push(card); },
    renderCoachActionReview() {},
    coachActionReceipt: () => ({ message: "Gespeichert." }),
    toast(message, isError) { toasts.push({ message, isError }); },
    isHttpClientRejection: () => false,
    isSessionEndedError: () => false,
    AppRouter: { navigate: async () => {} },
    load: async () => {},
  });
  vm.runInContext(source.slice(start, end) + ";globalThis.execute = executeCoachActionProposal;", context);
  return { context, receipts, toasts, calls };
}

test("a confirm response without a proposed payload is rejected before execute is sent", async () => {
  const { context, receipts, toasts, calls } = harness([{ action_token: "token-1" }]);
  const proposal = { id: "proposal-1", status: "ready", action_type: "remote_coach_write" };
  const button = { disabled: false };

  await context.execute(proposal, button);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/coach/actions/confirm");
  assert.equal(context.state.coachActionUnknownIds.has("proposal-1"), false);
  assert.equal(receipts.length, 1);
  assert.equal(receipts[0].title, "Aktion nicht bestätigt");
  assert.equal(receipts[0].status, "error");
  assert.match(receipts[0].message, /^Die Freigabe konnte nicht bestätigt werden/);
  assert.equal(toasts.at(-1).isError, true);
  assert.equal(button.disabled, false);
});

test("a valid confirm response forwards its token and payload hash to execute", async () => {
  const { context, calls } = harness([
    { action_token: "token-2", proposed_action: { payload_hash: "hash-2" } },
    { status: "completed" },
  ]);
  const button = { disabled: false };

  await context.execute({ id: "proposal-2", status: "ready", action_type: "remote_coach_write" }, button);

  assert.equal(calls.length, 2);
  assert.equal(calls[1].url, "/api/coach/actions/execute");
  assert.deepEqual(calls[1].body, { action_token: "token-2", payload_hash: "hash-2" });
});

function rejectHarness() {
  const context = vm.createContext({
    state: { route: "plan", coachActionUnknownIds: new Set(), coachActionProposals: [] },
    addCoachReceipt() {},
    renderCoachActionReview() {},
    toast() {},
    isSessionEndedError: (error) => error?.sessionEnded === true,
  });
  vm.runInContext(source.slice(start, end) + ";globalThis.reject = rejectCoachActionProposal;", context);
  return context;
}

test("a confirm 409 without a reason retires the card instead of re-enabling it", () => {
  const proposal = { id: "p", status: "ready" };
  rejectHarness().reject(proposal, { disabled: true }, Object.assign(new Error("Abgelaufen."), { status: 409, reason: "request_failed" }), true);
  assert.equal(proposal.status, "used");
});

test("a 409 after execute was sent keeps the card actionable", () => {
  const proposal = { id: "p", status: "ready" };
  rejectHarness().reject(proposal, { disabled: true }, Object.assign(new Error("Konflikt."), { status: 409, reason: "request_failed" }), false);
  assert.equal(proposal.status, "ready");
});

test("expired and changed payload reasons retire the card as expired", () => {
  for (const reason of ["proposal_expired", "proposal_payload_changed"]) {
    const proposal = { id: "p", status: "ready" };
    rejectHarness().reject(proposal, { disabled: true }, Object.assign(new Error("x"), { status: 409, reason }), false);
    assert.equal(proposal.status, "expired");
  }
});

test("an expired card shows no action buttons", () => {
  const slice = (name) => {
    const at = source.indexOf(`function ${name}(`);
    return source.slice(at, source.indexOf("\n}\n", at) + 3);
  };
  let buttonCalls = 0;
  const context = vm.createContext({
    document: { createElement: () => ({ append() {}, setAttribute() {}, dataset: {} }) },
    state: { coachActionUnknownIds: new Set() },
    coachActionDescription: () => "",
    coachActionDiff: () => "diff",
    coachActionButtons: () => { buttonCalls += 1; return "buttons"; },
  });
  vm.runInContext(["coachActionExpired", "coachActionStatus", "coachActionCard"].map(slice).join("\n"), context);
  context.coachActionCard({ id: "a", status: "ready", action_type: "undo_change", expires_at: Date.now() / 1000 - 1 });
  assert.equal(buttonCalls, 0);
  context.coachActionCard({ id: "b", status: "ready", action_type: "undo_change", expires_at: Date.now() / 1000 + 600 });
  assert.equal(buttonCalls, 1);
});
