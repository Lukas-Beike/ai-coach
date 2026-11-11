const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

function attachments(count) {
  return Array.from({ length: count }, (_, index) => ({ name: `route-${index}.gpx`, data: "AA==" }));
}

// Runs sendMessage, the chat queue and the recovery completion against a stubbed page.
function coach({ busy = false, chatRequest = null, chatServerOperationId = null } = {}) {
  const input = { value: "Neue Frage", dataset: {}, style: {}, focus() {} };
  const state = {
    busy,
    chatRequest,
    chatServerOperationId,
    chatStream: null,
    chatAttachments: attachments(2),
    chatAttachmentsLoading: false,
    chatQueue: [],
    chatQueueSequence: 0,
    chatDraftDirty: true,
    chatStreamText: "",
    chatResponseStarted: false,
    voiceTranscribing: false,
    quickTemplatesVisible: true,
    data: { messages: [], configured: { openai: true } },
  };
  const drained = [];
  const context = extractFunctions("coach.js", ["MAX_QUEUED_ATTACHMENT_BYTES", "resumeQueuedChat", "finishRecoveredChatStatus", "queueChatMessage", "chatControlState", "sendMessage"], {
    state,
    document: { visibilityState: "visible" },
    $: (selector) => (selector === "#messageInput" ? input : null),
    toast() {},
    renderChatAttachments() {},
    renderMessages() {},
    renderQuickMessageTemplates() {},
    updateChatControls() {},
    updateVoiceButton() {},
    scrollChatToResponseStart() {},
    shouldRestoreChatInputFocus: () => false,
    voiceIsRecording: () => false,
    loadChatHistoryFresh: async () => {},
    drainChatQueue: async (...args) => { drained.push(JSON.parse(JSON.stringify(args))); },
  });
  return { context, state, input, drained };
}

const submit = { preventDefault() {} };

test("a message sent while a chat recovers is queued with its attachments", async () => {
  const { context, state, input, drained } = coach({ chatRequest: { phase: "recovering", clientTurnId: "turn-1", message: null } });
  await context.sendMessage(submit);
  assert.equal(state.chatQueue.length, 1);
  assert.equal(state.chatQueue[0].message, "Neue Frage");
  assert.equal(state.chatQueue[0].mode, "queue");
  assert.deepEqual(JSON.parse(JSON.stringify(state.chatQueue[0].attachments)), attachments(2));
  assert.equal(state.chatAttachments.length, 0);
  assert.equal(input.value, "");
  assert.deepEqual(drained, []);
});

test("the recovered chat sends the queued message with its attachments", async () => {
  const { context, state, drained } = coach({ chatRequest: { phase: "recovering", clientTurnId: "turn-1", message: null } });
  await context.sendMessage(submit);
  await context.finishRecoveredChatStatus();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(drained, [["Neue Frage", null, attachments(2)]]);
  assert.equal(state.chatQueue.length, 0);
});

test("a message sent while the Coach answers is still queued", async () => {
  const { context, state, drained } = coach({ busy: true, chatRequest: { phase: "streaming", clientTurnId: "turn-1", message: "Erste Frage" } });
  await context.sendMessage(submit);
  assert.equal(state.chatQueue.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(state.chatQueue[0].attachments)), attachments(2));
  assert.equal(state.chatAttachments.length, 0);
  assert.deepEqual(drained, []);
});

// The working note names what the Coach is doing, for the visible label and the live region.
function workingLabel(chatRequest) {
  return extractFunctions("coach.js", ["coachWorkingLabel"], { state: { chatRequest } }).coachWorkingLabel();
}

test("the working note tells which phase a running Coach answer is in", () => {
  assert.equal(workingLabel({ phase: "running" }), "Coach arbeitet an deiner Antwort…");
  assert.equal(workingLabel({ phase: "recovering" }), "Verbindung unterbrochen · die Antwort wird im Hintergrund fertiggestellt…");
  assert.equal(workingLabel({ phase: "reconciling" }), "Antwort wird sicher übernommen…");
  assert.equal(workingLabel({ phase: "recovering", background: true }), "Der Coach arbeitet · du kannst die Seite neu laden…");
});

test("a running status of a background job marks the recovered request as background", () => {
  const state = { busy: true, chatRequest: null, chatServerOperationId: null };
  const context = extractFunctions("coach.js", ["showRunningChatStatus"], { state });
  context.showRunningChatStatus({ operation_id: "op-1", mode: "background" });
  assert.equal(state.chatRequest.phase, "recovering");
  assert.equal(state.chatRequest.background, true);
  assert.equal(state.chatServerOperationId, "op-1");
  state.chatRequest = null;
  context.showRunningChatStatus({ operation_id: "op-2", mode: "foreground" });
  assert.equal(state.chatRequest.background, false);
});
