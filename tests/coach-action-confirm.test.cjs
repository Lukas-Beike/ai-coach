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
