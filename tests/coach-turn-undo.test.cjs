const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/coach.js"), "utf8");
const start = source.indexOf("// What the Coach turn changed locally");
const end = source.indexOf("\nfunction appendChatStream", start);

class FakeElement {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.className = "";
    this.textContent = "";
    this.disabled = false;
  }
  append(...nodes) { this.children.push(...nodes); }
  addEventListener(type, listener) { this.listeners[type] = listener; }
}

function harness({ confirmed = true, apiResult, apiError } = {}) {
  assert.ok(start >= 0 && end > start);
  const calls = { api: [], confirm: [], toasts: [], loads: [], renders: 0 };
  const state = { data: { messages: [] } };
  const context = vm.createContext({
    state,
    document: { createElement: (tag) => new FakeElement(tag) },
    async requestConfirmation(message, options) {
      calls.confirm.push({ message, options });
      return confirmed;
    },
    async api(url, options) {
      calls.api.push({ url, body: JSON.parse(options.body), method: options.method });
      if (apiError) throw apiError;
      return apiResult;
    },
    renderMessages() { calls.renders += 1; },
    toast(message, isError) { calls.toasts.push({ message, isError: Boolean(isError) }); },
    async load(url, areas) { calls.loads.push({ url, areas: [...areas] }); },
  });
  vm.runInContext(source.slice(start, end), context);
  return { context, state, calls };
}

function changes(overrides = {}) {
  return { labels: ["Profil aktualisiert", "Trainingsvorlagen bearbeitet (2)"], undoable: true, undone_at: null, ...overrides };
}

function render(context, message) {
  const node = new FakeElement("div");
  context.appendMessageChanges(node, message);
  return node.children[0];
}

test("an undoable turn lists its changes with one undo button", () => {
  const { context } = harness();
  const line = render(context, { role: "assistant", client_turn_id: "turn-1", coach_changes: changes() });
  assert.equal(line.className, "message-changes");
  assert.equal(line.children[0].textContent, "Geändert: Profil aktualisiert · Trainingsvorlagen bearbeitet (2)");
  assert.equal(line.children[1].className, "message-undo");
  assert.equal(line.children[1].type, "button");
  assert.equal(line.children[1].textContent, "Rückgängig");
});

test("undone, untracked and turn-less changes show no undo button", () => {
  const { context } = harness();
  const cases = [
    [{ client_turn_id: "turn-1", coach_changes: changes({ undone_at: "2026-10-14T10:00:00Z" }) }, "Zurückgenommen: "],
    [{ client_turn_id: "turn-1", coach_changes: changes({ undoable: false }) }, "Geändert: "],
    [{ coach_changes: changes() }, "Geändert: "],
  ];
  for (const [message, prefix] of cases) {
    const line = render(context, { role: "assistant", ...message });
    assert.equal(line.children.length, 1);
    assert.ok(line.children[0].textContent.startsWith(prefix));
  }
});

test("user messages and answers without changes render nothing", () => {
  const { context } = harness();
  assert.equal(render(context, { role: "user", client_turn_id: "turn-1", coach_changes: changes() }), undefined);
  assert.equal(render(context, { role: "assistant", client_turn_id: "turn-1" }), undefined);
  assert.equal(render(context, { role: "assistant", coach_changes: changes({ labels: [] }) }), undefined);
});

test("a cancelled confirmation sends nothing and re-enables the button", async () => {
  const { context, calls } = harness({ confirmed: false });
  const button = new FakeElement("button");
  await context.undoCoachTurn("turn-1", button);
  assert.equal(calls.confirm.length, 1);
  assert.match(calls.confirm[0].message, /Intervals\.icu bleibt unverändert/);
  assert.deepEqual(calls.api, []);
  assert.equal(button.disabled, false);
});

test("a confirmed undo marks the answer as undone and reloads the local areas", async () => {
  const undone = changes({ undone_at: "2026-10-14T10:00:00Z" });
  const { context, state, calls } = harness({ apiResult: { status: "undone", coach_changes: undone } });
  state.data.messages = [
    { role: "user", client_turn_id: "turn-1" },
    { role: "assistant", client_turn_id: "turn-1", coach_changes: changes() },
    { role: "assistant", client_turn_id: "turn-2", coach_changes: changes() },
  ];
  const button = new FakeElement("button");
  await context.undoCoachTurn("turn-1", button);
  assert.deepEqual(calls.api, [{ url: "/api/change-history/undo-turn", method: "POST", body: { client_turn_id: "turn-1" } }]);
  assert.equal(state.data.messages[0].coach_changes, undefined);
  assert.equal(state.data.messages[1].coach_changes, undone);
  assert.equal(state.data.messages[2].coach_changes.undone_at, null);
  assert.equal(calls.renders, 1);
  assert.deepEqual(calls.toasts, [{ message: "Änderungen zurückgenommen", isError: false }]);
  assert.deepEqual(calls.loads, [{ url: "/api/bootstrap?local=1", areas: ["plan", "library", "profile"] }]);
  assert.equal(button.disabled, true);
});

test("a refused undo keeps the answer and lets the athlete retry", async () => {
  const { context, state, calls } = harness({ apiError: new Error("Diese Coach-Änderungen wurden bereits zurückgenommen.") });
  state.data.messages = [{ role: "assistant", client_turn_id: "turn-1", coach_changes: changes() }];
  const button = new FakeElement("button");
  await context.undoCoachTurn("turn-1", button);
  assert.equal(state.data.messages[0].coach_changes.undone_at, null);
  assert.equal(calls.renders, 0);
  assert.deepEqual(calls.loads, []);
  assert.deepEqual(calls.toasts, [{ message: "Diese Coach-Änderungen wurden bereits zurückgenommen.", isError: true }]);
  assert.equal(button.disabled, false);
});

test("a second click while the undo runs is ignored", async () => {
  const { context, calls } = harness();
  const button = new FakeElement("button");
  button.disabled = true;
  await context.undoCoachTurn("turn-1", button);
  assert.deepEqual(calls.confirm, []);
  assert.deepEqual(calls.api, []);
});
