const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const coachSource = fs.readFileSync(path.join(__dirname, "../public/coach.js"), "utf8");
const apiSource = fs.readFileSync(path.join(__dirname, "../public/api.js"), "utf8");
const start = coachSource.indexOf("function chatRequestIsCurrent");
const end = coachSource.indexOf("async function drainChatQueue");

function attachments(count) {
  return Array.from({ length: count }, (_, index) => ({ name: `route-${index}.gpx`, data: "AA==" }));
}

function unauthorizedResponse() {
  return new Response(JSON.stringify({ error: "Deine Sitzung ist abgelaufen. Bitte erneut anmelden." }), {
    status: 401,
    headers: { "Content-Type": "application/json" },
  });
}

// Sends a chat message whose request is rejected with 401 and returns the observable outcome.
async function sendChatIntoExpiredSession({ inputValue = "", beforeResponse = () => {} } = {}) {
  assert.ok(start >= 0 && end > start);
  const draftAttachments = attachments(2);
  const input = { value: inputValue, style: {}, dispatchEvent() {}, focus() {} };
  const state = {
    sessionGeneration: 0,
    chatGeneration: 0,
    chatAttachments: [],
    chatDraftDirty: false,
    chatFollowLatest: false,
    chatRequest: null,
    chatStream: null,
    chatStreamText: "",
    chatServerOperationId: null,
    chatQueue: [],
    rejectedMessages: [],
    data: null,
  };
  const counts = { showLogin: 0, renderChatAttachments: 0 };
  const context = vm.createContext({
    AbortController,
    Headers,
    Response,
    setTimeout,
    clearTimeout,
    document: { cookie: "ic_csrf=csrf-test" },
    fetch: async () => { beforeResponse(state); return unauthorizedResponse(); },
    state,
    $: () => input,
    toast() {},
    // Mirrors the generation and draft effects of public/auth.js showLogin().
    showLogin() {
      counts.showLogin += 1;
      state.sessionGeneration += 1;
      state.chatGeneration += 1;
      state.chatAttachments = [];
    },
    renderChatAttachments() { counts.renderChatAttachments += 1; },
    resizeChatInput() {},
    renderMessages() {},
    updateChatControls() {},
    rememberChatTurn() {},
    cancelScheduledChatStreamRender() {},
    invalidateContextPreview() {},
    scheduleChatStatusPoll() {},
    loadChatHistoryFresh: async () => {},
    chatIsNearBottom: () => false,
    AppState: { secureToken: () => "turn-test" },
  });
  vm.runInContext(apiSource, context);
  vm.runInContext(coachSource.slice(start, end), context);
  const message = "Mein Entwurf";
  const result = await context.requestCoachResponse(message, null, draftAttachments);
  return { result, state, input, counts, draftAttachments };
}

test("a chat 401 restores the typed draft and attachments once and shows login once", async () => {
  const { result, state, input, counts, draftAttachments } = await sendChatIntoExpiredSession();
  assert.equal(result, false);
  assert.equal(counts.showLogin, 1);
  assert.equal(input.value, "Mein Entwurf");
  // Copy out of the vm realm so deepStrictEqual compares prototypes as well as values.
  assert.deepEqual([...state.chatAttachments], draftAttachments);
  assert.equal(counts.renderChatAttachments, 1);
  assert.equal(state.chatDraftDirty, true);
  assert.deepEqual(state.rejectedMessages, []);
});

test("a chat 401 keeps newer typed text and parks the rejected message once when the input was edited", async () => {
  const { result, state, input, counts, draftAttachments } = await sendChatIntoExpiredSession({ inputValue: "Neuer Entwurf" });
  assert.equal(result, false);
  assert.equal(counts.showLogin, 1);
  assert.equal(input.value, "Neuer Entwurf");
  assert.deepEqual([...state.chatAttachments], draftAttachments);
  assert.equal(state.rejectedMessages.length, 1);
  assert.equal(state.rejectedMessages[0].content, "Mein Entwurf");
  assert.equal(state.rejectedMessages[0].error, "Bitte erneut anmelden.");
});

test("a chat 401 for a superseded chat still shows login once without restoring the stale draft", async () => {
  const { result, state, input, counts } = await sendChatIntoExpiredSession({
    beforeResponse: (current) => { current.chatGeneration += 1; },
  });
  assert.equal(result, false);
  assert.equal(counts.showLogin, 1);
  assert.equal(input.value, "");
  assert.equal(state.chatDraftDirty, false);
});
