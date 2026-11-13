const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, fakeDocument, FakeElement } = require("./frontend-harness.cjs");

const TURN_RENDERERS = ["appendMessageChanges", "groupPlanNotes", "appendPlanNotes", "undoCoachTurn", "appendFailedTurnRetry", "resendChatText", "profileSetupButton"];

function harness({ confirmed = true, apiResult, apiError } = {}) {
  const calls = { api: [], confirm: [], toasts: [], loads: [], renders: 0 };
  const state = { data: { messages: [] } };
  const context = extractFunctions("coach.js", TURN_RENDERERS, {
    state,
    AppFormat: require("../public/format.js"),
    document: fakeDocument(),
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
  assert.equal(line.children[0].className, "message-changes-icon");
  assert.equal(line.children[1].textContent, "Profil aktualisiert · Trainingsvorlagen bearbeitet (2)");
  assert.equal(line.children[2].className, "message-undo");
  assert.equal(line.children[2].type, "button");
  assert.equal(line.children[2].textContent, "Rückgängig");
});

test("plan notes render safe labels, dates, evidence and warning emphasis", () => {
  const { context } = harness();
  const node = new FakeElement("div");
  context.appendMessageChanges(node, { role: "assistant", coach_changes: changes({
    plan_check_notes: [{ code: "run_spike", dates: ["2026-11-02"], severity: "warning" },
      { code: "back_to_back_hard", dates: [], severity: "notice" },
      { code: "load_spike", dates: [], severity: "notice" },
      { code: "weekly_load_rise", dates: [], severity: "notice" },
      { code: "load_unknown", dates: [], severity: "notice" },
      { code: "calendar_load", dates: ["2026-11-03"], severity: "notice" }],
  }) });
  assert.equal(node.children[1].className, "message-plan-note is-warning");
  assert.match(node.children[1].textContent, /Warnung: Laufsprung · 02\.11\.2026 · Beobachtungsstudie/);
  assert.match(node.children[2].textContent, /Hinweis: Harte Tage in Folge · Praxisbasiert/);
  assert.match(node.children[3].textContent, /Hinweis: Lastsprung · Aus Distanzstudien übertragen/);
  assert.match(node.children[4].textContent, /Hinweis: Wochenlast steigt/);
  assert.match(node.children[5].textContent, /Hinweis: Last unbekannt/);
  assert.match(node.children[6].textContent, /Hinweis: Kalender und Einheit · 03\.11\.2026/);
});

test("repeated plan notes condense to one line, distribution weeks by their first day (#2617)", () => {
  const { context } = harness();
  const node = new FakeElement("div");
  const week = (start) => [0, 1, 2, 3, 4].map((offset) => `2026-11-${String(start + offset).padStart(2, "0")}`);
  context.appendMessageChanges(node, { role: "assistant", coach_changes: changes({
    plan_check_notes: [16, 23, 9].map((start) => ({ code: "intensity_distribution", dates: week(start), severity: "notice" }))
      .concat([{ code: "calendar_load", dates: ["2026-11-05"], severity: "notice" },
        { code: "calendar_load", dates: ["2026-11-03", "2026-11-05"], severity: "notice" }]),
  }) });
  assert.equal(node.children.length, 3);
  assert.equal(node.children[1].textContent, "Hinweis: Intensitätsverteilung · Wochen ab 09.11.2026, 16.11.2026, 23.11.2026 · Praxisbasierte Referenzbereiche");
  assert.match(node.children[2].textContent, /^Hinweis: Kalender und Einheit · 03\.11\.2026, 05\.11\.2026 · /);
  const single = new FakeElement("div");
  context.appendPlanNotes(single, [{ code: "intensity_distribution", dates: week(16), severity: "notice" }]);
  assert.match(single.children[0].textContent, /Intensitätsverteilung · Woche ab 16\.11\.2026 · /);
});

test("undone, untracked and turn-less changes show no undo button", () => {
  const { context } = harness();
  const cases = [
    [{ client_turn_id: "turn-1", coach_changes: changes({ undone_at: "2026-10-14T10:00:00Z" }) }, "Zurückgenommen: "],
    [{ client_turn_id: "turn-1", coach_changes: changes({ undoable: false }) }, "Profil aktualisiert"],
    [{ coach_changes: changes() }, "Profil aktualisiert"],
  ];
  for (const [message, prefix] of cases) {
    const line = render(context, { role: "assistant", ...message });
    assert.equal(line.children.length, 2);
    assert.ok(line.children[1].textContent.startsWith(prefix));
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

function retryHarness(messages, { draft = "", attachments = [] } = {}) {
  const submitted = [];
  const input = { value: draft, dataset: { requestKind: "plan_week" }, dispatchEvent() {} };
  const state = { data: { messages }, chatAttachments: [...attachments] };
  const context = extractFunctions("coach.js", TURN_RENDERERS, {
    state,
    document: fakeDocument(),
    messageAttachmentLabel: (names) => (names?.length ? names.join(", ") : ""),
    $: (selector) => (selector === "#messageInput" ? input : { requestSubmit() {
      submitted.push({ text: input.value, attachments: state.chatAttachments, requestKind: input.dataset.requestKind });
      input.value = "";
      state.chatAttachments = [];
    } }),
    Event: class { constructor(type) { this.type = type; } },
    renderChatAttachments() {},
    updateChatControls() {},
  });
  return { context, state, input, submitted };
}

test("the newest failed reply sends its request again and keeps the draft", () => {
  const messages = [
    { role: "user", client_turn_id: "turn-1", content: "Plane meine Woche" },
    { role: "assistant", client_turn_id: "turn-1", content: "Timeout", coach_failed: true, coach_request_kind: "plan_week" },
  ];
  const { context, state, input, submitted } = retryHarness(messages, { draft: "Entwurf", attachments: ["a.fit"] });
  input.dataset.requestKind = "morning_checkin";
  const node = new FakeElement("div");
  context.appendFailedTurnRetry(node, messages[1], true);
  const retry = node.children[0];
  assert.equal(retry.textContent, "Erneut senden");
  assert.match(node.className, /is-failed/);
  retry.listeners.click();
  assert.deepEqual(JSON.parse(JSON.stringify(submitted)), [{ text: "Plane meine Woche", attachments: [], requestKind: "plan_week" }]);
  assert.equal(input.value, "Entwurf");
  assert.equal(input.dataset.requestKind, "morning_checkin");
  assert.deepEqual([...state.chatAttachments], ["a.fit"]);
});

test("older, attached or successful replies offer no retry", () => {
  const user = { role: "user", client_turn_id: "turn-1", content: "Analyse" };
  const failed = { role: "assistant", client_turn_id: "turn-1", content: "Timeout", coach_failed: true };
  const cases = [
    [[user, failed], failed, false],
    [[{ ...user, attachment_names: ["ride.fit"] }, failed], failed, true],
    [[user, { ...failed, coach_failed: undefined }], { ...failed, coach_failed: undefined }, true],
  ];
  for (const [messages, message, latest] of cases) {
    const { context } = retryHarness(messages);
    const node = new FakeElement("div");
    context.appendFailedTurnRetry(node, message, latest);
    assert.equal(node.children.length, 0);
  }
});
